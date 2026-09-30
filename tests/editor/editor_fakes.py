"""
Stand-ins for the renderer, so that the server can be tested in seconds and without a GPU.

`FakeBackend` draws a plain PNG of the right size and makes up object boxes, at once. What it
does can be steered from the document, through a scene's title, since that is the one thing a
test can set which reaches the worker process unchanged:

    crash          the worker process dies (os._exit)
    hang           the render never ends
    slow:0.5       the render takes half a second (per scene, for a video)
    fail           a RenderError, with a problem on the scene's first object
    boom           an unexpected exception
    gate:NAME      the render waits until a file NAME exists in the backend's folder
    nocancel       a video which ignores cancel()

Every render it does is recorded as a line in calls.log in its folder, so tests can count them.

This module is imported by worker processes too (the backend is pickled by reference to it),
which works because pytest puts this folder on sys.path and spawned processes inherit it.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manim_verbose.scenefile.validate import Problem


class RenderError(Exception):
    """Like scenefile.render.RenderError: problems with the document which a render ran into."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


class RenderCancelled(Exception):
    pass


@dataclass
class Box:
    id: str
    bbox: tuple[float, float, float, float]
    frame_bbox: tuple[float, float, float, float]


@dataclass
class Still:
    path: Path
    width: int
    height: int
    objects: list[Box]


@dataclass
class Timing:
    step_id: str
    index: int
    start: float
    duration: float


def png_bytes(width: int, height: int) -> bytes:
    """A valid, all black PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 64


class FakeBackend:
    def __init__(self, folder: str | Path):
        self.folder = str(folder)

    # Bookkeeping

    def record(self, *parts: Any) -> None:
        with open(Path(self.folder) / "calls.log", "a", encoding="utf-8") as log:
            log.write(json.dumps(parts) + "\n")

    def calls(self, kind: str | None = None) -> list[list[Any]]:
        path = Path(self.folder) / "calls.log"
        if not path.exists():
            return []
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return [line for line in lines if kind is None or line[0] == kind]

    def behave(self, scene, cancel=None) -> None:
        title = scene.title or ""
        if title == "crash":
            os._exit(3)
        if title == "hang":
            while True:
                time.sleep(1)
        if title.startswith("slow:"):
            end = time.monotonic() + float(title.split(":", 1)[1])
            while time.monotonic() < end:
                if cancel is not None and cancel():
                    raise RenderCancelled()
                time.sleep(0.02)
        if title.startswith("gate:"):
            gate = Path(self.folder) / title.split(":", 1)[1]
            end = time.monotonic() + 30
            while not gate.exists() and time.monotonic() < end:
                time.sleep(0.02)
        if title == "fail":
            obj = scene.objects[0]
            raise RenderError([Problem("LaTeX couldn't make sense of this formula", ["scenes", 0, "objects", 0, "tex"],
                                       scene_id=scene.id, item_id=obj.id)])
        if title == "boom":
            raise ValueError("the fake renderer fell over")

    # The backend

    def warm(self) -> None:
        pass

    def cache_salt(self) -> str:
        return "fake"

    def still(self, doc, scene_id, step_index, out_png, width, base_dir):
        scene = next(s for s in doc.scenes if s.id == scene_id)
        self.record("still", scene_id, step_index, width)
        self.behave(scene)
        res_w, res_h = doc.settings.resolution
        height = round(width * res_h / res_w)
        Path(out_png).write_bytes(png_bytes(width, height))
        shown = {obj.id for obj in scene.objects if obj.shown}
        for step in scene.steps[:step_index + 1]:
            if step.do in ("show", "add"):
                shown |= {step.target} if isinstance(step.target, str) else set(step.target)
        boxes = []
        for i, obj in enumerate(o for o in scene.objects if o.id in shown):
            x0 = 10.0 + 40 * i
            boxes.append(Box(obj.id, (x0, 20.0, x0 + 30, 50.0), (-1.0 + i, -0.5, -0.2 + i, 0.5)))
        return Still(Path(out_png), width, height, boxes)

    def clip(self, doc, scene_id, out_mp4, start_step, end_step, base_dir):
        scene = next(s for s in doc.scenes if s.id == scene_id)
        self.record("clip", scene_id, start_step, end_step)
        self.behave(scene)
        Path(out_mp4).write_bytes(FAKE_MP4)
        return Path(out_mp4)

    def video(self, doc, out_mp4, quality, base_dir, progress, cancel):
        self.record("video", quality, [s.id for s in doc.scenes])
        count = len(doc.scenes)
        for i, scene in enumerate(doc.scenes):
            progress(i / count, f"Rendering scene {i + 1} of {count}")
            if scene.title == "nocancel":
                time.sleep(3600)
            self.behave(scene, cancel)
            if cancel():
                raise RenderCancelled()
        progress(0.3, "Going backwards, which the server should ignore")
        progress(1.0, "Joining the scenes")
        Path(out_mp4).write_bytes(FAKE_MP4)
        return Path(out_mp4)

    def timeline(self, doc, scene_id):
        scene = next(s for s in doc.scenes if s.id == scene_id)
        if scene.title == "boom":
            raise ValueError("the fake timer fell over")
        timings, start = [], 0.0
        for index, step in enumerate(scene.steps):
            duration = getattr(step, "duration", None) if step.do == "wait" else step.run_time
            duration = float(duration or 1.0)
            timings.append(Timing(step.id, index, start, duration))
            start += duration
        return timings

    def scene_duration(self, doc, scene_id):
        return sum(t.duration for t in self.timeline(doc, scene_id))

    def code(self, doc, scene_ids, base_dir):
        scenes = [s for s in doc.scenes if scene_ids is None or s.id in scene_ids]
        if any(s.title == "boom" for s in scenes):
            raise ValueError("the fake code generator fell over")
        lines = ["from manimlib import *", ""]
        for scene in scenes:
            lines += [f"class {scene.id.title().replace('_', '')}(Scene):", "    def construct(self):", "        pass", ""]
        return "\n".join(lines)


# Functions for WorkerProcess.call, run in the worker as fn(backend, progress=..., cancel=..., **kwargs)

def echo(backend, *, value, **_):
    return value


def pid(backend, **_):
    return os.getpid()


def sleep_for(backend, *, seconds, **_):
    time.sleep(seconds)
    return "slept"


def crash(backend, *, code=7, **_):
    sys.stdout.flush()
    os._exit(code)


def hang_with_child(backend, *, pid_file, **_):
    """Start a grandchild process, note its pid, and hang: killing the worker has to take both."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    Path(pid_file).write_text(str(child.pid))
    while True:
        time.sleep(1)


def fail_render(backend, **_):
    raise RenderError([Problem("That formula doesn't compile", ["scenes", 0, "objects", 1, "tex"],
                               scene_id="intro", item_id="eq")])


def fail_unexpectedly(backend, **_):
    raise KeyError("nothing like this was expected")


def exit_politely(backend, **_):
    raise SystemExit(4)


def with_progress(backend, *, steps, delay=0.0, progress, cancel, **_):
    for i in range(steps):
        if cancel():
            raise RenderCancelled()
        progress(i / steps, f"step {i + 1} of {steps}")
        time.sleep(delay)
    return "finished"


def chatty_forever(backend, *, progress, **_):
    """Reports progress without end, and never finishes: a time limit must still stop it."""
    while True:
        progress(0.5, "still going")
        time.sleep(0.001)


def ignore_cancel(backend, **_):
    while True:
        time.sleep(0.05)


def unpicklable_result(backend, **_):
    return lambda: None
