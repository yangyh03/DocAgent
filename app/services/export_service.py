from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from app.schemas import FileResult
from app.services.task_service import task_service

ExportTarget = Literal["blocks", "chunks", "both"]
ExportFormat = Literal["json", "jsonl"]
SCHEMA_VERSION = "docagent.export.v1"


def build_file_export(
    task_id: str,
    file_index: int,
    target: ExportTarget,
    export_format: ExportFormat,
) -> tuple[str, str, str]:
    """导出当前任务中某个文件的 blocks/chunks，返回文件名、媒体类型和内容。"""
    results = task_service.get_result(task_id)
    if results is None:
        raise KeyError(task_id)
    if file_index < 0 or file_index >= len(results):
        raise IndexError(file_index)

    file_result = results[file_index]
    payload = _export_payload(task_id, file_index, file_result, target)
    if not payload["items"]:
        raise ValueError("当前文件没有可导出的内容")

    safe_target = target
    if export_format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
        file_name = f"docagent_file_{file_index}_{safe_target}.json"
    else:
        content = _payload_to_jsonl(payload)
        media_type = "application/x-ndjson; charset=utf-8"
        file_name = f"docagent_file_{file_index}_{safe_target}.jsonl"
    return file_name, media_type, content


def _export_payload(task_id: str, file_index: int, file_result: FileResult, target: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if target in {"blocks", "both"}:
        items.extend(_block_record(block.model_dump(), index) for index, block in enumerate(file_result.blocks))
    if target in {"chunks", "both"}:
        items.extend(_chunk_record(chunk.model_dump(), index) for index, chunk in enumerate(file_result.chunks))
    return {
        "schema_version": SCHEMA_VERSION,
        "export_type": target,
        "task_id": task_id,
        "file_index": file_index,
        "file_name": file_result.fileName,
        "file_type": file_result.fileType,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": file_result.metadata,
        "items": items,
    }


def _block_record(block: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "record_type": "block",
        "index": index,
        "type": block.get("type", "paragraph"),
        "content": block.get("content", ""),
        "metadata": block.get("metadata", {}),
    }


def _chunk_record(chunk: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "record_type": "chunk",
        "index": index,
        "chunk_id": chunk.get("chunk_id", f"chunk_{index + 1}"),
        "content": chunk.get("content", ""),
        "metadata": chunk.get("metadata", {}),
    }


def _payload_to_jsonl(payload: dict[str, Any]) -> str:
    source = {
        "task_id": payload["task_id"],
        "file_index": payload["file_index"],
        "file_name": payload["file_name"],
        "file_type": payload["file_type"],
    }
    lines: list[str] = []
    for item in payload["items"]:
        item_id = item.get("chunk_id") or f"block_{item.get('index', 0) + 1}"
        record = {
            "schema_version": payload["schema_version"],
            "export_type": payload["export_type"],
            "record_type": item.get("record_type"),
            "id": f"{payload['task_id']}:file{payload['file_index']}:{item_id}",
            "content": item.get("content", ""),
            "metadata": item.get("metadata", {}),
            "source": source,
        }
        if item.get("record_type") == "block":
            record["block_type"] = item.get("type")
            record["block_index"] = item.get("index")
        else:
            record["chunk_id"] = item.get("chunk_id")
            record["chunk_index"] = item.get("metadata", {}).get("chunk_index", item.get("index", 0) + 1)
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines) + "\n"
