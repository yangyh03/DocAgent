from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.schemas import (
    AnalyzeAccepted,
    BlockCorrectionRequest,
    ChunkCorrectionRequest,
    FileResult,
    KnowledgeAskRequest,
    KnowledgeAskResponse,
    KnowledgeIndexRequest,
    KnowledgeIndexStatus,
    TaskDeleteResponse,
    TaskInfo,
    TaskListResponse,
    TaskResult,
    TaskStatus,
)
from app.config import settings
from app.services.document_service import apply_block_corrections, apply_chunk_corrections, run_analysis_task
from app.services.export_service import build_file_export
from app.services.knowledge_service import knowledge_service
from app.services.storage_service import storage_service
from app.services.task_service import task_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/analyze", response_model=AnalyzeAccepted)
async def analyze_documents(
    background_tasks: BackgroundTasks,
    multiFiles: list[UploadFile] = File(...),
    serverSource: str = Form(...),
) -> AnalyzeAccepted:
    task = task_service.create_task(file_count=len(multiFiles))
    saved_paths = await storage_service.save_uploads(task.task_id, multiFiles)
    background_tasks.add_task(run_analysis_task, task.task_id, saved_paths, serverSource)
    return AnalyzeAccepted(
        message="任务已提交",
        task_id=task.task_id,
        status=TaskStatus.pending,
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(limit: int = 20) -> TaskListResponse:
    items = task_service.list_tasks(limit)
    return TaskListResponse(total=task_service.count_tasks(), items=items)


@router.delete("/tasks/{task_id}", response_model=TaskDeleteResponse)
async def delete_task(task_id: str) -> TaskDeleteResponse:
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    index_deleted = knowledge_service.delete_index(task_id)
    deleted = task_service.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskDeleteResponse(
        task_id=task_id,
        deleted=True,
        index_deleted=index_deleted,
        message="任务已删除",
    )


@router.get("/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str) -> TaskInfo:
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks/{task_id}/result", response_model=TaskResult)
async def get_task_result(task_id: str) -> TaskResult:
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    result = task_service.get_result(task_id) or []
    return TaskResult(
        message=task.message or "任务结果",
        task_id=task_id,
        status=task.status,
        progress=task.progress,
        data=result,
        runtimeMetrics=task.runtimeMetrics,
    )


@router.patch("/tasks/{task_id}/result/files/{file_index}/blocks", response_model=FileResult)
async def update_result_blocks(
    task_id: str,
    file_index: int,
    payload: BlockCorrectionRequest,
) -> FileResult:
    try:
        return apply_block_corrections(task_id, file_index, payload.blocks)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="文件结果不存在")


@router.patch("/tasks/{task_id}/result/files/{file_index}/chunks", response_model=FileResult)
async def update_result_chunks(
    task_id: str,
    file_index: int,
    payload: ChunkCorrectionRequest,
) -> FileResult:
    try:
        return apply_chunk_corrections(task_id, file_index, payload.chunks)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="文件结果不存在")


@router.get("/tasks/{task_id}/result/files/{file_index}/export")
async def export_file_result(
    task_id: str,
    file_index: int,
    target: Literal["blocks", "chunks", "both"] = "chunks",
    format: Literal["json", "jsonl"] = "json",
) -> Response:
    try:
        file_name, media_type, content = build_file_export(task_id, file_index, target, format)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="文件结果不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.post("/tasks/{task_id}/knowledge/index", response_model=KnowledgeIndexStatus)
async def build_knowledge_index(
    task_id: str,
    payload: KnowledgeIndexRequest,
) -> KnowledgeIndexStatus:
    try:
        return knowledge_service.build_index(task_id, payload.file_indices, payload.rebuild)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="文件结果不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/tasks/{task_id}/knowledge/index", response_model=KnowledgeIndexStatus)
async def get_knowledge_index_status(task_id: str) -> KnowledgeIndexStatus:
    try:
        return knowledge_service.get_index_status(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/tasks/{task_id}/knowledge/ask", response_model=KnowledgeAskResponse)
async def ask_knowledge(task_id: str, payload: KnowledgeAskRequest) -> KnowledgeAskResponse:
    try:
        return knowledge_service.ask(task_id, payload.question, payload.top_k)
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/tasks/{task_id}/assets/{file_name:path}")
async def get_task_asset(task_id: str, file_name: str) -> FileResponse:
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    safe_name = Path(file_name).name
    if safe_name != file_name:
        raise HTTPException(status_code=404, detail="资源不存在")

    assets_dir = (settings.data_dir / "tasks" / task_id / "assets").resolve()
    asset_path = (assets_dir / safe_name).resolve()
    if asset_path.parent != assets_dir or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="资源不存在")

    return FileResponse(asset_path)
