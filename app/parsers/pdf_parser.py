from __future__ import annotations

import mimetypes
from pathlib import Path
from statistics import median
from typing import Any

from app.parsers.word_parser import render_blocks_to_text

PDF_TINY_IMAGE_LIMIT = 10
PDF_RENDER_DPI = 144
PDF_OCR_IMAGE_AREA_RATIO = 0.55


def _parse_pdf_document_v1_unused(
    file_path: str | Path,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """解析可提取文本 PDF，输出和 Word/HTML 一致的 blocks/assets 结构。

    第一版只处理 PDF 内已有的文本层和内嵌图片；扫描版 OCR 放到后续阶段。
    """
    path = Path(file_path)
    asset_root = Path(assets_dir) if assets_dir else path.parent / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    assets: list[dict[str, str]] = []
    image_index = 0

    try:
        import fitz

        with fitz.open(path) as document:
            # 按页遍历 PDF
            for page_index, page in enumerate(document, start=1):
                page_dict = page.get_text("dict")
                for item in sorted(page_dict.get("blocks", []), key=_block_sort_key):
                    block_type = item.get("type")
                    # 0: text block, 1: image block
                    if block_type == 0: 
                        text = _text_block_content(item)
                        if text:
                            blocks.append(
                                {
                                    "type": "paragraph",
                                    "content": text,
                                    "metadata": {
                                        "source": "pdf",
                                        "page_number": page_index,
                                        "bbox": _bbox_to_list(item.get("bbox")),
                                    },
                                }
                            )
                    elif block_type == 1:
                        image_index += 1
                        image_block = _save_pdf_image_block(
                            image_block=item,
                            asset_root=asset_root,
                            page_number=page_index,
                            image_index=image_index,
                        )
                        if image_block:
                            blocks.append(image_block)
                            assets.append(_asset_from_image_block(image_block))
                        else:
                            image_index -= 1
    except ImportError:
        return {
            "content": "PDF 解析失败: 未安装 PyMuPDF，请先安装依赖 PyMuPDF。",
            "status": "failed",
            "blocks": [],
            "assets": [],
        }
    except Exception as exc:
        return {
            "content": f"PDF 解析失败: {exc}",
            "status": "failed",
            "blocks": [],
            "assets": [],
        }

    content = render_blocks_to_text(blocks)
    if not content.strip():
        content = "未检测到可提取文本或图片，可能是扫描版 PDF，后续可接入 OCR。"

    return {
        "content": content,
        "status": "success",
        "blocks": blocks,
        "assets": assets,
    }


def _block_sort_key(block: dict[str, Any]) -> tuple[float, float]:
    """按页内位置排序，先纵向再横向。"""
    bbox = block.get("bbox") or [0, 0, 0, 0]
    return float(bbox[1]), float(bbox[0])


def _text_block_content(block: dict[str, Any]) -> str:
    '''从 block 里取出 lines 和 spans，拼接成段落文本'''
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = [span.get("text", "") for span in line.get("spans", [])]
        text = "".join(spans).strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def _save_pdf_image_block(
    image_block: dict[str, Any],
    asset_root: Path,
    page_number: int,
    image_index: int,
) -> dict[str, Any] | None:
    image_bytes = image_block.get("image")
    if not image_bytes:
        return None

    extension = str(image_block.get("ext") or "png").lower().lstrip(".")
    mime_type = mimetypes.types_map.get(f".{extension}", f"image/{extension}")
    file_name = f"image_{image_index}.{extension}"
    target_path = asset_root / file_name
    target_path.write_bytes(image_bytes)

    return {
        "type": "image",
        "content": "",
        "metadata": {
            "source": "pdf",
            "page_number": page_number,
            "file_name": file_name,
            "path": str(target_path),
            "mime_type": mime_type,
            "width": image_block.get("width"),
            "height": image_block.get("height"),
            "bbox": _bbox_to_list(image_block.get("bbox")),
        },
    }


def _asset_from_image_block(block: dict[str, Any]) -> dict[str, str]:
    metadata = block.get("metadata", {})
    return {
        "file_name": metadata.get("file_name", "unknown"),
        "path": metadata.get("path", ""),
        "mime_type": metadata.get("mime_type", "application/octet-stream"),
    }


def _bbox_to_list(value: Any) -> list[float]:
    if not value:
        return []
    return [float(item) for item in value]


def parse_pdf_document(
    file_path: str | Path,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """PDF parser v2: text/image extraction, conservative titles, and page render fallback."""
    path = Path(file_path)
    asset_root = Path(assets_dir) if assets_dir else path.parent / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    assets: list[dict[str, str]] = []
    image_index = 0

    try:
        import fitz

        with fitz.open(path) as document:
            for page_index, page in enumerate(document, start=1):
                page_dict = page.get_text("dict")
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)
                page_blocks: list[dict[str, Any]] = []
                text_infos = [
                    _pdf_text_block_info(item)
                    for item in page_dict.get("blocks", [])
                    if item.get("type") == 0
                ]
                text_infos = [item for item in text_infos if item["text"]]
                body_font_size = _pdf_body_font_size(text_infos)
                has_text = bool(text_infos)
                has_usable_image = False

                for item in sorted(page_dict.get("blocks", []), key=_block_sort_key):
                    if item.get("type") == 0:
                        info = _pdf_text_block_info(item)
                        if info["text"]:
                            page_blocks.append(_pdf_text_info_to_block(info, page_index, body_font_size))
                    elif item.get("type") == 1:
                        image_index += 1
                        image_block = _save_pdf_image_block_v2(
                            item,
                            asset_root,
                            page_index,
                            image_index,
                            page_width=page_width,
                            page_height=page_height,
                            has_page_text=has_text,
                        )
                        if image_block:
                            page_blocks.append(image_block)
                            assets.append(_asset_from_image_block(image_block))
                            has_usable_image = True
                        else:
                            image_index -= 1

                if not has_text and not has_usable_image and _pdf_page_has_renderable_content(page):
                    image_index += 1
                    rendered_block = _render_pdf_page_to_image_block(
                        page,
                        asset_root,
                        page_index,
                        image_index,
                        page_width=page_width,
                        page_height=page_height,
                    )
                    page_blocks.append(rendered_block)
                    assets.append(_asset_from_image_block(rendered_block))

                blocks.extend(page_blocks)
    except ImportError:
        return {
            "content": "PDF 解析失败: 未安装 PyMuPDF，请先安装依赖 PyMuPDF。",
            "status": "failed",
            "blocks": [],
            "assets": [],
        }
    except Exception as exc:
        return {
            "content": f"PDF 解析失败: {exc}",
            "status": "failed",
            "blocks": [],
            "assets": [],
        }

    content = render_blocks_to_text(blocks)
    if not content.strip():
        content = "未检测到可提取文本或图片，可能是扫描版 PDF，后续可接入 OCR。"

    return {
        "content": content,
        "status": "success",
        "blocks": blocks,
        "assets": assets,
    }


def _pdf_text_block_info(block: dict[str, Any]) -> dict[str, Any]:
    lines: list[str] = []
    font_sizes: list[float] = []
    flags: list[int] = []
    for line in block.get("lines", []):
        spans: list[str] = []
        for span in line.get("spans", []):
            spans.append(span.get("text", ""))
            if span.get("size") is not None:
                font_sizes.append(float(span["size"]))
            if span.get("flags") is not None:
                flags.append(int(span["flags"]))
        text = "".join(spans).strip()
        if text:
            lines.append(text)
    return {
        "text": "\n".join(lines).strip(),
        "font_size": max(font_sizes, default=0.0),
        "is_bold": any(flag & 16 for flag in flags),
        "bbox": _bbox_to_list(block.get("bbox")),
    }


def _pdf_body_font_size(text_infos: list[dict[str, Any]]) -> float:
    sizes = [float(item["font_size"]) for item in text_infos if item.get("font_size")]
    return float(median(sizes)) if sizes else 0.0


def _pdf_text_info_to_block(info: dict[str, Any], page_number: int, body_font_size: float) -> dict[str, Any]:
    block_type = "title" if _looks_like_pdf_title(info, body_font_size) else "paragraph"
    metadata: dict[str, Any] = {
        "source": "pdf",
        "page_number": page_number,
        "bbox": info["bbox"],
        "font_size": info["font_size"],
    }
    if block_type == "title":
        metadata["title_source"] = "pdf_font_heuristic"
        metadata["bold"] = info["is_bold"]
    return {"type": block_type, "content": info["text"], "metadata": metadata}


def _looks_like_pdf_title(info: dict[str, Any], body_font_size: float) -> bool:
    text = info["text"].strip()
    font_size = float(info.get("font_size") or 0)
    if not text or len(text) > 120 or "\n" in text:
        return False
    if font_size >= 18:
        return True
    if body_font_size and font_size >= max(16, body_font_size * 1.35):
        return True
    return bool(info.get("is_bold") and body_font_size and font_size >= max(14, body_font_size * 1.2) and len(text) <= 80)


def _save_pdf_image_block_v2(
    image_block: dict[str, Any],
    asset_root: Path,
    page_number: int,
    image_index: int,
    page_width: float,
    page_height: float,
    has_page_text: bool,
) -> dict[str, Any] | None:
    image_bytes = image_block.get("image")
    if not image_bytes:
        return None

    width = int(image_block.get("width") or 0)
    height = int(image_block.get("height") or 0)
    if width <= PDF_TINY_IMAGE_LIMIT or height <= PDF_TINY_IMAGE_LIMIT:
        return None

    extension = str(image_block.get("ext") or "png").lower().lstrip(".")
    mime_type = mimetypes.types_map.get(f".{extension}", f"image/{extension}")
    file_name = f"image_{image_index}.{extension}"
    target_path = asset_root / file_name
    target_path.write_bytes(image_bytes)
    bbox = _bbox_to_list(image_block.get("bbox"))
    page_area_ratio = _bbox_area_ratio(bbox, page_width, page_height)
    ocr_candidate = (not has_page_text) and page_area_ratio >= PDF_OCR_IMAGE_AREA_RATIO

    return {
        "type": "image",
        "content": "",
        "metadata": {
            "source": "pdf",
            "page_number": page_number,
            "file_name": file_name,
            "path": str(target_path),
            "mime_type": mime_type,
            "width": width,
            "height": height,
            "bbox": bbox,
            "page_width": page_width,
            "page_height": page_height,
            "page_area_ratio": page_area_ratio,
            "image_status": "extracted",
            "ocr_candidate": ocr_candidate,
            "ocr_source": "pdf_large_image" if ocr_candidate else "",
        },
    }


def _pdf_page_has_renderable_content(page: Any) -> bool:
    try:
        return bool(page.get_contents() or page.get_drawings())
    except Exception:
        return False


def _render_pdf_page_to_image_block(
    page: Any,
    asset_root: Path,
    page_number: int,
    image_index: int,
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    import fitz

    zoom = PDF_RENDER_DPI / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    file_name = f"page_{page_number}.png"
    target_path = asset_root / file_name
    pixmap.save(target_path)
    return {
        "type": "image",
        "content": "",
        "metadata": {
            "source": "pdf_page_render",
            "page_number": page_number,
            "file_name": file_name,
            "path": str(target_path),
            "mime_type": "image/png",
            "width": pixmap.width,
            "height": pixmap.height,
            "page_width": page_width,
            "page_height": page_height,
            "page_area_ratio": 1.0,
            "render_dpi": PDF_RENDER_DPI,
            "image_status": "rendered_page",
            "ocr_candidate": True,
            "ocr_source": "pdf_page_render",
        },
    }


def _bbox_area_ratio(bbox: list[float], page_width: float, page_height: float) -> float:
    if len(bbox) != 4 or page_width <= 0 or page_height <= 0:
        return 0.0
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    page_area = page_width * page_height
    return round(min(1.0, (width * height) / page_area), 4) if page_area else 0.0
