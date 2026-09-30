"""
The rendering API the CLI and the editor's server use: timings without rendering, stills and
their boxes, clips which start from the right state, whole videos rendered scene by scene in
worker processes and joined, the cache which lets a re-render skip unchanged scenes,
cancelling, progress, failures reported as problems on the right item and field, golden
images, and the command line on top of it all.

Golden images live in tests/scenefile/golden/ and are refreshed by running the tests with
MANIM_VERBOSE_UPDATE_GOLDEN=1, after which they have to be looked at before being committed.
Where a golden comparison fails and MANIM_TEST_ARTIFACTS is set, the new image and the
difference are written there.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import pytest

from fake_blocks import blocks_impl, fake_blocks  # noqa: F401  (fixtures)
from steps_helpers import (
    FIXTURES, GOLDEN, UPDATE_GOLDEN, away_from_edges, difference, doc_from, fixture_doc, frame_count,
    image, lossless, render_cache, run_scene, video_frames,  # noqa: F401  (lossless, render_cache are fixtures)
)

from manim_verbose.scenefile import render
from manim_verbose.scenefile.render import RenderCancelled, RenderError
from manim_verbose.scenefile.runtime import RenderPlan, _frame_at


def tiny(doc):
    """The same document at 256x144 and 15 fps, so that `hd` renders it small."""
    settings = doc.settings.model_copy(update={"resolution": [256, 144], "fps": 15})
    return doc.model_copy(update={"settings": settings})


# Timings

def test_timeline_of_the_fixture(fake_blocks):
    doc = fixture_doc("every_step.yaml")
    timings = render.timeline(doc, "basics")
    assert [(t.step_id, t.index, t.start, t.duration) for t in timings] == [
        ("s_show", 0, 0, 1.5), ("s_show_many", 1, 1.5, 2.25), ("s_add", 2, 3.75, 0),
        ("s_highlight", 3, 3.75, 1), ("s_recolor", 4, 4.75, 1), ("s_move_by", 5, 5.75, 1),
        ("s_move_to", 6, 6.75, 1), ("s_change", 7, 7.75, 1), ("s_transform", 8, 8.75, 1.5),
        ("s_wait", 9, 10.25, 0.5), ("s_remove", 10, 10.75, 0), ("s_hide", 11, 10.75, 1),
        ("s_clear", 12, 11.75, 1),
    ]
    assert render.scene_duration(doc, "basics") == 12.75
    assert [t.duration for t in render.timeline(doc, "plane_view")] == [1.5, 2, 2, 1, 1]
    assert render.document_duration(doc) == 20.25


def test_timeline_of_a_scene_which_isnt_there(fake_blocks):
    with pytest.raises(RenderError) as caught:
        render.timeline(fixture_doc("every_step.yaml"), "nowhere")
    assert caught.value.problems[0].message == "There's no scene called 'nowhere'"


def test_the_example_video_lasts_as_long_as_its_author_counted(blocks_impl):
    from manim_verbose.scenefile.files import load_file
    example = Path(__file__).parents[2] / "examples" / "eola_vectors" / "vectors.yaml"
    if not example.exists():
        pytest.skip("the example scene file isn't in this checkout")
    doc, _ = load_file(example)
    assert render.document_duration(doc) == pytest.approx(597.5)


@pytest.mark.parametrize("settings, quality, expected", [
    ("{}", "low", (854, 480, 15)),
    ("{}", "medium", (1280, 720, 30)),
    ("{}", "hd", (1920, 1080, 30)),
    ("{}", "uhd", (3840, 2160, 30)),
    ("{fps: 60}", "medium", (1280, 720, 60)),
    ("{fps: 10}", "low", (854, 480, 10)),
    ("{resolution: [1080, 1920]}", "low", (480, 854, 15)),
    ("{resolution: [1000, 1000]}", "medium", (720, 720, 30)),
    ("{resolution: [255, 143]}", "hd", (256, 144, 30)),
])
def test_what_each_quality_renders_at(settings, quality, expected):
    doc = doc_from(f"settings: {settings}\nscenes: [{{id: s}}]", tiny=False)
    assert render.quality_settings(doc, quality) == expected


def test_a_quality_which_isnt_one():
    with pytest.raises(RenderError):
        render.quality_settings(doc_from("scenes: [{id: s}]"), "ultra")


# Failures, reported on what they are about

def headless(doc, scene_id=None):
    job = render.prepare_job(doc, scene_id or doc.scenes[0].id)
    return render.run_job(job, RenderPlan(still=True, headless=True), 256, 144, 15)


def test_an_object_which_fails_to_build_is_named(fake_blocks, monkeypatch):
    from fake_blocks import object_expression
    from manim_verbose.scenefile import blocks
    monkeypatch.setattr(blocks, "object_expression",
                        lambda obj, ctx: "Circle(radius=1 / 0)" if obj.id == "bad" else object_expression(obj, ctx))
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: good, type: square}, {id: bad, type: circle}]
            steps: [{do: show, target: good}]
    """)
    with pytest.raises(RenderError) as caught:
        headless(doc)
    [problem] = caught.value.problems
    assert (problem.scene_id, problem.item_id, problem.loc) == ("s", "bad", ["scenes", 0, "objects", 1])
    assert problem.message == "This object couldn't be made: division by zero"


def test_a_step_which_fails_to_play_is_named(fake_blocks, monkeypatch):
    from manim_verbose.scenefile import blocks
    monkeypatch.setattr(blocks, "part_selector", lambda obj, part, ctx: f"{ctx.var(obj.id)}.no_such_part()")
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: t, type: text, text: "one two", shown: true}]
            steps:
              - {id: fine, do: wait}
              - {id: broken, do: highlight, target: t, part: two}
    """)
    with pytest.raises(RenderError) as caught:
        headless(doc)
    [problem] = caught.value.problems
    assert (problem.item_id, problem.loc) == ("broken", ["scenes", 0, "steps", 1])
    assert problem.message.startswith("This step couldn't be played: ")
    assert "no_such_part" in problem.message


def test_a_step_inside_together_which_fails_is_found_inside(fake_blocks, monkeypatch):
    from fake_blocks import object_expression
    from manim_verbose.scenefile import blocks
    monkeypatch.setattr(blocks, "object_expression",
                        lambda obj, ctx: "Circle(radius=1 / 0)" if obj.radius == 3 else object_expression(obj, ctx))
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: c, type: circle, shown: true}, {id: d, type: dot, point: [1, 1]}]
            steps:
              - {id: both, do: together, steps: [{do: show, target: d}, {id: grow_c, do: change, target: c, set: {radius: 3}}]}
    """)
    with pytest.raises(RenderError) as caught:
        headless(doc)
    [problem] = caught.value.problems
    assert problem.item_id == "grow_c"
    assert problem.loc == ["scenes", 0, "steps", 0, "steps", 1, "set", "radius"]


def test_something_which_cant_be_turned_into_code_is_named_before_anything_renders(fake_blocks, monkeypatch, tmp_path):
    from manim_verbose.scenefile import blocks

    def refuse(obj, ctx):
        raise NotImplementedError(f"no {obj.type} yet")

    monkeypatch.setattr(blocks, "object_expression", refuse)
    doc = doc_from("scenes: [{id: s, objects: [{id: plot, type: graph, on: ax, function: 'x'}, {id: ax, type: axes}]}]")
    for call in (
        lambda: render.render_still(doc, "s", -1, tmp_path / "x.png"),
        lambda: render.render_clip(doc, "s", tmp_path / "x.mp4") if doc.scenes[0].steps else render.prepare_job(doc, "s"),
        lambda: render.render_video(doc, tmp_path / "x.mp4"),
    ):
        with pytest.raises(RenderError) as caught:
            call()
        [problem] = caught.value.problems
        assert problem.loc[:3] == ["scenes", 0, "objects"] and problem.item_id in ("plot", "ax")
        assert problem.message.startswith("This can't be turned into code yet")
    assert not (tmp_path / "x.mp4").exists()


def test_unexpected_failures_are_problems_too(fake_blocks, monkeypatch):
    def broken(code):
        raise MemoryError("out of memory, say")

    monkeypatch.setattr(render, "load_module", broken)
    with pytest.raises(RenderError) as caught:
        headless(doc_from("scenes: [{id: s}]"))
    assert caught.value.problems[0].message == "Scene 's' couldn't be rendered: out of memory, say"


@pytest.mark.parametrize("call, message", [
    (lambda doc, out: render.render_still(doc, "s", 2, out / "x.png"), "Scene 's' has 2 step(s), so there's no step 2"),
    (lambda doc, out: render.render_still(doc, "s", -2, out / "x.png"), "Scene 's' has 2 step(s), so there's no step -2"),
    (lambda doc, out: render.render_clip(doc, "s", out / "x.mp4", 1, 0), "Scene 's' has 2 step(s), so steps 1 to 0 can't be shown"),
    (lambda doc, out: render.render_clip(doc, "s", out / "x.mp4", 0, 5), "Scene 's' has 2 step(s), so steps 0 to 5 can't be shown"),
    (lambda doc, out: render.render_still(doc, "t", 0, out / "x.png"), "There's no scene called 't'"),
    (lambda doc, out: render.render_video(doc, out / "x.mp4", scene_ids=["t"]), "There's no scene called 't'"),
    (lambda doc, out: render.render_video(doc, out / "x.mp4", quality="best"), "'best' isn't a quality; use one of low, medium, hd, uhd"),
])
def test_asking_for_what_isnt_there(call, message, fake_blocks, tmp_path):
    doc = doc_from("scenes: [{id: s, objects: [{id: c, type: circle}], steps: [{do: show, target: c}, {do: wait}]}]")
    with pytest.raises(RenderError) as caught:
        call(doc, tmp_path)
    assert caught.value.problems[0].message == message


def test_the_cache_is_where_it_is_told_to_be(monkeypatch, tmp_path):
    monkeypatch.setenv("MANIM_VERBOSE_CACHE", str(tmp_path / "here"))
    assert render.cache_dir() == tmp_path / "here"
    monkeypatch.delenv("MANIM_VERBOSE_CACHE")
    assert render.cache_dir() == Path.home() / ".cache" / "manim-verbose"


def unique_formula() -> str:
    # Never compiled before, so that nothing comes back from manim's own cache of formulas
    return "x_{" + str(uuid.uuid4().int % 10**9) + "}"


@pytest.mark.render
def test_a_formula_latex_cannot_typeset_is_a_problem_on_its_tex(fake_blocks, tmp_path, render_cache):
    good, bad = unique_formula(), unique_formula() + r" \nosuchcommand"
    doc = doc_from(f"""
        scenes:
          - id: s
            objects:
              - {{id: fine, type: tex, tex: "{good}"}}
              - {{id: eq, type: tex, tex: '{bad}'}}
            steps: [{{do: show, target: eq}}]
    """)
    with pytest.raises(RenderError) as caught:
        render.render_still(doc, "s", 0, tmp_path / "x.png")
    [problem] = caught.value.problems
    assert (problem.item_id, problem.loc) == ("eq", ["scenes", 0, "objects", 1, "tex"])
    assert problem.message.startswith("This formula couldn't be typeset: Undefined control sequence")
    assert not (tmp_path / "x.png").exists()


@pytest.mark.render
def test_a_formula_changed_into_one_latex_cannot_typeset_is_a_problem_on_the_change(fake_blocks, tmp_path, render_cache):
    bad = unique_formula() + r" \frac{1}{"
    doc = doc_from(f"""
        scenes:
          - id: s
            objects: [{{id: eq, type: tex, tex: "{unique_formula()}", shown: true}}]
            steps: [{{id: to_bad, do: change, target: eq, set: {{tex: '{bad}', color: RED}}}}]
    """)
    with pytest.raises(RenderError) as caught:
        render.render_clip(doc, "s", tmp_path / "x.mp4", quality="hd")
    [problem] = caught.value.problems
    assert (problem.item_id, problem.loc) == ("to_bad", ["scenes", 0, "steps", 0, "set", "tex"])
    assert problem.message.startswith("A formula in this step couldn't be typeset")
    assert not (tmp_path / "x.mp4").exists()
    assert not list(tmp_path.glob("*_temp*")), "the half written video was left behind"


# Stills

@pytest.mark.render
def test_a_still_is_a_picture_with_boxes(fake_blocks, tmp_path, render_cache):
    doc = fixture_doc("every_step.yaml")
    result = render.render_still(doc, "basics", 1, tmp_path / "deeper" / "one.png", width=320)
    assert (result.path, result.width, result.height) == (tmp_path / "deeper" / "one.png", 320, 180)
    picture = image(result.path)
    assert picture.shape == (180, 320, 3)
    assert picture.max() > 150, "the picture is blank"
    assert [box.id for box in result.objects] == ["dot", "title", "pair", "ring", "box"]
    for box in result.objects:
        x0, y0, x1, y1 = box.bbox
        assert 0 <= x0 < x1 <= 320 and 0 <= y0 < y1 <= 180


@pytest.mark.render
def test_a_still_before_the_first_step_and_after_the_last(fake_blocks, tmp_path, render_cache):
    doc = fixture_doc("every_step.yaml")
    first = render.render_still(doc, "basics", -1, tmp_path / "first.png", width=320)
    assert [box.id for box in first.objects] == ["dot"]
    last = render.render_still(doc, "basics", 12, tmp_path / "last.png", width=320)
    assert last.objects == []
    background = image(last.path)
    assert (background == background[0, 0]).all(), "the clear should have left an empty frame, caption and all"


@pytest.mark.render
def test_captions_are_drawn_but_never_boxed(fake_blocks, tmp_path, render_cache):
    doc = fixture_doc("every_step.yaml")
    result = render.render_still(doc, "basics", 0, tmp_path / "c.png", width=320)
    assert [box.id for box in result.objects] == ["dot", "title"]
    picture = image(result.path)
    band = picture[-12:]
    assert band.mean() < picture[60:120].mean(), "the dark band is at the bottom"
    assert band.max() > 200, "with the words on it"


# Clips

@pytest.mark.render
@pytest.mark.parametrize("first, last", [(0, 0), (1, 3), (5, 8), (9, 12), (12, 12)])
def test_a_clip_is_the_same_frames_as_that_stretch_of_the_whole(first, last, fake_blocks, tmp_path, render_cache,
                                                                 lossless):
    doc = tiny(fixture_doc("every_step.yaml"))
    whole = video_frames(render.render_clip(doc, "basics", tmp_path / "whole.mp4", quality="hd"))
    timings = render.timeline(doc, "basics")
    assert len(whole) == _frame_at(render.scene_duration(doc, "basics"), 15)
    clip = video_frames(render.render_clip(doc, "basics", tmp_path / "part.mp4", first, last, quality="hd"))
    start = _frame_at(timings[first].start, 15)
    end = _frame_at(timings[last].start + timings[last].duration, 15)
    assert len(clip) == max(end - start, 1)
    for index, frame in enumerate(clip[:end - start]):
        reference = whole[start + index]
        assert away_from_edges(reference, frame) == 0, index
        assert difference(reference, frame)[1] < 0.5, index


@pytest.mark.render
def test_a_clip_of_steps_taking_no_time_is_the_frame_they_leave(fake_blocks, tmp_path, render_cache):
    doc = tiny(fixture_doc("every_step.yaml"))
    clip = render.render_clip(doc, "basics", tmp_path / "add.mp4", 2, 2, quality="hd")
    assert frame_count(clip) == 1


@pytest.mark.render
def test_a_low_quality_clip(fake_blocks, tmp_path, render_cache):
    import av
    doc = doc_from("scenes: [{id: s, objects: [{id: c, type: circle}], steps: [{do: show, target: c, run_time: 0.5}]}]",
                   tiny=False)
    clip = render.render_clip(doc, "s", tmp_path / "low.mp4")
    with av.open(str(clip)) as container:
        stream = container.streams.video[0]
        assert (stream.codec_context.width, stream.codec_context.height) == (854, 480)
        assert stream.average_rate == 15
    assert frame_count(clip) == 8


# Whole videos

TWO_SCENES = """
    scenes:
      - id: first
        objects: [{id: c, type: circle, color: BLUE, fill: BLUE, fill_opacity: 1}]
        steps: [{do: show, target: c, style: draw, run_time: 1, caption: One}]
      - id: second
        objects: [{id: s, type: square, color: GREEN, fill: GREEN, fill_opacity: 1}, {id: t, type: text, text: two}]
        steps:
          - {do: show, target: s, run_time: 0.8}
          - {do: together, lag: 0.5, steps: [{do: show, target: t, run_time: 0.4}, {do: hide, target: s, run_time: 0.4}]}
"""


@pytest.mark.render
def test_scenes_are_joined_in_order_to_their_summed_length(fake_blocks, tmp_path, render_cache):
    doc = doc_from(TWO_SCENES)
    seen: list[tuple[float, str]] = []
    path = render.render_video(doc, tmp_path / "out" / "video.mp4", quality="hd",
                               progress=lambda fraction, message: seen.append((fraction, message)))
    assert path == tmp_path / "out" / "video.mp4"
    assert render.scene_duration(doc, "second") == pytest.approx(1.4)
    frames = video_frames(path)
    assert len(frames) == _frame_at(1.0, 15) + _frame_at(1.4, 15)
    assert abs(len(frames) / 15 - render.document_duration(doc)) <= 1 / 15
    # The first scene's blue circle, then the second's green square

    def blue(frame):
        return ((frame[..., 2] > 180) & (frame[..., 0] < 130)).any()

    def green(frame):
        return ((frame[..., 1] > 150) & (frame[..., 0] < 160) & (frame[..., 2] < 140)).any()

    assert blue(frames[14]) and not green(frames[14])
    assert green(frames[26]) and not blue(frames[26])
    fractions = [fraction for fraction, _ in seen]
    assert fractions == sorted(fractions) and fractions[0] >= 0 and fractions[-1] == 1.0
    assert seen[-1][1] == "Done"
    assert render._last_run == {"rendered": ["first", "second"], "cached": []}
    assert not list((render_cache / "tmp").iterdir()), "scratch files were left behind"


@pytest.mark.render
def test_rendering_again_uses_what_was_rendered_and_only_redoes_what_changed(fake_blocks, tmp_path, render_cache):
    doc = doc_from(TWO_SCENES)
    first = render.render_video(doc, tmp_path / "a.mp4", quality="hd")
    started = time.monotonic()
    again = render.render_video(doc, tmp_path / "b.mp4", quality="hd")
    assert time.monotonic() - started < 3
    assert render._last_run == {"rendered": [], "cached": ["first", "second"]}
    assert first.read_bytes() == again.read_bytes()
    doc.scenes[1].steps[0].caption = "A caption, which changes how the scene looks"
    render.render_video(doc, tmp_path / "c.mp4", quality="hd")
    assert render._last_run == {"rendered": ["second"], "cached": ["first"]}
    render.render_video(doc, tmp_path / "d.mp4", quality="low")
    assert render._last_run["rendered"] == ["first", "second"], "another quality is another video"


@pytest.mark.render
def test_rendering_scenes_side_by_side_gives_the_same_video_as_one_at_a_time(fake_blocks, tmp_path, monkeypatch):
    doc = doc_from(TWO_SCENES)
    monkeypatch.setenv("MANIM_VERBOSE_CACHE", str(tmp_path / "one"))
    serial = render.render_video(doc, tmp_path / "serial.mp4", quality="hd", jobs=1)
    monkeypatch.setenv("MANIM_VERBOSE_CACHE", str(tmp_path / "two"))
    parallel = render.render_video(doc, tmp_path / "parallel.mp4", quality="hd", jobs=2)
    a, b = video_frames(serial), video_frames(parallel)
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert difference(x, y)[0] == 0


@pytest.mark.render
def test_just_some_scenes(fake_blocks, tmp_path, render_cache):
    doc = doc_from(TWO_SCENES)
    path = render.render_video(doc, tmp_path / "second.mp4", quality="hd", scene_ids=["second"])
    assert frame_count(path) == _frame_at(1.4, 15)


def worker_processes() -> list[int]:
    """Render workers started by this process which are still running."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        parent = int(stat.rsplit(")", 1)[1].split()[1])
        if parent == os.getpid() and "manim_verbose.scenefile.render" in command:
            found.append(int(entry.name))
    return found


@pytest.mark.render
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="looks for leftover processes in /proc")
def test_cancelling_stops_promptly_and_leaves_nothing_behind(fake_blocks, tmp_path, render_cache):
    long = "\n".join(
        f"  - {{id: s{i}, objects: [{{id: c, type: circle}}], steps: [{{do: show, target: c, run_time: 6}}]}}"
        for i in range(3)
    )
    doc = doc_from("scenes:\n" + long)
    asked = threading.Event()
    when: list[float] = []

    def progress(fraction, message):
        if fraction > 0.02 and not asked.is_set():
            when.append(time.monotonic())
            asked.set()

    with pytest.raises(RenderCancelled):
        render.render_video(doc, tmp_path / "never.mp4", quality="hd", jobs=2, progress=progress, cancel=asked.is_set)
    assert time.monotonic() - when[0] < 5
    assert worker_processes() == []
    assert not (tmp_path / "never.mp4").exists()
    assert not list((render_cache / "tmp").iterdir())


@pytest.mark.render
def test_a_problem_in_one_scene_of_a_video_is_reported_from_its_worker(fake_blocks, tmp_path, render_cache):
    bad = unique_formula() + r" \nosuchcommand"
    doc = doc_from(TWO_SCENES.replace("{id: t, type: text, text: two}", f"{{id: t, type: tex, tex: '{bad}'}}"))
    with pytest.raises(RenderError) as caught:
        render.render_video(doc, tmp_path / "x.mp4", quality="hd")
    [problem] = caught.value.problems
    assert (problem.scene_id, problem.item_id, problem.loc) == ("second", "t", ["scenes", 1, "objects", 1, "tex"])
    assert not (tmp_path / "x.mp4").exists()


# Golden images

GOLDEN_STILLS = [
    ("basics", -1), ("basics", 1), ("basics", 4), ("basics", 7), ("basics", 11),
    ("plane_view", 0), ("plane_view", 1), ("plane_view", 2), ("plane_view", 4),
]


def golden_name(scene_id: str, step: int) -> str:
    return f"every_step_{scene_id}_{'start' if step < 0 else step}.png"


@pytest.mark.render
@pytest.mark.parametrize("scene_id, step", GOLDEN_STILLS)
def test_stills_look_as_they_did(scene_id, step, fake_blocks, tmp_path, render_cache):
    doc = fixture_doc("every_step.yaml")
    result = render.render_still(doc, scene_id, step, tmp_path / "new.png", width=320)
    golden = GOLDEN / golden_name(scene_id, step)
    if UPDATE_GOLDEN:
        golden.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(result.path, golden)
        return
    if not golden.exists():
        pytest.fail(f"No golden image {golden.name}: run with MANIM_VERBOSE_UPDATE_GOLDEN=1, and look at it")
    reference, new = image(golden), image(result.path)
    worst, mean = difference(reference, new)
    stray = away_from_edges(reference, new)
    if stray or mean >= 1.0:
        artifacts = os.environ.get("MANIM_TEST_ARTIFACTS")
        if artifacts:
            from PIL import Image
            folder = Path(artifacts) / "scenefile-golden"
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(result.path, folder / golden.name.replace(".png", ".new.png"))
            diff = np.clip(np.abs(reference - new) * 4, 0, 255).astype(np.uint8)
            Image.fromarray(np.vstack([reference.astype(np.uint8), new.astype(np.uint8), diff])).save(
                folder / golden.name.replace(".png", ".diff.png"))
        pytest.fail(f"{golden.name} differs: {stray} pixels away from any edge, worst {worst}, mean {mean:.2f}")


# The command line

def write_fixture(tmp_path: Path, tiny_copy: bool = False) -> Path:
    path = tmp_path / "every_step.yaml"
    text = (FIXTURES / "every_step.yaml").read_text()
    if tiny_copy:
        text = text.replace("settings:\n", "settings:\n  resolution: [256, 144]\n  fps: 15\n")
    path.write_text(text)
    return path


def test_cli_info(fake_blocks, tmp_path, capsys):
    from manim_verbose.scenefile.cli import main
    assert main(["info", str(write_fixture(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "basics   0:12.8  7 objects, 13 steps  (Showing, moving and changing)" in out
    assert "     0:03.8    0.0s  add          s_add" in out
    assert out.rstrip().endswith("total   0:20.2")


def test_cli_code(fake_blocks, tmp_path, capsys):
    from manim_verbose.scenefile.cli import main
    path = write_fixture(tmp_path)
    assert main(["code", str(path), "-s", "plane_view"]) == 0
    out = capsys.readouterr().out
    assert "class PlaneView(DocScene):" in out and "class Basics" not in out
    assert main(["code", str(path), "-o", str(tmp_path / "code.py")]) == 0
    compile((tmp_path / "code.py").read_text(), "code.py", "exec")


def test_cli_code_reports_what_cant_be_turned_into_code(fake_blocks, tmp_path, capsys, monkeypatch):
    from manim_verbose.scenefile import blocks
    from manim_verbose.scenefile.cli import main

    def refuse(obj, ctx):
        raise ValueError("can't draw that")

    monkeypatch.setattr(blocks, "object_expression", refuse)
    assert main(["code", str(write_fixture(tmp_path))]) == 1
    err = capsys.readouterr().err
    assert "error: scenes[0].objects[0]: can't draw that" in err
    assert "Traceback" not in err


@pytest.mark.render
def test_cli_still_and_render(fake_blocks, tmp_path, capsys, render_cache):
    from manim_verbose.scenefile.cli import main
    path = write_fixture(tmp_path, tiny_copy=True)
    assert main(["still", str(path), "-s", "basics", "--step", "1", "-o", str(tmp_path / "s.png"), "--width", "320"]) == 0
    assert "Wrote" in capsys.readouterr().out and (tmp_path / "s.png").exists()
    assert main(["render", str(path), "-q", "hd", "-s", "plane_view", "-j", "1"]) == 0
    video = path.with_suffix(".mp4")
    assert frame_count(video) == _frame_at(7.5, 15)
    assert "100.0%" in capsys.readouterr().err
