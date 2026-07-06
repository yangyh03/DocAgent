#task_service.py：管理任务状态

from datetime import datetime
from threading import Lock
from uuid import uuid4

from app.schemas import FileResult, TaskInfo, TaskStatus
from app.services.runtime_metrics import empty_runtime_metrics, merge_runtime_metrics


class TaskService:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = Lock()

    def create_task(self, file_count: int) -> TaskInfo:
        now = datetime.now()
        task_id = uuid4().hex
        task = {
            "task_id": task_id,
            "status": TaskStatus.pending,
            "message": "任务已创建",
            "created_at": now,
            "updated_at": now,
            "file_count": file_count,
            "progress": {
                "total_files": file_count,
                "processed_files": 0,
                "current_file": "",
                "current_step": "等待解析",
                "percent": 0,
            },
            "runtimeMetrics": empty_runtime_metrics(),
            "runtimeEvents": [],
            "result": [],
        }
        with self._lock:
            self._tasks[task_id] = task
        return TaskInfo(**task)

    def get_task(self, task_id: str) -> TaskInfo | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return TaskInfo(**task) if task else None

    def get_result(self, task_id: str) -> list[FileResult] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return [FileResult(**item) for item in task["result"]]

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        message: str = "",
    ) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task["status"] = status
            task["message"] = message
            task["updated_at"] = datetime.now()

    def update_progress(
        self,
        task_id: str,
        *,
        processed_files: int | None = None,
        current_file: str | None = None,
        current_step: str | None = None,
        percent: int | None = None,
    ) -> None:
        with self._lock:
            task = self._tasks[task_id]
            progress = dict(task.get("progress", {}))
            if processed_files is not None:
                progress["processed_files"] = max(0, processed_files)
            if current_file is not None:
                progress["current_file"] = current_file
            if current_step is not None:
                progress["current_step"] = current_step
            if percent is not None:
                progress["percent"] = max(0, min(100, percent))
            task["progress"] = progress
            task["updated_at"] = datetime.now()

    def set_result(self, task_id: str, result: list[FileResult]) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task["result"] = [item.model_dump() for item in result]
            task["status"] = _aggregate_task_status(result)
            task["message"] = "解析完成" if task["status"] == TaskStatus.success else "解析完成，部分文件需关注"
            task_level_events = task.get("runtimeEvents", [])
            task["runtimeMetrics"] = merge_runtime_metrics(
                [item.runtimeMetrics for item in result] + [{"events": task_level_events}]
            )
            task["progress"] = {
                "total_files": task.get("file_count", len(result)),
                "processed_files": len(result),
                "current_file": "",
                "current_step": "解析完成",
                "percent": 100,
            }
            task["updated_at"] = datetime.now()

    def add_runtime_event(self, task_id: str, event: dict) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task_events = list(task.get("runtimeEvents", []))
            task_events.append(event)
            task["runtimeEvents"] = task_events
            file_metrics = []
            for item in task.get("result", []):
                if isinstance(item, dict):
                    file_metrics.append(item.get("runtimeMetrics"))
            task["runtimeMetrics"] = merge_runtime_metrics(file_metrics + [{"events": task_events}])
            task["updated_at"] = datetime.now()


def _aggregate_task_status(result: list[FileResult]) -> TaskStatus:
    if not result:
        return TaskStatus.failed
    statuses = [item.status for item in result]
    if all(status == "failed" for status in statuses):
        return TaskStatus.failed
    if any(status in {"failed", "partial_success"} for status in statuses):
        return TaskStatus.partial_success
    return TaskStatus.success


task_service = TaskService()
