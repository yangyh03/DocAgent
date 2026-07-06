from __future__ import annotations

import re
import zipfile
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from langgraph.graph import END, StateGraph
from PIL import Image

from app.config import settings
from app.llm.agents import (
    extract_metadata_with_llm,
    is_metadata_enabled,
    is_vision_enabled,
    understand_images_with_vlm,
)
from app.parsers.html_parser import parse_html_archive_document, parse_html_document
from app.parsers.image_parser import parse_image_document
from app.parsers.pdf_parser import parse_pdf_document
from app.parsers.word_parser import parse_word_document, render_blocks_to_text
from app.services.runtime_metrics import add_runtime_event, empty_runtime_metrics
from app.workflow.router import route_file
from app.workflow.state import WorkflowState

# 函数签名约定 
MetadataExtractor = Callable[[str, list[dict[str, Any]]], dict[str, Any]]   # [输入1: str, 输入2: list[dict[str, Any]]] -> 输出: dict[str, Any]
VisionUnderstander = Callable[[list[dict[str, Any]], list[dict[str, str]]], list[dict[str, Any]]]
ProgressCallback = Callable[[str], None]
CHUNK_TARGET_CHARS = 1000
DEBUG_METADATA_KEYS = {"bbox", "page_width", "page_height", "font_size", "bold"}
STATUS_SEVERITY = {"success": 0, "skipped": 0, "partial_success": 1, "failed": 2}


def create_docagent_workflow(
    metadata_extractor: MetadataExtractor | None = None,
    vision_understander: VisionUnderstander | None = None,
    progress_callback: ProgressCallback | None = None,
):
    """创建 DocAgent 的 LangGraph 工作流。

    Router/Parser 是确定性工具节点；Metadata/Vision/Normalizer 是 Agent 风格节点。
    默认有 API key 时调用多模态大模型；测试环境可注入 mock；失败时自动降级。
    """
    graph = StateGraph(WorkflowState)

    graph.add_node("router", _with_progress("router", _router_node, progress_callback))
    graph.add_node("parser_tool", _with_progress("parser_tool", _parser_tool_node, progress_callback))
    graph.add_node(
        "metadata_extraction_agent",
        _with_progress(
            "metadata_extraction_agent",
            lambda state: _metadata_extraction_agent(state, metadata_extractor),
            progress_callback,
        ), # LangGraph 调节点时，默认只传一个参数，所以这里用 lambda 包装，传入 metadata_extractor
    )
    graph.add_node(
        "vision_understanding_agent",
        _with_progress(
            "vision_understanding_agent",
            lambda state: _vision_understanding_agent(state, vision_understander),
            progress_callback,
        ),
    )
    graph.add_node(
        "result_normalizer_agent",
        _with_progress("result_normalizer_agent", _result_normalizer_agent, progress_callback),
    )
    graph.add_node("rag_chunking_agent", _with_progress("rag_chunking_agent", _rag_chunking_agent, progress_callback))

    graph.set_entry_point("router")
    graph.add_edge("router", "parser_tool")
    graph.add_edge("parser_tool", "metadata_extraction_agent")
    graph.add_edge("metadata_extraction_agent", "vision_understanding_agent")
    graph.add_edge("vision_understanding_agent", "result_normalizer_agent")
    graph.add_edge("result_normalizer_agent", "rag_chunking_agent")
    graph.add_edge("rag_chunking_agent", END)

    return graph.compile()


def run_docagent_workflow(
    file_path: str | Path,
    task_id: str = "",
    server_source: str = "",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    workflow = create_docagent_workflow(progress_callback=progress_callback)
    return workflow.invoke(
        {
            "task_id": task_id,
            "file_path": str(file_path),
            "server_source": server_source,
            "errors": [],
            "agent_trace": [],
            "runtime_metrics": empty_runtime_metrics(),
        }
    )


def _with_progress(
    node_name: str,
    handler: Callable[[WorkflowState], dict[str, Any]],
    progress_callback: ProgressCallback | None,
) -> Callable[[WorkflowState], dict[str, Any]]:
    def wrapped(state: WorkflowState) -> dict[str, Any]:
        if progress_callback is not None:
            progress_callback(node_name)
        return handler(state)

    return wrapped


def _trace(state: WorkflowState, node: str, message: str, **extra: Any) -> list[dict[str, Any]]:
    """记录工作流节点执行轨迹"""
    trace = list(state.get("agent_trace", []))
    item: dict[str, Any] = {
        "node": node,
        "message": message,
        "status": extra.pop("status", "success"),
        "duration_ms": extra.pop("duration_ms", 0),
        "fallback_used": extra.pop("fallback_used", False),
        "error": extra.pop("error", ""),
    }
    item.update(extra)
    trace.append(item)
    return trace


def _duration_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))


def _combine_status(current: str | None, incoming: str | None) -> str:
    current_status = current or "success"
    incoming_status = incoming or "success"
    return incoming_status if STATUS_SEVERITY.get(incoming_status, 0) > STATUS_SEVERITY.get(current_status, 0) else current_status


def _router_node(state: WorkflowState) -> dict[str, Any]:
    """判断文件类型"""
    start = perf_counter()
    file_type = route_file(state["file_path"])
    return {
        "file_type": file_type,
        "agent_trace": _trace(
            state,
            "router",
            "按文件扩展名完成确定性路由",
            file_type=file_type,
            duration_ms=_duration_ms(start),
        ),
    }


def _parser_tool_node(state: WorkflowState) -> dict[str, Any]:
    """调用对应 parser 工具完成基础解析"""
    start = perf_counter()
    file_path = Path(state["file_path"])
    file_type = state.get("file_type", "unsupported")
    validation_error = _validate_file_signature(file_path, file_type)

    if validation_error:
        parsed = {
            "content": validation_error,
            "status": "failed",
            "blocks": [],
            "assets": [],
            "metadata": {
                "validation_error": validation_error,
                "declared_file_type": file_type,
            },
        }
    elif file_type == "word":
        parsed = parse_word_document(file_path, assets_dir=file_path.parent / "assets")
    elif file_type == "pdf":
        parsed = parse_pdf_document(file_path, assets_dir=file_path.parent / "assets")
    elif file_type == "html":
        parsed = parse_html_document(file_path, assets_dir=file_path.parent / "assets")
    elif file_type == "html_archive":
        parsed = parse_html_archive_document(file_path, assets_dir=file_path.parent / "assets")
    elif file_type == "image":
        parsed = parse_image_document(file_path, assets_dir=file_path.parent / "assets")
    else:
        parsed = {
            "content": f"不支持的文件类型: {file_path.suffix.lower()}",
            "status": "failed",
            "blocks": [],
            "assets": [],
        }

    errors = list(state.get("errors", []))
    if parsed.get("status") == "failed":
        errors.append(parsed.get("content", "解析失败"))
    status = parsed.get("status", "success")

    return {
        "content": parsed.get("content", ""),
        "blocks": parsed.get("blocks", []),
        "assets": parsed.get("assets", []),
        "metadata": parsed.get("metadata", {}),
        "status": status,
        "errors": errors,
        "agent_trace": _trace(
            state,
            "parser_tool",
            "调用对应 parser 工具完成基础解析",
            status=status,
            file_type=file_type,
            block_count=len(parsed.get("blocks", [])),
            asset_count=len(parsed.get("assets", [])),
            validation_status="failed" if validation_error else "passed",
            duration_ms=_duration_ms(start),
            error=parsed.get("content", "") if status == "failed" else "",
        ),
    }


def _validate_file_signature(file_path: Path, file_type: str) -> str | None:
    """按路由类型做轻量文件头校验，避免后缀伪装导致底层 parser 报错。"""
    if file_type == "unsupported":
        return None
    if not file_path.exists():
        return f"文件不存在: {file_path}"

    suffix = file_path.suffix.lower() or "UNKNOWN"
    if file_type == "pdf" and not _file_starts_with(file_path, b"%PDF-"):
        return f"文件扩展名为 {suffix}，但文件内容不是有效 PDF，请确认文件类型"
    if file_type == "word" and not _is_docx_file(file_path):
        return f"文件扩展名为 {suffix}，但文件内容不是有效 DOCX，请确认文件类型"
    if file_type == "html_archive" and not zipfile.is_zipfile(file_path):
        return f"文件扩展名为 {suffix}，但文件内容不是有效 ZIP，请确认文件类型"
    if file_type == "html" and _looks_like_binary_document(file_path):
        return f"文件扩展名为 {suffix}，但文件内容不像有效 HTML，请确认文件类型"
    if file_type == "image" and not _is_readable_image(file_path):
        return f"文件扩展名为 {suffix}，但文件内容不是有效图片，请确认文件类型"
    return None


def _file_starts_with(file_path: Path, prefix: bytes) -> bool:
    return _read_file_head(file_path, len(prefix)) == prefix


def _is_docx_file(file_path: Path) -> bool:
    if not zipfile.is_zipfile(file_path):
        return False
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def _looks_like_binary_document(file_path: Path) -> bool:
    head = _read_file_head(file_path, 512)
    return b"\x00" in head or head.startswith((b"PK\x03\x04", b"%PDF-", b"\x89PNG", b"\xff\xd8\xff"))


def _is_readable_image(file_path: Path) -> bool:
    try:
        with Image.open(file_path) as image:
            image.verify()
        return True
    except Exception:
        return False


def _read_file_head(file_path: Path, size: int) -> bytes:
    with file_path.open("rb") as file:
        return file.read(size)


def _metadata_extraction_agent(
    state: WorkflowState,
    metadata_extractor: MetadataExtractor | None,
) -> dict[str, Any]:
    """抽取文档元信息：优先真实 LLM，失败后降级。"""
    start = perf_counter()
    content = state.get("content", "")
    blocks = state.get("blocks", [])
    trace_extra: dict[str, Any] = {}
    fallback_used = False
    model_event: dict[str, Any] | None = None

    parser_metadata = dict(state.get("metadata", {}))

    if metadata_extractor is not None:
        metadata = metadata_extractor(content, blocks)
        mode = "mock_or_llm"
        model_event = _model_event(
            stage="metadata",
            model_type="llm",
            model="mock_or_llm",
            status="success",
            duration_ms=_duration_ms(start),
            input_items=len(blocks),
            output_items=1,
            details={"input_chars": len(content)},
        )
    elif not settings.metadata_enabled:
        metadata = _heuristic_metadata(content, blocks)
        mode = "disabled_fallback"
        fallback_used = True
        model_event = _model_event(
            stage="metadata",
            model_type="llm",
            model=settings.llm_model,
            status="skipped",
            duration_ms=_duration_ms(start),
            fallback_used=True,
            input_items=len(blocks),
            output_items=1,
            error="METADATA_ENABLED=false",
            details={"input_chars": len(content)},
        )
    elif is_metadata_enabled():
        try:
            metadata = extract_metadata_with_llm(content, blocks)
            mode = "llm"
            model_event = _model_event(
                stage="metadata",
                model_type="llm",
                model=settings.llm_model,
                status="success",
                duration_ms=_duration_ms(start),
                input_items=len(blocks),
                output_items=1,
                details={"input_chars": len(content)},
            )
        except Exception as exc:
            metadata = _heuristic_metadata(content, blocks)
            mode = "llm_failed_fallback"
            fallback_used = True
            trace_extra["llm_error"] = str(exc)
            model_event = _model_event(
                stage="metadata",
                model_type="llm",
                model=settings.llm_model,
                status="failed",
                duration_ms=_duration_ms(start),
                fallback_used=True,
                input_items=len(blocks),
                output_items=1,
                error=str(exc),
                details={"input_chars": len(content)},
            )
    else:
        metadata = _heuristic_metadata(content, blocks)
        mode = "heuristic_fallback"
        fallback_used = True
        model_event = _model_event(
            stage="metadata",
            model_type="llm",
            model=settings.llm_model,
            status="skipped",
            duration_ms=_duration_ms(start),
            fallback_used=True,
            input_items=len(blocks),
            output_items=1,
            error="未配置 LLM API key",
            details={"input_chars": len(content)},
        )

    metadata = {**parser_metadata, **metadata}
    runtime_metrics = state.get("runtime_metrics")
    if model_event is not None:
        runtime_metrics = add_runtime_event(runtime_metrics, model_event)

    return {
        "metadata": metadata,
        "status": _combine_status(state.get("status"), "partial_success" if fallback_used else "success"),
        "runtime_metrics": runtime_metrics,
        "agent_trace": _trace(
            state,
            "metadata_extraction_agent",
            "抽取作者、发布时间、机构、主题等元信息",
            status="partial_success" if fallback_used else "success",
            mode=mode,
            model=settings.llm_model if mode in {"llm", "llm_failed_fallback"} else "",
            input_chars=len(content),
            block_count=len(blocks),
            extracted_keys=sorted(metadata.keys()),
            duration_ms=_duration_ms(start),
            fallback_used=fallback_used,
            error=str(trace_extra.get("llm_error", "")),
            **trace_extra,
        ),
    }


def _vision_understanding_agent(
    state: WorkflowState,
    vision_understander: VisionUnderstander | None,
) -> dict[str, Any]:
    """对图片 block 进行视觉理解：优先真实 VLM，失败后标记 pending。"""
    start = perf_counter()
    blocks = list(state.get("blocks", []))
    assets = state.get("assets", [])
    image_count = sum(1 for block in blocks if block.get("type") == "image")
    inserted_text_count = 0
    trace_extra: dict[str, Any] = {}
    mode = "skipped"
    fallback_used = False
    model_event: dict[str, Any] | None = None

    node_status = "success"
    if image_count == 0:
        message = "未发现图片 block，跳过视觉理解"
        node_status = "skipped"
    elif vision_understander is not None:
        blocks = vision_understander(blocks, assets)
        blocks, inserted_text_count = _insert_image_text_blocks(blocks)
        message = "已通过视觉理解器增强图片 block"
        mode = "mock_or_llm"
        node_status = _image_blocks_status(blocks)
        success_images = _count_images_by_status(blocks, {"success"})
        model_event = _model_event(
            stage="vision",
            model_type="vlm",
            model="mock_or_llm",
            status=node_status,
            duration_ms=_duration_ms(start),
            fallback_used=node_status == "partial_success",
            input_items=image_count,
            output_items=success_images,
            details=_vision_event_details(blocks, inserted_text_count),
        )
    elif not settings.vision_enabled:
        blocks = _mark_images_pending(blocks, "视觉理解已被配置关闭，图片描述待生成")
        message = "VISION_ENABLED=false，图片 block 标记为 pending"
        mode = "disabled_fallback"
        fallback_used = image_count > 0
        node_status = "partial_success" if image_count > 0 else "skipped"
        model_event = _model_event(
            stage="vision",
            model_type="vlm",
            model=settings.llm_model,
            status="skipped",
            duration_ms=_duration_ms(start),
            fallback_used=fallback_used,
            input_items=image_count,
            output_items=0,
            error="VISION_ENABLED=false",
            details=_vision_event_details(blocks, inserted_text_count),
        )
    elif is_vision_enabled():
        try:
            blocks = understand_images_with_vlm(blocks, assets)
            blocks, inserted_text_count = _insert_image_text_blocks(blocks)
            message = "已通过多模态大模型增强图片 block"
            mode = "vlm"
            node_status = _image_blocks_status(blocks)
            success_images = _count_images_by_status(blocks, {"success"})
            fallback_used = node_status == "partial_success"
            model_event = _model_event(
                stage="vision",
                model_type="vlm",
                model=settings.llm_model,
                status=node_status,
                duration_ms=_duration_ms(start),
                fallback_used=fallback_used,
                input_items=image_count,
                output_items=success_images,
                error=_first_image_error(blocks),
                details=_vision_event_details(blocks, inserted_text_count),
            )
        except Exception as exc:
            blocks = _mark_images_pending(blocks, "模型调用失败，待重试生成图片描述")
            message = "视觉模型调用失败，图片 block 标记为 pending"
            mode = "vlm_failed_fallback"
            fallback_used = True
            trace_extra["vlm_error"] = str(exc)
            node_status = "partial_success"
            model_event = _model_event(
                stage="vision",
                model_type="vlm",
                model=settings.llm_model,
                status="failed",
                duration_ms=_duration_ms(start),
                fallback_used=True,
                input_items=image_count,
                output_items=0,
                error=str(exc),
                details=_vision_event_details(blocks, inserted_text_count),
            )
    else:
        blocks = _mark_images_pending(blocks, "待接入多模态大模型 生成图片描述")
        message = "无视觉模型 API key，图片 block 标记为 pending"
        mode = "pending_fallback"
        fallback_used = image_count > 0
        node_status = "partial_success" if image_count > 0 else "skipped"
        model_event = _model_event(
            stage="vision",
            model_type="vlm",
            model=settings.llm_model,
            status="skipped",
            duration_ms=_duration_ms(start),
            fallback_used=fallback_used,
            input_items=image_count,
            output_items=0,
            error="未配置 VLM API key",
            details=_vision_event_details(blocks, inserted_text_count),
        )

    runtime_metrics = state.get("runtime_metrics")
    if model_event is not None:
        runtime_metrics = add_runtime_event(runtime_metrics, model_event)

    return {
        "blocks": blocks,
        "status": _combine_status(state.get("status"), node_status),
        "runtime_metrics": runtime_metrics,
        "agent_trace": _trace(
            state,
            "vision_understanding_agent",
            message,
            status=node_status,
            mode=mode,
            model=settings.llm_model if mode in {"vlm", "vlm_failed_fallback"} else "",
            image_count=image_count,
            inserted_text_count=inserted_text_count,
            duration_ms=_duration_ms(start),
            fallback_used=fallback_used,
            error=str(trace_extra.get("vlm_error", "")),
            **trace_extra,
        ),
    }


def _image_blocks_status(blocks: list[dict[str, Any]]) -> str:
    image_blocks = [block for block in blocks if block.get("type") == "image"]
    if not image_blocks:
        return "skipped"
    for block in image_blocks:
        vision_status = dict(block.get("metadata", {})).get("vision_status")
        if vision_status in {"pending", "failed"}:
            return "partial_success"
    return "success"


def _model_event(
    *,
    stage: str,
    model_type: str,
    model: str = "",
    status: str = "success",
    duration_ms: int = 0,
    fallback_used: bool = False,
    input_items: int = 0,
    output_items: int = 0,
    error: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "model_type": model_type,
        "model": model,
        "status": status,
        "duration_ms": duration_ms,
        "fallback_used": fallback_used,
        "input_items": input_items,
        "output_items": output_items,
        "error": error,
        "details": details or {},
    }


def _count_images_by_status(blocks: list[dict[str, Any]], statuses: set[str]) -> int:
    count = 0
    for block in blocks:
        if block.get("type") != "image":
            continue
        status = str(dict(block.get("metadata", {})).get("vision_status") or "")
        if status in statuses:
            count += 1
    return count


def _vision_event_details(blocks: list[dict[str, Any]], inserted_text_count: int) -> dict[str, Any]:
    return {
        "success_images": _count_images_by_status(blocks, {"success"}),
        "pending_images": _count_images_by_status(blocks, {"pending"}),
        "failed_images": _count_images_by_status(blocks, {"failed"}),
        "skipped_images": _count_images_by_status(blocks, {"skipped"}),
        "inserted_text_count": inserted_text_count,
        "vision_max_images_per_file": settings.vision_max_images_per_file,
    }


def _first_image_error(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block.get("type") != "image":
            continue
        error = dict(block.get("metadata", {})).get("vision_error")
        if error:
            return str(error)
    return ""


def _insert_image_text_blocks(blocks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """按来源决定图片文字是否进入正文；普通插图只保留在 metadata。"""
    updated: list[dict[str, Any]] = []
    inserted_count = 0
    inserted_keys: set[str] = set()

    for block in blocks:
        metadata = dict(block.get("metadata", {}))
        if block.get("type") == "paragraph" and metadata.get("source") in {"pdf_image_text", "image_text"}:
            linked_image = str(metadata.get("linked_image") or "")
            if linked_image:
                inserted_keys.add(linked_image)
            updated.append(block)
            continue

        if block.get("type") == "image":
            extracted_text = str(metadata.get("extracted_text") or "").strip()
            file_name = str(metadata.get("file_name") or "")
            paragraph_source = ""
            if metadata.get("ocr_candidate"):
                paragraph_source = "pdf_image_text"
            elif metadata.get("source") == "image":
                paragraph_source = "image_text"

            if extracted_text and paragraph_source and file_name not in inserted_keys:
                updated.append(
                    {
                        "type": "paragraph",
                        "content": extracted_text,
                        "metadata": {
                            "source": paragraph_source,
                            "page_number": metadata.get("page_number"),
                            "linked_image": file_name,
                            "vision_mode": "ocr_and_description",
                        },
                    }
                )
                inserted_keys.add(file_name)
                inserted_count += 1

        updated.append({**block, "metadata": metadata} if block.get("type") == "image" else block)

    return updated, inserted_count


def _mark_images_pending(blocks: list[dict[str, Any]], description: str) -> list[dict[str, Any]]:
    updated = [dict(block) for block in blocks]
    for block in updated:
        if block.get("type") == "image":
            metadata = dict(block.get("metadata", {}))
            metadata.setdefault("vision_status", "pending")
            metadata.setdefault("description", description)
            block["metadata"] = metadata
    return updated


def _result_normalizer_agent(state: WorkflowState) -> dict[str, Any]:
    """统一输出字段，并用增强后的 blocks 重新生成最终正文。"""
    start = perf_counter()
    blocks = list(state.get("blocks", []))
    assets = list(state.get("assets", []))
    metadata = dict(state.get("metadata", {}))
    errors = list(state.get("errors", []))

    normalized_blocks = []
    for block in blocks:
        block_metadata = _normalize_block_metadata(dict(block.get("metadata", {})))
        block_content = block.get("content", "")
        if block.get("type") == "image" and not block_content:
            block_content = block_metadata.get("description", "")
        normalized_blocks.append(
            {
                "type": block.get("type", "paragraph"),
                "content": block_content,
                "metadata": block_metadata,
            }
        )

    status = "failed" if errors else state.get("status", "success")
    metadata.setdefault("author", "未知")
    metadata.setdefault("posted_time", "未知")
    metadata.setdefault("organization", "未知")
    metadata.setdefault("topic", "未知")
    metadata.setdefault("summary", "未知")

    content = render_blocks_to_text(normalized_blocks)
    if not content.strip() and state.get("content"):
        content = str(state.get("content") or "")

    return {
        "content": content,
        "blocks": normalized_blocks,
        "assets": assets,
        "metadata": metadata,
        "status": status,
        "agent_trace": _trace(
            state,
            "result_normalizer_agent",
            "统一输出字段，保证 API 响应稳定",
            status=status,
            error_count=len(errors),
            content_chars=len(content),
            block_count=len(normalized_blocks),
            asset_count=len(assets),
            duration_ms=_duration_ms(start),
            error="; ".join(errors),
        ),
    }


def _normalize_block_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """把底层定位字段收进 debug_metadata，默认 JSON 更面向业务阅读。"""
    normalized = dict(metadata)
    debug_metadata = normalized.get("debug_metadata")
    debug: dict[str, Any] = dict(debug_metadata) if isinstance(debug_metadata, dict) else {}

    for key in DEBUG_METADATA_KEYS:
        if key not in normalized:
            continue
        value = normalized.pop(key)
        if value is None or value == "":
            continue
        debug[key] = value

    if debug:
        normalized["debug_metadata"] = debug
    else:
        normalized.pop("debug_metadata", None)
    return normalized


def _rag_chunking_agent(state: WorkflowState) -> dict[str, Any]:
    """把最终 blocks 转成面向 RAG/知识库入库的 chunks。"""
    start = perf_counter()
    chunks = _build_rag_chunks(
        blocks=list(state.get("blocks", [])),
        assets=list(state.get("assets", [])),
        source_file=Path(state.get("file_path", "")).name,
    )
    return {
        "chunks": chunks,
        "agent_trace": _trace(
            state,
            "rag_chunking_agent",
            "生成面向知识库/RAG 入库的 chunks",
            chunk_count=len(chunks),
            content_chars=sum(len(chunk.get("content", "")) for chunk in chunks),
            duration_ms=_duration_ms(start),
        ),
    }


def _build_rag_chunks(
    blocks: list[dict[str, Any]],
    assets: list[dict[str, str]],
    source_file: str,
    target_chars: int = CHUNK_TARGET_CHARS,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    asset_names = {asset.get("file_name") for asset in assets if asset.get("file_name")}
    buffer_parts: list[str] = []
    buffer_types: list[str] = []
    buffer_pages: list[Any] = []
    buffer_assets: list[str] = []
    buffer_sources: list[str] = []
    heading_path: list[str] = []

    def flush_buffer() -> None:
        content = "\n".join(part for part in buffer_parts if part.strip()).strip()
        if not content:
            buffer_parts.clear()
            buffer_types.clear()
            buffer_pages.clear()
            buffer_assets.clear()
            buffer_sources.clear()
            return
        chunk_metadata = {
            "block_types": _dedupe(buffer_types),
            "source_file": source_file,
            "page_number": _first_nonempty(buffer_pages),
            "asset_refs": _dedupe(buffer_assets),
            "heading_path": list(heading_path),
        }
        sources = _dedupe(buffer_sources)
        if sources:
            chunk_metadata["block_sources"] = sources
        if any(source in {"pdf_image_text", "image_text"} for source in sources):
            chunk_metadata["ocr_review_required"] = True
        _append_chunk(chunks, content, chunk_metadata)
        buffer_parts.clear()
        buffer_types.clear()
        buffer_pages.clear()
        buffer_assets.clear()
        buffer_sources.clear()

    for block in blocks:
        block_type = str(block.get("type") or "paragraph")
        metadata = dict(block.get("metadata", {}))
        content = str(block.get("content") or "").strip()
        page_number = metadata.get("page_number")

        if block_type == "title" and content:
            heading_path[:] = _updated_heading_path(heading_path, content, metadata.get("level"))

        if block_type == "image":
            content = content or str(metadata.get("description") or "").strip()
            if not content:
                continue
            flush_buffer()
            file_name = str(metadata.get("file_name") or "")
            asset_refs = [file_name] if file_name and file_name in asset_names else ([file_name] if file_name else [])
            chunk_metadata: dict[str, Any] = {
                "block_types": ["image"],
                "source_file": source_file,
                "page_number": page_number,
                "asset_refs": asset_refs,
                "heading_path": list(heading_path),
            }
            if metadata.get("extracted_text"):
                chunk_metadata["extracted_text"] = metadata.get("extracted_text")
            if metadata.get("image_role"):
                chunk_metadata["image_role"] = metadata.get("image_role")
            vision_status = metadata.get("vision_status")
            if vision_status:
                chunk_metadata["vision_status"] = vision_status
            if _should_disable_image_chunk(content, metadata):
                chunk_metadata["ingest_enabled"] = False
            _append_chunk(chunks, content, chunk_metadata)
            continue

        if not content:
            continue

        if block_type == "table":
            flush_buffer()
            rows = metadata.get("rows") or []
            row_count = len(rows) if isinstance(rows, list) else metadata.get("row_count", 0)
            col_count = max((len(row) for row in rows if isinstance(row, list)), default=0) if isinstance(rows, list) else 0
            table_content = _prepend_heading_path(content, heading_path)
            _append_chunk(
                chunks,
                table_content,
                {
                    "block_types": ["table"],
                    "source_file": source_file,
                    "page_number": page_number,
                    "asset_refs": [],
                    "heading_path": list(heading_path),
                    "row_count": row_count,
                    "col_count": col_count,
                },
            )
            continue

        if block_type == "paragraph" and len(content) > target_chars:
            for segment in _split_long_text_by_natural_boundaries(content, target_chars):
                if buffer_parts and len("\n".join(buffer_parts)) + len(segment) + 1 > target_chars:
                    flush_buffer()
                buffer_parts.append(segment)
                buffer_types.append(block_type)
                buffer_pages.append(page_number)
                if metadata.get("source"):
                    buffer_sources.append(str(metadata.get("source")))
            continue

        if block_type == "title":
            flush_buffer()
        elif buffer_parts and len("\n".join(buffer_parts)) + len(content) + 1 > target_chars:
            flush_buffer()

        buffer_parts.append(content)
        buffer_types.append(block_type)
        buffer_pages.append(page_number)
        if metadata.get("source"):
            buffer_sources.append(str(metadata.get("source")))

    flush_buffer()
    return chunks


def _split_long_text_by_natural_boundaries(text: str, target_chars: int) -> list[str]:
    """长段落优先按自然语句边界切分，找不到边界时才硬切。"""
    if len(text) <= target_chars:
        return [text]
    pieces = [piece.strip() for piece in re.split(r"(?<=[。！？；.!?;])\s*|\n+", text) if piece.strip()]
    if len(pieces) <= 1:
        return _hard_split_text(text, target_chars)

    segments: list[str] = []
    current_parts: list[str] = []

    def flush_current() -> None:
        content = "".join(current_parts).strip()
        if content:
            segments.append(content)
        current_parts.clear()

    for piece in pieces:
        if len(piece) > target_chars:
            flush_current()
            segments.extend(_hard_split_text(piece, target_chars))
            continue
        current_len = len("".join(current_parts))
        if current_parts and current_len + len(piece) > target_chars:
            flush_current()
        current_parts.append(piece)

    flush_current()
    return segments or _hard_split_text(text, target_chars)


def _hard_split_text(text: str, target_chars: int) -> list[str]:
    if target_chars <= 0:
        return [text]
    return [text[index : index + target_chars].strip() for index in range(0, len(text), target_chars) if text[index : index + target_chars].strip()]


def _prepend_heading_path(content: str, heading_path: list[str]) -> str:
    path_text = " > ".join(item.strip() for item in heading_path if item.strip())
    if not path_text:
        return content
    return f"{path_text}\n\n{content}"


def _append_chunk(chunks: list[dict[str, Any]], content: str, metadata: dict[str, Any]) -> None:
    chunk_index = len(chunks) + 1
    metadata = dict(metadata)
    metadata["chunk_index"] = chunk_index
    metadata["char_count"] = len(content)
    metadata.setdefault("ingest_enabled", True)
    chunks.append(
        {
            "chunk_id": f"chunk_{chunk_index}",
            "content": content,
            "metadata": metadata,
        }
    )


def _updated_heading_path(current_path: list[str], title: str, level: Any) -> list[str]:
    try:
        normalized_level = int(level)
    except (TypeError, ValueError):
        normalized_level = len(current_path) + 1 if current_path else 1
    normalized_level = max(1, normalized_level)
    next_path = list(current_path[: normalized_level - 1])
    next_path.append(title)
    return next_path


def _should_disable_image_chunk(content: str, metadata: dict[str, Any]) -> bool:
    vision_status = str(metadata.get("vision_status") or "").strip().lower()
    if vision_status in {"pending", "failed"}:
        return True
    pending_markers = ["待接入", "待生成", "模型调用失败", "图片描述可能仍是占位文本"]
    return any(marker in content for marker in pending_markers)


def _dedupe(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value in {None, ""} or value in result:
            continue
        result.append(value)
    return result


def _first_nonempty(values: list[Any]) -> Any:
    for value in values:
        if value not in {None, ""}:
            return value
    return None


def _heuristic_metadata(content: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    author = _match_first(content, [r"作者[:：]\s*([^\n\r]+)", r"撰写人[:：]\s*([^\n\r]+)"])
    organization = _match_first(
        content,
        [
            r"学院[:：]\s*([^\n\r]+)",
            r"学校[:：]\s*([^\n\r]+)",
            r"院系[:：]\s*([^\n\r]+)",
            r"部门[:：]\s*([^\n\r]+)",
            r"单位[:：]\s*([^\n\r]+)",
            r"机构[:：]\s*([^\n\r]+)",
        ],
    )
    posted_time = _match_first(
        content,
        [
            r"(\d{4}[年./-]\d{1,2}[月./-]\d{1,2}日?)",
            r"(\d{4}[年./-]\d{1,2}月?)",
        ],
    )

    topic = "未知"
    for block in blocks:
        if block.get("type") == "title" and block.get("content"):
            topic = block["content"]
            break
    if topic == "未知":
        topic = _first_short_paragraph(blocks) or "未知"

    return {
        "author": author or "未知",
        "posted_time": posted_time or "未知",
        "organization": organization or "未知",
        "topic": topic,
        "summary": "未知",
        "extraction_mode": "heuristic_fallback",
    }


def _match_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def _first_short_paragraph(blocks: list[dict[str, Any]]) -> str | None:
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        content = str(block.get("content") or "").strip()
        if 4 <= len(content) <= 80 and not content.endswith(("。", "！", "？", "；", ".", "!", "?", ";")):
            return content
    return None

