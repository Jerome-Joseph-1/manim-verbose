"""
Pictures people add to a video: uploaded through the editor, kept beside the scene file.

    POST /api/assets    a multipart upload with one file; answers {"path": "assets/cat.png"}

A file is saved in an `assets` folder next to the scene file, under a name made safe from the
name it was sent with (`cat.png`, then `cat-2.png` for a different picture sent with the same
name; the same picture sent again gets its old name back), and the path returned is relative
to the scene file, which is what an image or svg object's `path` wants.

What is accepted is decided by the file's content, never by its name or the type the browser
claims: PNG, JPEG, GIF and WebP pictures, and SVG drawings which are plain XML with an <svg>
root (no DTD, so no entities). Anything else, anything over the size limit, and anything which
would land outside the scene file's folder is refused with a problem saying why.

Multipart bodies are read with the standard library's email parser, so that the server needs no
extra package for the one endpoint which takes a file.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from xml.etree import ElementTree

from starlette.requests import Request

ASSETS_FOLDER = "assets"
MAX_NAME_LENGTH = 48
# The kinds of file an image or svg object can show, by what they start with
KINDS = ("png", "jpg", "gif", "webp", "svg")


class AssetError(Exception):
    """An upload refused: `status` for the answer, `message` for the person."""

    def __init__(self, status: int, message: str, field: str = "file"):
        self.status = status
        self.message = message
        self.field = field
        super().__init__(message)


@dataclass
class Upload:
    filename: str
    data: bytes


def sniff(data: bytes) -> str | None:
    """What kind of picture `data` is ("png", "jpg", "gif", "webp" or "svg"), or None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if _is_svg(data):
        return "svg"
    return None


def _is_svg(data: bytes) -> bool:
    """Plain XML whose root is <svg>, without a DTD (which could declare entities)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    head = text.lstrip()[:512].lower()
    if not (head.startswith("<?xml") or head.startswith("<svg") or head.startswith("<!--")):
        return False
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        return False
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return False
    return root.tag == "svg" or root.tag.endswith("}svg")


def safe_stem(filename: str) -> str:
    """
    A name to save under, from the name a file was sent with: only its last part (whether
    the sender used / or \\), without its extension, in letters, digits, - and _.
    """
    base = re.split(r"[\\/]", filename or "")[-1]
    stem = base.rsplit(".", 1)[0] if "." in base.lstrip(".") else base
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")
    stem = stem[:MAX_NAME_LENGTH].rstrip("-_")
    return stem or "picture"


def assets_dir(base_dir: Path) -> Path:
    """The assets folder beside the scene file, made if need be; refused if it leads elsewhere."""
    base = Path(base_dir).resolve()
    folder = base / ASSETS_FOLDER
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise AssetError(500, f"'{ASSETS_FOLDER}' beside the scene file isn't a folder the editor can put pictures in")
    folder.mkdir(exist_ok=True)
    if not folder.resolve().is_relative_to(base):
        raise AssetError(500, f"'{ASSETS_FOLDER}' leads outside the scene file's folder")
    return folder


def save_asset(base_dir: Path, filename: str, data: bytes, max_bytes: int) -> str:
    """
    Save an uploaded picture beside the scene file; returns its path relative to the scene
    file's folder, with / between its parts, as a `path` field wants it.
    """
    if len(data) == 0:
        raise AssetError(422, "That file is empty")
    if len(data) > max_bytes:
        raise AssetError(413, f"That file is {_megabytes(len(data))}; pictures can be at most {_megabytes(max_bytes)}")
    kind = sniff(data)
    if kind is None:
        raise AssetError(415, "That isn't a picture the editor can use: send a PNG, JPEG, GIF, WebP or SVG file")
    folder = assets_dir(base_dir)
    stem = safe_stem(filename)
    digest = hashlib.sha256(data).digest()
    for n in range(1, 1000):
        name = f"{stem}.{kind}" if n == 1 else f"{stem}-{n}.{kind}"
        target = folder / name
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
        except FileExistsError:
            if _same_content(target, digest):
                return f"{ASSETS_FOLDER}/{name}"
            continue
        except OSError as err:
            if err.errno == errno.ENAMETOOLONG:
                stem = stem[:16] or "picture"
                continue
            raise AssetError(500, f"The picture couldn't be saved: {err.strerror}") from None
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
        except OSError as err:
            target.unlink(missing_ok=True)
            raise AssetError(500, f"The picture couldn't be saved: {err.strerror}") from None
        return f"{ASSETS_FOLDER}/{name}"
    raise AssetError(500, f"There are too many pictures called '{stem}' already")


def _same_content(path: Path, digest: bytes) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).digest() == digest
    except OSError:
        return False


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def parse_upload(body: bytes, content_type: str) -> Upload:
    """The one file of a multipart/form-data body (the part named `file`, else the first file)."""
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type.lower():
        raise AssetError(415, "Send the picture as multipart/form-data, in a part called 'file'")
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    try:
        message = BytesParser(policy=HTTP).parsebytes(head + body)
    except Exception:  # the email parser is lenient, but a body can still be beyond it
        raise AssetError(422, "The upload couldn't be read") from None
    if not message.is_multipart():
        raise AssetError(422, "The upload couldn't be read")
    files: list[Upload] = []
    named: Upload | None = None
    for part in message.iter_parts():
        filename = part.get_filename()
        name = part.get_param("name", header="content-disposition")
        if filename is None:
            continue
        payload = part.get_payload(decode=True) or b""
        upload = Upload(str(filename), payload)
        files.append(upload)
        if name == "file" and named is None:
            named = upload
    chosen = named or (files[0] if files else None)
    if chosen is None:
        raise AssetError(422, "The upload has no file in it")
    return chosen


def install_routes(app, editor) -> None:
    """POST /api/assets on the server's app (see server.create_app)."""
    from fastapi.concurrency import run_in_threadpool

    from manim_verbose.editor.server import ApiError, problem

    @app.post("/api/assets")
    async def upload_asset(request: Request):
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        def save() -> dict:
            upload = parse_upload(body, content_type)
            path = save_asset(editor.base_dir, upload.filename, upload.data, editor.limits.max_asset_bytes)
            return {"path": path, "kind": path.rsplit(".", 1)[-1]}

        try:
            return await run_in_threadpool(save)
        except AssetError as err:
            raise ApiError(err.status, [problem(err.message, [err.field])]) from None
