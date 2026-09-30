"""
The layer between the server and scenefile's renderer: that RenderBackend calls render.py and
codegen.py the way their docstrings say, and that whatever they return, dataclasses or plain
data, reaches the browser in the shape server-api.md promises.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from editor_fakes import Box, RenderCancelled, RenderError, Still, Timing
from manim_verbose.editor import backend as backend_module
from manim_verbose.editor.backend import (
    RenderBackend, is_cancellation, problem_json, render_error_problems, run_still, still_data, timeline_data,
)
from manim_verbose.scenefile import codegen, render
from manim_verbose.scenefile.validate import Problem


@pytest.fixture
def calls(monkeypatch):
    """Stand-ins for render.py and codegen.py's functions, recording how they're called."""
    seen = []

    def recorder(name, result):
        def fn(*args, **kwargs):
            seen.append((name, args, kwargs))
            return result
        return fn

    monkeypatch.setattr(render, "render_still", recorder("render_still", "still"), raising=False)
    monkeypatch.setattr(render, "render_clip", recorder("render_clip", "clip"), raising=False)
    monkeypatch.setattr(render, "render_video", recorder("render_video", "video"), raising=False)
    monkeypatch.setattr(render, "timeline", recorder("timeline", []), raising=False)
    monkeypatch.setattr(render, "scene_duration", recorder("scene_duration", 2.5), raising=False)
    monkeypatch.setattr(codegen, "document_to_python", recorder("document_to_python", "code"))
    return seen


def test_render_backend_calls_the_documented_api(calls):
    b = RenderBackend(export_jobs=2)
    doc, base = object(), Path("/scenes")
    progress, cancel = (lambda f, m: None), (lambda: False)
    assert b.still(doc, "intro", 3, Path("a.png"), 480, base) == "still"
    assert b.clip(doc, "intro", Path("a.mp4"), 1, None, base) == "clip"
    assert b.video(doc, Path("v.mp4"), "hd", base, progress, cancel) == "video"
    assert b.timeline(doc, "intro") == []
    assert b.scene_duration(doc, "intro") == 2.5
    assert b.code(doc, ["intro"], base) == "code"
    assert calls == [
        ("render_still", (doc, "intro", 3, Path("a.png")), {"width": 480, "base_dir": base}),
        ("render_clip", (doc, "intro", Path("a.mp4")), {"start_step": 1, "end_step": None, "quality": "low",
                                                        "base_dir": base}),
        ("render_video", (doc, Path("v.mp4")), {"quality": "hd", "jobs": 2, "base_dir": base, "progress": progress,
                                                "cancel": cancel}),
        ("timeline", (doc, "intro"), {}),
        ("scene_duration", (doc, "intro"), {}),
        ("document_to_python", (doc,), {"base_dir": base, "scene_ids": ["intro"]}),
    ]


def test_the_cache_salt_follows_the_renderers_source(monkeypatch, tmp_path):
    b = RenderBackend()
    salt = b.cache_salt()
    assert salt == b.cache_salt() and len(salt) == 16
    fake_package = tmp_path / "editor"
    fake_package.mkdir()
    (tmp_path / "scenefile").mkdir()
    (tmp_path / "scenefile" / "render.py").write_text("# a different renderer")
    monkeypatch.setattr(backend_module, "__file__", str(fake_package / "backend.py"))
    assert b.cache_salt() != salt


def test_still_results_become_plain_data(tmp_path):
    result = Still(tmp_path / "a.png", 480, 270, [Box("eq", (1, 2, 3, 4), (-1, -0.5, 1, 0.5))])
    assert still_data(result, "ignored.png") == {
        "path": str(tmp_path / "a.png"), "width": 480, "height": 270,
        "objects": [{"id": "eq", "bbox": [1.0, 2.0, 3.0, 4.0], "frame_bbox": [-1.0, -0.5, 1.0, 0.5]}],
    }
    as_dict = {"width": 10, "height": 5, "objects": [{"id": "d", "bbox": [0, 0, 1, 1], "frame_bbox": [0, 0, 1, 1]}]}
    assert still_data(as_dict, "out.png")["path"] == "out.png"


def test_run_still_passes_the_request_through(tmp_path):
    @dataclass
    class Recorder:
        def still(self, doc, scene_id, step_index, out_png, width, base_dir):
            self.args = (doc, scene_id, step_index, out_png, width, base_dir)
            return Still(out_png, width, 1, [])

    recorder = Recorder()
    data = run_still(recorder, doc="doc", scene_id="s", step_index=-1, width=64, out_png=str(tmp_path / "x.png"),
                     base_dir=str(tmp_path), progress=None, cancel=None)
    assert recorder.args == ("doc", "s", -1, tmp_path / "x.png", 64, tmp_path)
    assert data["width"] == 64 and data["objects"] == []


def test_timings_become_plain_data():
    assert timeline_data([Timing("a_1", 0, 0, 1.5), {"step_id": "a_2", "index": 1, "start": 1.5, "duration": 2}]) == [
        {"step_id": "a_1", "index": 0, "start": 0.0, "duration": 1.5},
        {"step_id": "a_2", "index": 1, "start": 1.5, "duration": 2.0},
    ]


def test_problems_in_any_form_become_json():
    expected = {"message": "m", "loc": ["scenes", 0], "severity": "warning", "scene_id": "a", "item_id": None,
                "path": "scenes[0]"}
    assert problem_json(Problem("m", ["scenes", 0], "warning", "a")) == expected
    assert problem_json({"message": "m", "loc": ("scenes", 0), "severity": "warning", "scene_id": "a"}) == expected
    assert problem_json("just words")["message"] == "just words"


def test_render_errors_and_cancellations_are_recognised():
    assert render_error_problems(RenderError([Problem("bad", ["scenes", 0])]))[0]["path"] == "scenes[0]"
    assert render_error_problems(ValueError("x")) is None
    assert is_cancellation(RenderCancelled())
    assert not is_cancellation(RuntimeError())
    if hasattr(render, "RenderError"):
        assert render_error_problems(render.RenderError([Problem("real")]))[0]["message"] == "real"
    if hasattr(render, "RenderCancelled"):
        assert is_cancellation(render.RenderCancelled())
