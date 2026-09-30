"""
The layout checker (scenefile/layout_check.py): things off the frame, under the captions, or
colliding, found by building scenes without drawing them. Every rule is tried both ways, and
every exemption from the collision rule has a case which would be reported without it.

Nothing here draws a pixel, so none of it needs a graphics device. Tests which typeset
formulas (tex, labels, braces) need LaTeX, and are marked render as the other tests needing
it are, since CI's fast job has no LaTeX; the rest use plain text. The run over the ten
minute example is marked slow as well.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from steps_helpers import doc_from, render_cache, run_scene  # noqa: F401  (render_cache is a fixture)

from manim_verbose.scenefile import layout_check
from manim_verbose.scenefile.cli import main as cli_main
from manim_verbose.scenefile.files import load_file
from manim_verbose.scenefile.layout_check import (
    EXEMPTIONS, caption_band, caption_words_size, check_document_layout, check_layout, check_scene,
)
from manim_verbose.scenefile.render import RenderError

EXAMPLE = Path(__file__).parents[2] / "examples" / "eola_vectors" / "vectors.yaml"


@pytest.fixture(autouse=True)
def fresh_memory():
    """Each test starts with nothing remembered in this process, so that it sees its own checks."""
    layout_check.clear_memory_cache()
    yield
    layout_check.clear_memory_cache()


def found(yaml_text: str, scene_id: str | None = None):
    doc = doc_from(yaml_text)
    return check_scene(doc, scene_id or doc.scenes[0].id)


def messages(yaml_text: str, scene_id: str | None = None) -> list[str]:
    return [p.message for p in found(yaml_text, scene_id)]


# Off the frame

def test_text_running_off_the_right_edge_is_reported_on_its_placement():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello world, place: [7, 0]}
            steps:
              - {id: s1, do: show, target: t}
              - {id: s2, do: wait}
        """)
    assert len(problems) == 1
    problem = problems[0]
    assert problem.message == "After steps 1 to 2 ('s1' to 's2'), 't' runs off the right edge of the frame"
    assert problem.severity == "warning"
    assert problem.loc == ["scenes", 0, "objects", 0, "place"]
    assert (problem.scene_id, problem.item_id) == ("s", "t")
    assert problem.to_json()["path"] == "scenes[0].objects[0].place"


@pytest.mark.parametrize("place, words", [
    ("[0, 6]", "'t' is entirely off the frame"),
    ("[-8, 0]", "'t' runs off the left edge of the frame"),
    ("[0, -4]", "'t' runs off the bottom edge of the frame"),
    ("[6.9, 3.9]", "'t' runs off the top and right edges of the frame"),
])
def test_every_way_off_the_frame_is_named(place, words):
    assert messages(f"""
        scenes:
          - id: s
            objects:
              - {{id: t, type: text, text: Hello world, place: {place}, shown: true}}
        """) == [f"At the start of the scene, {words}"]


@pytest.mark.parametrize("place", ["top", "bottom_left", "top_right", "left", "[0, 0]", "[5, -3]"])
def test_text_inside_the_frame_is_fine(place):
    assert messages(f"""
        scenes:
          - id: s
            objects:
              - {{id: t, type: text, text: Hello world, place: {place}, shown: true}}
            steps:
              - {{do: wait}}
        """) == []


def test_a_little_past_the_edge_is_within_tolerance():
    # The frame runs to x = 7.111; the first line reaches 0.03 past it, the second 0.3
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: near, type: line, start: [-7.14, 0], end: [0, 0], shown: true}
              - {id: far, type: line, start: [-7.4, 1], end: [0, 1], shown: true}
        """)
    assert [(p.item_id, p.message) for p in problems] == [
        ("far", "At the start of the scene, 'far' runs off the left edge of the frame"),
    ]
    # A plotted object has no placement to blame
    assert problems[0].loc == ["scenes", 0, "objects", 1]


def test_a_portrait_frame_is_narrower():
    doc = """
        settings: {{resolution: [1080, 1920], fps: 15}}
        scenes:
          - id: s
            objects:
              - {{id: t, type: text, text: Hello, place: {place}, shown: true}}
        """
    assert messages(doc.format(place="[1.5, 0]")) == []
    assert messages(doc.format(place="[2, 0]")) == ["At the start of the scene, 't' runs off the right edge of the frame"]


def test_number_planes_run_past_the_frame_on_purpose():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: plane, type: number_plane, x_range: [-12, 12, 1], y_range: [-8, 8, 1], shown: true}
        """) == []


def test_axes_are_held_to_the_frame_until_the_camera_moves():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: ax, type: axes, x_range: [-10, 10, 1], shown: true}
            steps:
              - {id: s1, do: wait}
              - {id: s2, do: camera, zoom: 2}
              - {id: s3, do: camera, reset: true}
        """)
    assert [p.message for p in problems] == [
        "From the start of the scene through step 1 ('s1'), 'ax' runs off the left and right edges of the frame",
        "After step 3 ('s3'), 'ax' runs off the left and right edges of the frame",
    ]


def test_a_camera_zoom_takes_things_off_the_frame():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: l, type: line, start: [2, 0], end: [5, 0], shown: true}
              - {id: t, type: text, text: far, place: [6, 2], shown: true}
            steps:
              - {id: s1, do: wait}
              - {id: zoom, do: camera, zoom: 2}
        """)
    assert [(p.item_id, p.message) for p in problems] == [
        ("l", "After step 2 ('zoom'), 'l' runs off the right edge of the frame"),
        ("t", "After step 2 ('zoom'), 't' is entirely off the frame"),
    ]
    # The camera moved it off, not its placement
    assert problems[1].loc == ["scenes", 0, "objects", 1]


def test_a_camera_move_takes_things_off_the_frame():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: l, type: line, start: [-6, 0], end: [-3, 0], shown: true}
            steps:
              - {id: pan, do: camera, center: [3, 0]}
        """) == ["After step 1 ('pan'), 'l' runs off the left edge of the frame"]


def test_fixed_objects_stay_on_the_screen_whatever_the_camera_does():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: l, type: line, start: [2, 0], end: [5, 0], fixed: true, shown: true}
              - {id: t, type: text, text: label, place: [5, 3], fixed: true, shown: true}
            steps:
              - {id: zoom, do: camera, zoom: 2, center: [-2, -1]}
              - {id: turn, do: camera, orientation: [-30, 70]}
        """) == []


def test_a_turned_3d_camera_is_projected_and_its_axes_left_alone():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: axes3, type: axes_3d, y_range: [-3, 3, 1], z_range: [-8, 8, 1], shown: true}
              - {id: up, type: line, on: axes3, start: [0, 0, 0], end: [0, 0, 7], shown: true}
              - {id: low, type: line, start: [-1, 0, 0], end: [1, 0, 0], shown: true}
            steps:
              - {id: turn, do: camera, orientation: [-30, 70]}
        """)
    # Looked at from above, the line up the z axis is a point; turned, it reaches off the top
    assert [p.message for p in problems] == ["After step 1 ('turn'), 'up' runs off the top edge of the frame"]


def test_moving_something_off_the_frame_and_back_is_one_problem_per_stretch():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello, place: [0, 2], shown: true}
            steps:
              - {id: out, do: move, target: t, by: [10, 0]}
              - {id: still_out, do: wait}
              - {id: back, do: move, target: t, by: [-10, 0]}
              - {id: out_again, do: move, target: t, to: [7, 2]}
        """)
    assert [p.message for p in problems] == [
        "After steps 1 to 2 ('out' to 'still_out'), 't' is entirely off the frame",
        "After step 4 ('out_again'), 't' runs off the right edge of the frame",
    ]
    # Moved there by a step, so its placement isn't what to fix
    assert all(p.loc == ["scenes", 0, "objects", 0] for p in problems)


def test_edges_run_off_over_a_stretch_are_named_together():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello, place: [6.9, 0], shown: true}
            steps:
              - {id: s1, do: move, target: t, by: [0, 3.9]}
        """) == ["From the start of the scene through step 1 ('s1'), 't' runs off the top and right edges of the frame"]


# Under the captions

CAPTIONED = """
    scenes:
      - id: s
        objects:
          - {{id: t, type: text, text: Hello world, place: {place}, shown: true}}
        steps:
          - {{id: s1, do: wait, caption: {caption}}}
          - {{id: s2, do: wait, caption: ""}}
    """


def test_text_under_the_caption_is_reported_while_the_caption_shows():
    problems = found(CAPTIONED.format(place="[0, -3.7]", caption="Something to read"))
    assert [p.message for p in problems] == ["After step 1 ('s1'), 't' is under the caption at the bottom of the frame"]
    assert problems[0].loc == ["scenes", 0, "objects", 0, "place"]


def test_without_a_caption_the_bottom_of_the_frame_is_free():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello world, place: [0, -3.7], shown: true}
            steps:
              - {do: wait}
        """) == []


def test_text_above_the_band_is_fine():
    assert messages(CAPTIONED.format(place="[0, -2.9]", caption="Something to read")) == []


def test_a_long_caption_makes_a_taller_band():
    line = """
        scenes:
          - id: s
            objects:
              - {{id: l, type: line, start: [-2, -3.1], end: [2, -3.1], shown: true}}
            steps:
              - {{id: s1, do: wait, caption: {caption}}}
        """
    assert messages(line.format(caption="One short line")) == []
    long_caption = "This caption goes on and on, far too long to fit on one line, and so it wraps " * 2
    assert messages(line.format(caption=json.dumps(long_caption))) == [
        "After step 1 ('s1'), 'l' is under the caption at the bottom of the frame",
    ]


def test_captions_at_the_top_guard_the_top():
    doc = """
        settings: {{resolution: [256, 144], fps: 15, captions: {{edge: top}}}}
        scenes:
          - id: s
            objects:
              - {{id: t, type: text, text: Hello world, place: {place}, shown: true}}
            steps:
              - {{id: s1, do: wait, caption: Read me}}
        """
    assert messages(doc.format(place="top")) == ["After step 1 ('s1'), 't' is under the caption at the top of the frame"]
    assert messages(doc.format(place="[0, -3.7]")) == []


def test_captions_without_a_background_cover_only_their_words():
    doc = """
        settings: {{resolution: [256, 144], fps: 15, captions: {{background: false}}}}
        scenes:
          - id: s
            objects:
              - {{id: t, type: text, text: Aside, place: {place}, shown: true}}
            steps:
              - {{id: s1, do: wait, caption: Hi}}
        """
    assert messages(doc.format(place="[-5.5, -3.6]")) == []
    assert messages(doc.format(place="[0, -3.6]")) == [
        "After step 1 ('s1'), 't' is under the caption at the bottom of the frame",
    ]


def test_captions_come_and_go_with_clears():
    """A clear takes the caption with it; one given to the clear, or a later step, brings the band back."""
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Low down, place: [0, -3.7]}
              - {id: u, type: text, text: Low again, place: [0, -3.7]}
            steps:
              - {id: s1, do: show, target: t, caption: First words}
              - {id: s2, do: clear}
              - {id: s3, do: show, target: u}
              - {id: s4, do: wait, caption: Back again}
              - {id: s5, do: clear, caption: Kept through the clear}
              - {id: s6, do: show, target: t}
        """)
    assert [p.message for p in problems] == [
        "After step 1 ('s1'), 't' is under the caption at the bottom of the frame",
        "After step 4 ('s4'), 'u' is under the caption at the bottom of the frame",
        "After step 6 ('s6'), 't' is under the caption at the bottom of the frame",
    ]


def test_coordinate_systems_sit_under_captions():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: ax, type: axes, y_range: [-3.9, 3.9, 1], shown: true}
              - {id: nl, type: number_line, place: [0, -3.3], shown: true}
            steps:
              - {do: wait, caption: Something to read over the grid}
        """) == []


@pytest.mark.parametrize("settings, text", [
    ({}, "A short caption"),
    ({"font": "CMU Serif"}, "Two lines of caption: the second begins about here, once the first has run out of room"),
    ({"captions": {"font_size": 40, "edge": "top"}}, "A bigger caption at the top"),
    ({"captions": {"background": False}}, "No band behind these words"),
    ({"captions": {"background": False, "edge": "top"}}, "Words alone at the top, gjpqy"),
    ({"resolution": [144, 256]}, "A portrait frame is narrower, so this caption wraps sooner than it would"),
])
def test_the_band_is_where_the_real_caption_is(settings, text):
    """The band is measured without building the caption; it has to match the one a render builds."""
    doc = doc_from(f"""
        settings: {json.dumps({"resolution": [256, 144], "fps": 15, **settings})}
        scenes:
          - id: s
            steps:
              - {{do: wait, caption: {json.dumps(text)}}}
        """)
    scene = run_scene(doc)
    pieces = scene._caption
    # The band behind the words, or the words alone
    (x0, y0, _), _, (x1, y1, _) = pieces[0].get_bounding_box()
    band = caption_band(text, scene.caption_style, scene.frame_width)
    room = 0 if len(pieces) == 2 else 0.1
    assert band.box == pytest.approx((x0 - room, y0 - room, x1 + room, y1 + room), abs=1e-3)


def test_words_are_measured_as_manim_would_build_them():
    from manimlib.mobject.svg.text_mobject import Text
    for text, size, width in [("Hello there", 30, 12.7), ("A caption, with commas; and gjpqy", 24, 12.7),
                              ("Wrapped " * 20, 30, 12.7), ("Line one\nline two", 36, 6)]:
        real = Text(text, font_size=size, alignment="CENTER", line_width=width)
        assert caption_words_size(text, size, width) == pytest.approx((real.get_width(), real.get_height()), abs=1e-6)


def test_the_quick_svg_measure_agrees_with_the_thorough_one():
    svg = layout_check._caption_svg("Measure me, twice: gjpqy AVAW", 30, 12.7)
    assert layout_check._svg_extent(svg) == pytest.approx(layout_check._svg_extent_slowly(svg), abs=1e-6)


# Collisions

def test_text_on_text_is_reported_on_whichever_came_last():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, place: [0, 0]}
              - {id: b, type: text, text: Another text, place: [0.3, 0.1]}
            steps:
              - {id: s1, do: show, target: b}
              - {id: s2, do: show, target: a}
        """)
    assert [(p.item_id, p.message) for p in problems] == [("a", "After step 2 ('s2'), 'a' and 'b' overlap")]
    assert problems[0].loc == ["scenes", 0, "objects", 0, "place"]


def test_text_apart_or_just_touching_is_fine():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, shown: true}
              - {id: b, type: text, text: Above it, place: [0, 1], shown: true}
              - {id: c, type: text, text: Touching, place: {next_to: a, side: right, buff: 0}, shown: true}
              - {id: d, type: text, text: just below, font_size: 30, place: {next_to: a, side: down, buff: 0.05}, shown: true}
        """) == []


def test_a_line_through_text_crosses_it():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello world, shown: true}
              - {id: l, type: line, start: [-3, 0], end: [3, 0]}
            steps:
              - {id: s1, do: show, target: l}
        """) == ["After step 1 ('s1'), 'l' crosses 't'"]


def test_a_line_passing_by_text_is_fine():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hello world, shown: true}
              - {id: under, type: line, start: [-3, -0.45], end: [3, -0.45], shown: true}
              - {id: beside, type: vector, tail: [1.7, -1], tip: [1.7, 1], shown: true}
        """) == []


def test_only_the_arrow_counts_not_the_box_around_it():
    """A slanting vector's bounding box covers a lot it doesn't draw on."""
    doc = """
        scenes:
          - id: s
            objects:
              - {{id: v, type: vector, tip: [4, 3], shown: true}}
              - {{id: t, type: text, text: note, place: {place}, shown: true}}
        """
    assert messages(doc.format(place="[3, 0.6]")) == []
    assert messages(doc.format(place="[2, 1.5]")) == ["At the start of the scene, 'v' crosses 't'"]


def test_a_titles_underline_is_a_line():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: title, type: title, text: A heading, shown: true}
              - {id: sub, type: text, text: pushed up into it, font_size: 36, place: {next_to: title, shift: [0, 0.3]}}
            steps:
              - {id: s1, do: show, target: sub}
        """)
    assert [(p.item_id, p.message) for p in problems] == [("sub", "After step 1 ('s1'), 'title' crosses 'sub'")]


def test_a_fill_drawn_over_text_covers_it():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hidden, shown: true}
              - {id: sq, type: square, side: 4, fill: BLUE, fill_opacity: 1}
            steps:
              - {id: s1, do: show, target: sq}
        """) == ["After step 1 ('s1'), 'sq' covers 't'"]


def test_a_picture_drawn_over_text_covers_it(tmp_path):
    from PIL import Image
    Image.new("RGB", (40, 20), "red").save(tmp_path / "red.png")
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Hidden, shown: true}
              - {id: pic, type: image, path: red.png, height: 2}
              - {id: aside, type: image, path: red.png, height: 1, place: [-5, 2]}
            steps:
              - {id: s1, do: show, target: [pic, aside]}
        """)
    assert [p.message for p in check_scene(doc, "s", tmp_path)] == ["After step 1 ('s1'), 'pic' covers 't'"]


def test_text_on_a_shape_drawn_beneath_it_is_fine_when_it_fits():
    doc = """
        scenes:
          - id: s
            objects:
              - {{id: card, type: rectangle, width: {width}, height: 1.5, fill: BLUE_E, fill_opacity: 1, shown: true}}
              - {{id: t, type: text, text: On a card}}
            steps:
              - {{id: s1, do: show, target: t}}
        """
    assert messages(doc.format(width=5)) == []
    # Sticking out of it, the card's edge runs through the words
    assert messages(doc.format(width=1)) == ["After step 1 ('s1'), 'card' crosses 't'"]


def test_shapes_meeting_shapes_are_left_alone():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: c1, type: circle, radius: 1, fill: BLUE, fill_opacity: 1, shown: true}
              - {id: c2, type: circle, radius: 1, place: [0.5, 0], shown: true}
              - {id: v, type: vector, tip: [2, 1], shown: true}
              - {id: w, type: vector, tail: [2, 1], tip: [3, -1], shown: true}
              - {id: tip, type: dot, point: [2, 1], shown: true}
              - {id: cross, type: line, start: [-2, -2], end: [2, 2], shown: true}
        """) == []


def test_text_hardly_visible_doesnt_collide():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, shown: true}
              - {id: b, type: text, text: Hello again, place: [0.2, 0], shown: true}
            steps:
              - {id: s1, do: change, target: b, set: {opacity: 0}}
        """) == ["At the start of the scene, 'a' and 'b' overlap"]


def test_members_of_a_group_are_checked_against_each_other():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: First, shown: true}
              - {id: b, type: text, text: Second, place: [0.2, 0], shown: true}
              - {id: both, type: group, members: [a, b]}
        """)
    assert [p.message for p in problems] == ["At the start of the scene, 'a' and 'b' overlap"]


# What isn't a collision (every exemption has a case which would be one without it)

def test_every_exemption_has_a_reason():
    assert [e.name for e in EXEMPTIONS] == ["background", "group", "annotation", "label", "transform", "layered"]
    assert all(e.reason for e in EXEMPTIONS)


def test_backgrounds_are_drawn_on():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: plane, type: number_plane, numbers: true, shown: true}
              - {id: ax, type: axes, shown: true}
              - {id: nl, type: number_line, place: [0, -2], shown: true}
              - {id: t, type: text, text: On the grid, place: [1, 0], shown: true}
              - {id: u, type: text, text: "x = 3", place: [0, -2], shown: true}
        """) == []


def test_a_group_and_its_own_backdrop_are_one_thing():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: First line}
              - {id: b, type: text, text: Second line}
              - {id: both, type: group, members: [a, b], arrange: column, backdrop: true}
              - {id: other, type: text, text: Elsewhere, place: [0, 2.5]}
            steps:
              - {do: show, target: [both, other]}
        """) == []


def test_a_group_backdrop_over_something_else_covers_it():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: under, type: text, text: Underneath, place: [0, -0.15], shown: true}
              - {id: a, type: text, text: First line}
              - {id: b, type: text, text: Second line}
              - {id: both, type: group, members: [a, b], arrange: column, backdrop: true, place: [0, -1]}
            steps:
              - {id: s1, do: show, target: both}
        """) == ["After step 1 ('s1'), 'both' covers 'under'"]


def test_boxes_go_around_their_targets():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: eq, type: text, text: "a + b = c", place: [2, 2], shown: true}
              - {id: box, type: box, target: eq, fill_opacity: 0.5, buff: 0}
              - {id: a, type: text, text: One, place: [-3, 2]}
              - {id: b, type: text, text: Two, place: [-3, 1.4]}
              - {id: pair, type: group, members: [a, b]}
              - {id: around, type: box, target: pair, fill_opacity: 1, buff: 0}
            steps:
              - {do: show, target: [box, a, b, around]}
        """) == []
    # The same box over text it isn't around covers it
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: eq, type: text, text: "a + b = c", shown: true}
              - {id: other, type: text, text: "above", font_size: 30, place: [0, 0.5], shown: true}
              - {id: box, type: box, target: eq, fill_opacity: 1, buff: 0.3}
            steps:
              - {id: s1, do: show, target: box}
        """) == ["After step 1 ('s1'), 'box' covers 'other'"]


@pytest.mark.render  # braces and formulas need LaTeX
def test_braces_go_beside_their_targets():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: eq, type: tex, tex: "a^2 + b^2 = c^2", shown: true}
              - {id: brace, type: brace, target: eq, part: "c^2", label: "hyp", buff: 0}
              - {id: whole, type: brace, target: eq, side: up, label: "\\text{all of it}", buff: 0}
            steps:
              - {do: show, target: [brace, whole]}
        """) == []
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: eq, type: tex, tex: "a^2 + b^2 = c^2", shown: true}
              - {id: below, type: text, text: in the way, font_size: 30, place: [0, -0.45], shown: true}
              - {id: brace, type: brace, target: eq, buff: 0}
            steps:
              - {id: s1, do: show, target: brace}
        """) == ["After step 1 ('s1'), 'below' and 'brace' overlap"]


def test_a_label_beside_a_shape_is_its_label():
    doc = """
        scenes:
          - id: s
            objects:
              - {{id: v, type: vector, tail: [-2, 0], tip: [2, 0], shown: true}}
              - {{id: t, type: text, text: label, place: {place}, shown: true}}
        """
    # Tucked beside the tip, over the shaft: placed there on purpose
    assert messages(doc.format(place="{next_to: v, anchor: tip, side: left, buff: 0}")) == []
    # The same spot, not placed beside it, is a collision
    assert messages(doc.format(place="[1.4, 0]")) == ["At the start of the scene, 'v' crosses 't'"]


@pytest.mark.render  # a vector's own label is a formula
def test_a_label_beside_a_shape_still_collides_with_its_text():
    """Beside a shape, but over the shape's own label: a label may touch lines, not text."""
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: v, type: vector, tail: [-2, 0], tip: [2, 0], label: "\\\\vec{v}", shown: true}
              - {id: t, type: text, text: label, place: {next_to: v, anchor: tip, side: right, shift: [-0.4, 0]}, shown: true}
        """) == ["At the start of the scene, 'v' and 't' overlap"]


def test_text_beside_text_is_still_checked():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, shown: true}
              - {id: b, type: text, text: pushed back, place: {next_to: a, side: right, shift: [-1.5, 0]}, shown: true}
        """) == ["At the start of the scene, 'a' and 'b' overlap"]


def test_what_a_transform_turns_into_is_the_same_thing():
    doc = """
        scenes:
          - id: s
            objects:
              - {{id: a, type: text, text: "x + y", shown: true}}
              - {{id: b, type: text, text: "x + y + z", place: [0.1, 0]}}
            steps:
              - {{id: s1, do: {step}}}
        """
    assert messages(doc.format(step="transform, target: a, into: b, keep: dim")) == []
    assert messages(doc.format(step="show, target: b")) == ["After step 1 ('s1'), 'a' and 'b' overlap"]


def test_layering_with_z_is_on_purpose():
    doc = """
        scenes:
          - id: s
            objects:
              - {{id: panel, type: rectangle, width: 1, height: 1, fill: BLACK, fill_opacity: 0.8, z: {z}, shown: true}}
              - {{id: t, type: text, text: In front of it, z: 1, shown: true}}
        """
    assert messages(doc.format(z=-1)) == []
    assert messages(doc.format(z=1)) == ["At the start of the scene, 'panel' crosses 't'"]


@pytest.mark.render  # labels and formulas need LaTeX
def test_an_objects_own_label_is_part_of_it():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: v, type: vector, tail: [-2, 0], tip: [2, 0], label: "\\\\vec{v}", label_side: left, show_coordinates: true, shown: true}
              - {id: d, type: dot, point: [0, 2], label: "P", label_side: down, radius: 0.3, shown: true}
              - {id: g, type: graph, on: ax, function: "x**2 / 4", label: "f", shown: true}
              - {id: ax, type: axes, x_range: [-3, 3, 1], y_range: [-1, 1, 1], place: [0, -2.5]}
        """) == []


@pytest.mark.render  # labels and formulas need LaTeX
def test_an_objects_own_label_still_collides_with_others():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: v, type: vector, tail: [-2, 0], tip: [2, 0], label: "\\\\vec{v}", shown: true}
              - {id: t, type: text, text: Other, place: [2.55, 0], shown: true}
        """) == ["At the start of the scene, 'v' and 't' overlap"]


# Reporting

def test_a_collision_lasting_several_steps_is_reported_once():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, shown: true}
              - {id: b, type: text, text: Right on top, place: [0.2, 0]}
            steps:
              - {id: s1, do: show, target: b}
              - {id: s2, do: wait}
              - {id: s3, do: wait, caption: Still there}
              - {id: s4, do: hide, target: b}
              - {id: s5, do: show, target: b}
        """)
    assert [p.message for p in problems] == [
        "After steps 1 to 3 ('s1' to 's3'), 'a' and 'b' overlap",
        "After step 5 ('s5'), 'a' and 'b' overlap",
    ]
    assert {p.item_id for p in problems} == {"b"}


def test_whoever_moved_last_is_blamed():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello world, shown: true}
              - {id: b, type: text, text: Below, place: [0, -2], shown: true}
            steps:
              - {id: s1, do: move, target: a, by: [0, -2]}
        """)
    assert [(p.item_id, p.loc, p.message) for p in problems] == [
        ("a", ["scenes", 0, "objects", 0], "After step 1 ('s1'), 'a' and 'b' overlap"),
    ]


def test_moving_a_group_moves_its_members_off_their_placements():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: a, type: text, text: Hello, place: [0, 2]}
              - {id: g, type: group, members: [a], shown: true}
            steps:
              - {id: s1, do: wait}
              - {id: s2, do: move, target: g, by: [0, 3]}
        """)
    assert [(p.loc, p.message) for p in problems] == [
        (["scenes", 0, "objects", 0], "After step 2 ('s2'), 'a' is entirely off the frame"),
    ]


def test_problems_come_in_the_order_they_happen():
    problems = found("""
        scenes:
          - id: s
            objects:
              - {id: late, type: text, text: Late, place: [9, 0]}
              - {id: early, type: text, text: Early, place: [0, -9]}
            steps:
              - {id: s1, do: show, target: early}
              - {id: s2, do: show, target: late}
        """)
    assert [p.item_id for p in problems] == ["early", "late"]


def test_a_scene_with_no_steps_is_looked_at_once():
    assert messages("""
        scenes:
          - id: s
            objects:
              - {id: t, type: text, text: Off, place: [9, 0], shown: true}
        """) == ["At the start of the scene, 't' is entirely off the frame"]


# Carried objects

def carry_supported() -> bool:
    """Whether codegen gives a scene the objects its `carry` names yet (being built in parallel)."""
    doc = doc_from("""
        scenes:
          - id: a
            objects: [{id: x, type: text, text: Hi, shown: true}]
          - id: b
            carry: [x]
            steps: [{do: wait}]
        """)
    from manim_verbose.scenefile.codegen import generate_module
    code = generate_module(doc, scene_ids=["b"]).code
    return '"x"' in code


def test_a_carried_object_is_checked_and_reported_on_its_carry_entry():
    if not carry_supported():
        pytest.skip("codegen doesn't carry objects between scenes yet")
    problems = found("""
        scenes:
          - id: a
            objects:
              - {id: plane, type: number_plane, shown: true}
              - {id: t, type: text, text: Carried along, place: [0, 2], shown: true}
            steps: [{do: wait}]
          - id: b
            carry: [plane, t]
            objects:
              - {id: u, type: text, text: New here, place: [0.3, 2]}
            steps:
              - {id: b1, do: move, target: t, by: [9, 0]}
              - {id: b2, do: move, target: t, by: [-9, 0]}
              - {id: b3, do: show, target: u}
        """, "b")
    assert [(p.loc, p.item_id, p.message) for p in problems] == [
        (["scenes", 1, "carry", 1], "t", "After step 1 ('b1'), 't' is entirely off the frame"),
        (["scenes", 1, "objects", 0, "place"], "u", "After step 3 ('b3'), 't' and 'u' overlap"),
    ]


def test_carried_objects_are_known_by_their_kind():
    """Scene facts find a carried object's spec in the scene it was declared in, however far back."""
    doc = doc_from("""
        scenes:
          - id: a
            objects: [{id: plane, type: number_plane, shown: true}, {id: v, type: vector, on: plane, tip: [1, 1], shown: true}]
          - id: b
            carry: [plane, v]
          - id: c
            carry: [plane, v]
            objects: [{id: t, type: text, text: label, place: {next_to: v}}]
        """)
    facts = layout_check.scene_facts(doc, 2)
    assert facts.kind("plane") == "number_plane" and facts.kind("v") == "vector"
    assert facts.locs["v"] == ["scenes", 2, "carry", 1]
    assert layout_check.exemption_for(facts, "t", "v") == "label"
    assert layout_check.exemption_for(facts, "t", "plane") == "background"


# The whole document, cached

TWO_SCENES = """
    scenes:
      - id: first
        objects:
          - {id: t, type: text, text: Off, place: [9, 0], shown: true}
      - id: second
        objects:
          - {id: u, type: text, text: Fine, shown: true}
    """


def test_check_layout_goes_through_every_scene_and_caches_them(render_cache, monkeypatch):
    doc = doc_from(TWO_SCENES)
    calls = []
    real = layout_check.check_scene
    monkeypatch.setattr(layout_check, "check_scene", lambda d, s, b=None: calls.append(s) or real(d, s, b))
    first = check_layout(doc)
    assert [p.message for p in first] == ["At the start of the scene, 't' is entirely off the frame"]
    assert calls == ["first", "second"]
    assert [p.to_json() for p in check_layout(doc)] == [p.to_json() for p in first]
    assert calls == ["first", "second"]
    # Kept on disk too, for the next process
    layout_check.clear_memory_cache()
    assert [p.to_json() for p in check_layout(doc, "first")] == [p.to_json() for p in first]
    assert calls == ["first", "second"]
    assert len(list((render_cache / "layout").glob("*.json"))) == 2


def test_a_changed_scene_is_checked_again_and_a_moved_one_isnt(render_cache, monkeypatch):
    calls = []
    real = layout_check.check_scene
    monkeypatch.setattr(layout_check, "check_scene", lambda d, s, b=None: calls.append(s) or real(d, s, b))
    check_layout(doc_from(TWO_SCENES))
    swapped = doc_from("""
        scenes:
          - id: second
            objects:
              - {id: u, type: text, text: Fine, shown: true}
          - id: first
            objects:
              - {id: t, type: text, text: Off, place: [9, 0], shown: true}
        """)
    problems = check_layout(swapped)
    assert calls == ["first", "second"]
    assert [(p.loc, p.scene_id) for p in problems] == [(["scenes", 1, "objects", 0, "place"], "first")]
    changed = doc_from(TWO_SCENES.replace("[9, 0]", "[9.5, 0]"))
    check_layout(changed)
    assert calls == ["first", "second", "first"]


@pytest.mark.render  # a formula LaTeX refuses needs LaTeX to refuse it
def test_a_scene_which_cant_be_built_gives_its_errors_and_the_rest_are_checked(render_cache):
    doc = doc_from("""
        scenes:
          - id: broken
            objects:
              - {id: bad, type: tex, tex: "\\\\frac{1}{", shown: true}
          - id: fine
            objects:
              - {id: t, type: text, text: Off, place: [0, 9], shown: true}
        """)
    problems = check_layout(doc)
    assert [p.severity for p in problems] == ["error", "warning"]
    assert problems[0].loc[:4] == ["scenes", 0, "objects", 0] and problems[0].item_id == "bad"
    assert problems[1].scene_id == "fine"


def test_an_unknown_scene_is_an_error():
    with pytest.raises(RenderError):
        check_layout(doc_from(TWO_SCENES), "nowhere")


def test_scenes_with_errors_are_left_out_of_a_document_check(render_cache):
    doc = doc_from(TWO_SCENES)
    from manim_verbose.scenefile.validate import Problem
    blocked = [Problem("broken", ["scenes", 0], "error", "first")]
    assert check_document_layout(doc, blocked) == []
    assert check_document_layout(doc, [Problem("whole document", [], "error")]) == []
    assert [p.scene_id for p in check_document_layout(doc, [])] == ["first"]


# The command line

def write(tmp_path: Path, text: str) -> Path:
    import textwrap
    path = tmp_path / "lesson.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_validate_layout_prints_warnings_and_exits_0(tmp_path, capsys, render_cache):
    path = write(tmp_path, TWO_SCENES)
    assert cli_main(["validate", "--layout", str(path)]) == 0
    captured = capsys.readouterr()
    assert (f"{path}: warning: scenes[0].objects[0].place: At the start of the scene, 't' is entirely off the frame"
            in captured.err)
    assert captured.out.strip() == f"{path}: ok, 1 warning(s)"


def test_validate_layout_as_json(tmp_path, capsys, render_cache):
    path = write(tmp_path, TWO_SCENES)
    assert cli_main(["validate", "--layout", "--json", str(path)]) == 0
    problems = json.loads(capsys.readouterr().out)
    assert problems == [{
        "message": "At the start of the scene, 't' is entirely off the frame",
        "loc": ["scenes", 0, "objects", 0, "place"], "severity": "warning",
        "scene_id": "first", "item_id": "t", "path": "scenes[0].objects[0].place",
    }]


def test_validate_layout_keeps_what_latex_prints_off_the_json(tmp_path, capsys, monkeypatch):
    """LaTeX's progress ("Writing ...") is printed as formulas are first typeset."""
    path = write(tmp_path, TWO_SCENES)

    def noisy(doc, scene_id=None, base_dir=None):
        print("Writing a^2 + b^2...", end="\r")
        return []

    monkeypatch.setattr(layout_check, "check_layout", noisy)
    assert cli_main(["validate", "--layout", "--json", str(path)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "Writing a^2 + b^2..." in captured.err


def test_validate_without_layout_builds_nothing(tmp_path, capsys, monkeypatch):
    path = write(tmp_path, TWO_SCENES)
    monkeypatch.setattr(layout_check, "check_layout", lambda *a, **k: pytest.fail("layout was checked"))
    assert cli_main(["validate", str(path)]) == 0
    assert capsys.readouterr().out.strip() == f"{path}: ok"


def test_validate_layout_of_a_document_the_models_cant_read(tmp_path, capsys, render_cache):
    path = write(tmp_path, TWO_SCENES.replace("id: u, type: text", "id: u, type: text, colour: RED"))
    assert cli_main(["validate", "--layout", str(path)]) == 1
    err = capsys.readouterr().err
    assert "error: scenes[1].objects[0].colour" in err
    assert "warning: scenes[0].objects[0].place" not in err  # the models couldn't read it at all


def test_validate_layout_skips_only_the_scene_with_errors(tmp_path, capsys, render_cache):
    path = write(tmp_path, TWO_SCENES + """
      - id: third
        objects:
          - {id: w, type: text, text: Off too, place: [0, -9], shown: true}
        steps:
          - {do: show, target: nothere}
    """)
    assert cli_main(["validate", "--layout", str(path)]) == 1
    err = capsys.readouterr().err
    assert "warning: scenes[0].objects[0].place" in err
    assert "error: scenes[2].steps[0].target" in err
    assert "scenes[2].objects[0]" not in err


# The ten minute example

@pytest.mark.slow
@pytest.mark.render  # the example is full of formulas, which need LaTeX
def test_the_example_is_checked_in_well_under_a_minute(render_cache):
    if not EXAMPLE.exists():
        pytest.skip("the example scene file isn't in this checkout")
    doc, problems = load_file(EXAMPLE)
    assert doc is not None
    started = time.monotonic()
    found_problems = check_layout(doc, base_dir=EXAMPLE.parent)
    cold = time.monotonic() - started
    assert all(p.severity == "warning" for p in found_problems), [str(p) for p in found_problems]
    # The one stretch found in it is real: changing the entries of the two matrices in the
    # scaling scene puts both at the centre of the frame, one over the other and under the
    # vectors (reported to the example's author). Everything else is clean.
    assert {p.scene_id for p in found_problems} <= {"scaling"}
    assert cold < 60, f"checking the example took {cold:.1f}s"
    started = time.monotonic()
    again = check_layout(doc, base_dir=EXAMPLE.parent)
    assert [p.to_json() for p in again] == [p.to_json() for p in found_problems]
    assert time.monotonic() - started < 5
    # One scene, as the editor asks for it, from nothing cached
    layout_check.clear_memory_cache()
    started = time.monotonic()
    check_scene(doc, "physics_view", EXAMPLE.parent)
    assert time.monotonic() - started < 10
