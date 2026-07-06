from __future__ import annotations

import base64
import html
import mimetypes
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, NavigableString, Tag

from app.config import settings
from app.parsers.word_parser import render_blocks_to_text

TITLE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
PARAGRAPH_TAGS = {"p", "li", "blockquote"}
CONTAINER_TAGS = {"div", "section", "article", "main"}
IGNORED_TAGS = {"script", "style", "noscript", "template", "meta", "link"}
NOISE_TAGS = IGNORED_TAGS | {"svg", "canvas", "iframe", "object", "embed", "form", "button", "select", "option", "textarea", "input"}
STRUCTURAL_TAGS = TITLE_TAGS | PARAGRAPH_TAGS | {"table", "img"}
IMAGE_SOURCE_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-actualsrc")
IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg", ".ico"}
NOISE_ATTR_EXACT = {
    "nav",
    "footer",
    "menu",
    "toolbar",
    "share",
    "sidebar",
    "comment",
    "search",
    "login",
    "breadcrumb",
    "breadcrumbs",
    "language",
    "copyright",
    "pagination",
}
NOISE_ATTR_PREFIXES = (
    "nav",
    "footer",
    "menu",
    "toolbar",
    "share",
    "sidebar",
    "comment",
    "search",
    "login",
    "breadcrumb",
    "language",
    "copyright",
    "pagination",
    "advert",
    "ads",
    "ad-",
)
ZIP_HTML_NOT_FOUND = "ZIP 中未找到 HTML 文件，请上传包含 html 和附件文件夹的网页压缩包"


def parse_html_document(
    file_path: str | Path,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """解析静态 HTML，输出与 Word Parser 一致的 blocks/assets 结构。"""
    path = Path(file_path)
    asset_root = Path(assets_dir) if assets_dir else path.parent / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

    soup = BeautifulSoup(_read_html_text(path), "html.parser")
    _remove_noise_nodes(soup)
    root = soup.body or soup
    blocks: list[dict[str, Any]] = []
    assets: list[dict[str, str]] = []
    image_index = 0

    image_index = _walk_dom(
        root=root,
        blocks=blocks,
        assets=assets,
        asset_root=asset_root,
        source_dir=path.parent,
        image_index=image_index,
    )

    return {
        "content": render_blocks_to_text(blocks),
        "status": "success",
        "blocks": blocks,
        "assets": assets,
    }


def parse_html_archive_document(
    file_path: str | Path,
    assets_dir: str | Path | None = None,
) -> dict[str, Any]:
    """解析本地保存网页 zip 包：先安全解压，再选择 HTML 主文件解析。"""
    archive_path = Path(file_path)
    extract_root = archive_path.parent / "extracted" / archive_path.stem
    asset_root = Path(assets_dir) if assets_dir else archive_path.parent / "assets"
    metadata: dict[str, Any] = {"archive_path": str(archive_path)}

    try:
        if extract_root.exists():
            shutil.rmtree(extract_root)
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_zip_members(archive)
            html_member = _select_html_member(members)
            if html_member is None:
                return {
                    "content": ZIP_HTML_NOT_FOUND,
                    "status": "failed",
                    "blocks": [],
                    "assets": [],
                    "metadata": metadata,
                }
            _extract_zip_members(archive, members, extract_root, required_html=html_member["safe_name"])

        selected_html_path = (extract_root / html_member["safe_name"]).resolve()
        parsed = parse_html_document(selected_html_path, assets_dir=asset_root)
        metadata.update(
            {
                "selected_html_member": html_member["safe_name"],
                "selected_html_path": str(selected_html_path),
            }
        )
        parsed["metadata"] = {**metadata, **parsed.get("metadata", {})}
        return parsed
    except Exception as exc:
        return {
            "content": f"HTML ZIP 解析失败: {exc}",
            "status": "failed",
            "blocks": [],
            "assets": [],
            "metadata": metadata,
        }
 

def _walk_dom(
    root: Tag,
    blocks: list[dict[str, Any]],
    assets: list[dict[str, str]],
    asset_root: Path,
    source_dir: Path,
    image_index: int,
) -> int:
    """按 DOM 顺序遍历节点，遇到结构化元素就生成 block。"""
    for child in root.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue

        tag_name = child.name.lower()
        if tag_name in NOISE_TAGS or _is_noise_container(child):
            continue
        if tag_name in TITLE_TAGS:
            level = int(tag_name[1])
            image_index = _append_text_and_images(
                tag=child,
                block_type="title",
                metadata={"tag": tag_name, "level": level},
                blocks=blocks,
                assets=assets,
                asset_root=asset_root,
                source_dir=source_dir,
                image_index=image_index,
            )
            continue
        if tag_name in PARAGRAPH_TAGS:
            image_index = _append_text_and_images(
                tag=child,
                block_type="paragraph",
                metadata={"tag": tag_name},
                blocks=blocks,
                assets=assets,
                asset_root=asset_root,
                source_dir=source_dir,
                image_index=image_index,
            )
            continue
        if tag_name == "table":
            blocks.append(_table_to_block(child, table_index=_next_table_index(blocks)))
            continue
        if tag_name == "img":
            image_index += 1
            image_block = _image_to_block(
                img=child,
                asset_root=asset_root,
                source_dir=source_dir,
                image_index=image_index,
            )
            blocks.append(image_block)
            assets.append(_asset_from_image_block(image_block))
            continue
        if tag_name in CONTAINER_TAGS and not _has_structural_children(child):
            text = _clean_text(child.get_text(" ", strip=True))
            if _should_keep_text(text):
                blocks.append({"type": "paragraph", "content": text, "metadata": {"tag": tag_name}})
            continue

        image_index = _walk_dom(child, blocks, assets, asset_root, source_dir, image_index)

    return image_index


def _append_text_and_images(
    tag: Tag,
    block_type: str,
    metadata: dict[str, Any],
    blocks: list[dict[str, Any]],
    assets: list[dict[str, str]],
    asset_root: Path,
    source_dir: Path,
    image_index: int,
) -> int:
    """处理标题/段落里的文本和图片，尽量保留二者在标签内的顺序。"""
    text_parts: list[str] = []

    def flush_text() -> None:
        text = _clean_text(" ".join(part.strip() for part in text_parts if part.strip()))
        text_parts.clear()
        if _should_keep_text(text):
            blocks.append({"type": block_type, "content": text, "metadata": dict(metadata)})

    def walk_inline(node: Tag) -> None:
        nonlocal image_index
        for child in node.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in NOISE_TAGS or _is_noise_container(child):
                continue
            if name == "br":
                text_parts.append("\n")
                continue
            if name == "img":
                flush_text()
                image_index += 1
                image_block = _image_to_block(child, asset_root, source_dir, image_index)
                blocks.append(image_block)
                assets.append(_asset_from_image_block(image_block))
                continue
            if name == "table":
                flush_text()
                blocks.append(_table_to_block(child, table_index=_next_table_index(blocks)))
                continue
            walk_inline(child)

    walk_inline(tag)
    flush_text()
    return image_index


def _image_to_block(img: Tag, asset_root: Path, source_dir: Path, image_index: int) -> dict[str, Any]:
    src = _image_src(img)
    alt = _clean_text(img.get("alt") or "")
    metadata: dict[str, Any] = {"source": "html", "alt": alt, "original_src": src}

    if src.startswith("data:image/"):
        asset = _save_data_uri_image(src, asset_root, image_index)
    elif _is_remote_url(src):
        asset = _save_remote_image(src, asset_root, image_index)
        metadata["source_url"] = src
    else:
        asset = _save_local_image(src, source_dir, asset_root, image_index)

    metadata.update(asset)
    return {"type": "image", "content": "", "metadata": metadata}


def _save_data_uri_image(src: str, asset_root: Path, image_index: int) -> dict[str, str]:
    header, encoded = src.split(",", 1)
    mime_type = header.split(";")[0].replace("data:", "") or "image/png"
    extension = mimetypes.guess_extension(mime_type) or ".png"
    file_name = f"image_{image_index}{extension}"
    target_path = asset_root / file_name
    target_path.write_bytes(base64.b64decode(encoded))
    return {"file_name": file_name, "path": str(target_path), "mime_type": mime_type}


def _save_local_image(src: str, source_dir: Path, asset_root: Path, image_index: int) -> dict[str, str]:
    source_path, local_status, local_error = _resolve_local_image_path(src, source_dir)
    mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
    extension = source_path.suffix or mimetypes.guess_extension(mime_type) or ".bin"
    file_name = f"image_{image_index}{extension}"
    target_path = asset_root / file_name

    if local_status == "candidate" and source_path.exists() and source_path.is_file():
        shutil.copyfile(source_path, target_path)
        path = str(target_path)
        local_status = "success"
    else:
        path = str(source_path)
        if local_status == "candidate":
            local_status = "missing"

    result = {"file_name": file_name, "path": path, "mime_type": mime_type, "local_status": local_status}
    if local_error:
        result["local_error"] = local_error
    return result


def _save_remote_image(src: str, asset_root: Path, image_index: int) -> dict[str, str]:
    remote_asset = _remote_image_asset(src, image_index)
    if not settings.remote_image_download_enabled:
        return {**remote_asset, "download_status": "skipped"}

    max_bytes = settings.remote_image_max_mb * 1024 * 1024
    try:
        request = Request(src, headers={"User-Agent": "DocAgent/1.0"})
        with urlopen(request, timeout=settings.remote_image_timeout_seconds) as response:
            content_type = _response_header(response, "Content-Type") or remote_asset["mime_type"]
            content_type = content_type.split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                return {**remote_asset, "mime_type": content_type, "download_status": "failed", "download_error": "response is not an image"}

            content_length = _response_header(response, "Content-Length")
            if content_length and int(content_length) > max_bytes:
                return {**remote_asset, "mime_type": content_type, "download_status": "failed", "download_error": "image exceeds size limit"}

            extension = mimetypes.guess_extension(content_type) or Path(urlparse(src).path).suffix or ".bin"
            file_name = f"image_{image_index}{extension}"
            target_path = asset_root / file_name
            downloaded = 0
            with target_path.open("wb") as buffer:
                while chunk := response.read(8192):
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        buffer.close()
                        target_path.unlink(missing_ok=True)
                        return {**remote_asset, "mime_type": content_type, "download_status": "failed", "download_error": "image exceeds size limit"}
                    buffer.write(chunk)

            return {"file_name": file_name, "path": str(target_path), "mime_type": content_type, "download_status": "success"}
    except Exception as exc:
        return {**remote_asset, "download_status": "failed", "download_error": str(exc)}


def _response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get(name)
        if value is not None:
            return str(value)
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader(name)
        if value is not None:
            return str(value)
    return None


def _remote_image_asset(src: str, image_index: int) -> dict[str, str]:
    parsed = urlparse(src)
    original_name = Path(parsed.path).name
    mime_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    extension = Path(original_name).suffix or mimetypes.guess_extension(mime_type) or ".bin"
    return {"file_name": f"image_{image_index}{extension}", "path": src, "mime_type": mime_type}


def _asset_from_image_block(block: dict[str, Any]) -> dict[str, str]:
    metadata = block.get("metadata", {})
    return {
        "file_name": metadata.get("file_name", "unknown"),
        "path": metadata.get("path", ""),
        "mime_type": metadata.get("mime_type", "application/octet-stream"),
    }


def _table_to_block(table: Tag, table_index: int) -> dict[str, Any]:
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        rows.append([_clean_text(cell.get_text(" ", strip=True)) for cell in cells])

    return {
        "type": "table",
        "content": _rows_to_markdown(rows),
        "metadata": {
            "table_index": table_index,
            "rows": rows,
            "row_count": len(rows),
            "column_count": max((len(row) for row in rows), default=0),
        },
    }


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    return "\n".join("| " + " | ".join(_clean_cell(cell) for cell in row) + " |" for row in rows)


def _clean_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _has_structural_children(tag: Tag) -> bool:
    return tag.find(STRUCTURAL_TAGS) is not None


def _next_table_index(blocks: list[dict[str, Any]]) -> int:
    return sum(1 for block in blocks if block.get("type") == "table") + 1


def _read_html_text(path: Path) -> str:
    """读取 HTML 文本，优先使用页面声明的 charset，兼容常见中文编码。"""
    data = path.read_bytes()
    encodings = _candidate_encodings(data)
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _candidate_encodings(data: bytes) -> list[str]:
    head = data[:4096]
    declared: list[str] = []
    for pattern in (
        br"<meta[^>]+charset=[\"']?\s*([a-zA-Z0-9_\-]+)",
        br"content=[\"'][^\"']*charset=([a-zA-Z0-9_\-]+)",
    ):
        match = re.search(pattern, head, flags=re.IGNORECASE)
        if match:
            declared.append(match.group(1).decode("ascii", errors="ignore"))

    candidates = declared + ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    unique: list[str] = []
    for encoding in candidates:
        normalized = encoding.strip().lower()
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def _remove_noise_nodes(soup: BeautifulSoup) -> None:
    for node in soup.find_all(lambda tag: isinstance(tag, Tag) and (tag.name.lower() in NOISE_TAGS or _is_noise_container(tag))):
        node.decompose()


def _is_noise_container(tag: Tag) -> bool:
    role = str(tag.get("role") or "").lower()
    values = [role, str(tag.get("id") or "").lower()]
    class_value = tag.get("class") or []
    if isinstance(class_value, str):
        values.append(class_value.lower())
    else:
        values.extend(str(item).lower() for item in class_value)
    tokens: list[str] = []
    for value in values:
        tokens.extend(token for token in re.split(r"[\s_]+", value) if token)
    for token in tokens:
        if token in NOISE_ATTR_EXACT:
            return True
        if any(token.startswith(prefix) for prefix in NOISE_ATTR_PREFIXES):
            return True
    return False


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = text.replace("\xa0", " ").replace("\r", "\n")
    # 有些网页会把 HTML 片段作为普通文本保存，这里去掉残留标签形态。
    text = re.sub(r"</?[\w:-]+(?:\s+[^<>]*)?>", " ", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _should_keep_text(text: str) -> bool:
    if not text:
        return False
    tag_like_count = text.count("<") + text.count(">")
    return tag_like_count <= 2


def _image_src(img: Tag) -> str:
    for attr in IMAGE_SOURCE_ATTRS:
        value = (img.get(attr) or "").strip()
        if value:
            return value
    srcset = (img.get("srcset") or img.get("data-srcset") or "").strip()
    if srcset:
        first = srcset.split(",", 1)[0].strip()
        return first.split()[0] if first else ""
    return ""


def _resolve_local_image_path(src: str, source_dir: Path) -> tuple[Path, str, str]:
    if not src:
        return source_dir / "", "missing", "empty image src"

    parsed = urlparse(src)
    if parsed.scheme == "file":
        raw_path = unquote(parsed.path)
        if re.match(r"^/[a-zA-Z]:/", raw_path):
            raw_path = raw_path[1:]
        candidate = Path(raw_path).resolve()
        if not _is_relative_to(candidate, source_dir.resolve()):
            return candidate, "blocked", "file URL is outside html task directory"
        return candidate, "candidate", ""
    if parsed.scheme and parsed.scheme not in {"", "file"}:
        return Path(src), "blocked", f"unsupported local image scheme: {parsed.scheme}"

    cleaned = unquote(src.split("#", 1)[0].split("?", 1)[0])
    candidate = (source_dir / cleaned).resolve()
    if not _is_relative_to(candidate, source_dir.resolve()):
        return candidate, "blocked", "relative path is outside html task directory"
    return candidate, "candidate", ""


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_zip_members(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    total_size = 0
    max_files = settings.html_archive_max_files
    max_file_bytes = settings.html_archive_max_file_mb * 1024 * 1024
    max_total_bytes = settings.html_archive_max_total_mb * 1024 * 1024

    for info in archive.infolist():
        safe_name = _safe_zip_name(info.filename)
        if safe_name is None or info.is_dir():
            continue
        if info.file_size > max_file_bytes:
            raise ValueError(f"ZIP 内单个文件过大: {info.filename}")
        total_size += info.file_size
        if total_size > max_total_bytes:
            raise ValueError("ZIP 解压后总大小超过限制")
        members.append({"info": info, "safe_name": safe_name, "size": info.file_size})
        if len(members) > max_files:
            raise ValueError("ZIP 内文件数量超过限制")
    return members


def _safe_zip_name(name: str) -> str | None:
    normalized = name.replace("\\", "/").strip("/")
    if not normalized:
        return None
    parts = PurePosixPath(normalized).parts
    if "__MACOSX" in parts or Path(parts[-1]).name in {".DS_Store", "Thumbs.db"}:
        return None
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"ZIP 包含危险路径: {name}")
    if PureWindowsPath(normalized).drive or Path(normalized).is_absolute():
        raise ValueError(f"ZIP 包含绝对路径: {name}")
    return PurePosixPath(*parts).as_posix()


def _select_html_member(members: list[dict[str, Any]]) -> dict[str, Any] | None:
    html_members = [
        member for member in members
        if Path(member["safe_name"]).suffix.lower() in {".html", ".htm"}
    ]
    if not html_members:
        return None
    if len(html_members) == 1:
        return html_members[0]

    for member in html_members:
        if Path(member["safe_name"]).name.lower() in {"index.html", "index.htm"}:
            return member

    root_html = [
        member for member in html_members
        if len(PurePosixPath(member["safe_name"]).parts) == 1
    ]
    if root_html:
        return max(root_html, key=lambda member: member["size"])
    return max(html_members, key=lambda member: member["size"])


def _extract_zip_members(
    archive: zipfile.ZipFile,
    members: list[dict[str, Any]],
    extract_root: Path,
    required_html: str,
) -> None:
    extract_root_resolved = extract_root.resolve()
    for member in members:
        if not _should_extract_zip_member(member["safe_name"], required_html):
            continue
        target_path = (extract_root_resolved / member["safe_name"]).resolve()
        if not _is_relative_to(target_path, extract_root_resolved):
            raise ValueError(f"ZIP 解压目标越界: {member['safe_name']}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member["info"]) as src, target_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _should_extract_zip_member(safe_name: str, required_html: str) -> bool:
    if safe_name == required_html:
        return True
    return Path(safe_name).suffix.lower() in IMAGE_EXTENSIONS


def _is_remote_url(src: str) -> bool:
    return src.startswith("http://") or src.startswith("https://")
