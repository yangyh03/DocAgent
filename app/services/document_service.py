from datetime import datetime
import asyncio
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from app.schemas import DocumentBlock, DocumentChunk, FileResult, QualityHint, TaskStatus
from app.services.task_service import task_service
from app.parsers.word_parser import render_blocks_to_text
from app.workflow.graph import _build_rag_chunks
from app.workflow.graph import run_docagent_workflow


WORKFLOW_NODE_PROGRESS = {
    "router": ("Workflow: router 文件路由", 4),
    "parser_tool": ("Workflow: parser_tool 基础解析", 18),
    "metadata_extraction_agent": ("Workflow: metadata_extraction_agent 元信息抽取", 45),
    "vision_understanding_agent": ("Workflow: vision_understanding_agent 图片理解", 65),
    "result_normalizer_agent": ("Workflow: result_normalizer_agent 结果标准化", 82),
    "rag_chunking_agent": ("Workflow: rag_chunking_agent 知识库切片", 92),
}
LOCAL_PATH_METADATA_KEYS = {"path", "archive_path", "selected_html_path"}
METADATA_FIELD_LABELS = {
    "author": "作者",
    "posted_time": "发布时间",
    "organization": "机构",
    "topic": "主题",
    "summary": "摘要",
}


def parse_file(
    file_path: Path,
    task_id: str = "",
    server_source: str = "",
    progress_callback=None,
) -> dict[str, Any]:
    return run_docagent_workflow(
        file_path=file_path,
        task_id=task_id,
        server_source=server_source,
        progress_callback=progress_callback,
    )


async def run_analysis_task(
    task_id: str,
    file_paths: list[Path],
    server_source: str,
) -> None:
    try:
        task_service.update_status(task_id, TaskStatus.running, "正在解析")
        total_files = len(file_paths)
        task_service.update_progress(
            task_id,
            processed_files=0,
            current_file="",
            current_step="准备解析",
            percent=0,
        )
        results: list[FileResult] = []
        for index, file_path in enumerate(file_paths):
            task_service.update_progress(
                task_id,
                processed_files=index,
                current_file=file_path.name,
                current_step=f"正在解析第 {index + 1}/{total_files} 个文件",
                percent=_in_progress_percent(index, total_files),
            )
            try:
                def update_workflow_step(node_name: str) -> None:
                    step_name, node_percent = WORKFLOW_NODE_PROGRESS.get(
                        node_name,
                        (f"Workflow: {node_name}", 50),
                    )
                    task_service.update_progress(
                        task_id,
                        processed_files=index,
                        current_file=file_path.name,
                        current_step=step_name,
                        percent=_node_progress_percent(index, total_files, node_percent),
                    )

                parsed = await asyncio.to_thread(
                    parse_file,
                    file_path,
                    task_id=task_id,
                    server_source=server_source,
                    progress_callback=update_workflow_step,
                )
            except Exception as exc:
                parsed = _failed_parse_result(f"解析文件时发生异常: {exc}")

            file_result = _build_file_result(file_path, parsed, server_source)
            file_result.qualityHints = _build_quality_hints(file_result)
            results.append(file_result)
            task_service.update_progress(
                task_id,
                processed_files=index + 1,
                current_file=file_path.name,
                current_step=f"已完成第 {index + 1}/{total_files} 个文件",
                percent=_progress_percent(index + 1, total_files),
            )
        task_service.set_result(task_id, results)
    except Exception as exc:
        task_service.update_status(task_id, TaskStatus.failed, str(exc))
        task_service.update_progress(task_id, current_step="任务失败")


def _progress_percent(processed_files: int, total_files: int) -> int:
    if total_files <= 0:
        return 0
    return max(0, min(100, int(processed_files / total_files * 100)))


def _in_progress_percent(current_index: int, total_files: int) -> int:
    if total_files <= 0:
        return 0
    completed = _progress_percent(current_index, total_files)
    step = max(1, int(100 / total_files * 0.2))
    return max(1, min(95, completed + step))


def _node_progress_percent(current_index: int, total_files: int, node_percent: int) -> int:
    if total_files <= 0:
        return 0
    per_file = 100 / total_files
    percent = current_index * per_file + per_file * (node_percent / 100)
    return max(1, min(99, int(percent)))


def _failed_parse_result(message: str) -> dict[str, Any]:
    return {
        "content": message,
        "status": "failed",
        "blocks": [],
        "assets": [],
        "chunks": [],
        "metadata": {"runtime_error": message},
        "agent_trace": [],
    }


def _build_file_result(file_path: Path, parsed: dict[str, Any], server_source: str) -> FileResult:
    file_status = _normalize_file_status(parsed.get("status"))
    error_message = _extract_error_message(parsed) if file_status == "failed" else ""
    content = parsed.get("content", "")
    if file_status == "failed" and not str(content).strip():
        content = error_message or "解析失败"

    return FileResult(
        fileName=file_path.name,
        fileType=file_path.suffix.upper().lstrip(".") or "UNKNOWN",
        fileUrl=str(file_path),
        fileContent=content,
        fileSource=server_source,
        createDate=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        status=file_status,
        errorMessage=error_message,
        blocks=_sanitize_blocks_for_api(parsed.get("blocks", [])),
        assets=_sanitize_assets_for_api(parsed.get("assets", [])),
        chunks=parsed.get("chunks", []),
        metadata=_sanitize_metadata_for_api(parsed.get("metadata", {})),
        agentTrace=parsed.get("agent_trace", []),
        runtimeMetrics=parsed.get("runtime_metrics", {}),
    )


def _normalize_file_status(status: Any) -> str:
    return str(status) if status in {"success", "partial_success", "failed"} else "success"


def _sanitize_blocks_for_api(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for block in blocks:
        updated = dict(block)
        metadata = dict(updated.get("metadata", {}))
        for key in LOCAL_PATH_METADATA_KEYS:
            if key in metadata and not _is_public_url(metadata[key]):
                metadata.pop(key, None)
        updated["metadata"] = metadata
        sanitized.append(updated)
    return sanitized


def _sanitize_assets_for_api(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for asset in assets:
        updated = dict(asset)
        # 前端预览通过 task_id + file_name 访问受控接口，默认 JSON 不暴露本地路径。
        if not _is_public_url(updated.get("path")):
            updated["path"] = ""
        sanitized.append(updated)
    return sanitized


def _sanitize_metadata_for_api(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(metadata)
    for key in LOCAL_PATH_METADATA_KEYS:
        if key in sanitized and not _is_public_url(sanitized[key]):
            sanitized.pop(key, None)
    return sanitized


def _is_public_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_error_message(parsed: dict[str, Any]) -> str:
    errors = parsed.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(error) for error in errors if error)
    content = str(parsed.get("content") or "").strip()
    if content:
        return content
    metadata = parsed.get("metadata", {})
    if isinstance(metadata, dict):
        return str(metadata.get("validation_error") or metadata.get("runtime_error") or "解析失败")
    return "解析失败"


def _build_quality_hints(file_result: FileResult) -> list[QualityHint]:
    hints: list[QualityHint] = []
    blocks = file_result.blocks
    chunks = file_result.chunks
    metadata = file_result.metadata
    trace = file_result.agentTrace

    if file_result.status == "failed":
        hints.append(
            QualityHint(
                level="error",
                code="parse_failed",
                message=file_result.errorMessage or "文件解析失败，请检查文件类型或内容是否有效。",
            )
        )

    if not blocks:
        hints.append(
            QualityHint(
                level="error" if file_result.status == "failed" else "warning",
                code="no_blocks",
                message="未生成结构块，请检查文件类型、正文内容或解析错误。",
            )
        )

    if not chunks:
        hints.append(
            QualityHint(
                level="warning",
                code="no_chunks",
                message="未生成知识库切片，暂不适合直接入库检索。",
            )
        )
    else:
        disabled_chunks = [
            chunk for chunk in chunks if chunk.metadata.get("ingest_enabled") is False
        ]
        enabled_chunks = [
            chunk for chunk in chunks if chunk.metadata.get("ingest_enabled") is not False
        ]
        if not enabled_chunks:
            hints.append(
                QualityHint(
                    level="warning",
                    code="no_enabled_chunks",
                    message="当前没有可入库切片，请至少启用一个 chunk 或重新校正内容。",
                )
            )
        elif disabled_chunks:
            hints.append(
                QualityHint(
                    level="info",
                    code="chunks_disabled",
                    message=f"{len(disabled_chunks)} 个切片被标记为不入库。",
                )
            )

    pending_images = [
        block
        for block in blocks
        if block.type == "image" and block.metadata.get("vision_status") in {"pending", "failed"}
    ]
    if pending_images:
        hints.append(
            QualityHint(
                level="warning",
                code="pending_images",
                message=f"{len(pending_images)} 张图片未完成视觉理解，图片描述可能仍是占位文本。",
            )
        )

    unknown_keys = [
        key
        for key in ["author", "posted_time", "organization", "topic", "summary"]
        if not metadata.get(key) or metadata.get(key) == "未知"
    ]
    if unknown_keys:
        unknown_labels = "、".join(METADATA_FIELD_LABELS.get(key, key) for key in unknown_keys)
        hints.append(
            QualityHint(
                level="info",
                code="metadata_unknown",
                message=(
                    f"{len(unknown_keys)} 个元信息字段仍为未知：{unknown_labels}。"
                    "概览页已隐藏这些未知字段，可后续人工补充，或优化元信息抽取提示词。"
                ),
            )
        )

    fallback_count = sum(1 for item in trace if item.get("fallback_used"))
    if fallback_count:
        hints.append(
            QualityHint(
                level="info",
                code="fallback_used",
                message=f"{fallback_count} 个工作流节点使用了降级逻辑，结果可用但建议抽查。",
            )
        )

    runtime_events = file_result.runtimeMetrics.events
    disabled_events = [
        event
        for event in runtime_events
        if event.status == "skipped" and event.fallback_used and event.stage in {"metadata", "vision"}
    ]
    if disabled_events:
        stages = "、".join(_runtime_stage_label(event.stage) for event in disabled_events)
        hints.append(
            QualityHint(
                level="warning",
                code="model_disabled",
                message=f"{stages} 模型未启用或已被配置关闭，相关智能增强未执行。",
            )
        )

    failed_events = [event for event in runtime_events if event.status == "failed"]
    if failed_events:
        stages = "、".join(_runtime_stage_label(event.stage) for event in failed_events)
        hints.append(
            QualityHint(
                level="warning",
                code="model_call_failed",
                message=f"{stages} 模型调用失败，系统已保留可用解析结果并走降级逻辑。",
            )
        )

    limited_images = [
        block
        for block in blocks
        if block.type == "image" and "VISION_MAX_IMAGES_PER_FILE" in str(block.metadata.get("vision_error") or "")
    ]
    if limited_images:
        hints.append(
            QualityHint(
                level="warning",
                code="vision_limit_reached",
                message=f"{len(limited_images)} 张图片超过单文件视觉理解上限，未调用视觉模型。",
            )
        )

    if not hints:
        hints.append(
            QualityHint(
                level="info",
                code="quality_ok",
                message="结构、切片和执行轨迹完整，适合继续做人工抽查或入库验证。",
            )
        )

    return hints


def _runtime_stage_label(stage: str) -> str:
    labels = {
        "metadata": "元信息抽取",
        "vision": "图片理解",
        "embedding": "向量入库",
        "qa": "知识库问答",
    }
    return labels.get(stage, stage)


def apply_block_corrections(task_id: str, file_index: int, blocks: list[DocumentBlock]) -> FileResult:
    results = task_service.get_result(task_id)
    if results is None:
        raise KeyError(task_id)
    if file_index < 0 or file_index >= len(results):
        raise IndexError(file_index)

    current = results[file_index]
    corrected_blocks = _prepare_corrected_blocks(current.blocks, blocks)
    content = render_blocks_to_text(corrected_blocks)
    chunks = _build_rag_chunks(
        blocks=corrected_blocks,
        assets=[asset.model_dump() for asset in current.assets],
        source_file=current.fileName,
    )
    trace = list(current.agentTrace)
    trace.append(
        {
            "node": "manual_correction",
            "message": "人工校正结构块后重新生成正文和知识库切片",
            "status": "success",
            "duration_ms": 0,
            "fallback_used": False,
            "error": "",
            "block_count": len(corrected_blocks),
            "chunk_count": len(chunks),
        }
    )

    updated_data = current.model_dump()
    updated_data.update(
        {
            "fileContent": content,
            "blocks": corrected_blocks,
            "chunks": chunks,
            "agentTrace": trace,
        }
    )
    updated = FileResult(**updated_data)
    updated.qualityHints = _build_quality_hints(updated)
    results[file_index] = updated
    task_service.set_result(task_id, results)
    return updated


def _prepare_corrected_blocks(
    original_blocks: list[DocumentBlock],
    corrected_blocks: list[DocumentBlock],
) -> list[dict[str, Any]]:
    original = [block.model_dump() for block in original_blocks]
    prepared: list[dict[str, Any]] = []
    for index, block_model in enumerate(corrected_blocks):
        block = block_model.model_dump()
        metadata = dict(block.get("metadata", {}))
        block_type = block.get("type")

        if block_type == "image":
            content = str(block.get("content") or "").strip()
            description = str(metadata.get("description") or "").strip()
            if content:
                metadata["description"] = content
            elif description:
                block["content"] = description

        original_block = original[index] if index < len(original) else {}
        if _block_was_edited(original_block, block):
            metadata["edited"] = True
            metadata["edit_source"] = "manual"

        block["metadata"] = metadata
        prepared.append(block)
    return prepared


def _block_was_edited(original_block: dict[str, Any], corrected_block: dict[str, Any]) -> bool:
    if not original_block:
        return True
    if original_block.get("type") != corrected_block.get("type"):
        return True
    if str(original_block.get("content") or "") != str(corrected_block.get("content") or ""):
        return True

    original_metadata = dict(original_block.get("metadata", {}))
    corrected_metadata = dict(corrected_block.get("metadata", {}))
    return str(original_metadata.get("description") or "") != str(corrected_metadata.get("description") or "")


def apply_chunk_corrections(task_id: str, file_index: int, chunks: list[DocumentChunk]) -> FileResult:
    results = task_service.get_result(task_id)
    if results is None:
        raise KeyError(task_id)
    if file_index < 0 or file_index >= len(results):
        raise IndexError(file_index)

    current = results[file_index]
    corrected_chunks = _prepare_corrected_chunks(current.chunks, chunks)
    trace = list(current.agentTrace)
    trace.append(
        {
            "node": "manual_chunk_correction",
            "message": "人工校正知识库切片入库草稿",
            "status": "success",
            "duration_ms": 0,
            "fallback_used": False,
            "error": "",
            "chunk_count": len(corrected_chunks),
            "enabled_chunk_count": sum(
                1 for chunk in corrected_chunks if dict(chunk.get("metadata", {})).get("ingest_enabled") is not False
            ),
        }
    )

    updated_data = current.model_dump()
    updated_data.update(
        {
            "chunks": corrected_chunks,
            "agentTrace": trace,
        }
    )
    updated = FileResult(**updated_data)
    updated.qualityHints = _build_quality_hints(updated)
    results[file_index] = updated
    task_service.set_result(task_id, results)
    return updated


def _prepare_corrected_chunks(
    original_chunks: list[DocumentChunk],
    corrected_chunks: list[DocumentChunk],
) -> list[dict[str, Any]]:
    original = [chunk.model_dump() for chunk in original_chunks]
    prepared: list[dict[str, Any]] = []
    for index, chunk_model in enumerate(corrected_chunks):
        chunk = chunk_model.model_dump()
        metadata = dict(chunk.get("metadata", {}))
        content = str(chunk.get("content") or "")
        metadata.setdefault("ingest_enabled", bool(content.strip()))
        if not content.strip():
            metadata["ingest_enabled"] = False

        original_chunk = original[index] if index < len(original) else {}
        if _chunk_was_edited(original_chunk, chunk):
            metadata["edited"] = True
            metadata["edit_source"] = "manual"

        metadata["char_count"] = len(content)
        chunk["metadata"] = metadata
        prepared.append(chunk)
    return prepared


def _chunk_was_edited(original_chunk: dict[str, Any], corrected_chunk: dict[str, Any]) -> bool:
    if not original_chunk:
        return True
    if str(original_chunk.get("content") or "") != str(corrected_chunk.get("content") or ""):
        return True
    original_metadata = dict(original_chunk.get("metadata", {}))
    corrected_metadata = dict(corrected_chunk.get("metadata", {}))
    return original_metadata.get("ingest_enabled", True) != corrected_metadata.get("ingest_enabled", True)
