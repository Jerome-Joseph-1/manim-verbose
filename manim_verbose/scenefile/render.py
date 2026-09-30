"""
Scene files to pictures and videos. This is the API the CLI and the editor's server use;
nothing outside this package should need to know how rendering works.

OWNER: steps/render agent. Keep these signatures; the server is being built against them.

    Quality = Literal["low", "medium", "hd", "uhd"]
        low 854x480 at 15 fps, medium 1280x720, hd the document's resolution (1920x1080 by
        default), uhd 3840x2160; all but low at the document's fps.

    @dataclass ObjectBox:
        id: str
        bbox: tuple[float, float, float, float]        # pixels x0, y0, x1, y1; origin top left
        frame_bbox: tuple[float, float, float, float]  # manim units xmin, ymin, xmax, ymax

    @dataclass StillResult:
        path: Path; width: int; height: int
        objects: list[ObjectBox]                       # everything registered and on screen, drawn order

    @dataclass StepTiming:
        step_id: str; index: int; start: float; duration: float   # seconds from the start of its scene

    timeline(doc, scene_id) -> list[StepTiming]         # top level steps; no rendering involved
    scene_duration(doc, scene_id) -> float
    document_duration(doc) -> float

    render_still(doc, scene_id, step_index, out_png, width=960, base_dir=None) -> StillResult
        The frame once step `step_index` has finished; -1 for before the first step.
    render_clip(doc, scene_id, out_mp4, start_step=0, end_step=None, quality="low", base_dir=None) -> Path
        Steps start_step..end_step inclusive, starting from the state the earlier steps left.
    render_video(doc, out_mp4, quality="hd", scene_ids=None, jobs=None, base_dir=None,
                 progress=None, cancel=None) -> Path
        Every scene, rendered separately (in parallel up to `jobs`) and joined in order.
        progress(fraction, message) is called as it goes; cancel() returning True stops it,
        raising RenderCancelled.

    class RenderError(Exception): problems: list[Problem]   # LaTeX failures and the like, reworded
    class RenderCancelled(Exception)

How a render runs: the scene is turned into code (codegen.py), the code written to a module
file and imported, and its scene class run with a configuration built here from manim_config,
never from the command line. Stills and clips run in the calling process. A whole video runs
each scene in a worker process of its own and joins what they write without re-encoding it.
Rendered scenes are cached, keyed by everything which decides what they look like (see
scene_cache_key), in MANIM_VERBOSE_CACHE, or ~/.cache/manim-verbose/ when that isn't set, so
that re-rendering a long video after changing one scene renders only that scene.

Anything which goes wrong comes back as a RenderError holding problems, placed on the object
or step at fault where that can be worked out (see problems_from_exception), never as a
traceback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import queue as queue_module
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from manim_verbose.scenefile.codegen import (
    GENERATOR_VERSION, CodegenContext, CodegenError, SourceRef, generate_module,
)
from manim_verbose.scenefile.model import (
    ChangeStep, Document, ImageObject, ObjectBase, SceneSpec, SvgObject,
)
from manim_verbose.scenefile.validate import Problem

log = logging.getLogger(__name__)

Quality = Literal["low", "medium", "hd", "uhd"]
QUALITIES: tuple[str, ...] = ("low", "medium", "hd", "uhd")
# The shorter side of the picture at each quality but hd, which is the document's own size
SHORT_SIDES = {"low": 480, "medium": 720, "uhd": 2160}
LOW_FPS = 15


@dataclass
class ObjectBox:
    id: str
    bbox: tuple[float, float, float, float]
    frame_bbox: tuple[float, float, float, float]


@dataclass
class StillResult:
    path: Path
    width: int
    height: int
    objects: list[ObjectBox]


@dataclass
class StepTiming:
    step_id: str
    index: int
    start: float
    duration: float


class RenderError(Exception):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


class RenderCancelled(Exception):
    pass


# Timings, with no rendering

def timeline(doc: Document, scene_id: str) -> list[StepTiming]:
    from manim_verbose.scenefile.actions import step_duration
    index, scene = _find_scene(doc, scene_id)
    ctx = CodegenContext(doc=doc, scene=scene, objects={obj.id: obj for obj in scene.objects})
    timings = []
    start = 0.0
    for step_index, step in enumerate(scene.steps):
        duration = step_duration(step, ctx)
        timings.append(StepTiming(step.id or f"step_{step_index}", step_index, start, duration))
        start += duration
    return timings


def scene_duration(doc: Document, scene_id: str) -> float:
    total = 0.0
    for timing in timeline(doc, scene_id):
        total += timing.duration
    return total


def document_duration(doc: Document) -> float:
    return sum(scene_duration(doc, scene.id) for scene in doc.scenes)


def quality_settings(doc: Document, quality: str) -> tuple[int, int, int]:
    """Width, height and frames per second of a render at a quality."""
    if quality not in QUALITIES:
        raise RenderError([Problem(f"'{quality}' isn't a quality; use one of {', '.join(QUALITIES)}")])
    width, height = doc.settings.resolution
    fps = doc.settings.fps
    if quality == "hd":
        return _even(width), _even(height), fps
    scale = SHORT_SIDES[quality] / min(width, height)
    if quality == "low":
        fps = min(fps, LOW_FPS)
    return _even(width * scale), _even(height * scale), fps


def _even(size: float) -> int:
    """Video encoders want even sizes."""
    return max(2, int(round(size / 2)) * 2)


# Stills and clips, in this process

def render_still(
    doc: Document,
    scene_id: str,
    step_index: int,
    out_png: str | Path,
    width: int = 960,
    base_dir: Path | None = None,
) -> StillResult:
    from manim_verbose.scenefile.runtime import RenderPlan
    index, scene = _find_scene(doc, scene_id)
    if not -1 <= step_index < len(scene.steps):
        raise RenderError([Problem(
            f"Scene '{scene_id}' has {len(scene.steps)} step(s), so there's no step {step_index}",
            ["scenes", index], scene_id=scene_id,
        )])
    job = prepare_job(doc, scene_id, base_dir)
    doc_width, doc_height = doc.settings.resolution
    width = max(2, int(width))
    height = max(2, int(round(width * doc_height / doc_width)))
    try:
        scene_obj = run_job(job, RenderPlan(still=True, last_step=step_index), width, height, doc.settings.fps)
        scene_obj.update_frame(force_draw=True)
        image = scene_obj.get_image().convert("RGB")
        out_png = Path(out_png)
        out_png.parent.mkdir(parents=True, exist_ok=True)
        # Written aside and moved into place, so that nobody serving it finds half a picture
        partial = out_png.with_name(f".{out_png.stem}.{os.getpid()}.png")
        image.save(partial)
        partial.replace(out_png)
        boxes = [ObjectBox(obj_id, pixels, frame) for obj_id, frame, pixels in scene_obj.object_boxes()]
    except RenderError:
        raise
    except Exception as err:
        raise job.error_from(err) from None
    return StillResult(out_png, width, height, boxes)


def render_clip(
    doc: Document,
    scene_id: str,
    out_mp4: str | Path,
    start_step: int = 0,
    end_step: int | None = None,
    quality: Quality = "low",
    base_dir: Path | None = None,
) -> Path:
    from manim_verbose.scenefile.runtime import RenderPlan
    index, scene = _find_scene(doc, scene_id)
    count = len(scene.steps)
    end = count - 1 if end_step is None else end_step
    if count == 0:
        raise RenderError([Problem(f"Scene '{scene_id}' has no steps to show", ["scenes", index], scene_id=scene_id)])
    if not 0 <= start_step <= end < count:
        raise RenderError([Problem(
            f"Scene '{scene_id}' has {count} step(s), so steps {start_step} to {end} can't be shown",
            ["scenes", index], scene_id=scene_id,
        )])
    width, height, fps = quality_settings(doc, quality)
    job = prepare_job(doc, scene_id, base_dir)
    out_mp4 = Path(out_mp4)
    run_job(job, RenderPlan(first_step=start_step, last_step=end), width, height, fps, movie=out_mp4)
    return out_mp4


# Running one scene

@dataclass
class RenderJob:
    """Everything needed to render one scene, made in the calling process and picklable, so a worker needs nothing else."""
    scene_id: str
    scene_data: dict[str, Any]
    code: str
    class_name: str
    line_map: dict[int, SourceRef]
    base_dir: str

    def error_from(self, err: BaseException) -> RenderError:
        scene = SceneSpec.model_validate(self.scene_data)
        return RenderError(problems_from_exception(err, self, scene))


def prepare_job(doc: Document, scene_id: str, base_dir: Path | None = None) -> RenderJob:
    """The code for one scene, or a RenderError saying what in it couldn't be turned into code."""
    index, scene = _find_scene(doc, scene_id)
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    try:
        generated = generate_module(doc, base, [scene_id])
    except CodegenError as err:
        ref = err.ref
        raise RenderError([Problem(err.message, list(ref.loc), "error", ref.scene_id, ref.item_id)]) from None
    except Exception as err:
        log.exception("Generating code for scene %s failed", scene_id)
        raise RenderError([Problem(
            f"Scene '{scene_id}' couldn't be turned into code: {err}", ["scenes", index], scene_id=scene_id,
        )]) from None
    return RenderJob(
        scene_id=scene_id,
        scene_data=scene.model_dump(mode="json"),
        code=generated.code,
        class_name=generated.class_names[scene_id],
        line_map=generated.line_map,
        base_dir=str(base),
    )


def run_job(
    job: RenderJob,
    plan,
    width: int,
    height: int,
    fps: int,
    movie: Path | None = None,
):
    """
    Runs a scene to the end, or as far as the plan asks, writing a movie if given one, and
    hands back the scene as it was left. Failures come back as RenderError.
    """
    prepare_process()
    try:
        module = load_module(job.code)
        scene_class = getattr(module, job.class_name)
        config = scene_config(width, height, fps, movie)
        scene = scene_class(plan=plan, **config)
    except Exception as err:
        raise job.error_from(err) from None
    global _running_scene
    _running_scene = scene
    try:
        scene.run()
    except BaseException as err:
        _abandon_movie(scene)
        if isinstance(err, (KeyboardInterrupt, SystemExit)):
            raise
        raise job.error_from(err) from None
    finally:
        _running_scene = None
    if movie is not None and not movie.exists():
        raise RenderError([Problem(f"The video for scene '{job.scene_id}' wasn't written", scene_id=job.scene_id)])
    return scene


# The scene being run, for a worker told to stop to clean up after
_running_scene = None


def scene_config(width: int, height: int, fps: int, movie: Path | None = None) -> dict[str, Any]:
    """
    What a scene class is constructed with: manim's own scene configuration, with the size,
    frame rate and output of this render in place of anything the command line would say.
    """
    from manimlib.config import manim_config
    config = {key: value for key, value in manim_config.scene.items()}
    writer: dict[str, Any] = dict(
        write_to_movie=movie is not None,
        save_last_frame=False,
        subdivide_output=False,
        quiet=True,
        open_file_upon_completion=False,
        show_file_location_upon_completion=False,
        total_frames=0,
    )
    if movie is not None:
        movie = Path(movie)
        movie.parent.mkdir(parents=True, exist_ok=True)
        writer.update(
            output_directory=str(movie.parent),
            file_name=movie.stem,
            movie_file_extension=movie.suffix or ".mp4",
        )
    else:
        writer.update(output_directory=str(_private_dir()), file_name=None)
    config.update(
        camera_config=dict(resolution=(int(width), int(height)), fps=int(fps)),
        file_writer_config=writer,
        skip_animations=False,
        start_at_animation_number=None,
        end_at_animation_number=None,
        presenter_mode=False,
        show_animation_progress=False,
        leave_progress_bars=False,
    )
    return config


def _abandon_movie(scene) -> None:
    """A scene which failed part way leaves ffmpeg waiting on frames; stop it, and drop what it wrote."""
    writer = getattr(scene, "file_writer", None)
    process = getattr(writer, "writing_process", None)
    if process is None:
        return
    try:
        process.stdin.close()
    except Exception:
        pass
    process.kill()
    process.wait()
    temp = getattr(writer, "temp_file_path", None)
    if temp:
        Path(temp).unlink(missing_ok=True)


_modules: dict[str, Any] = {}


def load_module(code: str):
    """Imports generated code, from a file named by its hash so tracebacks can name it."""
    import importlib.util
    digest = _digest(code)
    if digest in _modules:
        return _modules[digest]
    folder = cache_dir() / "modules"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"scene_{digest}.py"
    if not path.exists() or path.read_text(encoding="utf-8") != code:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(code, encoding="utf-8")
        tmp.replace(path)
    name = f"manim_verbose_generated_{digest}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    _modules[digest] = module
    return module


def cache_dir() -> Path:
    """Where rendered scenes and generated modules are kept: MANIM_VERBOSE_CACHE, or ~/.cache/manim-verbose/."""
    configured = os.environ.get("MANIM_VERBOSE_CACHE")
    return Path(configured) if configured else Path.home() / ".cache" / "manim-verbose"


# Getting a process ready to render

_prepared_pid: int | None = None
_private: Path | None = None


def _private_dir() -> Path:
    global _private
    if _private is None or not _private.exists():
        _private = Path(tempfile.mkdtemp(prefix="manim-verbose-"))
    return _private


def prepare_process() -> None:
    """
    Settings manim reads from its global configuration which don't suit renders running
    side by side, set once per process:

    - LaTeX runs in a folder of this process's own, rather than ./latex_cache, where two
      renders compiling at once would overwrite each other's working files.
    - Text is laid out through temporary files named by the text alone, so two processes
      writing the same words would delete each other's; this process gets its own.
    """
    global _prepared_pid
    if _prepared_pid == os.getpid() and Path(tempfile.gettempdir()).is_dir():
        return
    from manim_verbose.manim_import import import_manim
    import_manim()
    from manimlib.config import manim_config
    private = _private_dir()
    latex = private / "latex"
    latex.mkdir(exist_ok=True)
    manim_config.directories.latex_cache = str(latex)
    temp = private / "tmp"
    temp.mkdir(exist_ok=True)
    tempfile.tempdir = str(temp)
    _prepared_pid = os.getpid()


# Failures, reworded

def problems_from_exception(err: BaseException, job: RenderJob, scene: SceneSpec) -> list[Problem]:
    """
    What went wrong, placed on the object or step whose line of generated code it went wrong
    in, and on the field at fault where that can be told: the formula a LaTeX error came from,
    the text markup was refused in, the file an image couldn't be read from.
    """
    log.debug("Render of scene %s failed", job.scene_id, exc_info=err)
    ref = _failing_ref(err, job)
    latex = _failing_latex(err)
    reason = _reason(err, latex is not None)
    if ref is None or ref.kind == "scene":
        loc = list(ref.loc) if ref else []
        return [Problem(f"Scene '{job.scene_id}' couldn't be rendered: {reason}", loc, "error", job.scene_id, None)]
    loc = list(ref.loc)
    if ref.kind == "object":
        obj = scene.objects[ref.loc[-1]]
        field_name = _field_at_fault(obj, err, latex)
        what = "This formula couldn't be typeset" if latex is not None else "This object couldn't be made"
        return [Problem(f"{what}: {reason}", loc + ([field_name] if field_name else []), "error", job.scene_id, ref.item_id)]
    step = _step_at(scene, ref.loc)
    extra: list[str | int] = []
    if isinstance(step, ChangeStep):
        target = next((obj for obj in scene.objects if obj.id == step.target), None)
        if target is not None:
            key = _field_at_fault(target, err, latex, only=list(step.set))
            if key:
                extra = ["set", key]
    what = "A formula in this step couldn't be typeset" if latex is not None else "This step couldn't be played"
    return [Problem(f"{what}: {reason}", loc + extra, "error", job.scene_id, ref.item_id)]


def _failing_ref(err: BaseException, job: RenderJob) -> SourceRef | None:
    """The deepest line of generated code the failure passed through, as what it was generated from."""
    generated = f"scene_{_digest(job.code)}.py"
    found = None
    for tb in _tracebacks(err):
        while tb is not None:
            if Path(tb.tb_frame.f_code.co_filename).name == generated and tb.tb_lineno in job.line_map:
                found = job.line_map[tb.tb_lineno]
            tb = tb.tb_next
        if found is not None:
            return found
    return found


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:24]


def _tracebacks(err: BaseException):
    seen = set()
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        yield err.__traceback__
        err = err.__cause__ or err.__context__


def _failing_latex(err: BaseException) -> str | None:
    """
    The LaTeX being worked on when this went wrong, if it went wrong over a formula: either
    compiling it, or in manim's own reading of it beforehand (for unbalanced braces, say).
    An empty string where it was a formula but which one can't be told; None otherwise.
    """
    from manimlib.utils.tex_file_writing import LatexError
    is_latex = any(isinstance(e, LatexError) for e in _chain(err))
    found = None
    for tb in _tracebacks(err):
        while tb is not None:
            frame = tb.tb_frame
            name = frame.f_code.co_name
            if name == "latex_to_svg" and isinstance(frame.f_locals.get("latex"), str):
                return frame.f_locals["latex"]
            if Path(frame.f_code.co_filename).name == "tex_mobject.py":
                is_latex = True
                if found is None and isinstance(frame.f_locals.get("tex_string"), str):
                    found = frame.f_locals["tex_string"]
            if name == "__init__" and Path(frame.f_code.co_filename).name == "string_mobject.py" and is_latex:
                if isinstance(frame.f_locals.get("string"), str):
                    found = frame.f_locals["string"]
            tb = tb.tb_next
    if found is not None:
        return found
    return "" if is_latex else None


def _chain(err: BaseException):
    seen = set()
    while err is not None and id(err) not in seen:
        seen.add(id(err))
        yield err
        err = err.__cause__ or err.__context__


def _reason(err: BaseException, latex: bool) -> str:
    text = str(err).strip()
    if latex:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # LaTeX's own words for it, and the line it gave up on, without its bookkeeping
        message = lines[0].rstrip(".") if lines else "LaTeX couldn't compile it"
        context = next((line for line in lines[1:] if line.startswith("l.")), None)
        if context:
            where = re.sub(r"^l\.[0-9]+ ?", "", context)
            message += f" (at '{where}')"
        return message
    if isinstance(err, FileNotFoundError):
        return f"there's no file {err.filename or text}"
    text = re.sub(r"\s+", " ", text) or type(err).__name__
    return text if len(text) <= 300 else text[:297] + "..."


# Fields of an object which hold LaTeX, and which are text for Pango, in the order to blame them
LATEX_FIELDS = ("tex", "label", "x_label", "y_label", "entries", "items", "text")
TEXT_FIELDS = ("text", "items", "author", "font")


def _field_at_fault(obj: ObjectBase, err: BaseException, latex: str | None, only: list[str] | None = None) -> str | None:
    fields = [name for name in type(obj).model_fields if only is None or name in only]
    if latex is not None:
        for name in LATEX_FIELDS:
            if name in fields and _appears_in(getattr(obj, name, None), latex):
                return name
        for name in LATEX_FIELDS:
            if name in fields and getattr(obj, name, None):
                return name
    if isinstance(obj, (ImageObject, SvgObject)) and "path" in fields and isinstance(err, (OSError, ValueError)):
        return "path"
    if isinstance(err, ValueError) and "markup" in str(err).lower():
        return next((name for name in TEXT_FIELDS if name in fields and getattr(obj, name, None)), None)
    return fields[0] if only and len(fields) == 1 else None


def _appears_in(value: Any, latex: str) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(_appears_in(item, latex) for item in value)
    text = str(value).strip()
    return bool(text) and (not latex or text in latex)


def _step_at(scene: SceneSpec, loc: tuple) -> Any:
    node: Any = scene
    for i in range(2, len(loc), 2):
        if loc[i] != "steps":
            return None
        node = node.steps[loc[i + 1]]
    return node


# Whole videos

_last_run: dict[str, list[str]] = {"rendered": [], "cached": []}


def render_video(
    doc: Document,
    out_mp4: str | Path,
    quality: Quality = "hd",
    scene_ids: list[str] | None = None,
    jobs: int | None = None,
    base_dir: Path | None = None,
    progress: Callable[[float, str], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> Path:
    out_mp4 = Path(out_mp4)
    scenes = _scenes_to_render(doc, scene_ids)
    width, height, fps = quality_settings(doc, quality)
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    report = _Progress(progress)
    report(0.0, "Preparing")
    if cancel is not None and cancel():
        raise RenderCancelled()

    # Code for every scene first, so that a scene which can't be turned into code is
    # reported before anything is rendered
    problems: list[Problem] = []
    prepared: list[tuple[SceneSpec, RenderJob, Path]] = []
    folder = cache_dir() / "scenes"
    for scene in scenes:
        try:
            job = prepare_job(doc, scene.id, base)
        except RenderError as err:
            problems.extend(err.problems)
            continue
        key = scene_cache_key(doc, scene, job, quality, width, height, fps, base)
        prepared.append((scene, job, folder / f"{key}.mp4"))
    if problems:
        raise RenderError(problems)

    durations = {scene.id: max(scene_duration(doc, scene.id), 1 / fps) for scene, _, _ in prepared}
    total = sum(durations.values())
    pending = [(scene, job, path) for scene, job, path in prepared if not path.exists()]
    _last_run["cached"] = [scene.id for scene, _, path in prepared if path.exists()]
    _last_run["rendered"] = [scene.id for scene, _, _ in pending]
    done = {scene.id: durations[scene.id] for scene, _, path in prepared if path.exists()}

    def overall() -> float:
        return 0.97 * sum(min(done.get(sid, 0.0), durations[sid]) for sid in durations) / total

    def message() -> str:
        order = [scene.id for scene, _, _ in prepared]
        unfinished = [i for i, sid in enumerate(order) if done.get(sid, 0.0) < durations[sid]]
        if not unfinished:
            return "Joining scenes"
        return f"Rendering scene {unfinished[0] + 1} of {len(order)}"

    if pending:
        folder.mkdir(parents=True, exist_ok=True)
        workers = max(1, min(jobs or os.cpu_count() or 1, len(pending)))
        _render_in_workers(pending, width, height, fps, workers, done, durations,
                           lambda: report(overall(), message()), cancel)
    report(overall(), "Joining scenes")
    if cancel is not None and cancel():
        raise RenderCancelled()
    _join([path for _, _, path in prepared], out_mp4)
    report(1.0, "Done")
    return out_mp4


def _scenes_to_render(doc: Document, scene_ids: list[str] | None) -> list[SceneSpec]:
    if scene_ids is None:
        return list(doc.scenes)
    known = {scene.id for scene in doc.scenes}
    missing = [sid for sid in scene_ids if sid not in known]
    if missing:
        raise RenderError([Problem(f"There's no scene called '{sid}'", ["scenes"], scene_id=sid) for sid in missing])
    return [scene for scene in doc.scenes if scene.id in scene_ids]


def scene_cache_key(
    doc: Document, scene: SceneSpec, job: RenderJob, quality: str, width: int, height: int, fps: int, base_dir: Path,
) -> str:
    """
    Everything a rendered scene depends on: its code (which carries the scene, its captions'
    style and its background), the size and frame rate, the files its images come from, and
    the versions of what made it.
    """
    from manim_verbose.manim_import import import_manim
    assets = {}
    for obj in scene.objects:
        if isinstance(obj, (ImageObject, SvgObject)):
            path = Path(base_dir) / obj.path
            assets[obj.path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
    data = {
        "generator": GENERATOR_VERSION,
        "manim": getattr(import_manim(), "__version__", ""),
        "code": job.code,
        "scene": job.scene_data,
        "settings": doc.settings.model_dump(mode="json"),
        "quality": quality,
        "size": [width, height],
        "fps": fps,
        "assets": assets,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


class _Progress:
    """Passes progress on, never going backwards, and not more often than it is worth."""

    def __init__(self, callback: Callable[[float, str], None] | None):
        self.callback = callback
        self.last = -1.0
        self.last_message = ""
        self.last_time = 0.0

    def __call__(self, fraction: float, message: str) -> None:
        if self.callback is None:
            return
        fraction = min(1.0, max(fraction, self.last, 0.0))
        now = time.monotonic()
        if fraction == self.last and message == self.last_message:
            return
        if fraction < 1.0 and message == self.last_message and now - self.last_time < 0.1:
            return
        self.last, self.last_message, self.last_time = fraction, message, now
        self.callback(fraction, message)


def _render_in_workers(pending, width, height, fps, workers, done, durations, tick, cancel) -> None:
    """
    Renders each pending scene in a process of its own, `workers` at a time. Workers are
    plain subprocesses running this module (see worker_main), so that nothing about the
    caller, such as its main module, has to be importable a second time. They stay in the
    caller's process group, so that whatever stops the caller that way stops them too.
    """
    scratch = cache_dir() / "tmp" / uuid.uuid4().hex
    scratch.mkdir(parents=True, exist_ok=True)
    messages: queue_module.Queue = queue_module.Queue()
    waiting = list(pending)
    running: dict[str, _Worker] = {}
    problems: list[Problem] = []
    try:
        while waiting or running:
            while waiting and len(running) < workers and not problems:
                scene, job, path = waiting.pop(0)
                running[scene.id] = _Worker(job, width, height, fps, scratch, path, messages)
            if not running:
                break
            if cancel is not None and cancel():
                raise RenderCancelled()
            try:
                scene_id, message = messages.get(timeout=0.1)
            except queue_module.Empty:
                continue
            worker = running.get(scene_id)
            if worker is None:
                continue
            if "progress" in message:
                done[scene_id] = max(done.get(scene_id, 0.0), message["progress"])
                tick()
            elif "done" in message:
                running.pop(scene_id).finish()
                done[scene_id] = durations[scene_id]
                tick()
            elif "error" in message:
                running.pop(scene_id).finish()
                problems.extend(Problem(**problem) for problem in message["error"])
                waiting.clear()
            elif "exited" in message:
                running.pop(scene_id).finish()
                log.error("Rendering scene %s stopped unexpectedly:\n%s", scene_id, message["log"])
                problems.append(Problem(
                    f"Rendering scene '{scene_id}' stopped unexpectedly (exit code {message['exited']})",
                    scene_id=scene_id,
                ))
                waiting.clear()
        if problems:
            raise RenderError(problems)
    finally:
        for worker in running.values():
            worker.stop()
        shutil.rmtree(scratch, ignore_errors=True)


class _Worker:
    """A subprocess rendering one scene, and a thread passing on what it says."""

    def __init__(self, job: RenderJob, width: int, height: int, fps: int, scratch: Path, final: Path, messages):
        self.scene_id = job.scene_id
        self.log_path = scratch / f"{final.stem}.log"
        env = dict(os.environ)
        # The worker has to import this same copy of the package, wherever it came from
        paths = [str(Path(entry).resolve()) for entry in sys.path if entry and Path(entry).is_dir()]
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths + env.get("PYTHONPATH", "").split(os.pathsep)))
        with open(self.log_path, "wb") as log_file:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "manim_verbose.scenefile.render"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log_file, env=env,
            )
        payload = pickle.dumps(dict(job=job, width=width, height=height, fps=fps,
                                    scratch=str(scratch / f"{final.stem}.mp4"), final=str(final)))
        # The job goes first, its length ahead of it; stdin then stays open for as long as
        # this process lives, and the worker takes it closing as word to stop
        self.process.stdin.write(len(payload).to_bytes(8, "big") + payload)
        self.process.stdin.flush()
        self.reader = threading.Thread(target=self._read, args=(messages,), daemon=True)
        self.reader.start()

    def _read(self, messages) -> None:
        for line in self.process.stdout:
            try:
                messages.put((self.scene_id, json.loads(line)))
            except ValueError:
                continue
        code = self.process.wait()
        if code != 0:
            text = self.log_path.read_text(errors="replace")[-4000:] if self.log_path.exists() else ""
            messages.put((self.scene_id, {"exited": code, "log": text}))

    def finish(self) -> None:
        self.process.wait()
        self._close_stdin()
        self.reader.join(timeout=5)

    def stop(self) -> None:
        """Stops the worker, which stops the ffmpeg it is writing through on its way out."""
        for stop in (self.process.terminate, self.process.kill):
            if self.process.poll() is not None:
                break
            stop()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                continue
        self._close_stdin()
        self.reader.join(timeout=5)

    def _close_stdin(self) -> None:
        try:
            self.process.stdin.close()
        except OSError:
            pass


def worker_main() -> int:
    """
    What a worker process runs: one scene, read pickled from stdin, rendered into scratch and
    then moved into the cache. It says how it is getting on as json lines on what was stdout,
    which is kept for that alone; anything else written there (LaTeX's progress, say) goes to
    /dev/null instead.
    """
    channel = os.fdopen(os.dup(1), "w", buffering=1)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 1)
    sys.stdout = open(os.devnull, "w")
    size = int.from_bytes(_read_exactly(sys.stdin.buffer, 8), "big")
    payload = pickle.loads(_read_exactly(sys.stdin.buffer, size))
    job: RenderJob = payload["job"]

    def say(message: dict) -> None:
        channel.write(json.dumps(message) + "\n")

    def stop(signum=None, frame=None):
        if _running_scene is not None:
            _abandon_movie(_running_scene)
        os._exit(1)

    def stop_when_orphaned():
        # stdin closes when the process which started this one is gone, however it went
        sys.stdin.buffer.read()
        stop()

    signal.signal(signal.SIGTERM, stop)
    threading.Thread(target=stop_when_orphaned, daemon=True).start()
    last_sent = [0.0]

    def progress(seconds: float, step_index: int) -> None:
        now = time.monotonic()
        if now - last_sent[0] >= 0.2:
            last_sent[0] = now
            say({"progress": seconds})

    try:
        from manim_verbose.scenefile.runtime import RenderPlan
        scratch = Path(payload["scratch"])
        run_job(job, RenderPlan(progress=progress), payload["width"], payload["height"], payload["fps"], movie=scratch)
        scratch.replace(payload["final"])
        say({"done": True})
    except RenderError as err:
        say({"error": [_problem_data(p) for p in err.problems]})
    except BaseException as err:
        traceback.print_exc()
        say({"error": [_problem_data(Problem(f"Rendering scene '{job.scene_id}' failed: {err}", scene_id=job.scene_id))]})
    return 0


def _read_exactly(stream, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("the job for this worker was cut short")
        data += chunk
    return data


def _problem_data(problem: Problem) -> dict[str, Any]:
    return {
        "message": problem.message, "loc": list(problem.loc), "severity": problem.severity,
        "scene_id": problem.scene_id, "item_id": problem.item_id,
    }


def _join(paths: list[Path], out: Path) -> None:
    """The scenes' videos one after another, copied rather than encoded again, since they were all encoded alike."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.stem}.{uuid.uuid4().hex[:8]}{out.suffix or '.mp4'}")
    try:
        if len(paths) == 1:
            shutil.copyfile(paths[0], tmp)
        else:
            listing = tmp.with_suffix(".txt")
            listing.write_text("".join(
                "file '" + str(path.resolve()).replace("'", "'\\''") + "'\n" for path in paths
            ), encoding="utf-8")
            try:
                result = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                     "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(tmp)],
                    capture_output=True, text=True,
                )
            finally:
                listing.unlink(missing_ok=True)
            if result.returncode != 0:
                raise RenderError([Problem(f"The scenes couldn't be joined into one video: {result.stderr.strip()}")])
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)


def _find_scene(doc: Document, scene_id: str) -> tuple[int, SceneSpec]:
    for index, scene in enumerate(doc.scenes):
        if scene.id == scene_id:
            return index, scene
    raise RenderError([Problem(f"There's no scene called '{scene_id}'", ["scenes"], scene_id=scene_id)])


if __name__ == "__main__":
    # A worker process, see _Worker. The module is imported by its name so that the job
    # unpickles into the same classes this runs with.
    from manim_verbose.scenefile.render import worker_main as _worker_main
    sys.exit(_worker_main())
