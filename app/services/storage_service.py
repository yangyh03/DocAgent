# storage_service.py：保存上传文件

from pathlib import Path
from fastapi import UploadFile
from app.config import settings


class StorageService:
    def task_dir(self, task_id: str) -> Path:
        path = settings.data_dir / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def save_uploads(
        self,
        task_id: str,
        upload_files: list[UploadFile],
    ) -> list[Path]:
        saved_paths: list[Path] = []
        target_dir = self.task_dir(task_id)
        for upload_file in upload_files:
            safe_name = Path(upload_file.filename or "uploaded_file").name
            target_path = target_dir / safe_name
            with target_path.open("wb") as buffer:
                while chunk := await upload_file.read(1024 * 1024):
                    buffer.write(chunk)
            saved_paths.append(target_path)
        return saved_paths


storage_service = StorageService()
