"""
Videos to start from: every scene file in manim_verbose/templates/ (`*.yaml`) is a template,
named by its file name, with its title and description taken from the document itself and a
thumbnail from `<name>.png` beside it when there is one.

    GET  /api/templates                      [{name, title, description, thumbnail_url}]
    GET  /api/templates/{name}               {name, title, description, thumbnail_url, document, problems}
    GET  /api/templates/{name}/thumbnail.png the picture
    POST /api/templates/{name}/apply         {base_revision} -> saved in place of the current document

The folder is read on every request (cheaply: files are parsed again only when they change),
so templates added while the editor runs show up without a restart. A template which can't be
read as a scene file is left out of the list, with a line in the log.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field

from manim_verbose.scenefile.files import parse_text, to_data
from manim_verbose.editor.documents import problems_json, read_document

log = logging.getLogger("manim_verbose.editor")

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ApplyBody(BaseModel):
    base_revision: Annotated[int, Field(strict=True)]


class TemplateNotFound(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"There's no template called '{name}'")


class Templates:
    """The templates in one folder."""

    def __init__(self, folder: str | Path | None = None):
        self.folder = Path(folder) if folder is not None else TEMPLATES_DIR
        self._cache: dict[Path, tuple[float, int, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        if not self.folder.is_dir():
            return []
        return sorted(p.stem for p in self.folder.glob("*.yaml") if p.is_file() and NAME.match(p.stem))

    def list(self) -> list[dict[str, Any]]:
        out = []
        for name in self.names():
            entry = self._read(name)
            if entry is not None:
                out.append(self._summary(name, entry))
        return out

    def get(self, name: str) -> dict[str, Any]:
        entry = self._read(name) if NAME.match(name or "") else None
        if entry is None:
            raise TemplateNotFound(name)
        return {**self._summary(name, entry), "document": entry["document"], "problems": entry["problems"]}

    def thumbnail(self, name: str) -> Path:
        if not NAME.match(name or "") or name not in self.names():
            raise TemplateNotFound(name)
        path = self.folder / f"{name}.png"
        if not path.is_file():
            raise TemplateNotFound(name)
        return path

    def _summary(self, name: str, entry: dict[str, Any]) -> dict[str, Any]:
        thumb = self.folder / f"{name}.png"
        return {
            "name": name,
            "title": entry["title"],
            "description": entry["description"],
            "thumbnail_url": f"/api/templates/{name}/thumbnail.png" if thumb.is_file() else None,
        }

    def _read(self, name: str) -> dict[str, Any] | None:
        path = self.folder / f"{name}.yaml"
        try:
            stat = path.stat()
        except OSError:
            return None
        with self._lock:
            cached = self._cache.get(path)
            if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                return cached[2]
        entry = _load(path)
        with self._lock:
            self._cache[path] = (stat.st_mtime, stat.st_size, entry)
        return entry


def _load(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        log.warning("template %s can't be read: %s", path.name, err)
        return None
    data, problems = parse_text(text, "yaml")
    doc = None
    if not problems:
        doc, problems = read_document(data)
    if doc is None:
        log.warning("template %s isn't a scene file: %s", path.name, "; ".join(p.message for p in problems))
        return None
    return {
        "title": doc.title,
        "description": doc.description,
        "document": to_data(doc),
        "problems": problems_json(problems),
    }


def install_routes(app, editor, templates: Templates) -> None:
    """The /api/templates routes on the server's app (see server.create_app)."""
    from fastapi.responses import FileResponse

    from manim_verbose.editor.server import ApiError, SaveBody, problem

    def found(name: str) -> dict[str, Any]:
        try:
            return templates.get(name)
        except TemplateNotFound as err:
            raise ApiError(404, [problem(str(err), ["name"])]) from None

    @app.get("/api/templates")
    def list_templates():
        return {"templates": templates.list()}

    @app.get("/api/templates/{name}")
    def get_template(name: str):
        return found(name)

    @app.get("/api/templates/{name}/thumbnail.png")
    def template_thumbnail(name: str):
        try:
            path = templates.thumbnail(name)
        except TemplateNotFound:
            raise ApiError(404, [problem(f"There's no picture for a template called '{name}'", ["name"])]) from None
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.post("/api/templates/{name}/apply")
    def apply_template(name: str, body: ApplyBody):
        template = found(name)
        return editor.put_document(SaveBody(document=template["document"], base_revision=body.base_revision))
