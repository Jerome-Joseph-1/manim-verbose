"""
That every kind of step does what model.py says it does. Each case of STEP_CASES is run in
a real scene with its animations skipped, and what is on screen afterwards checked against
the format's own words; then rendered for real, small, to check that it takes as long as
timeline() says and ends on the frame a still of it shows.
"""
from __future__ import annotations

import numpy as np
import pytest

from fake_blocks import blocks_impl, fake_blocks  # noqa: F401  (fixtures)
from steps_helpers import (
    STEP_CASES, away_from_edges, case_doc, case_params, difference, doc_from, image, lossless,  # noqa: F401
    render_cache, run_scene, video_frames,
)

from manim_verbose.scenefile import render
from manim_verbose.scenefile.actions import (
    Anim, StepCode, _together_time, default_run_time, num, point3, step_lines,
)
from manim_verbose.scenefile.codegen import CodegenContext

SHOWN = {"t", "u", "g", "c", "sq"}

# What is on screen once each case's last step has run, by the format's definition of it
ON_SCREEN: dict[str, set[str]] = {
    "show_auto": {"u"},
    "show_auto_tex": {"eq"},
    "show_write": {"t"},
    "show_draw": {"c"},
    "show_fade": {"sq"},
    "show_fade_up": {"t"},
    "show_grow_vector": {"plane", "v"},
    "show_grow_shape": {"sq"},
    "show_pop": {"d"},
    "show_many": {"c", "sq", "d", "g"},
    "show_many_lagged": {"c", "sq", "d", "g"},
    "show_group": {"g", "c", "sq"},
    "hide_auto": SHOWN - {"u"},
    "hide_fade_down": SHOWN - {"t"},
    "hide_uncreate": SHOWN - {"c", "g"},
    "hide_shrink": SHOWN - {"sq", "g"},
    "hide_many_lagged": SHOWN - {"t", "u"},
    "hide_group": {"t", "u"},
    "add": {"t", "d"},
    "add_held": {"d"},
    "remove": SHOWN - {"u"},
    "remove_member": SHOWN - {"c", "g"},
    "clear": set(),
    "transform_auto_text": SHOWN - {"t"} | {"w"},
    "transform_auto_tex": {"eq2"},
    "transform_morph": SHOWN - {"c", "g"} | {"d"},
    "transform_match_shapes": SHOWN - {"sq", "g"} | {"d"},
    "transform_fade": SHOWN - {"t"} | {"w"},
    "transform_keep": SHOWN | {"w"},
    "transform_keep_tex": {"eq", "eq2"},
    "transform_keep_fade": SHOWN | {"d"},
    "move_to_on_plane": {"plane", "u"},
    "change_tex": {"eq"},
    "highlight_indicate_tex_part": {"eq"},
    "highlight_recolor_tex": {"eq"},
    "camera_reset": {"t"},
    "apply_matrix_plane": {"plane", "v"},
    "together": {"t", "c"},
    "together_lagged": {"t", "c", "sq", "g", "d"},
    "together_run_time": SHOWN - {"u"},
    "together_instant": SHOWN - {"u"} | {"d"},
    "together_all_instant": SHOWN - {"u"} | {"d"},
    "together_clear": {"d"},
    "caption": {"t"},
    "caption_on_wait": set(),
    "caption_on_add": {"t"},
}


def expected_on_screen(name: str) -> set[str]:
    # Everything else (changes, moves, highlights, waits, camera moves) leaves what is on
    # screen as it was
    return ON_SCREEN.get(name, SHOWN)


def stray_mobjects(scene) -> list:
    """Anything drawn which belongs to no registered object on screen and isn't a caption."""
    owned = set()
    for obj_id in scene.registered_on_screen():
        owned.update(scene.objects[obj_id].get_family())
    return [
        mob for top in scene.mobjects if top is not scene.frame and not scene._is_caption(top)
        for mob in top.get_family() if mob.has_points() and mob not in owned
    ]


@pytest.mark.parametrize("name", case_params())
def test_every_step_leaves_the_screen_as_the_format_says(name, blocks_impl):
    doc = case_doc(name)
    scene = run_scene(doc)
    present = {obj.id for obj in doc.scenes[0].objects}
    assert set(scene.registered_on_screen()) == expected_on_screen(name) & present
    assert stray_mobjects(scene) == [], "a step left something on screen which isn't an object of the file"
    timings = render.timeline(doc, "case")
    assert [r.step_id for r in scene.step_records] == [t.step_id for t in timings]
    for record, timing in zip(scene.step_records, timings):
        assert record.start == pytest.approx(timing.start)
        assert record.duration == pytest.approx(timing.duration)


def centre(scene, obj_id):
    return scene.objects[obj_id].get_center()[:2]


def test_move_by_moves_by_exactly_that_much(blocks_impl):
    before = run_scene(case_doc("move_by"), last_step=0)
    after = run_scene(case_doc("move_by"))
    assert centre(after, "t") == pytest.approx(centre(before, "t") + [1, -1])


def test_moving_several_by_moves_each(blocks_impl):
    before = run_scene(case_doc("move_by_many"), last_step=0)
    after = run_scene(case_doc("move_by_many"))
    for obj_id in ("t", "u"):
        assert centre(after, obj_id) == pytest.approx(centre(before, obj_id) + [0, 1])


def test_move_to_an_edge_puts_it_against_the_edge_centred_along_it(blocks_impl):
    scene = run_scene(case_doc("move_to_edge"))
    u = scene.objects["u"]
    assert u.get_bottom()[1] == pytest.approx(-4 + 0.25, abs=1e-3)
    assert u.get_center()[0] == pytest.approx(0, abs=1e-3)


def test_move_to_a_point(blocks_impl):
    assert centre(run_scene(case_doc("move_to_point")), "u") == pytest.approx([2, 1])


def test_move_to_a_point_on_a_coordinate_system(blocks_impl):
    scene = run_scene(case_doc("move_to_on_plane"))
    assert centre(scene, "u") == pytest.approx(scene.objects["plane"].c2p(2, 1)[:2])


def test_move_next_to_another(blocks_impl):
    scene = run_scene(case_doc("move_to_next_to"))
    assert scene.objects["u"].get_top()[1] == pytest.approx(scene.objects["t"].get_bottom()[1] - 0.5, abs=1e-3)


def test_moving_several_to_a_place_moves_them_as_one(blocks_impl):
    before = run_scene(case_doc("move_to_many"), last_step=0)
    after = run_scene(case_doc("move_to_many"))
    gap_before = centre(before, "u") - centre(before, "t")
    assert centre(after, "u") - centre(after, "t") == pytest.approx(gap_before)
    right = max(after.objects[i].get_right()[0] for i in ("t", "u"))
    bottom = min(after.objects[i].get_bottom()[1] for i in ("t", "u"))
    assert right == pytest.approx(after.frame.get_width() / 2 - 0.25, abs=1e-3)
    assert bottom == pytest.approx(-4 + 0.25, abs=1e-3)


def test_moving_a_group_moves_its_members(blocks_impl):
    scene = run_scene(case_doc("move_group"))
    assert centre(scene, "c") == pytest.approx([-3, -1])
    assert centre(scene, "sq") == pytest.approx([3, -1])


def test_change_color(blocks_impl):
    scene = run_scene(case_doc("change_color"))
    assert scene.objects["c"].get_stroke_color().upper() == "#FC6255"


def test_change_text_takes_the_new_words_shape(blocks_impl):
    from manimlib import Text
    scene = run_scene(case_doc("change_text"))
    assert scene.objects["t"].get_width() == pytest.approx(Text("Goodbye", font_size=48).get_width(), rel=1e-3)


def test_change_placement(blocks_impl):
    scene = run_scene(case_doc("change_place"))
    assert scene.objects["t"].get_bottom()[1] == pytest.approx(-4 + 0.25, abs=1e-3)


def test_change_a_group_rearranges_its_members(blocks_impl):
    scene = run_scene(case_doc("change_group"))
    c, sq = scene.objects["c"], scene.objects["sq"]
    assert c.get_center()[0] == pytest.approx(sq.get_center()[0], abs=1e-3)
    assert c.get_bottom()[1] == pytest.approx(sq.get_top()[1] + 0.2, abs=1e-3)


def test_a_later_change_builds_on_the_earlier_one(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: c, type: circle, radius: 1, shown: true}]
            steps:
              - {do: change, target: c, set: {color: RED}}
              - {do: change, target: c, set: {radius: 2}}
    """)
    scene = run_scene(doc)
    assert scene.objects["c"].get_width() == pytest.approx(4)
    assert scene.objects["c"].get_stroke_color().upper() == "#FC6255"


def test_a_change_after_a_move_keeps_the_object_where_it_was_moved(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: here, place: top}
              - {id: c, type: circle, place: [-2, 0]}
              - {id: g, type: group, members: [c]}
            steps:
              - {do: add, target: [t, g]}
              - {do: move, target: t, by: [2, -1]}
              - {do: move, target: g, by: [0, -2]}
              - {do: change, target: t, set: {text: "there!"}}
              - {do: change, target: c, set: {color: RED}}
    """)
    before = run_scene(doc, last_step=2)
    after = run_scene(doc)
    assert centre(after, "t")[1] == pytest.approx(centre(before, "t")[1])
    assert centre(after, "c") == pytest.approx([-2, -2])


def test_a_recolor_lasts_and_later_changes_keep_it(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: t, type: text, text: "one two", shown: true}]
            steps:
              - {do: highlight, target: t, part: two, style: recolor, color: RED}
              - {do: change, target: t, set: {font_size: 60}}
    """)
    scene = run_scene(doc, last_step=0)
    assert scene.objects["t"]["two"].get_fill_color().upper() == "#FC6255"
    scene = run_scene(doc)
    assert scene.objects["t"]["two"].get_fill_color().upper() == "#FC6255"
    assert scene.objects["t"]["one"].get_fill_color().upper() == "#FFFFFF"


def test_recolor_whole_and_part(blocks_impl):
    scene = run_scene(case_doc("highlight_recolor"))
    assert scene.objects["t"]["there"].get_fill_color().upper() == "#FF8800"
    assert scene.objects["t"]["Hello"].get_fill_color().upper() == "#FFFFFF"
    scene = run_scene(case_doc("highlight_recolor_whole"))
    assert scene.objects["u"].get_fill_color().upper() == "#FFFF00"


@pytest.mark.render
def test_recolor_part_of_a_formula(blocks_impl):
    scene = run_scene(case_doc("highlight_recolor_tex"))
    assert scene.objects["eq"]["a^2"].get_fill_color().upper() == "#FFFF00"


@pytest.mark.parametrize("name", case_params(["highlight_indicate", "highlight_indicate_part", "highlight_indicate_tex_part",
                                              "highlight_flash", "highlight_box", "highlight_underline", "highlight_wiggle"]))
def test_momentary_highlights_leave_the_object_as_it_was(name, blocks_impl):
    before = run_scene(case_doc(name), last_step=0)
    after = run_scene(case_doc(name))
    for obj_id in before.registered_on_screen():
        a, b = before.objects[obj_id], after.objects[obj_id]
        assert np.allclose(a.get_all_points(), b.get_all_points(), atol=1e-6), obj_id
        assert a.get_color() == b.get_color()


def test_camera_steps(blocks_impl):
    scene = run_scene(case_doc("camera_zoom"))
    assert scene.frame.get_height() == pytest.approx(4)
    scene = run_scene(case_doc("camera_center"))
    assert scene.frame.get_center()[:2] == pytest.approx([1, 1])
    scene = run_scene(case_doc("camera_focus"))
    assert scene.frame.get_center()[:2] == pytest.approx(centre(scene, "sq"))
    assert scene.frame.get_height() == pytest.approx(8 / 1.5)
    scene = run_scene(case_doc("camera_orientation"))
    theta, phi, _ = np.degrees(scene.frame.get_euler_angles())
    assert (theta, phi) == pytest.approx((-30, 70))
    scene = run_scene(case_doc("camera_orientation_gamma"))
    assert np.degrees(scene.frame.get_euler_angles()) == pytest.approx([-30, 70, 10])
    assert scene.frame.get_height() == pytest.approx(8)
    scene = run_scene(case_doc("camera_reset"))
    assert scene.frame.get_height() == pytest.approx(8)
    assert scene.frame.get_center() == pytest.approx([0, 0, 0])


def test_apply_matrix_on_a_plane_carries_vectors_by_their_ends(blocks_impl):
    scene = run_scene(case_doc("apply_matrix_plane"))
    plane, v = scene.objects["plane"], scene.objects["v"]
    assert plane.get_origin() == pytest.approx([0, 0, 0])
    assert v.get_end()[:2] == pytest.approx([3, 2], abs=0.02)


def test_apply_matrix_in_frame_units(blocks_impl):
    scene = run_scene(case_doc("apply_matrix_frame"))
    assert scene.objects["sq"].get_width() == pytest.approx(2)
    assert centre(scene, "sq") == pytest.approx([6, 0])
    scene = run_scene(case_doc("apply_matrix_3d"))
    assert scene.objects["c"].get_height() == pytest.approx(2)
    assert centre(scene, "c") == pytest.approx([-3, 0])


def test_apply_matrix_follows_a_plane_which_isnt_at_the_origin(blocks_impl):
    from manim_verbose.scenefile.runtime import ApplyMatrixOn
    from manimlib import Dot, NumberPlane
    plane = NumberPlane(x_range=[-4, 4, 1], y_range=[-2, 2, 1], width=4, height=4).shift([1, 1, 0])
    dot = Dot(plane.c2p(1, 1))
    anim = ApplyMatrixOn([[0, -1], [1, 0]], dot, plane)
    anim.begin()
    anim.finish()
    assert dot.get_center() == pytest.approx(plane.c2p(-1, 1))


@pytest.mark.parametrize("style", ["uncreate", "shrink", "fade", "fade_down"])
def test_something_hidden_comes_back_as_it_was(style, blocks_impl):
    doc = doc_from(f"""
        scenes:
          - id: s
            objects: [{{id: c, type: circle, place: [1, 1]}}, {{id: t, type: text, text: words, place: bottom}}]
            steps:
              - {{do: show, target: [c, t]}}
              - {{do: hide, target: [c, t], style: {style}}}
              - {{do: show, target: [c, t]}}
    """)
    first = run_scene(doc, last_step=0)
    again = run_scene(doc)
    for obj_id in ("c", "t"):
        assert np.allclose(first.objects[obj_id].get_all_points(), again.objects[obj_id].get_all_points())
        assert first.objects[obj_id].get_opacity() == again.objects[obj_id].get_opacity()


def test_hiding_what_isnt_shown_leaves_it_whole(blocks_impl):
    """Found by the random documents below: uncreating a hidden plane emptied it for good."""
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: plane, type: number_plane}, {id: c, type: circle}]
            steps:
              - {do: hide, target: [plane, c], style: uncreate}
              - {do: hide, target: c, style: shrink}
              - {do: apply_matrix, target: plane, matrix: [[1, 1], [0, 1]]}
              - {do: show, target: [plane, c]}
    """)
    before = run_scene(doc, last_step=-1)
    after = run_scene(doc)
    assert after.registered_on_screen() == ["plane", "c"]
    assert np.allclose(before.objects["c"].get_all_points(), after.objects["c"].get_all_points())
    assert after.objects["plane"].c2p(1, 1)[:2] == pytest.approx([2, 1])


def test_changes_to_what_is_hidden_last(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: c, type: circle, place: [1, 0]}]
            steps:
              - {do: move, target: c, by: [0, 2]}
              - {do: change, target: c, set: {radius: 2}}
              - {do: show, target: c}
    """)
    scene = run_scene(doc)
    assert centre(scene, "c") == pytest.approx([1, 2])
    assert scene.objects["c"].get_width() == pytest.approx(4)


def test_transforming_there_and_back(blocks_impl):
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: "x + y", shown: true}
              - {id: b, type: text, text: "y + x + z"}
              - {id: c, type: circle}
            steps:
              - {do: transform, target: a, into: b}
              - {do: transform, target: b, into: a}
              - {do: transform, target: a, into: c, style: morph}
              - {do: transform, target: c, into: a, style: fade}
    """)
    start = run_scene(doc, last_step=-1)
    for last, shown in [(0, "b"), (1, "a"), (2, "c"), (3, "a")]:
        scene = run_scene(doc, last_step=last)
        assert scene.registered_on_screen() == [shown]
    end = run_scene(doc)
    assert np.allclose(start.objects["a"].get_all_points(), end.objects["a"].get_all_points())


def test_clear_takes_everything_and_the_caption(blocks_impl):
    scene = run_scene(case_doc("clear"))
    assert scene.registered_on_screen() == []
    assert [m for m in scene.mobjects if m is not scene.frame] == []


# The code each kind of step comes to

def ctx_for(doc) -> CodegenContext:
    scene = doc.scenes[0]
    return CodegenContext(doc=doc, scene=scene, objects={obj.id: obj for obj in scene.objects})


@pytest.mark.parametrize("name, expected", [
    ("show_write", ["self.play(Write(t), run_time=1.5)"]),
    ("show_fade_up", ["self.play(FadeIn(t, shift=0.5 * UP), run_time=1)"]),
    ("show_pop", ["self.play(GrowFromCenter(d, rate_func=overshoot), run_time=0.75)"]),
    ("show_many_lagged", ["self.play(LaggedStart(ShowCreation(c, run_time=1), ShowCreation(sq, run_time=1), "
                          "ShowCreation(d, run_time=1), lag_ratio=0.5), run_time=2)"]),
    ("hide_shrink", ["self.play(ShrinkToCenter(sq, remover=True), run_time=1)"]),
    ("add", ["self.add(t, d)"]),
    ("add_held", ["self.add(d)", "self.wait(1)"]),
    ("remove", ["self.remove(u)"]),
    ("clear", ["self.play(FadeOut(self.everything_on_screen()), run_time=1)"]),
    ("transform_auto_text", ["self.play(TransformMatchingStrings(t, w), run_time=1.5)"]),
    ("transform_auto_tex", ["self.play(TransformMatchingTex(eq, eq2), run_time=1.5)"]),
    ("transform_morph", ["self.play(ReplacementTransform(c, d), run_time=1.5)"]),
    ("transform_keep", ["self.play(TransformMatchingStrings(t.copy(), w), run_time=1.5)"]),
    ("transform_keep_tex", ["self.play(TransformMatchingTex(eq.copy(), eq2), run_time=1.5)"]),
    ("transform_keep_fade", ["self.play(FadeTransform(c.copy(), d), run_time=1.5)"]),
    ("move_by", ["self.play(t.animate.shift([1, -1, 0]), run_time=1)"]),
    ("move_to_edge", ['self.play(u.animate.move_to(place(u.copy(), edge="bottom")), run_time=1)']),
    ("move_to_on_plane", ["self.play(u.animate.move_to(place(u.copy(), at=[2, 1], on=plane)), run_time=1)"]),
    ("move_to_many", ["moving = Group(t, u)",
                      'self.play(moving.animate.move_to(place(moving.copy(), edge="bottom_right")), run_time=1)']),
    ("highlight_box", ['self.play(ShowCreationThenFadeAround(t["Hello"], stroke_color=GREEN), run_time=1.5)']),
    ("highlight_underline", ["self.play(ShowCreationThenFadeOut(Underline(t, stroke_color=YELLOW)), run_time=1.5)"]),
    ("highlight_recolor", ['self.play(t["there"].animate.set_color("#FF8800"), run_time=1)']),
    ("highlight_recolor_tex", ['self.play(eq["a^2"].animate.set_color(YELLOW), run_time=1)']),
    ("wait", ["self.wait(0.5)"]),
    ("camera_focus", ["self.play(self.frame.animate.set_height(FRAME_HEIGHT / 1.5).move_to(sq), run_time=2)"]),
    ("camera_orientation_gamma", ["self.play(self.frame.animate.reorient(-30, 70, 10).set_height(FRAME_HEIGHT), run_time=2)"]),
    ("camera_reset", ["self.play(self.frame.animate.to_default_state(), run_time=2)"]),
    ("apply_matrix_plane", ["self.play(ApplyMatrixOn([[1, 1], [0, 1]], plane), ApplyMatrixOn([[1, 1], [0, 1]], v, plane), run_time=2)"]),
    ("together", ["self.play(AnimationGroup(Write(t, run_time=1.5), ShowCreation(c, run_time=2)), run_time=2)"]),
    ("together_lagged", ["self.play(LaggedStart(Write(t, run_time=1.5), AnimationGroup(ShowCreation(c, run_time=1), "
                         "ShowCreation(sq, run_time=1), run_time=1.5), ShowCreation(d, run_time=1.5), lag_ratio=0.5), run_time=3)"]),
    ("together_run_time", ["self.play(t.animate.shift([0, -1, 0]), FadeOut(u), run_time=3)"]),
    ("together_instant", ["self.add(d)", "self.remove(u)", "self.play(Indicate(t), run_time=1)"]),
    ("together_all_instant", ["self.add(d)", "self.remove(u)"]),
])
def test_step_lines(name, expected, fake_blocks):
    doc = case_doc(name)
    ctx = ctx_for(doc)
    for step in doc.scenes[0].steps[:-1]:
        step_lines(step, ctx)
    assert step_lines(doc.scenes[0].steps[-1], ctx) == expected


@pytest.mark.parametrize("name, seconds", [
    ("show_write", 1.5), ("show_auto", 1.5), ("show_fade", 1), ("show_pop", 0.75), ("show_grow_vector", 1),
    ("show_many", 1.5), ("show_many_lagged", 2), ("hide_auto", 1), ("hide_many_lagged", 2),
    ("add", 0), ("add_held", 1), ("remove", 0), ("clear", 1),
    ("transform_morph", 1.5), ("change_color", 1), ("move_by", 1),
    ("highlight_indicate", 1), ("highlight_box", 1.5), ("highlight_wiggle", 1.5), ("wait", 0.5),
    ("camera_zoom", 2), ("apply_matrix_plane", 2),
    ("together", 2), ("together_lagged", 3), ("together_run_time", 3), ("together_all_instant", 0),
])
def test_how_long_steps_take(name, seconds, fake_blocks):
    doc = case_doc(name)
    assert render.timeline(doc, "case")[-1].duration == pytest.approx(seconds)


@pytest.mark.parametrize("durations, lag", [
    ([1, 2, 3], 0), ([1, 2, 3], 0.5), ([3, 1, 1], 0.5), ([2, 2], 1), ([1.5, 0.25, 2], 0.3), ([1], 0.7),
])
def test_together_timing_is_what_animation_group_does(durations, lag):
    from manimlib import AnimationGroup, Animation, Mobject
    group = AnimationGroup(*(Animation(Mobject(), run_time=d) for d in durations), lag_ratio=lag)
    assert _together_time(durations, lag) == pytest.approx(group.max_end_time, abs=1e-3)


def test_small_pieces():
    assert num(2.0) == "2" and num(0.5) == "0.5" and num(-3) == "-3" and num(1e-7) == "1e-07"
    assert point3([1, 2]) == "[1, 2, 0]" and point3([1.5, 0, -2]) == "[1.5, 0, -2]"
    assert Anim.call("Write", "eq").text(run_time="2") == "Write(eq, run_time=2)"
    assert Anim.call("Foo").text(run_time="2") == "Foo(run_time=2)"
    assert Anim.builder("eq", ".shift(UP)").text(run_time="2") == "eq.animate(run_time=2).shift(UP)"
    assert StepCode(duration=1.5).lines() == ["self.wait(1.5)"]
    assert StepCode().lines() == []


def test_every_play_says_how_long_it_takes(fake_blocks):
    from manim_verbose.scenefile.codegen import document_to_python
    for name in STEP_CASES:
        for line in document_to_python(case_doc(name)).splitlines():
            if "self.play(" in line:
                assert line.rstrip().endswith(")") and ", run_time=" in line.rsplit(")", 2)[-2] + ")", line


def test_a_show_of_something_missing_still_has_a_time(fake_blocks):
    """A saved document may have errors in it, and still wants timings."""
    from manim_verbose.scenefile.model import Document
    doc = Document.model_validate({"scenes": [{"id": "s", "steps": [{"id": "x", "do": "show", "target": "nothing"}]}]})
    assert default_run_time(doc.scenes[0].steps[0], ctx_for(doc)) == 1


# A real render of each, small

@pytest.mark.render
@pytest.mark.parametrize("name", sorted(STEP_CASES))
def test_every_step_renders_for_as_long_as_its_timeline_and_ends_on_its_still(name, blocks_impl, tmp_path,
                                                                              render_cache, lossless):
    doc = case_doc(name)
    total = render.scene_duration(doc, "case")
    clip = render.render_clip(doc, "case", tmp_path / "clip.mp4", quality="hd")
    frames = video_frames(clip)
    assert len(frames) == max(1, int(np.floor(total * 15 + 0.5 + 1e-9)))
    still = render.render_still(doc, "case", len(doc.scenes[0].steps) - 1, tmp_path / "still.png", width=256)
    last = frames[-1]
    reference = image(still.path)
    worst, mean = difference(reference, last)
    assert away_from_edges(reference, last) == 0, (worst, mean)
    assert mean < 1.0, (worst, mean)


# Random documents

from hypothesis import HealthCheck, assume, given, settings, strategies as st  # noqa: E402

WORDS = ["alpha", "beta", "gamma", "delta"]
COLORS = ["RED", "BLUE", "YELLOW", "#FF8800"]
MATRICES = [[[1, 1], [0, 1]], [[2, 0], [0, 1]], [[0, -1], [1, 0]], [[1, 0], [0.5, 1]]]
coord = st.sampled_from([-3, -1.5, 0, 1, 2.5])
placements = st.one_of(
    st.sampled_from(["top", "bottom", "left", "right", "top_left", "bottom_right", "center"]),
    st.lists(coord, min_size=2, max_size=2),
)
run_times = st.one_of(st.none(), st.sampled_from([0.25, 0.37, 1, 1.5]))
captions = st.one_of(st.none(), st.none(), st.sampled_from(["", "Some words", "Other words"]))


@st.composite
def random_documents(draw):
    """A small valid scene: a few objects of kinds needing no LaTeX, and a few steps of any kind on them."""
    objects = []
    for i in range(draw(st.integers(1, 4))):
        kind = draw(st.sampled_from(["text", "circle", "square", "dot"]))
        obj = {"id": f"o{i}", "type": kind, "shown": draw(st.booleans())}
        if kind == "text":
            obj["text"] = " ".join(draw(st.lists(st.sampled_from(WORDS), min_size=1, max_size=2, unique=True)))
        if kind == "dot":
            obj["point"] = [draw(coord), draw(coord)]
        elif draw(st.booleans()):
            obj["place"] = draw(placements)
        if draw(st.booleans()):
            obj["color"] = draw(st.sampled_from(COLORS))
        objects.append(obj)
    leaves = [obj["id"] for obj in objects]
    if len(leaves) >= 2 and draw(st.booleans()):
        members = draw(st.lists(st.sampled_from(leaves), min_size=2, max_size=2, unique=True))
        objects.append({"id": "grp", "type": "group", "members": members,
                        "arrange": draw(st.sampled_from(["none", "row", "column"]))})
    if draw(st.booleans()):
        objects.append({"id": "plane", "type": "number_plane", "shown": draw(st.booleans())})
        objects.append({"id": "vec", "type": "vector", "on": "plane", "tip": [draw(coord) or 1, draw(coord)]})
    steps = draw(st.lists(random_step(objects), max_size=6))
    return {"settings": {"resolution": [256, 144], "fps": 15}, "scenes": [{"id": "s", "objects": objects, "steps": steps}]}


def random_step(objects, inside_together: bool = False):
    by_id = {obj["id"]: obj for obj in objects}
    ids = list(by_id)

    def leaves(obj_id):
        obj = by_id[obj_id]
        return {m for member in obj.get("members", []) for m in leaves(member)} if obj["type"] == "group" else {obj_id}

    @st.composite
    def step(draw):
        kinds = ["show", "hide", "add", "remove", "change", "move", "highlight", "camera", "apply_matrix"]
        if not inside_together:
            kinds += ["clear", "wait", "together"] + (["transform"] if len(ids) >= 2 else [])
        kind = draw(st.sampled_from(kinds))
        some = st.lists(st.sampled_from(ids), min_size=1, max_size=2, unique=True)
        one = st.sampled_from(ids)
        out: dict = {"do": kind}
        if kind == "show":
            out.update(target=draw(some), style=draw(st.sampled_from(["auto", "fade", "fade_up", "grow", "pop", "draw"])),
                       lag=draw(st.sampled_from([0, 0.5])))
        elif kind == "hide":
            out.update(target=draw(some), style=draw(st.sampled_from(["auto", "fade", "fade_down", "uncreate", "shrink"])))
        elif kind in ("add", "remove"):
            out.update(target=draw(some))
        elif kind == "transform":
            a, b = draw(st.lists(st.sampled_from(ids), min_size=2, max_size=2, unique=True))
            assume(not (leaves(a) & leaves(b)))
            out.update(target=a, into=b, style=draw(st.sampled_from(["auto", "morph", "match", "fade"])),
                       keep=draw(st.booleans()))
        elif kind == "change":
            target = draw(one)
            obj = by_id[target]
            options = [{"color": draw(st.sampled_from(COLORS))}]
            if obj["type"] == "circle":
                options.append({"radius": draw(st.sampled_from([0.5, 2]))})
            if obj["type"] == "text":
                options.append({"text": draw(st.sampled_from(WORDS))})
            if obj["type"] == "group":
                options.append({"arrange": draw(st.sampled_from(["row", "column"]))})
            if obj["type"] == "vector":
                options.append({"tip": [draw(coord), draw(coord) or 1]})
            out.update(target=target, set=draw(st.sampled_from(options)))
        elif kind == "move":
            if draw(st.booleans()):
                out.update(target=draw(some), by=[draw(coord), draw(coord)])
            else:
                out.update(target=draw(some), to=draw(placements))
        elif kind == "highlight":
            target = draw(one)
            out.update(target=target, style=draw(st.sampled_from(["indicate", "flash", "box", "underline", "wiggle", "recolor"])))
            if by_id[target]["type"] == "text" and draw(st.booleans()):
                out["part"] = draw(st.sampled_from(by_id[target]["text"].split()))
        elif kind == "wait":
            out["duration"] = draw(st.sampled_from([0.2, 1]))
        elif kind == "camera":
            out.update(draw(st.sampled_from([{"zoom": 2}, {"center": [1, 1]}, {"reset": True}, {"zoom": 1.5, "focus": ids[0]},
                                             {"orientation": [-20, 60]}])))
        elif kind == "apply_matrix":
            out.update(target=draw(some), matrix=draw(st.sampled_from(MATRICES)))
        elif kind == "together":
            # Each step inside on different objects, so that none of them undoes another
            inner = draw(st.lists(random_step(objects, inside_together=True), min_size=2, max_size=3))
            touched = [set(leaves(t)) for s in inner for t in ([s["target"]] if isinstance(s.get("target"), str) else s.get("target", []))]
            assume(sum(len(t) for t in touched) == len(set().union(*touched)) if touched else True)
            out.update(steps=inner, lag=draw(st.sampled_from([0, 0.5])))
        if kind not in ("wait", "together", "add", "remove") and not inside_together:
            run_time = draw(run_times)
            if run_time is not None:
                out["run_time"] = run_time
        caption = draw(captions)
        if caption is not None and not inside_together:
            out["caption"] = caption
        return out

    return step()


def expected_after(doc) -> set[str]:
    """What the format says is on screen after every step, worked out without manim."""
    scene = doc.scenes[0]
    by_id = {obj.id: obj for obj in scene.objects}

    def leaves(obj_id):
        obj = by_id[obj_id]
        return {m for member in obj.members for m in leaves(member)} if obj.type == "group" else {obj_id}

    def targets(step):
        return [step.target] if isinstance(step.target, str) else list(step.target)

    def apply(step, shown):
        if step.do in ("show", "add"):
            return shown | {leaf for t in targets(step) for leaf in leaves(t)}
        if step.do in ("hide", "remove"):
            return shown - {leaf for t in targets(step) for leaf in leaves(t)}
        if step.do == "clear":
            return set()
        if step.do == "transform":
            return (shown if step.keep else shown - leaves(step.target)) | leaves(step.into)
        if step.do == "together":
            for inner in step.steps:
                shown = apply(inner, shown)
        return shown

    shown = {leaf for obj in scene.objects if obj.shown for leaf in leaves(obj.id)}
    for step in scene.steps:
        shown = apply(step, shown)
    return {obj_id for obj_id in by_id if leaves(obj_id) <= shown and leaves(obj_id)}


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture,
                                                                   HealthCheck.too_slow, HealthCheck.filter_too_much])
@given(data=random_documents())
def test_random_documents_compile_run_and_leave_what_the_format_says(data, fake_blocks):
    from manim_verbose.scenefile.codegen import document_to_python
    from manim_verbose.scenefile.validate import has_errors, validate_data, assign_step_ids
    doc, problems = validate_data(data)
    assume(doc is not None and not has_errors(problems))
    assign_step_ids(doc)
    compile(document_to_python(doc), "random.py", "exec")
    scene = run_scene(doc)
    assert set(scene.registered_on_screen()) == expected_after(doc)
    assert stray_mobjects(scene) == []
    timings = render.timeline(doc, "s")
    assert [r.duration for r in scene.step_records] == pytest.approx([t.duration for t in timings])


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture,
                                                                   HealthCheck.too_slow, HealthCheck.filter_too_much])
@given(data=random_documents())
def test_random_documents_come_to_as_many_frames_as_their_timeline(data, fake_blocks):
    from manim_verbose.scenefile.runtime import RenderPlan, _frame_at
    from manim_verbose.scenefile.validate import has_errors, validate_data, assign_step_ids
    doc, problems = validate_data(data)
    assume(doc is not None and not has_errors(problems))
    assign_step_ids(doc)
    job = render.prepare_job(doc, "s")
    scene = render.run_job(job, RenderPlan(headless=True), 256, 144, 15)
    assert scene.frames_emitted == _frame_at(render.scene_duration(doc, "s"), 15)
