"""
Objects carried from one scene into the next (`carry: [ids]`): that each starts the new scene
exactly as the scene before left it, whatever happened to it there (changes, moves, matrices,
recolors, following, dimming), over several scenes; the code which brings them in; timings;
the warnings for what can't be carried exactly; and, rendering, that the first picture of a
scene is the last of the one before, and that the cache knows what a scene carries.

Everything runs headless except where marked `render`.
"""
from __future__ import annotations

import textwrap
import time

import numpy as np
import pytest

from fake_blocks import blocks_impl, fake_blocks  # noqa: F401  (fixtures)
from steps_helpers import (  # noqa: F401  (render_cache, lossless are fixtures)
    away_from_edges, difference, doc_from, image, lossless, render_cache, run_scene, video_frames,
)

from manim_verbose.scenefile import render
from manim_verbose.scenefile.carry import carry_problems, carried_specs, chain
from manim_verbose.scenefile.codegen import document_to_python, generate_module


def mobject_state(mob) -> list:
    """What a mobject looks like, point by point and color by color, for comparing two."""
    out = []
    for sub in mob.get_family():
        if not sub.has_points():
            continue
        out.append((np.array(sub.get_points()), np.array(sub.data["rgba"] if "rgba" in sub.data.dtype.names else
                                                          np.concatenate([sub.data[k] for k in sub.data.dtype.names
                                                                          if "rgba" in k]))))
    return out


def colors_of(mob) -> list[np.ndarray]:
    found = []
    for sub in mob.get_family():
        if sub.has_points():
            names = [name for name in sub.data.dtype.names if "rgba" in name]
            found.append(np.concatenate([np.asarray(sub.data[name]).reshape(len(sub.data), -1) for name in names], axis=1))
    return found


def assert_same_look(a, b, what: str) -> None:
    """Two mobjects drawn alike: the same points, the same colors and opacities, everywhere."""
    points_a = np.concatenate([m.get_points() for m in a.get_family() if m.has_points()] or [np.zeros((0, 3))])
    points_b = np.concatenate([m.get_points() for m in b.get_family() if m.has_points()] or [np.zeros((0, 3))])
    assert points_a.shape == points_b.shape, f"{what}: {points_a.shape} points and {points_b.shape}"
    assert np.allclose(points_a, points_b, atol=1e-4), f"{what}: moved by up to {np.abs(points_a - points_b).max()}"
    for ca, cb in zip(colors_of(a), colors_of(b)):
        assert ca.shape == cb.shape and np.allclose(ca, cb, atol=1e-4), f"{what}: colored differently"


def assert_carried_as_left(doc, scene_index: int) -> tuple:
    """Every object scene `scene_index` carries starts it exactly as the scene before left it."""
    before_id, scene = doc.scenes[scene_index - 1].id, doc.scenes[scene_index]
    before = run_scene(doc, before_id)
    after = run_scene(doc, scene.id, last_step=-1)
    for obj_id in scene.carry:
        assert_same_look(before.objects[obj_id], after.objects[obj_id], obj_id)
    assert after.carried_ids == list(dict.fromkeys(after.carried_ids))
    assert set(after.carried_ids) == set(scene.carry)
    assert set(scene.carry) <= set(after.registered_on_screen()), "carried objects start on screen"
    return before, after


# What carries

EVERYTHING_HAPPENS = """
    scenes:
      - id: first
        objects:
          - {id: plane, type: number_plane, x_range: [-6, 6, 1], y_range: [-4, 4, 1], shown: true}
          - {id: v, type: vector, on: plane, tip: [1, 2], color: YELLOW}
          - {id: w, type: vector, on: plane, tip: [2, -1], color: TEAL}
          - {id: d, type: dot, on: plane, point: [-2, 1], color: RED}
          - {id: t, type: text, text: "one two", place: top}
          - {id: sq, type: square, side: 1, color: GREEN, place: [4, -2]}
          - {id: c, type: circle, radius: 0.5, color: BLUE, place: [-4, -2]}
          - {id: g, type: group, members: [sq, c]}
          - {id: gone, type: text, text: "left behind", place: bottom}
        steps:
          - {do: show, target: [v, w, d, t, g, gone]}
          - {do: change, target: v, set: {color: RED}}
          - {do: move, target: t, by: [1, -0.5]}
          - {do: move, target: d, by: [0.5, 0.5]}
          - {do: apply_matrix, target: [plane, v, d], matrix: [[1, 1], [0, 1]]}
          - {do: change, target: v, set: {color: ORANGE}}
          - {do: change, target: w, set: {tip: [-1, -2]}}
          - {do: highlight, target: t, part: two, style: recolor, color: GREEN}
          - {do: move, target: g, by: [0, 1]}
          - {do: apply_matrix, target: sq, matrix: [[1.5, 0], [0, 0.5]]}
          - {do: change, target: c, set: {radius: 0.8}}
          - {do: move, target: t, to: {edge: left}}
          - {do: hide, target: gone}
      - id: second
        carry: [plane, v, w, d, t, sq, c, g]
        steps:
          - {do: wait, duration: 0.5}
"""


def test_every_kind_of_thing_a_scene_does_to_an_object_carries(blocks_impl):
    doc = doc_from(EVERYTHING_HAPPENS)
    before, after = assert_carried_as_left(doc, 1)
    # And to be sure the comparison had something to see: these did move
    first = run_scene(doc, "first", last_step=-1)
    assert not np.allclose(first.objects["v"].get_end(), after.objects["v"].get_end())
    assert "gone" not in after.objects


def test_carried_objects_are_drawn_in_the_order_the_scene_before_left_them(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: a, type: square, side: 2, color: RED, fill: RED, fill_opacity: 1}
              - {id: b, type: circle, radius: 1, color: BLUE, fill: BLUE, fill_opacity: 1}
              - {id: c, type: text, text: "on top"}
            steps:
              - {do: show, target: c}
              - {do: show, target: b}
              - {do: show, target: a}
              - {do: hide, target: b}
              - {do: show, target: b}
          - id: second
            carry: [a, b, c]
    """)
    before, after = assert_carried_as_left(doc, 1)
    assert after.registered_on_screen() == before.registered_on_screen() == ["c", "a", "b"]


def test_a_matrix_after_a_move_and_a_move_after_a_matrix_carry_in_order(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: v, type: vector, on: plane, tip: [1, 1], shown: true}
              - {id: sq, type: square, side: 1, shown: true}
            steps:
              - {do: move, target: [v, sq], by: [1, 0]}
              - {do: apply_matrix, target: [v, sq], matrix: [[0, -1], [1, 0]]}
              - {do: move, target: [v, sq], by: [0, -1]}
          - id: second
            carry: [plane, v, sq]
    """)
    before, after = assert_carried_as_left(doc, 1)
    # Moved right, turned a quarter about the origin, moved down
    assert after.objects["v"].get_end()[:2] == pytest.approx([-1, 1])
    assert after.objects["sq"].get_center()[:2] == pytest.approx([0, 0])


def test_a_follower_carries_where_it_followed_to_and_goes_on_following(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: v, type: vector, on: plane, tip: [2, 1], shown: true}
              - {id: label, type: text, text: v, place: {next_to: v, anchor: tip, side: right, follow: true}, shown: true}
              - {id: left_behind, type: text, text: w, place: {next_to: v, anchor: tail, side: left, follow: true}, shown: true}
            steps:
              - {do: move, target: v, by: [-1, 1]}
              - {do: apply_matrix, target: [plane, v], matrix: [[1, 0], [0.5, 1]]}
              - {do: move, target: left_behind, by: [0, -1]}
              - {do: move, target: v, by: [-1, 0]}
          - id: second
            carry: [plane, v, label, left_behind]
            steps:
              - {do: move, target: v, by: [0, -2]}
    """)
    before, after = assert_carried_as_left(doc, 1)
    label, v = after.objects["label"], after.objects["v"]
    assert label.get_left()[:2] == pytest.approx(v.get_end()[:2] + [0.25, 0], abs=1e-3)
    end = run_scene(doc, "second")
    assert end.objects["label"].get_left()[:2] == pytest.approx(end.objects["v"].get_end()[:2] + [0.25, 0], abs=1e-3)
    assert end.objects["left_behind"].get_center() == pytest.approx(after.objects["left_behind"].get_center())
    assert end.following() == {"label": "v"}


def test_recolored_parts_and_dimming_carry(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: title, type: title, text: "Adding vectors", underline: false}
              - {id: t, type: text, text: "one two three"}
              - {id: u, type: text, text: "other", place: bottom}
            steps:
              - {do: show, target: [title, t]}
              - {do: highlight, target: title, part: vectors, style: recolor, color: RED}
              - {do: highlight, target: t, part: three, style: recolor, color: "#FF8800"}
              - {do: transform, target: t, into: u, keep: dim}
          - id: second
            carry: [title, t, u]
    """)
    before, after = assert_carried_as_left(doc, 1)
    assert after.objects["title"]["vectors"].get_fill_color().upper() == "#FC6255"
    assert after.objects["t"].get_fill_opacity() == pytest.approx(0.35, abs=1e-3)


def test_objects_carry_on_through_several_scenes(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: one
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: v, type: vector, on: plane, tip: [1, 0], shown: true}
            steps:
              - {do: apply_matrix, target: [plane, v], matrix: [[2, 0], [0, 1]]}
          - id: two
            carry: [plane, v]
            objects:
              - {id: w, type: vector, on: plane, tip: [0, 1], shown: true}
            steps:
              - {do: move, target: v, by: [0, 1]}
              - {do: apply_matrix, target: [plane, v, w], matrix: [[1, 1], [0, 1]]}
          - id: three
            carry: [plane, v, w]
            steps:
              - {do: change, target: w, set: {color: RED}}
          - id: four
            carry: [w]
    """)
    assert_carried_as_left(doc, 1)
    assert_carried_as_left(doc, 2)
    assert_carried_as_left(doc, 3)
    assert chain(doc, 3) == [0, 1, 2, 3] and chain(doc, 0) == [0]


def test_a_carried_object_is_used_like_any_other(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: v, type: vector, on: plane, tip: [1, 1], shown: true}
            steps:
              - {do: apply_matrix, target: [plane, v], matrix: [[1, 1], [0, 1]]}
          - id: second
            carry: [plane, v]
            objects:
              - {id: label, type: text, text: "v", place: {next_to: v, anchor: tip, side: up}}
              - {id: w, type: vector, on: plane, tip: [0, 1]}
            steps:
              - {do: show, target: [label, w]}
              - {do: change, target: v, set: {color: RED}}
              - {do: hide, target: plane}
              - {do: transform, target: v, into: w}
    """)
    scene = run_scene(doc, "second", last_step=0)
    assert scene.objects["label"].get_bottom()[:2] == pytest.approx(scene.objects["v"].get_end()[:2] + [0, 0.25], abs=1e-3)
    # On the plane as the first scene left it, sheared
    assert scene.objects["w"].get_end()[:2] == pytest.approx([1, 1])
    scene = run_scene(doc, "second", last_step=1)
    assert scene.objects["v"].get_end()[:2] == pytest.approx([2, 1]), "a change keeps what the matrix did"
    assert run_scene(doc, "second").registered_on_screen() == ["label", "w"]


# The code

def test_the_code_bringing_objects_in(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: first
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: v, type: vector, on: plane, tip: [1, 2]}
              - {id: label, type: text, text: v, place: {next_to: v, anchor: tip, follow: true}}
            steps:
              - {do: show, target: [v, label]}
              - {do: apply_matrix, target: [plane, v], matrix: [[1, 1], [0, 1]]}
              - {do: change, target: v, set: {color: RED}}
          - id: second
            carry: [plane, v, label]
            steps: [{do: wait}]
    """)
    code = generate_module(doc, scene_ids=["second"]).code
    body = code.split("def construct(self):\n")[1].split("\n\n")[0]
    assert body == textwrap.indent(textwrap.dedent("""\
        with self.carried_from("first"):
            plane = self.obj("plane", NumberPlane(x_range=[-8, 8, 1], y_range=[-4, 4, 1]))
            v = self.obj("v", Arrow(plane.c2p(0, 0), plane.c2p(1, 2), buff=0).set_color(RED))
            label = self.obj("label", self.keep_beside(Text("v", font_size=48), v, anchor="tip"))
            self.apply_now(ApplyMatrixOn([[1, 1], [0, 1]], plane), ApplyMatrixOn([[1, 1], [0, 1]], v, plane))
            self.add(plane, v, label)"""), " " * 8)
    assert "class First" not in code, "a scene's class needs nothing of the one before's"
    compile(code, "second.py", "exec")


def test_objects_carried_are_named_on_their_lines(fake_blocks):
    doc = doc_from(EVERYTHING_HAPPENS)
    module = generate_module(doc, scene_ids=["second"])
    lines = module.code.splitlines()
    for number, ref in module.line_map.items():
        if ref.kind == "carry":
            assert ref.loc[:3] == ("scenes", 1, "carry") and doc.scenes[1].carry[ref.loc[3]] == ref.item_id
            assert ref.item_id in lines[number - 1]


def test_a_scene_carrying_nothing_has_no_carrying_code(fake_blocks):
    doc = doc_from(EVERYTHING_HAPPENS)
    assert "carried_from" not in generate_module(doc, scene_ids=["first"]).code


# Timings and the command line

def test_timings_know_what_kind_of_object_was_carried(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: first
            objects: [{id: t, type: text, text: words, shown: true}, {id: d, type: dot, point: [1, 1], shown: true}]
          - id: second
            carry: [t, d]
            steps:
              - {do: hide, target: [t, d]}
              - {do: show, target: t}
              - {do: show, target: d}
    """)
    assert [t.duration for t in render.timeline(doc, "second")] == [1, 1.5, 1]
    assert set(carried_specs(doc, 1)) == {"t", "d"}
    scene = run_scene(doc, "second")
    assert [r.duration for r in scene.step_records] == pytest.approx([1, 1.5, 1])


def test_info_says_what_each_scene_carries(blocks_impl, tmp_path, capsys):
    from manim_verbose.scenefile.cli import main
    path = tmp_path / "carry.yaml"
    path.write_text(textwrap.dedent(EVERYTHING_HAPPENS))
    assert main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "second   0:00.5  0 objects, 1 steps, carrying plane, v, w, d, t, sq, c, g" in out
    assert "first " in out and "carrying" not in out.split("second")[0]


# What can't be carried exactly

def warnings_for(yaml_text: str) -> list[str]:
    doc = doc_from(yaml_text)
    return [p.message for p in carry_problems(doc)]


def test_nothing_to_warn_about_when_everything_carries_exactly(fake_blocks):
    assert warnings_for(EVERYTHING_HAPPENS) == []


def test_a_warning_where_objects_were_moved_together_with_one_left_behind(fake_blocks):
    found = warnings_for("""
        scenes:
          - id: first
            objects: [{id: a, type: circle, shown: true}, {id: b, type: square, shown: true, place: [2, 0]}]
            steps: [{do: move, target: [a, b], to: top}]
          - id: second
            carry: [a]
    """)
    assert found == ["'a' was moved together with 'b' in scene 'first', which isn't carried, so it's carried as if moved without it"]


def test_a_warning_where_a_move_was_beside_something_left_behind(fake_blocks):
    found = warnings_for("""
        scenes:
          - id: first
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: d, type: dot, on: plane, point: [1, 1], shown: true}
              - {id: t, type: text, text: here, shown: true}
            steps: [{do: move, target: d, to: {next_to: t, side: up}}]
          - id: second
            carry: [plane, d]
    """)
    assert found == ["'d' was moved beside 't' in scene 'first', which isn't carried, so that move can't be carried: carry 't' too"]


def test_a_warning_where_something_was_placed_beside_what_changed_later(fake_blocks):
    found = warnings_for("""
        scenes:
          - id: first
            objects:
              - {id: t, type: text, text: here, shown: true}
              - {id: note, type: text, text: note, place: {next_to: t}, shown: true}
              - {id: follower, type: text, text: f, place: {next_to: t, side: up, follow: true}, shown: true}
            steps: [{do: move, target: t, to: bottom}]
          - id: second
            carry: [t, note, follower]
    """)
    assert found == ["'note' was put beside 't' before 't' was changed or moved, so it's carried beside 't' as that "
                     "ended up rather than where it was"]


def test_validation_passes_carry_warnings_on(fake_blocks):
    from manim_verbose.scenefile.files import load_text
    _, problems = load_text(textwrap.dedent("""
        scenes:
          - id: first
            objects: [{id: a, type: circle, shown: true}, {id: b, type: square, shown: true}]
            steps: [{do: move, target: [a, b], to: top}]
          - id: second
            carry: [a]
    """))
    [warning] = [p for p in problems if p.severity == "warning"]
    assert warning.loc == ["scenes", 1, "carry", 0] and warning.item_id == "a"


# Rendering

NO_CAPTIONS = """
    settings: {resolution: [320, 180], fps: 15}
    scenes:
      - id: first
        objects:
          - {id: plane, type: number_plane, x_range: [-8, 8, 2], y_range: [-4, 4, 2], shown: true}
          - {id: v, type: vector, on: plane, tip: [2, 1], color: YELLOW}
          - {id: label, type: tex, tex: "\\\\vec{v}", place: {next_to: v, anchor: tip, side: right, follow: true}}
          - {id: sq, type: square, side: 1.5, color: GREEN, fill: GREEN, fill_opacity: 0.5, place: [-4, 2]}
          - {id: t, type: text, text: "carried over", place: bottom}
        steps:
          - {id: show, do: show, target: [v, label, sq, t], run_time: 1}
          - {id: shear, do: apply_matrix, target: [plane, v, sq], matrix: [[1, 0.5], [0, 1]], run_time: 1}
          - {id: recolor, do: highlight, target: t, part: over, style: recolor, color: RED}
          - {id: dim, do: transform, target: sq, into: t, keep: dim, style: fade, run_time: 0.5}
      - id: second
        carry: [plane, v, label, sq, t]
        steps:
          - {id: onwards, do: move, target: v, by: [-2, -1], run_time: 1}
"""


@pytest.mark.render
def test_a_scene_starts_on_the_picture_the_scene_before_ended_on(blocks_impl, tmp_path, render_cache):
    doc = doc_from(NO_CAPTIONS, tiny=False)
    last = render.render_still(doc, "first", 3, tmp_path / "last.png", width=320)
    first = render.render_still(doc, "second", -1, tmp_path / "first.png", width=320)
    a, b = image(last.path), image(first.path)
    assert away_from_edges(a, b) == 0, difference(a, b)
    assert difference(a, b)[1] < 0.5
    assert [box.id for box in first.objects] == [box.id for box in last.objects]
    for x, y in zip(first.objects, last.objects):
        assert x.frame_bbox == pytest.approx(y.frame_bbox, abs=1e-3), x.id


@pytest.mark.render
def test_a_video_of_carried_scenes_runs_on_without_a_jump(blocks_impl, tmp_path, render_cache, lossless):
    doc = doc_from(NO_CAPTIONS, tiny=False)
    path = render.render_video(doc, tmp_path / "video.mp4", quality="hd")
    frames = video_frames(path)
    first_length = round(render.scene_duration(doc, "first") * 15)
    assert len(frames) == first_length + round(render.scene_duration(doc, "second") * 15)
    # The last frame of the first scene and the first of the second differ by a fifteenth of
    # a second of the vector's move, not by anything jumping
    last, next_one = frames[first_length - 1], frames[first_length]
    assert difference(last, next_one)[1] < 1.5


@pytest.mark.render
def test_changing_what_a_scene_carries_renders_it_again_and_nothing_else_does(blocks_impl, tmp_path, render_cache):
    doc = doc_from(NO_CAPTIONS, tiny=False)
    render.render_video(doc, tmp_path / "a.mp4", quality="hd")
    assert render._last_run == {"rendered": ["first", "second"], "cached": []}
    key = render.carry_key(doc, "second")
    assert key and render.carry_key(doc, "first") == ""
    # A caption in the first scene changes nothing the second carries
    doc.scenes[0].steps[0].caption = "Words"
    render.render_video(doc, tmp_path / "b.mp4", quality="hd")
    assert render._last_run == {"rendered": ["first"], "cached": ["second"]}
    assert render.carry_key(doc, "second") != key, "a server keying on the first scene would render again: safe"
    # The shear does
    doc.scenes[0].steps[1].matrix = [[1, 0.25], [0, 1]]
    render.render_video(doc, tmp_path / "c.mp4", quality="hd")
    assert render._last_run == {"rendered": ["first", "second"], "cached": []}
    # And the second scene alone
    doc.scenes[1].steps[0].run_time = 0.5
    started = time.monotonic()
    render.render_video(doc, tmp_path / "d.mp4", quality="hd")
    assert render._last_run == {"rendered": ["second"], "cached": ["first"]}
    assert time.monotonic() - started < 60


# Random documents: two scenes, the second carrying some of the first's objects

from hypothesis import HealthCheck, assume, given, settings, strategies as st  # noqa: E402

from test_actions import random_documents  # noqa: E402


@st.composite
def carrying_documents(draw):
    """A random scene, then a second carrying some of its objects (and what they are built on), with steps of its own."""
    data = draw(random_documents(follow=True))
    scene = data["scenes"][0]
    objects = {obj["id"]: obj for obj in scene["objects"]}
    chosen = draw(st.lists(st.sampled_from(sorted(objects)), min_size=1, unique=True))

    def needs(obj_id):
        obj = objects[obj_id]
        out = {obj_id}
        for ref in [obj.get("on"), *(obj.get("members") or []),
                    (obj.get("place") or {}).get("next_to") if isinstance(obj.get("place"), dict) else None]:
            if ref:
                out |= needs(ref)
        return out

    carried = sorted({needed for obj_id in chosen for needed in needs(obj_id)}, key=list(objects).index)
    second = {"id": "t", "carry": carried, "steps": draw(st.lists(
        st.sampled_from([
            {"do": "move", "target": carried[0], "by": [0.5, -0.5]},
            {"do": "hide", "target": carried[0]},
            {"do": "wait", "duration": 0.2},
            {"do": "highlight", "target": carried[-1], "style": "recolor", "color": "RED"},
        ]), max_size=2))}
    data["scenes"].append(second)
    return data


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture,
                                                                  HealthCheck.too_slow, HealthCheck.filter_too_much])
@given(data=carrying_documents())
def test_random_documents_carry_their_objects_as_they_left_them(data, blocks_impl):
    from manim_verbose.scenefile.validate import assign_step_ids, has_errors, validate_data
    doc, problems = validate_data(data)
    assume(doc is not None and not has_errors(problems))
    assign_step_ids(doc)
    compile(document_to_python(doc), "random.py", "exec")
    inexact = {p.item_id for p in carry_problems(doc)}
    before = run_scene(doc, "s")
    after = run_scene(doc, "t", last_step=-1)
    for obj_id in doc.scenes[1].carry:
        if obj_id not in inexact:
            assert_same_look(before.objects[obj_id], after.objects[obj_id], obj_id)
    assert set(doc.scenes[1].carry) <= set(after.registered_on_screen())
    end = run_scene(doc, "t")
    assert [r.duration for r in end.step_records] == pytest.approx([t.duration for t in render.timeline(doc, "t")])
