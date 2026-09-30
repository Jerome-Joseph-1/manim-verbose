"""
Layout checks for the editor: `POST /api/layout`, which finds what in a scene runs off the
frame, sits under the captions, or collides with something else (see
scenefile/layout_check.py for the rules), step by step.

    POST /api/layout  {document, scene_id, revision?}  ->  200 {problems: [...], revision?}

Every problem is a warning on an object of the scene (its `place` when that is what put it
there). `revision`, when the request gives one, comes back as it was sent, so the editor can
tell which version of the document an answer is about.

Checks run in a worker process of their own (see workers.py), one at a time, so that neither
a still nor an export waits on them, nor they on those. Answers are cached by the content of
the scene (and what it carries over from the scene before), in memory here and on disk by
the checker itself, and a request for a check already under way shares its answer.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from manim_verbose.editor.backend import problem_json
from manim_verbose.editor.jobs import JobPool, Task
from manim_verbose.editor.outputs import cache_key, file_stamps
from manim_verbose.editor.workers import RenderException, RenderProblems, WorkerCrashed, WorkerTimeout
from manim_verbose.scenefile.files import to_data
from manim_verbose.scenefile.validate import Problem

log = logging.getLogger("manim_verbose.editor")

# How long checking one scene may take before its worker is stopped, in seconds. A check
# builds the scene without drawing it, so this is generous.
LAYOUT_TIMEOUT = 120.0
# Answers kept in memory, by content
CACHED_ANSWERS = 500


class LayoutBody(BaseModel):
    document: dict[str, Any]
    scene_id: Annotated[str, Field(strict=True)]
    revision: Annotated[int, Field(strict=True)] | None = None


def run_layout(backend: Any, *, doc, scene_id: str, base_dir: str, **_: Any) -> list[dict[str, Any]]:
    """What a worker process runs: the backend's check of one scene, as json problems."""
    return [problem_json(p) for p in backend.layout(doc, scene_id, Path(base_dir))]


@dataclass
class _Prepared:
    checked: Any
    key: str
    cached: list[dict[str, Any]] | None


class LayoutChecks:
    """The layout checks behind the endpoint: a worker of their own, and answers cached by content."""

    def __init__(self, editor):
        self.editor = editor
        self.timeout = LAYOUT_TIMEOUT
        limits = editor.limits
        self.pool = JobPool(editor.backend, 1, limits.worker_start_timeout, limits.cancel_grace)
        self.pool.workers[0].name = "layout"
        self._answers: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._running: dict[str, Any] = {}
        self._lock = threading.Lock()

    def prepare(self, body: LayoutBody) -> _Prepared:
        editor = self.editor
        checked = editor.check(body.document, body.scene_id)
        data = to_data(checked.doc)
        index = checked.scene_index
        scene_data = data["scenes"][index]
        # A scene carrying objects over starts from where the scenes before it left them
        scenes = data["scenes"][:index + 1] if scene_data.get("carry") else [scene_data]
        stamps = [file_stamps(scene, editor.base_dir) for scene in scenes]
        key = cache_key("layout", editor.salt, data.get("version"), data.get("settings"), scenes,
                        str(editor.base_dir), stamps)
        with self._lock:
            cached = self._answers.get(key)
            if cached is not None:
                self._answers.move_to_end(key)
        return _Prepared(checked, key, cached)

    def submit(self, body: LayoutBody, prepared: _Prepared):
        """Queue a check, or share the one already queued or running for the same content."""
        with self._lock:
            future = self._running.get(prepared.key)
            if future is not None and not future.done():
                return future
            task = Task(
                fn=run_layout,
                kwargs={"doc": prepared.checked.doc, "scene_id": body.scene_id,
                        "base_dir": str(self.editor.base_dir)},
                timeout=self.timeout, key=prepared.key,
                finish=lambda problems: self._remember(prepared.key, problems),
            )
            self._running[prepared.key] = task.future
            task.future.add_done_callback(lambda _: self._forget(prepared.key, task.future))
            self.pool.submit(task)
            return task.future

    def _remember(self, key: str, problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._lock:
            self._answers[key] = problems
            self._answers.move_to_end(key)
            while len(self._answers) > CACHED_ANSWERS:
                self._answers.popitem(last=False)
        return problems

    def _forget(self, key: str, future) -> None:
        with self._lock:
            if self._running.get(key) is future:
                del self._running[key]

    def failure(self, err: BaseException, prepared: _Prepared) -> JSONResponse:
        """A check which didn't finish, as problems on the scene (or, from the checker, where they belong)."""
        checked = prepared.checked
        scene_id = checked.doc.scenes[checked.scene_index].id
        loc = ["scenes", checked.scene_index]
        if isinstance(err, RenderProblems):
            return JSONResponse({"problems": err.problems}, status_code=422)
        if isinstance(err, WorkerTimeout):
            message = (f"Checking the layout of this scene took longer than {err.seconds:g} seconds, "
                       "so it was stopped. Try it with fewer or simpler steps")
            return JSONResponse({"problems": [_problem(message, loc, scene_id)]}, status_code=422)
        if isinstance(err, WorkerCrashed):
            message = ("The layout checker stopped unexpectedly while checking this scene. "
                       "It has been restarted, so try again")
            return JSONResponse({"problems": [_problem(message, loc, scene_id)]}, status_code=500)
        if isinstance(err, RenderException):
            log.error("checking a layout failed: %s\n%s", err, err.details)
            message = f"Something went wrong while checking the layout of this scene: {err}"
        else:
            log.error("checking a layout failed", exc_info=err)
            message = "Something went wrong while checking the layout of this scene. The details are in the editor's log"
        return JSONResponse({"problems": [_problem(message, loc, scene_id)]}, status_code=500)

    def close(self) -> None:
        self.pool.close()


def add_layout_route(app: FastAPI, editor) -> LayoutChecks:
    """Adds `POST /api/layout` to the app, and hands back what serves it, for closing when the app stops."""
    checks = LayoutChecks(editor)

    @app.post("/api/layout")
    async def layout(body: LayoutBody):
        prepared = await run_in_threadpool(checks.prepare, body)
        answer: dict[str, Any] = {}
        if prepared.cached is not None:
            answer["problems"] = prepared.cached
        else:
            future = checks.submit(body, prepared)
            try:
                answer["problems"] = await asyncio.shield(asyncio.wrap_future(future))
            except Exception as err:
                return checks.failure(err, prepared)
        if body.revision is not None:
            answer["revision"] = body.revision
        return answer

    return checks


def _problem(message: str, loc: list[str | int], scene_id: str) -> dict[str, Any]:
    return Problem(message, loc, "error", scene_id).to_json()
