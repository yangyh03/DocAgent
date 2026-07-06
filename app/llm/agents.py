from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from PIL import Image

from app.config import settings
from app.llm.client import create_chat_model, create_embedding_client

UNKNOWN = "未知"


def is_llm_enabled() -> bool:
    """只有显式配置 API key 时才调用真实模型，避免测试环境误触发网络请求。"""
    api_key = (settings.llm_api_key or "").strip()
    return bool(api_key and api_key.upper() != "EMPTY")


def is_metadata_enabled() -> bool:
    return settings.metadata_enabled and is_llm_enabled()


def is_vision_enabled() -> bool:
    return settings.vision_enabled and is_llm_enabled()


def is_qa_enabled() -> bool:
    return settings.qa_enabled and is_llm_enabled()


def is_embedding_enabled() -> bool:
    """只有显式配置 embedding key 时才构建向量索引。"""
    api_key = (settings.embedding_api_key or "").strip()
    return settings.embedding_enabled and bool(api_key and api_key.upper() != "EMPTY")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """调用 OpenAI-compatible embedding API，并按服务上限自动分批。"""
    if not texts:
        return []
    client = create_embedding_client()
    embeddings: list[list[float]] = []
    batch_size = settings.embedding_batch_size
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(model=settings.embedding_model, input=batch)
        embeddings.extend(list(item.embedding) for item in response.data)
    return embeddings


def answer_question_with_llm(question: str, sources: list[dict[str, Any]]) -> str:
    """基于检索片段生成回答，不把完整文档塞给模型。"""
    context = "\n\n".join(
        f"[来源 {index + 1}]\n{source.get('content', '')}"
        for index, source in enumerate(sources)
        if source.get("content")
    )
    llm = create_chat_model()
    response = llm.invoke(
        [
            {
                "role": "system",
                "content": (
                    "你是知识库问答助手。只能基于给定来源片段回答，不要编造。"
                    "如果来源片段不足以回答，请回答“当前文档中未找到足够依据”。"
                    "回答要简洁，并尽量指出依据来自哪些来源编号。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{question}\n\n检索来源：\n{context or '无'}",
            },
        ]
    )
    return str(getattr(response, "content", response)).strip()


def extract_metadata_with_llm(content: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """使用多模态大模型从压缩上下文中抽取文档元信息。"""
    context = build_metadata_context(content, blocks)
    llm = create_chat_model()
    response = llm.invoke(
        [
            {
                "role": "system",
                "content": (
                    "你是文档元信息抽取助手。请只返回 JSON，不要输出解释、Markdown 或代码块。"
                    "字段必须包含 author、posted_time、organization、topic、summary。"
                    "找不到的信息填'未知'。"
                ),
            },
            {
                "role": "user",
                "content": f"请从下面的文档上下文中抽取元信息：\n\n{context}",
            },
        ]
    )
    payload = parse_json_object(getattr(response, "content", str(response)))
    return normalize_metadata(payload, extraction_mode=f"llm:{settings.llm_model}")


def understand_images_with_vlm(blocks: list[dict[str, Any]], assets: list[dict[str, str]], ) -> list[dict[str, Any]]:
    """逐张图片调用多模态大模型，同时提取可见文字和语义描述。"""
    llm = create_chat_model()
    asset_by_name = {asset.get("file_name"): asset for asset in assets}
    updated_blocks = [dict(block) for block in blocks]

    processed_images = 0
    max_images = settings.vision_max_images_per_file
    for index, block in enumerate(updated_blocks):
        if block.get("type") != "image":
            continue

        metadata = dict(block.get("metadata", {}))
        if max_images and processed_images >= max_images:
            metadata["vision_status"] = "pending"
            metadata["description"] = "超过单文件图片理解数量上限，未调用视觉模型"
            metadata["vision_error"] = f"VISION_MAX_IMAGES_PER_FILE={max_images}"
            block["metadata"] = metadata
            continue

        asset = asset_by_name.get(metadata.get("file_name"), metadata)
        image_path = Path(asset.get("path", ""))
        if not image_path.exists():
            metadata["vision_status"] = "failed"
            metadata["description"] = "图片文件不存在，无法进行视觉理解"
            block["metadata"] = metadata
            continue

        dimensions = image_dimensions(image_path)
        if dimensions is None:
            metadata["vision_status"] = "failed"
            metadata["description"] = "图片文件无法读取，跳过视觉理解"
            block["metadata"] = metadata
            continue
        width, height = dimensions
        metadata["width"] = width
        metadata["height"] = height
        if width <= 10 or height <= 10:
            metadata["vision_status"] = "skipped"
            metadata["description"] = "图片尺寸过小，疑似图标或统计像素，跳过视觉理解"
            block["metadata"] = metadata
            continue

        try:
            processed_images += 1
            prompt = build_image_prompt(updated_blocks, index)
            image_url = image_to_data_url(image_path, asset.get("mime_type"))
            response = llm.invoke(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是文档图片理解助手。请只返回 JSON，不要输出解释、Markdown 或代码块。"
                            "字段包含 description、extracted_text、image_role、confidence。"
                            "description 是图片语义描述；extracted_text 是图片中可见文字原文，没有则为空字符串。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                        ],
                    },
                ]
            )
            vision_payload = normalize_vision_payload(getattr(response, "content", str(response)))
            metadata["vision_status"] = "success"
            metadata["description"] = vision_payload["description"]
            metadata["extracted_text"] = vision_payload["extracted_text"]
            metadata["image_role"] = vision_payload["image_role"]
            metadata["confidence"] = vision_payload["confidence"]
            metadata["vision_mode"] = "ocr_and_description"
            metadata["vision_model"] = settings.llm_model
        except Exception as exc:
            metadata["vision_status"] = "failed"
            metadata["description"] = "单张图片模型调用失败，待重试生成图片描述"
            metadata["vision_error"] = str(exc)
        block["metadata"] = metadata

    return updated_blocks


def normalize_vision_payload(text: str) -> dict[str, str]:
    """兼容 JSON 输出和普通文本输出，避免模型格式异常中断主流程。"""
    cleaned = text.strip()
    try:
        payload = parse_json_object(cleaned)
    except Exception:
        return {
            "description": cleaned,
            "extracted_text": "",
            "image_role": "unknown",
            "confidence": "unknown",
        }

    return {
        "description": str(payload.get("description") or cleaned).strip(),
        "extracted_text": str(payload.get("extracted_text") or "").strip(),
        "image_role": str(payload.get("image_role") or "unknown").strip(),
        "confidence": str(payload.get("confidence") or "unknown").strip(),
    }



def build_metadata_context(content: str, blocks: list[dict[str, Any]]) -> str:
    """为元信息抽取构造短上下文，避免把整篇文档无脑交给模型。
       只保留前 5 个标题、前 20 个段落，以及正文的前 6000 字和后 2000 字"""
    title_blocks = [block.get("content", "") for block in blocks if block.get("type") == "title"][:5]
    paragraph_blocks = [
        block.get("content", "")[:300]
        for block in blocks
        if block.get("type") == "paragraph" and block.get("content")
    ][:20]

    head = content[:6000]
    tail = content[-2000:] if len(content) > 6000 else ""
    return "\n\n".join(
        part
        for part in [
            "【标题候选】\n" + "\n".join(title_blocks) if title_blocks else "",
            "【前部正文】\n" + head if head else "",
            "【尾部正文】\n" + tail if tail else "",
            "【段落候选】\n" + "\n".join(paragraph_blocks) if paragraph_blocks else "",
        ]
        if part
    )


def build_image_prompt(blocks: list[dict[str, Any]], image_index: int) -> str:
    """为图片理解构造上下文提示，收集前后各 2 个文本块。"""
    before = collect_neighbor_text(blocks, image_index, direction=-1)
    after = collect_neighbor_text(blocks, image_index, direction=1)
    return (
        "这张图片来自一个文档，请结合上下文完成两件事："
        "1. 提取图片中可见文字原文；2. 描述图片内容和它可能承担的文档作用。\n"
        "如果图片是 PDF 扫描页或整页截图，请优先按阅读顺序提取正文文字。\n\n"
        f"【图片前文】\n{before or '无'}\n\n"
        f"【图片后文】\n{after or '无'}"
    )


def collect_neighbor_text(blocks: list[dict[str, Any]], start: int, direction: int, limit: int = 2) -> str:
    texts: list[str] = []
    index = start + direction
    while 0 <= index < len(blocks) and len(texts) < limit:
        block = blocks[index]
        if block.get("type") in {"title", "paragraph", "table"} and block.get("content"):
            texts.append(block["content"][:500])
        index += direction
    if direction < 0:
        texts.reverse()
    return "\n".join(texts)


def image_to_data_url(path: Path, mime_type: str | None = None) -> str:
    mime = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def parse_json_object(text: str) -> dict[str, Any]:
    """从文本中解析 JSON 对象，忽略前后多余内容和代码块。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    return value


def normalize_metadata(payload: dict[str, Any], extraction_mode: str) -> dict[str, Any]:
    return {
        "author": str(payload.get("author") or UNKNOWN),
        "posted_time": str(payload.get("posted_time") or UNKNOWN),
        "organization": str(payload.get("organization") or UNKNOWN),
        "topic": str(payload.get("topic") or UNKNOWN),
        "summary": str(payload.get("summary") or UNKNOWN),
        "extraction_mode": extraction_mode,
    }
