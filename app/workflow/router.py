# router.py：判断文件类型

from pathlib import Path


WORD_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
HTML_EXTENSIONS = {".html", ".htm"}
HTML_ARCHIVE_EXTENSIONS = {".zip"}
IMAGE_EXTENSIONS = {
    ".jpeg",
    ".jpg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".tif",
}


def route_file(file_path: str | Path) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix in WORD_EXTENSIONS:
        return "word"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in HTML_EXTENSIONS:
        return "html"
    if suffix in HTML_ARCHIVE_EXTENSIONS:
        return "html_archive"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unsupported"
