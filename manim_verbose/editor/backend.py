"""
What the server needs from the rest of the package, gathered behind one object.

A backend is anything with the methods of `Backend` below. The real one, `RenderBackend`, is a
thin layer over scenefile/render.py and scenefile/codegen.py; tests hand the server a fake
which draws synthetic pictures at once. Its still, clip and video methods run in worker
processes (see workers.py), so a backend has to be picklable, which a plain class defined at
module level is. The others run in the server's own process, off the event loop.

The `run_*` functions at the bottom are what a worker process actually calls: each asks the
backend for a render and turns the result into plain data to send back to the server.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from manim_verbose.scenefile.model import Document
from manim_verbose.scenefile.validate import Problem

Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


class Backend(Protocol):
    def warm(self) -> None:
        """Called once in each new worker process, to import and set up whatever renders need."""

    def cache_salt(self) -> str:
        """Changes whenever the same document could start to render differently."""

    def still(self, doc: Document, scene_id: str, step_index: int, out_png: Path, width: int,
              base_dir: Path) -> Any:
        """A StillResult, or anything with its attributes."""

    def clip(self, doc: Document, scene_id: str, out_mp4: Path, start_step: int, end_step: int | None,
             base_dir: Path) -> Any:
        """The path of the clip written."""

    def video(self, doc: Document, out_mp4: Path, quality: str, base_dir: Path,
              progress: Progress, cancel: Cancelled) -> Any:
        """The path of the video written."""

    def timeline(self, doc: Document, scene_id: str) -> Sequence[Any]:
        """StepTimings, or anything with their attributes."""

    def scene_duration(self, doc: Document, scene_id: str) -> float: ...

    def code(self, doc: Document, scene_ids: list[str] | None, base_dir: Path) -> str: ...

    def layout(self, doc: Document, scene_id: str, base_dir: Path) -> Sequence[Any]:
        """Layout problems (Problems, or problem dicts) in one scene. Runs in a worker process."""


class RenderBackend:
    """The real renderer: scenefile/render.py for pictures and timings, codegen.py for code."""

    def __init__(self, export_jobs: int | None = None):
        self.export_jobs = export_jobs

    def warm(self) -> None:
        from manim_verbose.manim_import import import_manim
        import_manim()
        from manim_verbose.scenefile import render  # noqa: F401

    def cache_salt(self) -> str:
        """The package's own source, and manim's version: a stale still after an upgrade is worse than a slow one."""
        from importlib import metadata
        digest = hashlib.sha256()
        scenefile = Path(__file__).resolve().parent.parent / "scenefile"
        for source in sorted(scenefile.glob("*.py")):
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
        try:
            digest.update(metadata.version("manimgl").encode())
        except metadata.PackageNotFoundError:
            pass
        return digest.hexdigest()[:16]

    def still(self, doc, scene_id, step_index, out_png, width, base_dir):
        from manim_verbose.scenefile import render
        return render.render_still(doc, scene_id, step_index, out_png, width=width, base_dir=base_dir)

    def clip(self, doc, scene_id, out_mp4, start_step, end_step, base_dir):
        from manim_verbose.scenefile import render
        return render.render_clip(doc, scene_id, out_mp4, start_step=start_step, end_step=end_step,
                                  quality="low", base_dir=base_dir)

    def video(self, doc, out_mp4, quality, base_dir, progress, cancel):
        from manim_verbose.scenefile import render
        return render.render_video(doc, out_mp4, quality=quality, jobs=self.export_jobs, base_dir=base_dir,
                                   progress=progress, cancel=cancel)

    def timeline(self, doc, scene_id):
        from manim_verbose.scenefile import render
        return render.timeline(doc, scene_id)

    def scene_duration(self, doc, scene_id):
        from manim_verbose.scenefile import render
        return render.scene_duration(doc, scene_id)

    def code(self, doc, scene_ids, base_dir):
        from manim_verbose.scenefile.codegen import document_to_python
        return document_to_python(doc, base_dir=base_dir, scene_ids=scene_ids)

    def layout(self, doc, scene_id, base_dir):
        """Layout warnings for one scene (scenefile/layout_check.py); a RenderError if it can't be built."""
        from manim_verbose.scenefile.layout_check import check_layout
        from manim_verbose.scenefile.render import RenderError
        problems = check_layout(doc, scene_id, base_dir=base_dir)
        errors = [p for p in problems if p.severity == "error"]
        if errors:
            raise RenderError(errors)
        return problems


# Run in worker processes

def run_still(backend: Backend, *, doc: Document, scene_id: str, step_index: int, width: int,
              out_png: str, base_dir: str, **_: Any) -> dict[str, Any]:
    result = backend.still(doc, scene_id, step_index, Path(out_png), width, Path(base_dir))
    return still_data(result, out_png)


def run_clip(backend: Backend, *, doc: Document, scene_id: str, start_step: int, end_step: int | None,
             out_mp4: str, base_dir: str, **_: Any) -> dict[str, Any]:
    result = backend.clip(doc, scene_id, Path(out_mp4), start_step, end_step, Path(base_dir))
    return {"path": str(result if result is not None else out_mp4)}


def run_video(backend: Backend, *, doc: Document, quality: str, out_mp4: str, base_dir: str,
              progress: Progress, cancel: Cancelled, **_: Any) -> dict[str, Any]:
    result = backend.video(doc, Path(out_mp4), quality, Path(base_dir), progress, cancel)
    return {"path": str(result if result is not None else out_mp4)}


def still_data(result: Any, out_png: str) -> dict[str, Any]:
    objects = []
    for box in _get(result, "objects", []) or []:
        objects.append({
            "id": str(_get(box, "id")),
            "bbox": [float(v) for v in _get(box, "bbox")],
            "frame_bbox": [float(v) for v in _get(box, "frame_bbox")],
        })
    return {
        "path": str(_get(result, "path", None) or out_png),
        "width": int(_get(result, "width")),
        "height": int(_get(result, "height")),
        "objects": objects,
    }


def timeline_data(timings: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "step_id": _get(t, "step_id"),
            "index": int(_get(t, "index")),
            "start": float(_get(t, "start")),
            "duration": float(_get(t, "duration")),
        }
        for t in timings
    ]


def _get(obj: Any, name: str, *default: Any) -> Any:
    if isinstance(obj, dict):
        return obj[name] if not default else obj.get(name, default[0])
    return getattr(obj, name, *default)


# Errors a render reports

def render_error_problems(err: BaseException) -> list[dict[str, Any]] | None:
    """
    The problems carried by a RenderError, as json, or None for any other exception. Told
    apart by the `problems` it carries rather than by class, so that it works for the real
    RenderError and for a test's stand-in alike.
    """
    problems = getattr(err, "problems", None)
    if not isinstance(problems, list):
        return None
    return [problem_json(p) for p in problems]


def is_cancellation(err: BaseException) -> bool:
    return any(cls.__name__ == "RenderCancelled" for cls in type(err).__mro__)


def problem_json(problem: Any) -> dict[str, Any]:
    if isinstance(problem, Problem):
        return problem.to_json()
    if isinstance(problem, dict):
        loc = list(problem.get("loc") or [])
        return Problem(
            str(problem.get("message", "")), loc, problem.get("severity", "error"),
            problem.get("scene_id"), problem.get("item_id"),
        ).to_json()
    return Problem(str(problem)).to_json()
