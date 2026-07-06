from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.documents import router as documents_router
from app.config import settings
from app.utils.logger import configure_logging

configure_logging()

app = FastAPI(title=settings.app_name)
app.include_router(documents_router, prefix=settings.api_prefix)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def frontend_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/system", include_in_schema=False)
async def system_docs() -> FileResponse:
    return FileResponse(STATIC_DIR / "system.html")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
