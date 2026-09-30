"""
DocScene, what generated code runs on: time kept on a grid of frames, captions, stopping
after a step and starting at one, progress, boxes of objects in pixels and frame units, and
the rules which keep what is on screen what the scene file says.

Everything here runs headless (a camera which draws nothing, so no graphics device and no
LaTeX), except where marked `render`.
"""
from __future__ import annotations

import numpy as np
import pytest

from fake_blocks import blocks_impl, fake_blocks  # noqa: F401  (fixtures)
from steps_helpers import doc_from, render_cache, run_scene  # noqa: F401  (render_cache is a fixture)

from manim_verbose.scenefile import render
from manim_verbose.scenefile.runtime import (
    CAPTION_Z, DocScene, FlashOn, Grow, HeadlessCamera, RenderPlan, _frame_at,
)


def run_with(doc, plan: RenderPlan, width: int = 256, scene_id: str | None = None):
    """A scene run headless under a plan of the test's choosing."""
    plan.headless = True
    job = render.prepare_job(doc, scene_id or doc.scenes[0].id)
    height = round(width * doc.settings.resolution[1] / doc.settings.resolution[0])
    return render.run_job(job, plan, width, height, doc.settings.fps)


def expected_frames(seconds: float, fps: int = 15) -> int:
    return _frame_at(seconds, fps)


# Time

@pytest.mark.parametrize("seconds, fps, frame", [
    (0, 30, 0), (1, 30, 30), (0.5, 15, 8), (0.49, 15, 7), (1 / 3, 15, 5), (2.25, 15, 34), (597.5, 30, 17925),
])
def test_the_frame_showing_a_moment(seconds, fps, frame):
    assert _frame_at(seconds, fps) == frame


ODD_TIMES = """
    scenes:
      - id: s
        objects: [{id: c, type: circle}, {id: d, type: dot, point: [1, 1]}]
        steps:
          - {do: show, target: c, run_time: 0.37}
          - {do: wait, duration: 0.41}
          - {do: show, target: d, run_time: 0.53}
          - {do: add, target: d}
          - {do: move, target: [c, d], by: [1, 0], run_time: 0.29}
          - {do: wait, duration: 0.07}
          - {do: hide, target: c, run_time: 1.33}
"""


def test_a_scene_comes_to_its_length_in_frames_whatever_its_steps_add_up_to(fake_blocks):
    doc = doc_from(ODD_TIMES)
    total = render.scene_duration(doc, "s")
    scene = run_with(doc, RenderPlan())
    assert scene.frames_emitted == expected_frames(total)
    assert scene.doc_time == pytest.approx(total)
    # Each step's frames are those whose moments fall in it
    for record in scene.step_records:
        assert expected_frames(record.end) - expected_frames(record.start) >= 0


@pytest.mark.parametrize("first, last", [(0, 6), (1, 1), (2, 4), (3, 3), (4, 6), (6, 6), (0, 0)])
def test_a_clip_holds_the_frames_of_its_steps(first, last, fake_blocks):
    doc = doc_from(ODD_TIMES)
    timings = render.timeline(doc, "s")
    scene = run_with(doc, RenderPlan(first_step=first, last_step=last))
    start, end = timings[first].start, timings[last].start + timings[last].duration
    assert scene.frames_emitted == expected_frames(end) - expected_frames(start)
    assert [r.index for r in scene.step_records] == list(range(last + 1))


def test_the_last_frame_of_a_play_shows_where_it_ends(fake_blocks):
    doc = doc_from(ODD_TIMES)
    scene = run_with(doc, RenderPlan(last_step=-1))
    scene.skip_animations = False
    scene.doc_time = 0.37
    times = list(scene.get_time_progression(0.41))
    assert times[-1] == 0.41
    assert all(0 < t <= 0.41 for t in times)
    assert len(times) == expected_frames(0.78) - expected_frames(0.37)


def test_progress_goes_up_to_the_end(fake_blocks):
    doc = doc_from(ODD_TIMES)
    seen = []
    run_with(doc, RenderPlan(progress=lambda seconds, step: seen.append((seconds, step))))
    assert seen == sorted(seen)
    assert seen[-1][0] == pytest.approx(render.scene_duration(doc, "s"))
    assert {step for _, step in seen} == {0, 1, 2, 4, 5, 6}


# Stopping and starting

def test_stopping_before_the_first_step_leaves_only_what_is_shown_from_the_start(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: a, type: circle, shown: true}, {id: b, type: square}]
            steps: [{do: show, target: b}, {do: hide, target: a}]
    """)
    scene = run_scene(doc, last_step=-1)
    assert scene.registered_on_screen() == ["a"]
    assert scene.step_records == []
    assert run_scene(doc, last_step=0).registered_on_screen() == ["a", "b"]
    assert run_scene(doc).registered_on_screen() == ["b"]


def test_a_scene_with_no_steps_runs_to_its_objects(fake_blocks):
    doc = doc_from("scenes: [{id: s, objects: [{id: a, type: circle, shown: true}]}]")
    assert run_scene(doc).registered_on_screen() == ["a"]


def test_headless_needs_no_graphics_device(fake_blocks, monkeypatch):
    from manimlib.renderer import gpu

    def no_device(self):
        raise RuntimeError("no graphics device here")

    monkeypatch.setattr(gpu.Gpu, "__init__", no_device)
    doc = doc_from(ODD_TIMES)
    scene = run_with(doc, RenderPlan())
    assert isinstance(scene.camera, HeadlessCamera)
    assert scene.frames_emitted > 0
    assert scene.camera.get_image().size == (256, 144)


# Captions

CAPTIONED = """
    settings: {resolution: [256, 144], fps: 15, captions: {font_size: 30}}
    scenes:
      - id: s
        objects: [{id: a, type: circle}, {id: b, type: square, place: [3, 0]}]
        steps:
          - {id: s0, do: show, target: a, caption: "First words"}
          - {id: s1, do: wait, duration: 1}
          - {id: s2, do: show, target: b, caption: "Second words"}
          - {id: s3, do: add, target: a, caption: "Said at once"}
          - {id: s4, do: wait, duration: 1, caption: ""}
          - {id: s5, do: wait, duration: 1, caption: "Back again"}
          - {id: s6, do: clear}
          - {id: s7, do: wait, duration: 1}
          - {id: s8, do: clear, caption: "After the clear"}
"""


def caption_text(scene) -> str | None:
    return scene._caption_text if scene._caption is not None else None


@pytest.mark.parametrize("last, expected", [
    (-1, None), (0, "First words"), (1, "First words"), (2, "Second words"), (3, "Said at once"),
    (4, None), (5, "Back again"), (6, None), (7, None), (8, "After the clear"),
])
def test_captions_last_until_changed_and_an_empty_one_or_a_clear_takes_them_away(last, expected, fake_blocks):
    scene = run_scene(doc_from(CAPTIONED, tiny=False), last_step=last)
    assert caption_text(scene) == expected
    pieces = [m for m in scene.mobjects if scene._is_caption(m)]
    if expected is None:
        assert pieces == []
    else:
        assert len(pieces) == 2, "the band and the words, and nothing left over from the one before"
        assert all(piece.is_fixed_in_frame() for piece in pieces)


def test_captions_are_never_objects_and_keep_out_of_the_way_of_steps(fake_blocks):
    scene = run_scene(doc_from(CAPTIONED, tiny=False), last_step=2)
    assert scene.registered_on_screen() == ["a", "b"]
    assert [obj_id for obj_id, _, _ in scene.object_boxes()] == ["a", "b"]
    assert all(not scene._is_caption(m) for m in scene.everything_on_screen())


def test_captions_do_not_change_how_long_steps_take(fake_blocks):
    doc = doc_from(CAPTIONED, tiny=False)
    plain = doc.model_copy(deep=True)
    for step in plain.scenes[0].steps:
        step.caption = None
    assert [t.duration for t in render.timeline(doc, "s")] == [t.duration for t in render.timeline(plain, "s")]
    scene = run_with(doc, RenderPlan())
    assert scene.frames_emitted == expected_frames(render.scene_duration(doc, "s"))


def test_the_band_sits_at_the_edge_asked_for_with_the_words_on_top(fake_blocks):
    doc = doc_from(CAPTIONED, tiny=False)
    band, words = run_scene(doc, last_step=0)._caption
    assert band.get_bottom()[1] == pytest.approx(-4, abs=1e-6)
    assert band.get_width() > 14
    assert words.get_center()[1] == pytest.approx(band.get_center()[1])
    assert words.z_index > band.z_index >= CAPTION_Z - 1
    top = doc_from(CAPTIONED.replace("captions: {font_size: 30}", "captions: {edge: top, background: false}"),
                   tiny=False)
    pieces = run_scene(top, last_step=0)._caption
    assert len(pieces) == 1 and pieces[0].get_top()[1] > 3


def test_a_long_caption_fits_the_frame(fake_blocks):
    long = "words " * 60
    doc = doc_from(f"scenes: [{{id: s, steps: [{{do: wait, caption: '{long}'}}]}}]")
    band, words = run_scene(doc)._caption
    assert words.get_width() <= 14.22 - 1
    assert band.get_height() > 0.5, "wrapped onto more than one line"


def test_captions_stay_put_when_the_camera_moves(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            steps:
              - {do: wait, caption: Hello}
              - {do: camera, zoom: 3, center: [2, 1], orientation: [-30, 60]}
    """)
    scene = run_scene(doc)
    band = scene._caption[0]
    corners = band.get_bounding_box()[[0, 2]]
    pixels = scene.frame_to_pixels(corners, fixed=True)
    assert pixels[:, 0].min() < 0 and pixels[:, 0].max() > 256
    assert pixels[:, 1].max() == pytest.approx(144, abs=0.5)


# What is on screen

def test_a_step_which_shows_nothing_leaves_hidden_objects_hidden_but_changed(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: c, type: circle, place: [-2, 0]}, {id: t, type: text, text: here, shown: true}]
            steps:
              - {do: change, target: c, set: {color: RED}}
              - {do: move, target: c, by: [0, 1]}
              - {do: highlight, target: c}
              - {do: apply_matrix, target: c, matrix: [[2, 0], [0, 2]]}
              - {do: move, target: [c, t], to: bottom}
              - {do: show, target: c, style: fade}
    """)
    for last in range(5):
        assert run_scene(doc, last_step=last).registered_on_screen() == ["t"]
    scene = run_scene(doc)
    assert scene.registered_on_screen() == ["t", "c"]
    assert scene.objects["c"].get_stroke_color().upper() == "#FC6255"
    assert scene.objects["c"].get_width() == pytest.approx(4)


def test_adding_a_group_draws_its_members_through_it_once(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: a, type: circle}, {id: b, type: square}, {id: g, type: group, members: [a, b]}]
            steps: [{do: add, target: a}, {do: show, target: g}]
    """)
    scene = run_scene(doc)
    family = scene.get_mobject_family_members()
    assert family.count(scene.objects["a"]) == 1
    assert scene.registered_on_screen() == ["g", "a", "b"]


def test_everything_on_screen_leaves_out_the_camera_and_captions(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: a, type: circle, shown: true}]
            steps: [{do: wait, caption: words}]
    """)
    scene = run_scene(doc)
    group = scene.everything_on_screen()
    assert list(group.submobjects) == [scene.objects["a"]]


# Boxes

BOXES = """
    settings: {resolution: [640, 360]}
    scenes:
      - id: s
        objects:
          - {id: sq, type: square, side: 2}
          - {id: c, type: circle, radius: 0.5, place: [2, 1], z: 1}
          - {id: d, type: dot, point: [-3, -2], radius: 0.1}
          - {id: g, type: group, members: [sq, d]}
          - {id: label, type: text, text: fixed, place: [4, 3], fixed: true}
        steps:
          - {do: add, target: [c, g, label]}
          - {do: camera, zoom: 2, center: [1, 0]}
          - {do: camera, orientation: [0, 60], reset: true}
"""


def boxes(scene) -> dict[str, tuple]:
    return {obj_id: (frame, pixels) for obj_id, frame, pixels in scene.object_boxes()}


def test_boxes_of_known_objects_at_known_places(fake_blocks):
    scene = run_scene(doc_from(BOXES, tiny=False), last_step=0, width=640)
    found = boxes(scene)
    # 45 pixels to a unit at 640 wide, the origin in the middle, y downwards
    assert found["sq"][0] == pytest.approx((-1, -1, 1, 1))
    assert found["sq"][1] == pytest.approx((275, 135, 365, 225))
    assert found["c"][0] == pytest.approx((1.5, 0.5, 2.5, 1.5))
    assert found["c"][1] == pytest.approx((387.5, 112.5, 432.5, 157.5))
    assert found["d"][1] == pytest.approx((320 - 3.1 * 45, 180 + 1.9 * 45, 320 - 2.9 * 45, 180 + 2.1 * 45))
    assert found["g"][0] == pytest.approx((-3.1, -2.1, 1, 1))


def test_boxes_come_in_drawing_order_groups_before_their_members(fake_blocks):
    scene = run_scene(doc_from(BOXES, tiny=False), last_step=0, width=640)
    order = [obj_id for obj_id, _, _ in scene.object_boxes()]
    # c is added first but drawn last, being higher up
    assert order == ["g", "sq", "d", "label", "c"]


def test_boxes_follow_the_camera_but_fixed_objects_stay(fake_blocks):
    before = boxes(run_scene(doc_from(BOXES, tiny=False), last_step=0, width=640))
    after = boxes(run_scene(doc_from(BOXES, tiny=False), last_step=1, width=640))
    # Twice as close, looking at (1, 0): 90 pixels to a unit, (1, 0) in the middle
    assert after["sq"][1] == pytest.approx((140, 90, 320, 270))
    assert after["sq"][0] == before["sq"][0], "frame units are the scene's, whatever the camera does"
    assert after["label"][1] == pytest.approx(before["label"][1])


def test_boxes_under_a_turned_camera_still_contain_the_object(fake_blocks):
    found = boxes(run_scene(doc_from(BOXES, tiny=False), width=640))
    x0, y0, x1, y1 = found["sq"][1]
    assert x0 < 320 < x1 and y0 < 180 < y1
    # Tipped back 60 degrees, the square looks about half as tall as it is wide
    assert (y1 - y0) < 0.75 * (x1 - x0)


@pytest.mark.render
def test_boxes_match_the_pixels(fake_blocks, tmp_path, render_cache):
    """Where a box says an object is, there is something drawn, and outside it (nearby) there isn't."""
    from steps_helpers import image
    doc = doc_from(BOXES.replace("{id: label, type: text, text: fixed, place: [4, 3], fixed: true}",
                                 "{id: label, type: circle, radius: 0.3, place: [4, 3], fixed: true}"), tiny=False)
    for step in (0, 1):
        result = render.render_still(doc, "s", step, tmp_path / f"{step}.png", width=640)
        picture = image(result.path).sum(axis=2)
        background = picture[0, 0]
        height, width = picture.shape
        for box in result.objects:
            x0, y0, x1, y1 = (int(round(v)) for v in box.bbox)
            if box.id == "g" or x0 < 8 or y0 < 8 or x1 > width - 8 or y1 > height - 8:
                # A group's box holds what its members' do, and one off the picture has
                # nothing in the picture to check
                continue
            inside = np.zeros(picture.shape, bool)
            inside[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = True
            assert (picture[inside] != background).any(), box.id
            # Strokes reach a little past the points, so what has to be empty is a ring
            # a few pixels further out
            outer, near = np.zeros(picture.shape, bool), np.zeros(picture.shape, bool)
            outer[max(y0 - 8, 0):min(y1 + 8, height), max(x0 - 8, 0):min(x1 + 8, width)] = True
            near[max(y0 - 4, 0):min(y1 + 4, height), max(x0 - 4, 0):min(x1 + 4, width)] = True
            assert (picture[outer & ~near] == background).all(), f"{box.id} draws outside its box at step {step}"


# Helpers

def test_grow_picks_how_to_grow(fake_blocks):
    from manimlib import AnimationGroup, Arrow, GrowArrow, GrowFromCenter, Square, Text, VGroup
    assert isinstance(Grow(Arrow([0, 0, 0], [1, 1, 0], buff=0)), GrowArrow)
    labelled = VGroup(Arrow([0, 0, 0], [1, 1, 0], buff=0), Text("v"))
    assert isinstance(Grow(labelled), AnimationGroup)
    assert isinstance(Grow(Square()), GrowFromCenter)


def test_flash_goes_round_the_object():
    from manimlib import Square
    flash = FlashOn(Square(side_length=4))
    assert flash.flash_radius == pytest.approx(2.3)


def test_a_doc_scene_left_to_itself_is_a_scene():
    assert DocScene.caption_style.font_size == 30
    assert DocScene.caption_style.edge == "bottom"
    assert RenderPlan().first_step == 0 and RenderPlan().last_step is None
