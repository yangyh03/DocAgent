from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from app.parsers.word_parser import render_blocks_to_text

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
IMAGE_FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "GIF": ".gif",
    "TIFF": ".tiff",
}


def parse_image_document(
    file_path: str | Path,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """把单张图片标准化为 image block，后续交给 Vision Agent 理解。"""
    path = Path(file_path)
    if not path.exists():
        return _failed(f"图片解析失败: 文件不存在 {path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        return _failed(f"图片解析失败: 不支持的图片格式 {suffix or 'UNKNOWN'}")

    try:
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format or ""
            mime_type = image.get_format_mimetype() or mimetypes.guess_type(path.name)[0]
            image.verify()
    except Exception as exc:
        return _failed(f"图片解析失败: 文件不是可读取的图片，{exc}")

    asset_root = Path(assets_dir) if assets_dir else path.parent / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

    extension = IMAGE_FORMAT_EXTENSIONS.get(image_format.upper()) or mimetypes.guess_extension(mime_type or "") or suffix
    file_name = f"image_1{extension}"
    target_path = asset_root / file_name
    shutil.copyfile(path, target_path)

    mime_type = mime_type or mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"
    block = {
        "type": "image",
        "content": "",
        "metadata": {
            "source": "image",
            "file_name": file_name,
            "path": str(target_path),
            "mime_type": mime_type,
            "original_file_name": path.name,
            "original_extension": suffix,
            "detected_format": image_format,
            "extension_mismatch": bool(suffix and extension and suffix != extension),
            "width": width,
            "height": height,
            "image_status": "extracted",
        },
    }
    asset = {"file_name": file_name, "path": str(target_path), "mime_type": mime_type}

    return {
        "content": render_blocks_to_text([block]),
        "status": "success",
        "blocks": [block],
        "assets": [asset],
    }


def _failed(message: str) -> dict[str, Any]:
    return {"content": message, "status": "failed", "blocks": [], "assets": []}
