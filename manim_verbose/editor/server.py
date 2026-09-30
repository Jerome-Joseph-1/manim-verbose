"""
The editor's server: the HTTP API in docs/editor/server-api.md, and the browser editor itself.

    create_app(path)   a FastAPI app editing the scene file at `path`

The app edits one scene file. Documents come and go as JSON; anything wrong comes back as
problems (see scenefile/validate.py), never as a stack trace. Rendering happens in worker
processes (workers.py), scheduled by jobs.py, with results cached in the output folder
(outputs.py); what renders is decided by a backend (backend.py), which tests replace with a
fake. Handlers which only touch the document run in FastAPI's thread pool; those which wait on
a render wait on a future, so the event loop never blocks and the server keeps answering
whatever a render is doing.
"""
from __future__ import annotations

import asyncio
import difflib
import itertools
import logging
import re
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from manim_verbose.editor.backend import (
    Backend, RenderBackend, render_error_problems, run_clip, run_still, run_video, timeline_data,
)
from manim_verbose.editor.documents import (
    Conflict, DocumentStore, SaveFailed, Unreadable, problems_json, read_document,
)
from manim_verbose.editor.jobs import Job, JobPool, JobRegistry, StillQueue, Superseded, Task
from manim_verbose.editor.limits import Limits, size_problems
from manim_verbose.editor.outputs import OutputDir, cache_key, default_output_dir, file_stamps
from manim_verbose.editor.workers import (
    RenderException, RenderProblems, WorkerCancelled, WorkerCrashed, WorkerProcess, WorkerTimeout,
)
from manim_verbose.scenefile.files import to_data
from manim_verbose.scenefile.model import Document
from manim_verbose.scenefile.validate import Problem

log = logging.getLogger("manim_verbose.editor")

STATIC_DIR = Path(__file__).with_name("static")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def version() -> str:
    try:
        return metadata.version("manimgl")
    except metadata.PackageNotFoundError:
        return "unknown"


class ApiError(Exception):
    """Answer a request with `status` and `{"problems": [...], **extra}`."""

    def __init__(self, status: int, problems: list[dict[str, Any]], **extra: Any):
        self.status = status
        self.problems = problems
        self.extra = extra
        super().__init__(problems[0]["message"] if problems else str(status))


def problem(message: str, loc: list[str | int] | None = None, scene_id: str | None = None,
            item_id: str | None = None, severity: str = "error") -> dict[str, Any]:
    return Problem(message, list(loc or []), severity, scene_id, item_id).to_json()


# Request bodies. Numbers and names are strict, so "3" is not taken for 3.

StrictInt = Annotated[int, Field(strict=True)]
StrictStr = Annotated[str, Field(strict=True)]


class DocumentBody(BaseModel):
    document: dict[str, Any]


class SaveBody(DocumentBody):
    base_revision: StrictInt


class StillBody(DocumentBody):
    scene_id: StrictStr
    step_index: StrictInt = -1
    width: StrictInt = 960


class ClipBody(DocumentBody):
    scene_id: StrictStr
    start_step: StrictInt = 0
    end_step: StrictInt | None = None


class CodeBody(DocumentBody):
    scene_id: StrictStr | None = None


class ExportBody(DocumentBody):
    quality: Literal["low", "medium", "hd", "uhd"] = "hd"


@dataclass
class Checked:
    """A document which may be rendered, as far as the scene asked for goes."""
    doc: Document
    problems: list[dict[str, Any]]
    scene_index: int | None


@dataclass
class PreparedRender:
    checked: Checked
    key: str
    cached: Any


class Editor:
    """Everything behind the API: the document, the renderers and the output folder."""

    def __init__(self, path: str | Path, output_dir: str | Path | None, backend: Backend, limits: Limits):
        self.store = DocumentStore(path)
        self.backend = backend
        self.limits = limits
        self.outputs = OutputDir(output_dir or default_output_dir(self.store.path),
                                 limits.cached_stills, limits.cached_clips)
        self.salt = backend.cache_salt()
        self.stills = StillQueue(WorkerProcess(backend, "stills", limits.worker_start_timeout, limits.cancel_grace))
        self.pool = JobPool(backend, limits.job_workers, limits.worker_start_timeout, limits.cancel_grace)
        self.jobs = JobRegistry(limits.finished_jobs_kept)
        self._seq = itertools.count(1)
        self._clips: dict[str, Any] = {}
        self._clips_lock = threading.Lock()

    @property
    def base_dir(self) -> Path:
        return self.store.base_dir

    def next_seq(self) -> int:
        return next(self._seq)

    def close(self) -> None:
        for job in self.jobs.all():
            job.settle("cancelled", "The editor was closed")
        self.stills.close()
        self.pool.close()

    # The document

    def get_document(self) -> dict[str, Any]:
        snap = self.store.snapshot()
        return {"document": snap.document, "path": str(self.store.path), "revision": snap.revision,
                "problems": problems_json(snap.problems)}

    def put_document(self, body: SaveBody) -> dict[str, Any]:
        self.check_size(body.document)
        try:
            snap = self.store.save(body.document, body.base_revision)
        except Conflict as err:
            raise ApiError(409, err.current["problems"], document=err.current["document"],
                           revision=err.current["revision"])
        except Unreadable as err:
            raise ApiError(422, problems_json(err.problems))
        except SaveFailed as err:
            log.error("%s", err)
            raise ApiError(500, [problem(str(err))])
        return {"revision": snap.revision, "problems": problems_json(snap.problems), "document": snap.document}

    def validate(self, body: DocumentBody) -> dict[str, Any]:
        problems = size_problems(body.document, self.limits)
        if not problems:
            _, problems = read_document(body.document)
        return {"problems": problems_json(problems)}

    def check_size(self, data: Any) -> None:
        problems = size_problems(data, self.limits)
        if problems:
            raise ApiError(422, problems_json(problems))

    def check(self, data: dict[str, Any], scene_id: str | None) -> Checked:
        """
        Read a document for rendering. Errors stop it, but only those in the scene rendered
        (or anywhere, with no scene given), so that a typo in one scene doesn't stop the others
        being previewed.
        """
        self.check_size(data)
        doc, problems = read_document(data)
        if doc is None:
            raise ApiError(422, problems_json(problems))
        scene_index = None
        if scene_id is not None:
            scene_index = self.scene_index(doc, scene_id)
        blocking = [p for p in problems
                    if p.severity == "error" and (scene_id is None or p.scene_id in (None, scene_id))]
        if blocking:
            raise ApiError(422, problems_json(problems))
        return Checked(doc, problems_json(problems), scene_index)

    @staticmethod
    def scene_index(doc: Document, scene_id: str) -> int:
        ids = [scene.id for scene in doc.scenes]
        if scene_id in ids:
            return ids.index(scene_id)
        message = f"There's no scene called '{scene_id}'"
        close = difflib.get_close_matches(scene_id, ids, n=1, cutoff=0.6)
        if close:
            message += f" (did you mean '{close[0]}'?)"
        message += ". Scenes are: " + ", ".join(ids)
        raise ApiError(422, [problem(message, ["scene_id"])])

    # Stills

    def prepare_still(self, body: StillBody) -> PreparedRender:
        checked = self.check(body.document, body.scene_id)
        scene = checked.doc.scenes[checked.scene_index]
        count = len(scene.steps)
        if not -1 <= body.step_index < count:
            if count:
                message = f"Scene '{scene.id}' has {count} steps, so step_index can be from -1 to {count - 1}"
            else:
                message = f"Scene '{scene.id}' has no steps yet, so step_index can only be -1"
            raise ApiError(422, [problem(message, ["step_index"], scene.id)])
        low, high = self.limits.min_still_width, self.limits.max_still_width
        if not low <= body.width <= high:
            raise ApiError(422, [problem(f"width has to be between {low} and {high} pixels", ["width"], scene.id)])
        data = to_data(checked.doc)
        scene_data = data["scenes"][checked.scene_index]
        shown = {**scene_data, "steps": scene_data.get("steps", [])[:body.step_index + 1]}
        key = cache_key("still", self.salt, data.get("version"), data.get("settings"), shown, body.step_index,
                        body.width, str(self.base_dir), file_stamps(scene_data, self.base_dir))
        return PreparedRender(checked, key, self.outputs.still(key))

    def still_task(self, body: StillBody, prepared: PreparedRender, seq: int) -> Task:
        partial = self.outputs.partial("stills")
        return Task(
            fn=run_still,
            kwargs={"doc": prepared.checked.doc, "scene_id": body.scene_id, "step_index": body.step_index,
                    "width": body.width, "out_png": str(partial), "base_dir": str(self.base_dir)},
            timeout=self.limits.still_timeout, key=prepared.key, seq=seq,
            finish=lambda data: self.outputs.store_still(prepared.key, data),
            discard=lambda: self.outputs.discard(partial),
        )

    # Clips

    def prepare_clip(self, body: ClipBody) -> PreparedRender:
        checked = self.check(body.document, body.scene_id)
        scene = checked.doc.scenes[checked.scene_index]
        count = len(scene.steps)
        if count == 0:
            raise ApiError(422, [problem(f"Scene '{scene.id}' has no steps to play yet", ["scene_id"], scene.id)])
        end = count - 1 if body.end_step is None else body.end_step
        if not 0 <= body.start_step < count:
            raise ApiError(422, [problem(
                f"Scene '{scene.id}' has {count} steps, so start_step can be from 0 to {count - 1}",
                ["start_step"], scene.id)])
        if not body.start_step <= end < count:
            raise ApiError(422, [problem(
                f"end_step has to be from start_step ({body.start_step}) to {count - 1}", ["end_step"], scene.id)])
        data = to_data(checked.doc)
        scene_data = data["scenes"][checked.scene_index]
        played = {**scene_data, "steps": scene_data.get("steps", [])[:end + 1]}
        key = cache_key("clip", self.salt, data.get("version"), data.get("settings"), played, body.start_step, end,
                        "low", str(self.base_dir), file_stamps(scene_data, self.base_dir))
        return PreparedRender(checked, key, self.outputs.clip(key))

    def submit_clip(self, body: ClipBody, prepared: PreparedRender):
        """Queue a clip, or share the one already queued or rendering for the same key."""
        with self._clips_lock:
            future = self._clips.get(prepared.key)
            if future is not None and not future.done():
                return future
            partial = self.outputs.partial("clips")
            task = Task(
                fn=run_clip,
                kwargs={"doc": prepared.checked.doc, "scene_id": body.scene_id, "start_step": body.start_step,
                        "end_step": body.end_step, "out_mp4": str(partial), "base_dir": str(self.base_dir)},
                timeout=self.limits.clip_timeout, key=prepared.key, priority=0,
                finish=lambda data: self.outputs.store_clip(prepared.key, data),
                discard=lambda: self.outputs.discard(partial),
            )
            self._clips[prepared.key] = task.future
            task.future.add_done_callback(lambda _: self._forget_clip(prepared.key, task.future))
            self.pool.submit(task)
            return task.future

    def _forget_clip(self, key: str, future) -> None:
        with self._clips_lock:
            if self._clips.get(key) is future:
                del self._clips[key]

    # Failed renders

    def render_failure(self, err: BaseException, checked: Checked, what: str) -> JSONResponse:
        scene_id = None
        loc: list[str | int] = []
        if checked.scene_index is not None:
            scene_id = checked.doc.scenes[checked.scene_index].id
            loc = ["scenes", checked.scene_index]
        if isinstance(err, RenderProblems):
            return JSONResponse({"problems": err.problems + checked.problems}, status_code=422)
        if isinstance(err, WorkerTimeout):
            message = (f"Drawing this {what} took longer than {err.seconds:g} seconds, so it was stopped. "
                       "Try it with fewer or simpler steps")
            return JSONResponse({"problems": [problem(message, loc, scene_id)]}, status_code=422)
        if isinstance(err, WorkerCrashed):
            message = (f"The renderer stopped unexpectedly while drawing this {what}. "
                       "It has been restarted, so try again")
            return JSONResponse({"problems": [problem(message, loc, scene_id)]}, status_code=500)
        if isinstance(err, RenderException):
            log.error("rendering a %s failed: %s\n%s", what, err, err.details)
            message = f"Something went wrong while drawing this {what}: {err}"
        else:
            log.error("rendering a %s failed", what, exc_info=err)
            message = f"Something went wrong while drawing this {what}. The details are in the editor's log"
        return JSONResponse({"problems": [problem(message, loc, scene_id)]}, status_code=500)

    # Code and timings

    def code(self, body: CodeBody) -> dict[str, Any]:
        checked = self.check(body.document, body.scene_id)
        scene_ids = [body.scene_id] if body.scene_id is not None else None
        try:
            text = self.backend.code(checked.doc, scene_ids, self.base_dir)
        except Exception as err:
            problems = render_error_problems(err)
            if problems is not None:
                raise ApiError(422, problems + checked.problems)
            log.exception("making code failed")
            raise ApiError(500, [problem("Something went wrong while turning this into code. "
                                         "The details are in the editor's log")])
        return {"code": text}

    def timeline(self, scene_id: str) -> dict[str, Any]:
        snap = self.store.snapshot()
        if snap.doc is None:
            raise ApiError(422, problems_json(snap.problems))
        index = self.scene_index(snap.doc, scene_id)
        try:
            steps = timeline_data(self.backend.timeline(snap.doc, scene_id))
            duration = float(self.backend.scene_duration(snap.doc, scene_id))
        except Exception as err:
            blocking = [p for p in snap.problems if p.severity == "error" and p.scene_id in (None, scene_id)]
            if blocking:
                raise ApiError(422, problems_json(snap.problems))
            problems = render_error_problems(err)
            if problems is not None:
                raise ApiError(422, problems)
            log.exception("timing scene %s failed", scene_id)
            raise ApiError(500, [problem("Something went wrong while timing this scene. "
                                         "The details are in the editor's log", ["scenes", index], scene_id)])
        return {"steps": steps, "duration": duration, "revision": snap.revision}

    # Exports

    def export(self, body: ExportBody) -> Job:
        checked = self.check(body.document, None)
        if self.jobs.pending() >= self.limits.max_pending_exports:
            raise ApiError(429, [problem(
                f"There are already {self.limits.max_pending_exports} exports waiting or running. "
                "Wait for one to finish, or cancel one")])
        partial = self.outputs.partial("exports")
        job = Job()
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", self.store.path.stem).strip("_") or "video"
        name = f"{stem}-{body.quality}-{job.job_id[:8]}.mp4"
        task = Task(
            fn=run_video,
            kwargs={"doc": checked.doc, "quality": body.quality, "out_mp4": str(partial),
                    "base_dir": str(self.base_dir)},
            timeout=self.limits.export_timeout, priority=1,
            finish=lambda data: self.outputs.store_export(Path(data["path"]), name),
            discard=lambda: self.outputs.discard(partial),
            on_start=job.started, progress=job.advance,
        )
        job.task = task
        task.future.add_done_callback(lambda future: self._export_done(job, future))
        self.jobs.add(job)
        self.pool.submit(task)
        return job

    def _export_done(self, job: Job, future) -> None:
        if future.cancelled():
            job.settle("cancelled", "Cancelled")
            return
        err = future.exception()
        if err is None:
            url = future.result()
            if not job.settle("done", "Finished", output_url=url):
                self.outputs.discard(self.outputs.resolve("exports", url.rsplit("/", 1)[-1]))
            return
        if isinstance(err, WorkerCancelled):
            job.settle("cancelled", "Cancelled")
        elif isinstance(err, RenderProblems):
            job.settle("failed", "The video couldn't be made", problems=err.problems)
        elif isinstance(err, WorkerTimeout):
            job.settle("failed", "Stopped: it took too long", problems=[problem(
                f"The export took longer than {err.seconds / 60:g} minutes, so it was stopped")])
        elif isinstance(err, WorkerCrashed):
            job.settle("failed", "The renderer stopped unexpectedly", problems=[problem(
                "The renderer stopped unexpectedly while making the video. Try exporting again")])
        else:
            details = getattr(err, "details", "")
            log.error("an export failed: %s\n%s", err, details, exc_info=None if details else err)
            job.settle("failed", "Something went wrong", problems=[problem(
                f"Something went wrong while making the video: {err}")])

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job.finished:
            job.settle("cancelled", "Cancelled")
            if job.task is not None:
                self.pool.cancel(job.task)
        return job.to_json()

    def job(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise ApiError(404, [problem(f"There's no export with id '{job_id}'", ["job_id"])])
        return job


def create_app(path: str | Path, *, output_dir: str | Path | None = None, backend: Backend | None = None,
               limits: Limits | None = None, static_dir: str | Path | None = None,
               allowed_hosts: set[str] | frozenset[str] | None = None, start_workers: bool = True) -> FastAPI:
    """
    An app editing the scene file at `path`. Renders go to `output_dir` (a folder in the
    user's cache by default) and are made by `backend` (the real renderer by default).
    `allowed_hosts`, when given, is the set of host names requests may be addressed to, which
    keeps web pages elsewhere from reaching a server on localhost by DNS rebinding.
    `start_workers` starts the still worker as the app starts, rather than on the first still.
    """
    limits = limits or Limits()
    editor = Editor(path, output_dir, backend or RenderBackend(), limits)
    static = Path(static_dir) if static_dir is not None else STATIC_DIR

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_workers:
            editor.stills.start()
            threading.Thread(target=_warm_validation, name="warm-validation", daemon=True).start()
        try:
            yield
        finally:
            await run_in_threadpool(editor.close)

    app = FastAPI(title="manimgl editor", version=version(), lifespan=lifespan, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.editor = editor
    app.add_middleware(BodyLimit, max_bytes=limits.max_body_bytes)
    if allowed_hosts is not None:
        app.add_middleware(HostCheck, allowed=frozenset(h.lower() for h in allowed_hosts))

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse({"problems": exc.problems, **exc.extra}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError):
        return JSONResponse({"problems": [request_problem(e) for e in exc.errors()]}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            message = f"There's nothing at {request.url.path}"
        elif exc.status_code == 405:
            message = f"{request.method} isn't something {request.url.path} answers to"
        else:
            message = str(exc.detail)
        return JSONResponse({"problems": [problem(message)]}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.error("%s %s failed", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"problems": [problem(
            "Something went wrong in the editor's server. The details are in its log")]}, status_code=500)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": version()}

    @app.get("/api/document")
    def get_document():
        return editor.get_document()

    @app.put("/api/document")
    def put_document(body: SaveBody):
        return editor.put_document(body)

    @app.post("/api/validate")
    def validate(body: DocumentBody):
        return editor.validate(body)

    @app.get("/api/schema")
    def schema():
        return _schema()

    @app.get("/api/catalog")
    def get_catalog():
        from manim_verbose.editor.catalog import catalog
        return catalog()

    @app.post("/api/still")
    async def still(body: StillBody):
        seq = editor.next_seq()
        prepared = await run_in_threadpool(editor.prepare_still, body)
        if prepared.cached is not None:
            editor.stills.note(seq)
            return {**prepared.cached, "problems": prepared.checked.problems}
        future = editor.stills.submit(editor.still_task(body, prepared, seq))
        try:
            result = await asyncio.shield(asyncio.wrap_future(future))
        except Superseded:
            return JSONResponse({"superseded": True}, status_code=409)
        except Exception as err:
            return editor.render_failure(err, prepared.checked, "frame")
        return {**result, "problems": prepared.checked.problems}

    @app.post("/api/clip")
    async def clip(body: ClipBody):
        prepared = await run_in_threadpool(editor.prepare_clip, body)
        if prepared.cached is not None:
            return {"video_url": prepared.cached, "problems": prepared.checked.problems}
        future = editor.submit_clip(body, prepared)
        try:
            url = await asyncio.shield(asyncio.wrap_future(future))
        except Exception as err:
            return editor.render_failure(err, prepared.checked, "clip")
        return {"video_url": url, "problems": prepared.checked.problems}

    @app.post("/api/code")
    def code(body: CodeBody):
        return editor.code(body)

    @app.get("/api/timeline")
    def timeline(scene_id: str):
        return editor.timeline(scene_id)

    @app.post("/api/export", status_code=202)
    def export(body: ExportBody):
        job = editor.export(body)
        return JSONResponse({"job_id": job.job_id}, status_code=202)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return editor.job(job_id).to_json()

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str):
        return editor.cancel(job_id)

    @app.get("/files/{kind}/{name}")
    def files(kind: str, name: str):
        path = editor.outputs.resolve(kind, name)
        if path is None:
            raise ApiError(404, [problem(f"There's no file called '{name}' among the {kind}")])
        cache = "no-cache" if kind == "exports" else "public, max-age=31536000, immutable"
        return FileResponse(path, headers={"Cache-Control": cache})

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str):
        if path.split("/", 1)[0] in ("api", "files"):
            raise ApiError(404, [problem(f"There's nothing at /{path}")])
        index = static / "index.html"
        if not index.is_file():
            return HTMLResponse(UNBUILT_PAGE)
        if path:
            found = _static_file(static, path)
            if found is not None:
                return FileResponse(found)
            if "." in path.rsplit("/", 1)[-1]:
                raise ApiError(404, [problem(f"There's nothing at /{path}")])
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def _static_file(static: Path, path: str) -> Path | None:
    root = static.resolve()
    try:
        found = (root / path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not found.is_file() or not found.is_relative_to(root):
        return None
    return found


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    from manim_verbose.scenefile.schema import document_schema
    return document_schema()


def _warm_validation() -> None:
    """Checking a color name imports manim; do that now rather than during someone's first edit."""
    try:
        from manim_verbose.scenefile.model import manim_color_names
        manim_color_names()
    except Exception:
        log.exception("importing manim failed")


def request_problem(error: dict[str, Any]) -> dict[str, Any]:
    """A problem with a request itself (rather than the document in it), in words."""
    loc = [part for part in error.get("loc", ()) if part not in ("body", "query", "path")]
    etype = error.get("type", "")
    if etype == "json_invalid":
        return problem("The request isn't valid JSON")
    name = next((str(part) for part in reversed(loc) if isinstance(part, str)), None)
    if etype == "missing":
        message = f"The request needs '{name}'"
    elif etype in ("int_type", "int_parsing", "int_from_float"):
        message = f"'{name}' has to be a whole number"
    elif etype in ("string_type", "string_parsing"):
        message = f"'{name}' has to be text"
    elif etype in ("dict_type", "model_type", "model_attributes_type"):
        message = f"'{name}' has to be a JSON object" if name else "The request has to be a JSON object"
    elif etype == "literal_error":
        message = f"'{name}' has to be one of {(error.get('ctx') or {}).get('expected')}"
    else:
        message = f"'{name}': {error.get('msg')}" if name else str(error.get("msg"))
    return problem(message, loc)


# Middleware

class BodyLimit:
    """Refuse request bodies over `max_bytes` with 413, whether or not they say their length up front."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_big = int(value) > self.max_bytes
                except ValueError:
                    too_big = False
                if too_big:
                    return await self._too_large(scope, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                return await self._too_large(scope, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _too_large(self, scope, send):
        megabytes = self.max_bytes / (1024 * 1024)
        response = JSONResponse({"problems": [problem(
            f"That's too much to send at once: the editor takes at most {megabytes:g} MB in one request")]},
            status_code=413)
        await response(scope, _nothing, send)


async def _nothing():
    return {"type": "http.disconnect"}


class HostCheck:
    """Answer only requests addressed to one of `allowed` host names (any port)."""

    def __init__(self, app, allowed: frozenset[str]):
        self.app = app
        self.allowed = allowed

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = ""
            for name, value in scope.get("headers", []):
                if name == b"host":
                    host = value.decode("latin-1")
                    break
            if _host_name(host) not in self.allowed:
                response = JSONResponse({"problems": [problem(
                    "This editor only answers requests addressed to the computer it runs on")]}, status_code=400)
                return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def _host_name(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


UNBUILT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>manimgl editor</title>
<style>
  body { font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;
         color: #222; background: #fafafa; }
  code, pre { font-family: ui-monospace, monospace; background: #eee; padding: 0.1rem 0.3rem; border-radius: 4px; }
  pre { padding: 0.75rem 1rem; }
  @media (prefers-color-scheme: dark) {
    body { color: #ddd; background: #1b1b1b; } code, pre { background: #333; }
  }
</style>
</head>
<body>
<h1>The editor isn't built yet</h1>
<p>The server is running, but the browser editor it serves hasn't been built. From a checkout of
the repository, build it with:</p>
<pre>cd editor-ui &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>then reload this page. The API is up in the meantime: see <a href="/api/docs">/api/docs</a>.</p>
</body>
</html>
"""
