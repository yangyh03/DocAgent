#task_service.py：管理任务状态

from datetime import datetime
import json
import logging
from pathlib import Path
import shutil
from threading import Lock
from uuid import uuid4

from app.config import settings
from app.schemas import FileResult, TaskInfo, TaskListItem, TaskStatus
from app.services.runtime_metrics import empty_runtime_metrics, merge_runtime_metrics

TASK_SCHEMA_VERSION = "docagent.task"
logger = logging.getLogger(__name__)


class TaskService:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = Lock()
        self._data_dir = (data_dir or settings.data_dir).resolve()
        self._load_persisted_tasks()

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
            self._persist_task(task_id)
        return TaskInfo(**task)

    def get_task(self, task_id: str) -> TaskInfo | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return TaskInfo(**task) if task else None

    def list_tasks(self, limit: int = 20) -> list[TaskListItem]:
        limit = max(1, min(int(limit or 20), 100))
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda item: item.get("updated_at") or datetime.min,
                reverse=True,
            )[:limit]
            return [TaskListItem(**self._task_list_item(task)) for task in tasks]

    def count_tasks(self) -> int:
        with self._lock:
            return len(self._tasks)

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id not in self._tasks:
                return False
            self._delete_task_dir(task_id)
            self._tasks.pop(task_id, None)
            return True

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
            self._persist_task(task_id)

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
            self._persist_task(task_id)

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
            self._persist_task(task_id)

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
            self._persist_task(task_id)

    def _task_dir(self, task_id: str) -> Path:
        return self._data_dir / "tasks" / task_id

    def _task_file(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.json"

    def _delete_task_dir(self, task_id: str) -> None:
        task_dir = self._task_dir(task_id).resolve()
        tasks_root = (self._data_dir / "tasks").resolve()
        if task_dir.parent != tasks_root:
            raise ValueError(f"Invalid task directory: {task_dir}")
        if task_dir.exists():
            shutil.rmtree(task_dir)

    def _persist_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        target = self._task_file(task_id)
        temp = target.with_name("task.json.tmp")
        payload = {
            "schema_version": TASK_SCHEMA_VERSION,
            "task": self._json_ready_task(task),
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        temp.write_text(content, encoding="utf-8")
        try:
            temp.replace(target)
        except PermissionError:
            # Windows 上少数同步/扫描进程会短暂阻止 replace；降级为直接写入，避免任务状态丢失。
            target.write_text(content, encoding="utf-8")
            try:
                temp.unlink()
            except (FileNotFoundError, PermissionError):
                pass

    def _load_persisted_tasks(self) -> None:
        tasks_root = self._data_dir / "tasks"
        if not tasks_root.exists():
            return
        for task_file in tasks_root.glob("*/task.json"):
            try:
                payload = json.loads(task_file.read_text(encoding="utf-8"))
                task = payload.get("task", payload)
                task = self._normalize_loaded_task(task)
                if task.get("task_id"):
                    self._tasks[task["task_id"]] = task
            except Exception as exc:
                logger.warning("跳过无法恢复的任务文件 %s: %s", task_file, exc)

    def _normalize_loaded_task(self, task: dict) -> dict:
        loaded = dict(task)
        loaded["created_at"] = self._parse_datetime(loaded.get("created_at")) or datetime.now()
        loaded["updated_at"] = self._parse_datetime(loaded.get("updated_at")) or loaded["created_at"]
        loaded.setdefault("file_count", len(loaded.get("result", [])))
        loaded.setdefault("progress", {})
        loaded.setdefault("runtimeMetrics", empty_runtime_metrics())
        loaded.setdefault("runtimeEvents", [])
        loaded.setdefault("result", [])
        loaded.setdefault("message", "")
        status = loaded.get("status", TaskStatus.failed)
        status_value = status.value if isinstance(status, TaskStatus) else str(status)
        if status_value in {TaskStatus.pending.value, TaskStatus.running.value}:
            loaded["status"] = TaskStatus.failed
            loaded["message"] = "服务重启导致任务中断，请重新上传文件解析"
            progress = dict(loaded.get("progress") or {})
            progress["current_step"] = "任务中断"
            loaded["progress"] = progress
            loaded["updated_at"] = datetime.now()
        else:
            loaded["status"] = TaskStatus(status_value)
        return loaded

    def _json_ready_task(self, task: dict) -> dict:
        ready = dict(task)
        for key in ("created_at", "updated_at"):
            value = ready.get(key)
            if isinstance(value, datetime):
                ready[key] = value.isoformat()
        ready["status"] = ready["status"].value if isinstance(ready.get("status"), TaskStatus) else ready.get("status")
        return ready

    def _parse_datetime(self, value) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _task_list_item(self, task: dict) -> dict:
        results = task.get("result") or []
        file_names = [str(item.get("fileName")) for item in results if isinstance(item, dict) and item.get("fileName")]
        return {
            "task_id": task.get("task_id", ""),
            "status": task.get("status", TaskStatus.failed),
            "message": task.get("message", ""),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "file_count": task.get("file_count", len(results)),
            "progress": task.get("progress", {}),
            "file_names": file_names,
        }


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
