"""
Where layout.place puts things, measured by bounding boxes: an edge keeps the whole object
inside the frame, `buff` in from the border; beside another object means on that side of it
and clear of it; at means centred there. And that the builders generated code relies on put
labels, coordinates, brackets and graphs where they belong.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from manim_verbose.manim_import import import_manim

import_manim()

from manimlib import (  # noqa: E402
    DEGREES, DOWN, FRAME_HEIGHT, FRAME_WIDTH, LEFT, OUT, PI, RIGHT, TAU, UP, Arc, Arrow, Axes, BackgroundRectangle,
    Brace, Dot, Group, ImageMobject, Line, Matrix, NumberLine, NumberPlane, Rectangle, Tex, Text, ThreeDAxes,
    Transform, VGroup, VMobject,
)
from manimlib.camera.camera_frame import CameraFrame  # noqa: E402
from PIL import Image  # noqa: E402

from manim_verbose.scenefile import layout  # noqa: E402
from manim_verbose.scenefile.expressions import ExpressionError  # noqa: E402
from manim_verbose.scenefile.layout import (  # noqa: E402
    EDGES, angle_mark, brace_between, brace_part, face_camera, facing_camera, function_graph, matrix_part, place,
    set_frame_shape, frame_shape, with_arc_tip, with_axis_labels, with_backdrop, with_brace_label, with_coordinates,
    with_label, with_numbers, with_round_brackets, with_row_colors, with_tip_label, with_tips, with_underline,
)

TOL = 1e-3
HALF_W, HALF_H = FRAME_WIDTH / 2, FRAME_HEIGHT / 2
SIDES = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT}


def box(mob):
    """xmin, ymin, xmax, ymax"""
    low, _, high = mob.get_bounding_box()
    return low[0], low[1], high[0], high[1]


def rect(width, height, at=(0, 0)):
    return Rectangle(width=width, height=height).move_to([*at, 0])


def assert_inside_frame(mob, buff, shape=(FRAME_WIDTH, FRAME_HEIGHT)):
    x0, y0, x1, y1 = box(mob)
    hw, hh = shape[0] / 2, shape[1] / 2
    assert x0 >= -hw + buff - TOL and x1 <= hw - buff + TOL, (x0, x1)
    assert y0 >= -hh + buff - TOL and y1 <= hh - buff + TOL, (y0, y1)


def assert_apart(a, b, gap=0.0):
    ax0, ay0, ax1, ay1 = box(a)
    bx0, by0, bx1, by1 = box(b)
    assert ax1 <= bx0 - gap + TOL or bx1 <= ax0 - gap + TOL or ay1 <= by0 - gap + TOL or by1 <= ay0 - gap + TOL


def assert_on_side(mob, ref, side, buff):
    """mob is on `side` of ref, `buff` away from it."""
    mx0, my0, mx1, my1 = box(mob)
    rx0, ry0, rx1, ry1 = box(ref)
    if side == "down":
        assert my1 == pytest.approx(ry0 - buff, abs=TOL)
    elif side == "up":
        assert my0 == pytest.approx(ry1 + buff, abs=TOL)
    elif side == "left":
        assert mx1 == pytest.approx(rx0 - buff, abs=TOL)
    else:
        assert mx0 == pytest.approx(rx1 + buff, abs=TOL)


# place

def test_place_returns_the_mobject():
    mob = rect(1, 1)
    assert place(mob) is mob
    assert place(mob, edge="top") is mob


def test_nothing_given_centres():
    mob = place(rect(2, 1, at=(3, 2)))
    assert np.allclose(mob.get_center(), 0, atol=TOL)


@pytest.mark.parametrize("at", [(0, 0), (1, 2), (-3.5, -1.25), (6, 3.5)])
def test_at_puts_the_centre_there(at):
    mob = place(rect(2, 1, at=(-4, 3)), at=at)
    assert np.allclose(mob.get_center()[:2], at, atol=TOL)


def test_at_takes_a_third_coordinate():
    mob = place(Dot(), at=[1, 2, 3])
    assert np.allclose(mob.get_center(), [1, 2, 3], atol=TOL)


SIZES = [(1, 0.5), (4, 3), (FRAME_WIDTH + 3, 1), (1, FRAME_HEIGHT + 2), (30, 20), (0.01, 0.01)]


@pytest.mark.parametrize("edge", [e for e in EDGES if e != "center"])
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("buff", [0, 0.25, 1])
def test_edges_keep_the_whole_object_inside(edge, size, buff):
    mob = place(rect(*size), edge=edge, buff=buff)
    assert_inside_frame(mob, buff)
    x0, y0, x1, y1 = box(mob)
    direction = EDGES[edge]
    # Against the border it was sent to
    if direction[0] > 0:
        assert x1 == pytest.approx(HALF_W - buff, abs=TOL)
    if direction[0] < 0:
        assert x0 == pytest.approx(-HALF_W + buff, abs=TOL)
    if direction[1] > 0:
        assert y1 == pytest.approx(HALF_H - buff, abs=TOL)
    if direction[1] < 0:
        assert y0 == pytest.approx(-HALF_H + buff, abs=TOL)
    # And centred along it, having started in the middle
    if direction[0] == 0:
        assert (x0 + x1) / 2 == pytest.approx(0, abs=TOL)
    if direction[1] == 0:
        assert (y0 + y1) / 2 == pytest.approx(0, abs=TOL)


def test_edges_shrink_only_what_would_not_fit():
    small = place(rect(2, 1), edge="top")
    assert small.get_width() == pytest.approx(2, abs=TOL)
    wide = place(rect(FRAME_WIDTH * 2, 1), edge="bottom", buff=0.5)
    assert wide.get_width() == pytest.approx(FRAME_WIDTH - 1, abs=TOL)
    assert wide.get_height() == pytest.approx((FRAME_WIDTH - 1) / (2 * FRAME_WIDTH), abs=TOL)


def test_edge_center_centres():
    mob = place(rect(3, 2, at=(4, -2)), edge="center")
    assert np.allclose(mob.get_center(), 0, atol=TOL)


@pytest.mark.parametrize("start", [(20, 0), (-20, 0), (0, 20), (0, -20), (6.5, 3.8)])
@pytest.mark.parametrize("edge", ["top", "bottom", "left", "right"])
def test_edges_pull_in_something_already_off_screen(start, edge):
    mob = place(rect(3, 1.5, at=start), edge=edge)
    assert_inside_frame(mob, 0.25)


@pytest.mark.parametrize("edge", [e for e in EDGES if e != "center"])
@pytest.mark.parametrize("start", [(5, -3), (-6, 2.5), (0.5, 0.5), (40, -40)])
def test_edges_centre_along_the_edge_wherever_the_object_was(edge, start):
    """As a move to an edge needs: top is top centre whatever came before, a corner sets both."""
    mob = place(rect(2, 1, at=start), edge=edge)
    x0, y0, x1, y1 = box(mob)
    direction = EDGES[edge]
    expected_x = {1: HALF_W - 0.25 - 1, -1: -HALF_W + 0.25 + 1, 0: 0}[int(direction[0])]
    expected_y = {1: HALF_H - 0.25 - 0.5, -1: -HALF_H + 0.25 + 0.5, 0: 0}[int(direction[1])]
    assert mob.get_center()[:2] == pytest.approx([expected_x, expected_y], abs=TOL)


def test_at_on_a_coordinate_system():
    plane = NumberPlane(x_range=[-4, 4, 1], y_range=[-2, 2, 1], width=6, height=3).shift(RIGHT)
    mob = place(rect(0.5, 0.5), at=[2, 1], on=plane)
    assert np.allclose(mob.get_center(), plane.c2p(2, 1), atol=TOL)
    axes = Axes(x_range=[0, 10, 1], y_range=[0, 100, 10], width=5, height=4)
    mob = place(Dot(), at=[5, 50], on=axes, shift=[0, 0.5])
    assert np.allclose(mob.get_center(), axes.c2p(5, 50) + 0.5 * UP, atol=TOL)


def test_at_on_a_number_line_is_along_it_then_above_it():
    line = NumberLine(x_range=[0, 4, 1], width=8).shift(DOWN)
    mob = place(Dot(), at=[1.5, 0.75], on=line)
    assert np.allclose(mob.get_center(), line.n2p(1.5) + 0.75 * UP, atol=TOL)
    assert np.allclose(layout.point_on(line, [3]), line.n2p(3), atol=TOL)


def test_on_needs_at_and_a_coordinate_system():
    with pytest.raises(ValueError, match="needs `at`"):
        place(Dot(), edge="top", on=NumberPlane())
    with pytest.raises(TypeError, match="isn't a coordinate system"):
        place(Dot(), at=[1, 1], on=rect(1, 1))


@pytest.mark.parametrize("make, keeps_type", [
    (lambda: NumberPlane(x_range=[-3, 3, 1], y_range=[-2, 2, 1]), True),
    (lambda: Axes(x_range=[-3, 3, 1], y_range=[-2, 2, 1]), True),
    pytest.param(lambda: Matrix([["1"], ["2"]]), True, marks=pytest.mark.render),
    (lambda: Text("over a grid"), False),
    pytest.param(lambda: Tex("x^2"), False, marks=pytest.mark.render),
    (lambda: rect(2, 1), False),
    (lambda: VGroup(Text("a"), Text("b")).arrange(DOWN), False),
])
def test_with_backdrop_puts_a_panel_behind(make, keeps_type):
    mob = make()
    x0, y0, x1, y1 = box(mob)
    result = with_backdrop(mob)
    if keeps_type:
        assert result is mob
        panel = mob.submobjects[0]
    else:
        assert isinstance(result, VGroup) and result[1] is mob
        panel = result[0]
    assert isinstance(panel, BackgroundRectangle)
    # Drawn first, around the whole of it, and dark
    family = [m for m in result.get_family() if m.has_points()]
    assert family[0] is panel
    px0, py0, px1, py1 = box(panel)
    assert px0 <= x0 - 0.15 + TOL and py0 <= y0 - 0.15 + TOL and px1 >= x1 + 0.15 - TOL and py1 >= y1 + 0.15 - TOL
    assert panel.get_fill_opacity() == pytest.approx(0.75)
    assert panel.get_stroke_width() == 0


def test_with_backdrop_keeps_coordinate_systems_working(tmp_path):
    plane = with_backdrop(NumberPlane(x_range=[-3, 3, 1], y_range=[-2, 2, 1]))
    assert np.allclose(plane.c2p(1, 1), [1, 1, 0], atol=TOL)
    path = tmp_path / "pic.png"
    Image.new("RGB", (4, 3), (255, 0, 0)).save(path)
    image = ImageMobject(str(path), height=1)
    group = with_backdrop(image)
    assert isinstance(group, Group) and group[1] is image


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("ref_at", [(0, 0), (-5.5, 0), (5.5, 0), (0, 3), (0, -3), (-6, -3.3)])
@pytest.mark.parametrize("buff", [0, 0.25, 0.8])
def test_next_to_is_on_that_side_and_clear(side, ref_at, buff):
    ref = rect(1.2, 0.6, at=ref_at)
    mob = place(rect(3, 1), next_to=ref, side=side, buff=buff)
    assert_on_side(mob, ref, side, buff)
    assert_apart(mob, ref, gap=buff)
    # Slid along that side to stay in the frame, if it had to be
    x0, y0, x1, y1 = box(mob)
    if side in ("up", "down"):
        assert x0 >= -HALF_W + buff - TOL and x1 <= HALF_W - buff + TOL
    else:
        assert y0 >= -HALF_H + buff - TOL and y1 <= HALF_H - buff + TOL


def test_next_to_lines_up_centres_when_there_is_room():
    ref = rect(2, 1, at=(1, 1))
    mob = place(rect(1, 0.5), next_to=ref, side="down")
    assert mob.get_center()[0] == pytest.approx(1, abs=TOL)
    mob = place(rect(1, 0.5), next_to=ref, side="right")
    assert mob.get_center()[1] == pytest.approx(1, abs=TOL)


def test_shift_comes_after():
    mob = place(rect(1, 1), at=[1, 1], shift=[0.5, -2])
    assert np.allclose(mob.get_center()[:2], [1.5, -1], atol=TOL)
    mob = place(rect(1, 1), edge="top", shift=[0, -1])
    assert box(mob)[3] == pytest.approx(HALF_H - 0.25 - 1, abs=TOL)


@pytest.mark.parametrize("kwargs, message", [
    (dict(at=[0, 0], edge="top"), "Give only one of at, edge or next_to"),
    (dict(edge="middle"), "'middle' isn't an edge"),
    (dict(next_to=Dot(), side="above"), "'above' isn't a side"),
])
def test_bad_placements_are_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        place(rect(1, 1), **kwargs)


def test_frame_shape_can_be_changed():
    assert frame_shape() == (FRAME_WIDTH, FRAME_HEIGHT)
    try:
        set_frame_shape(8, 8)
        mob = place(rect(2, 1), edge="right")
        assert box(mob)[2] == pytest.approx(4 - 0.25, abs=TOL)
        big = place(rect(12, 1), edge="top")
        assert_inside_frame(big, 0.25, shape=(8, 8))
    finally:
        layout._frame_shape = None
    assert frame_shape() == (FRAME_WIDTH, FRAME_HEIGHT)


def test_text_goes_where_rectangles_do():
    mob = place(Text("A heading which is fairly long", font_size=60), edge="top_left")
    assert_inside_frame(mob, 0.25)
    assert box(mob)[0] == pytest.approx(-HALF_W + 0.25, abs=TOL)


sizes = st.floats(0.05, 25)
buffs = st.floats(0, 1.5)


@settings(max_examples=300, deadline=None)
@given(sizes, sizes, st.sampled_from([e for e in EDGES if e != "center"]), buffs,
       st.tuples(st.floats(-30, 30), st.floats(-30, 30)))
def test_property_edges_stay_inside(width, height, edge, buff, start):
    mob = place(rect(width, height, at=start), edge=edge, buff=buff)
    assert_inside_frame(mob, buff)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
@given(st.floats(0.1, 6), st.floats(0.1, 4), st.tuples(st.floats(-6, 6), st.floats(-3.5, 3.5)),
       st.floats(0.05, 16), st.floats(0.05, 9), st.sampled_from(list(SIDES)), buffs)
def test_property_next_to_is_on_its_side(ref_w, ref_h, ref_at, width, height, side, buff):
    ref = rect(ref_w, ref_h, at=ref_at)
    mob = place(rect(width, height), next_to=ref, side=side, buff=buff)
    assert_on_side(mob, ref, side, buff)
    assert_apart(mob, ref, gap=buff)
    x0, y0, x1, y1 = box(mob)
    along = (0, width, HALF_W) if side in ("up", "down") else (1, height, HALF_H)
    dim, size, half = along
    low, high = (x0, x1) if dim == 0 else (y0, y1)
    if size <= 2 * (half - buff):
        assert low >= -half + buff - TOL and high <= half - buff + TOL
    else:
        assert (low + high) / 2 == pytest.approx(0, abs=TOL)


# Builders

def test_with_underline():
    title = Text("Title", font_size=60)
    group = with_underline(title)
    assert isinstance(group, VGroup) and group[0] is title
    line = group[1]
    assert box(line)[3] < box(title)[1]
    assert line.get_width() == pytest.approx(title.get_width() * 1.2, rel=1e-3)


@pytest.mark.render
@pytest.mark.parametrize("side", SIDES)
def test_with_label_puts_it_on_that_side(side):
    dot = Dot([1, 1, 0])
    alone = dot.copy()
    label = Tex("A")
    result = with_label(dot, label, side)
    assert result is dot and label in dot.submobjects
    assert_on_side(label, alone, side, 0.15)


@pytest.mark.render
@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("tip", [(2, 1), (-1, 2), (0, -2), (-3, 0)])
def test_with_tip_label_is_beside_the_tip(side, tip):
    arrow = Arrow([0, 0, 0], [*tip, 0], buff=0)
    label = Tex(R"\vec{v}")
    with_tip_label(arrow, label, side)
    assert label in arrow.submobjects
    assert np.allclose(arrow.get_end()[:2], tip, atol=TOL)
    x0, y0, x1, y1 = box(label)
    tx, ty = tip
    if side == "right":
        assert x0 == pytest.approx(tx + 0.15, abs=TOL) and y0 < ty < y1
    elif side == "left":
        assert x1 == pytest.approx(tx - 0.15, abs=TOL) and y0 < ty < y1
    elif side == "up":
        assert y0 == pytest.approx(ty + 0.15, abs=TOL) and x0 < tx < x1
    else:
        assert y1 == pytest.approx(ty - 0.15, abs=TOL) and x0 < tx < x1


def arrow_points_inside(arrow, mob) -> bool:
    x0, y0, x1, y1 = box(mob)
    points = arrow.get_points()
    return bool(((points[:, 0] > x0) & (points[:, 0] < x1) & (points[:, 1] > y0) & (points[:, 1] < y1)).any())


@pytest.mark.render
@pytest.mark.parametrize("tip", [(2, 1), (-1, 2), (3, -2), (0, 3), (-2, 0), (-2, -2), (0, -1), (0.1, 0.1)])
def test_with_coordinates_sits_past_the_tip(tip):
    arrow = Arrow([0, 0, 0], [*tip, 0], buff=0)
    with_coordinates(arrow, list(tip))
    coordinates = arrow.submobjects[-1]
    assert isinstance(coordinates, Matrix)
    assert not arrow_points_inside(arrow, coordinates)
    along = np.dot(coordinates.get_center()[:2] - np.array(tip), np.array(tip))
    assert along > 0


@pytest.mark.render
@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("tip", [(2, 1), (-1, 2), (1, -2)])
def test_with_coordinates_keeps_clear_of_a_label(side, tip):
    arrow = with_tip_label(Arrow([0, 0, 0], [*tip, 0], buff=0), Tex(R"\vec{v}"), side)
    with_coordinates(arrow, list(tip))
    label, coordinates = arrow.submobjects[-2:]
    assert_apart(label, coordinates)
    assert not arrow_points_inside(arrow, coordinates)


@pytest.mark.render
def test_with_coordinates_writes_numbers_as_people_do():
    arrow = with_coordinates(Arrow([0, 0, 0], [1, 1, 0], buff=0), [2.0, -1.5])
    matrix = arrow.submobjects[-1]
    assert [entry.get_tex() for entry in matrix.elements] == ["2", "-1.5"]
    arrow = with_coordinates(Arrow([0, 0, 0], [1, 1, 0], buff=0), Tex("x"))
    assert isinstance(arrow.submobjects[-1], Tex)


@pytest.mark.render
@pytest.mark.parametrize("side", SIDES)
def test_with_brace_label(side):
    target = rect(2, 1)
    brace = Brace(target, SIDES[side], buff=0.1)
    group = with_brace_label(brace, Tex("n"))
    assert group[0] is brace
    assert_apart(group[1], brace)
    assert_apart(group[1], target)
    # Beyond the brace, away from what it braces
    offset = group[1].get_center() - target.get_center()
    assert np.dot(offset, SIDES[side]) > np.dot(brace.get_center() - target.get_center(), SIDES[side])


@pytest.mark.render
def test_with_round_brackets():
    matrix = Matrix([["a", "b"], ["c", "d"]])
    old = list(matrix.brackets)
    heights = [b.get_height() for b in old]
    with_round_brackets(matrix)
    family = matrix.get_family()
    assert all(b not in family for b in old)
    left, right = matrix.brackets
    assert left in family and right in family
    entries = VGroup(*matrix.elements)
    assert box(left)[2] < box(entries)[0] and box(right)[0] > box(entries)[2]
    assert [left.get_height(), right.get_height()] == pytest.approx(heights, rel=1e-3)
    # Evenly either side of the entries, and level with them
    assert box(entries)[0] - box(left)[2] == pytest.approx(box(right)[0] - box(entries)[2], abs=1e-3)
    assert left.get_center()[1] == pytest.approx(entries.get_center()[1], abs=1e-3)
    assert matrix.get_center() == pytest.approx(entries.get_center(), abs=1e-3)


@pytest.mark.render
def test_with_row_colors():
    matrix = with_row_colors(Matrix([["1", "2"], ["3", "4"], ["5", "6"]]), "#FF0000", "#00FF00")
    rows = matrix.get_rows()
    assert rows[0][0].get_fill_color().upper() == "#FF0000"
    assert rows[1][1].get_fill_color().upper() == "#00FF00"
    assert rows[2][0].get_fill_color().upper() != "#00FF00"


def test_with_numbers():
    axes = with_numbers(Axes(x_range=[-3, 3, 1], y_range=[-2, 2, 1]))
    numbers = axes.coordinate_labels
    assert [len(numbers[0]), len(numbers[1])] == [6, 4]
    plane = with_numbers(NumberPlane(x_range=[-2, 2, 0.5], y_range=[-1, 1, 0.5]), num_decimal_places=1)
    assert len(plane.coordinate_labels[0]) == 8
    family = plane.get_family()
    assert all(number in family for numbers in plane.coordinate_labels for number in numbers)


@pytest.mark.render
def test_with_axis_labels():
    axes = Axes(x_range=[-3, 3, 1], y_range=[-2, 2, 1])
    before = len(axes.submobjects)
    with_axis_labels(axes, x_label="t", y_label="f(t)")
    x_label, y_label = axes.submobjects[before:]
    assert x_label.get_center()[0] > 2 and abs(x_label.get_center()[1]) < 1
    assert y_label.get_center()[1] > 1.5 and abs(y_label.get_center()[0]) < 1.5
    assert len(with_axis_labels(Axes(), y_label="y").submobjects) == before + 1


def test_only_3d_axes_have_a_z_label():
    with pytest.raises(ValueError, match="Only 3D axes"):
        with_axis_labels(Axes(), z_label="z")


def test_with_backdrop_takes_the_background_color():
    from manimlib.config import manim_config
    from manimlib.utils.color import color_to_hex
    # What is drawn, rather than what BackgroundRectangle.get_fill_color says, which is always white
    def drawn(panel):
        return VMobject.get_fill_color(panel).upper()

    for color in ["#FFFFFF", "#123456"]:
        assert drawn(with_backdrop(Text("x"), color=color)[0]) == color
        plane = with_backdrop(NumberPlane(x_range=[-1, 1, 1], y_range=[-1, 1, 1]), color=color)
        assert drawn(plane.submobjects[0]) == color
    assert drawn(with_backdrop(Text("x"))[0]) == color_to_hex(manim_config.camera.background_color)


@pytest.mark.render
def test_with_coordinates_colors_its_rows_and_not_its_brackets():
    arrow = Arrow([0, 0, 0], [2, 1, 0], buff=0).set_color("#FFFF00")
    with_coordinates(arrow, [2, 1, 3], colors=["#00FF00", "#FF0000"])
    matrix = arrow.submobjects[-1]
    x, y, z = matrix.elements
    assert {m.get_fill_color().upper() for m in x.family_members_with_points()} == {"#00FF00"}
    assert {m.get_fill_color().upper() for m in y.family_members_with_points()} == {"#FF0000"}
    # A row given no color, and the brackets, stay as they were
    plain = Matrix([["3"]])
    assert z.get_fill_color().upper() == plain.elements[0].get_fill_color().upper()
    assert {m.get_fill_color().upper() for m in matrix.brackets.family_members_with_points()} == {
        plain.brackets[0].get_fill_color().upper()
    }
    assert arrow.get_fill_color().upper() == "#FFFF00"


# Tips past the ends of number lines and axes

TIP_RANGES = [[0, 4, 1], [-1, 1, 0.25], [-3, 3, 0.5], [2, 5, 1], [-10, 10, 5]]


def number_values(numbers) -> list[float]:
    return [round(float(number.get_value()), 6) for number in numbers]


@pytest.mark.parametrize("x_range", TIP_RANGES)
def test_a_tip_goes_past_the_end_and_hides_no_number(x_range):
    plain = NumberLine(x_range=x_range, width=6, include_numbers=True)
    line = with_tips(NumberLine(x_range=x_range, width=6, include_numbers=True))
    # Every number and tick is still there, the last ones too, and the line means what it did
    assert number_values(line.numbers) == number_values(plain.numbers)
    assert number_values(line.numbers)[-1] == pytest.approx(x_range[1])
    assert len(line.ticks) == len(plain.ticks)
    for x in np.linspace(x_range[0], x_range[1], 7):
        assert np.allclose(line.n2p(x), plain.n2p(x), atol=TOL)
    # The tip starts where the line ends, points on past it, and covers no number
    tip = line.tip
    assert line.has_tip() and tip in line.submobjects
    end = line.n2p(x_range[1])
    assert np.allclose(tip.get_base(), end, atol=TOL)
    assert np.allclose(tip.get_tip_point(), end + layout.TIP_LENGTH * RIGHT, atol=TOL)
    for number in line.numbers:
        assert_apart(number, tip)
    assert tip.get_fill_color().upper() == line.get_stroke_color().upper()


def test_manims_own_tip_is_what_hid_the_last_number():
    """Why with_tips exists: include_tip leaves out the last tick and number."""
    line = NumberLine(x_range=[0, 4, 1], include_numbers=True, include_tip=True)
    assert 4 not in number_values(line.numbers)


def test_tips_on_axes_keep_every_number_and_every_coordinate():
    plain = Axes(x_range=[0, 5, 1], y_range=[0, 3, 1], width=5, height=3)
    axes = with_numbers(with_tips(Axes(x_range=[0, 5, 1], y_range=[0, 3, 1], width=5, height=3)))
    x_numbers, y_numbers = axes.coordinate_labels
    assert number_values(x_numbers) == [1, 2, 3, 4, 5]
    assert number_values(y_numbers) == [1, 2, 3]
    for axis, numbers in zip(axes.get_axes(), (x_numbers, y_numbers)):
        assert axis.has_tip()
        end = axis.n2p(axis.x_max)
        direction = (end - axis.n2p(axis.x_min)) / np.linalg.norm(end - axis.n2p(axis.x_min))
        assert np.allclose(axis.tip.get_tip_point(), end + layout.TIP_LENGTH * direction, atol=TOL)
        for number in numbers:
            assert_apart(number, axis.tip)
    for coords in [(0, 0), (5, 3), (2.5, 1)]:
        assert np.allclose(axes.c2p(*coords), plain.c2p(*coords), atol=TOL)


LABELLED_AXES = [
    dict(x_range=[0, 5, 1], y_range=[0, 3, 1], width=5, height=3),
    dict(x_range=[-6, 6, 1], y_range=[-3, 3, 1]),
    dict(x_range=[-1, 1, 0.25], y_range=[-2, 2, 0.5], width=10, height=6),
    dict(x_range=[-7, 7, 1], y_range=[-4, 4, 1], width=14, height=8),
    dict(x_range=[-5, 0, 1], y_range=[0, 10, 2], width=6, height=5),
]


@pytest.mark.render
@pytest.mark.parametrize("kwargs", LABELLED_AXES)
@pytest.mark.parametrize("tips", [False, True])
@pytest.mark.parametrize("x_label", ["t", R"\text{time}", R"\frac{x}{2}"])
def test_axis_labels_keep_clear_of_every_number(kwargs, tips, x_label):
    axes = Axes(**kwargs)
    if tips:
        with_tips(axes)
    # Wide numbers, the harder to keep clear of
    with_numbers(axes, num_decimal_places=2)
    with_axis_labels(axes, x_label=x_label, y_label="y")
    x_label_mob, y_label_mob = axes.submobjects[-2:]
    for number in [*axes.coordinate_labels[0], *axes.coordinate_labels[1]]:
        assert_apart(x_label_mob, number, gap=0.05)
        assert_apart(y_label_mob, number, gap=0.05)
    for label in (x_label_mob, y_label_mob):
        assert_inside_frame(label, 0)
    # At the ends of their axes: x past its end, level with it, or where there is no room, above it
    x_end = axes.get_x_axis().get_right()
    if box(x_label_mob)[0] >= x_end[0]:
        assert x_label_mob.get_center()[1] == pytest.approx(x_end[1], abs=TOL)
    else:
        assert box(x_label_mob)[1] > x_end[1] and box(x_label_mob)[2] <= x_end[0] + TOL
    assert y_label_mob.get_center()[1] > axes.c2p(0, kwargs["y_range"][1])[1] - 0.5


@pytest.mark.render
def test_an_x_label_goes_past_the_end_of_its_axis_and_its_tip():
    axes = with_axis_labels(with_tips(Axes(x_range=[0, 5, 1], y_range=[0, 3, 1], width=5, height=3)), x_label="t")
    label, axis = axes.submobjects[-1], axes.get_x_axis()
    assert box(label)[0] == pytest.approx(box(axis.tip)[2] + 0.25, abs=TOL)
    assert label.get_center()[1] == pytest.approx(axis.get_center()[1], abs=TOL)


# Parts of matrices

def grid() -> Matrix:
    return Matrix([["a", "b", "c"], ["d", "e", "f"]])


def same(group, expected) -> bool:
    return len(group) == len(expected) and all(a is b for a, b in zip(group, expected))


@pytest.mark.render
def test_matrix_part_picks_out_exactly_the_entries():
    matrix = grid()
    a, b, c, d, e, f = matrix.elements
    assert same(matrix_part(matrix, row=1), [a, b, c])
    assert same(matrix_part(matrix, row=2), [d, e, f])
    assert same(matrix_part(matrix, column=1), [a, d])
    assert same(matrix_part(matrix, column=3), [c, f])
    assert same(matrix_part(matrix, entry=(2, 1)), [d])
    assert same(matrix_part(matrix, entries=[(1, 3), (2, 2)]), [c, e])
    brackets = set(matrix.brackets.get_family())
    for part in [matrix_part(matrix, row=1), matrix_part(matrix, column=2), matrix_part(matrix, entry=(1, 1))]:
        assert isinstance(part, VGroup)
        assert not set(part.get_family()) & brackets


@pytest.mark.render
@pytest.mark.parametrize("kwargs, message", [
    (dict(row=3), "rows 1 to 2, so no row 3"),
    (dict(row=0), "rows 1 to 2"),
    (dict(column=4), "columns 1 to 3"),
    (dict(entry=(3, 1)), "2 rows and 3 columns"),
    (dict(entries=[(1, 1), (1, 0)]), "2 rows and 3 columns"),
    (dict(), "Give one of"),
    (dict(row=1, column=1), "Give one of"),
])
def test_matrix_part_refuses_what_isnt_there(kwargs, message):
    with pytest.raises((IndexError, ValueError), match=message):
        matrix_part(grid(), **kwargs)


@pytest.mark.render
def test_matrix_part_is_where_the_entries_are_after_a_move():
    matrix = grid()
    # Once a row group has been measured, as coloring a row does, a move (which plays a
    # transform) leaves it measured where the row was
    matrix.get_rows()[0].get_center()
    move = Transform(matrix, matrix.copy().shift(2 * UP + RIGHT))
    move.begin()
    move.interpolate(1)
    move.finish()
    row = matrix_part(matrix, row=1)
    entries = matrix.elements[:3]
    assert box(row) == pytest.approx((
        min(box(m)[0] for m in entries), min(box(m)[1] for m in entries),
        max(box(m)[2] for m in entries), max(box(m)[3] for m in entries),
    ), abs=TOL)
    assert not np.allclose(matrix.get_rows()[0].get_center(), row.get_center(), atol=TOL)


@pytest.mark.render
def test_matrix_part_of_a_copy_and_of_dressed_up_matrices():
    matrix = grid()
    copy = matrix.copy()
    part = matrix_part(copy, column=2)
    assert all(m in copy.get_family() for m in part) and not any(m in matrix.get_family() for m in part)
    round_matrix = with_round_brackets(grid())
    assert same(matrix_part(round_matrix, row=2), round_matrix.elements[3:])
    panelled = with_backdrop(grid())
    assert same(matrix_part(panelled, entry=(1, 1)), panelled.elements[:1])


# Angles

def own_curve(mob, samples: int = 80) -> np.ndarray:
    """Points along the mobject's own path (not its submobjects'), from its start to its end."""
    return np.array([mob.quick_point_from_proportion(t) for t in np.linspace(0, 1, samples)])


def pad(point) -> np.ndarray:
    return np.array([*point, 0, 0][:3], dtype=float)


def unit(vect) -> np.ndarray:
    return np.asarray(vect, dtype=float) / np.linalg.norm(vect)


def turning(points, centre, first, second) -> np.ndarray:
    """The angle of each point round centre, from `first` towards `second`, unwrapped so that it runs on."""
    offsets = points - centre
    return np.unwrap(np.arctan2(offsets @ second, offsets @ first))


ANGLES = [
    ([2, 0], [0, 0], [1, 1.5]),
    ([1, 0], [0, 0], [-1, 1]),
    ([0, 2], [0, 0], [2, 0]),
    ([3, 1], [1, 1], [1, -2]),
    ([-1, -1], [0.5, 0.5], [2, -0.5]),
    ([1, 0], [0, 0], [-1, 0]),
    ([1, 0, 0], [0, 0, 0], [0, 1, 1]),
    ([1, 2, 3], [0, 1, -1], [-2, 0, 1]),
]


@pytest.mark.parametrize("a, vertex, b", ANGLES)
@pytest.mark.parametrize("other_side", [False, True])
@pytest.mark.parametrize("radius", [0.3, 1])
def test_angle_arc_lies_between_the_lines_at_its_radius(a, vertex, b, other_side, radius):
    a, vertex, b = pad(a), pad(vertex), pad(b)
    mark = angle_mark(a, vertex, b, radius=radius, other_side=other_side)
    assert isinstance(mark, Arc)
    along_a, along_b = unit(a - vertex), unit(b - vertex)
    points = own_curve(mark)
    # On the circle of that radius round the vertex, from the one line to the other
    assert np.allclose(np.linalg.norm(points - vertex, axis=1), radius, rtol=1e-3)
    assert np.allclose(points[0], vertex + radius * along_a, atol=TOL)
    assert np.allclose(points[-1], vertex + radius * along_b, atol=TOL)
    # In the plane of the two lines, turning steadily one way from a to b: the short way
    # round, through the angle between them, or with other_side the long way
    across = along_b - np.dot(along_b, along_a) * along_a
    across = unit(across) if np.linalg.norm(across) > 1e-9 else unit(np.cross(OUT, along_a))
    assert np.allclose((points - vertex) @ np.cross(along_a, across), 0, atol=TOL)
    angles = turning(points, vertex, along_a, across)
    steps = np.diff(angles)
    assert (steps >= -1e-9).all() or (steps <= 1e-9).all()
    between = math.acos(np.clip(np.dot(along_a, along_b), -1, 1))
    assert angles[-1] == pytest.approx(between - TAU if other_side else between, abs=1e-3)


@pytest.mark.parametrize("a, vertex, b", [
    ([2, 0], [0, 0], [0, 3]),
    ([1, 1], [0, 0], [-1, 1]),
    ([0, -1], [1, 1], [3, 0]),
    ([1, 0, 0], [0, 0, 0], [0, 0, 2]),
])
@pytest.mark.parametrize("radius", [0.2, 0.5])
def test_right_angle_mark_is_a_square_in_the_corner(a, vertex, b, radius):
    a, vertex, b = pad(a), pad(vertex), pad(b)
    mark = angle_mark(a, vertex, b, radius=radius, right_angle=True)
    along_a, along_b = unit(a - vertex), unit(b - vertex)
    corners = [mark.get_start()]
    for point in mark.get_anchors():
        if not np.allclose(point, corners[-1]):
            corners.append(point)
    expected = [vertex + radius * along_a, vertex + radius * (along_a + along_b), vertex + radius * along_b]
    assert np.allclose(corners, expected, atol=TOL)
    # Sides as long as the radius, square to each other, and with the vertex the fourth corner
    sides = np.diff(corners, axis=0)
    assert np.linalg.norm(sides, axis=1) == pytest.approx([radius, radius], abs=TOL)
    assert np.dot(*sides) == pytest.approx(0, abs=TOL)
    assert np.allclose(corners[0] + corners[2] - corners[1], vertex, atol=TOL)


def test_a_right_angle_marked_the_other_way_round_is_three_quarters_of_a_turn():
    mark = angle_mark([2, 0, 0], [0, 0, 0], [0, 2, 0], radius=0.5, right_angle=True, other_side=True)
    assert isinstance(mark, Arc)
    angles = turning(own_curve(mark), np.zeros(3), RIGHT, UP)
    assert angles[-1] == pytest.approx(-3 * PI / 2, abs=1e-3)


@pytest.mark.parametrize("a, vertex, b", [
    ([0, 0], [0, 0], [0, 0]),
    ([1, 0], [1, 0], [2, 2]),
    ([1, 1], [0, 0], [1, 1]),
    ([1, 1, 1], [0, 0, 0], [2, 2, 2]),
    ([0, 0, 1], [0, 0, 0], [0, 0, -1]),
])
@pytest.mark.parametrize("options", [{}, {"right_angle": True}, {"other_side": True}])
def test_angles_between_lines_that_arent_there_still_draw(a, vertex, b, options):
    mark = angle_mark(pad(a), pad(vertex), pad(b), **options)
    assert np.isfinite(mark.get_all_points()).all() and mark.has_points()


@pytest.mark.render
@pytest.mark.parametrize("options", [{}, {"right_angle": True}, {"other_side": True}, {"radius": 1.5}])
def test_angle_label_is_beyond_the_mark_halving_the_angle(options):
    label = Tex(R"\theta")
    mark = angle_mark([2, 0, 0], [0, 0, 0], [1, 1.5, 0], label=label, **options)
    assert mark.submobjects[-1] is label
    along_a, along_b = unit([2, 0, 0]), unit([1, 1.5, 0])
    halfway = unit(along_a + along_b)
    if options.get("other_side"):
        halfway = -halfway
    centre = label.get_center()
    assert np.dot(unit(centre), halfway) == pytest.approx(1, abs=1e-6)
    # Clear of the mark
    x0, y0, x1, y1 = box(label)
    points = own_curve(mark)
    assert not ((points[:, 0] > x0) & (points[:, 0] < x1) & (points[:, 1] > y0) & (points[:, 1] < y1)).any()


# Arcs with tips

ARCS = [
    (0, 90, 1, [0, 0]),
    (30, 270, 2, [1, -1]),
    (90, -90, 1.5, [0, 0]),
    (0, 360, 1, [-2, 1]),
    (200, -300, 0.8, [0, 0]),
    (45, 60, 0.3, [2, 2]),
    (10, 5, 0.1, [0, 0]),
]


@pytest.mark.parametrize("start, sweep, radius, centre", ARCS)
def test_an_arc_tip_ends_where_the_arc_did_and_leaves_the_rest_on_its_circle(start, sweep, radius, centre):
    centre = pad(centre)
    arc = Arc(start_angle=start * DEGREES, angle=sweep * DEGREES, radius=radius, arc_center=centre)
    first, last, length = arc.get_start().copy(), arc.get_end().copy(), arc.get_arc_length()
    assert with_arc_tip(arc) is arc
    assert arc.has_tip() and arc.tip in arc.submobjects
    assert np.allclose(arc.get_start(), first, atol=TOL) and np.allclose(arc.get_end(), last, atol=TOL)
    assert np.allclose(arc.tip.get_tip_point(), last, atol=TOL)
    # What is left of the arc is on the same circle, and the tip carries on from where it stops
    assert np.allclose(np.linalg.norm(own_curve(arc) - centre, axis=1), radius, rtol=1e-3)
    assert np.allclose(arc.tip.get_base(), arc.get_points()[-1], atol=TOL)
    # Pointing the way the arc goes round, and no more than a third of it
    tangent = np.sign(sweep) * np.cross(OUT, unit(last - centre))
    assert np.dot(unit(arc.tip.get_vector()), tangent) > 0.95
    assert arc.tip.get_length() <= length / 3 + TOL


def test_an_arc_too_short_for_any_tip_is_left_alone():
    arc = Arc(angle=0, radius=1)
    points = arc.get_points().copy()
    with_arc_tip(arc)
    assert not arc.has_tip() and np.allclose(arc.get_points(), points)


# Braces between points

BRACE_SIDES = [
    # start, end, side, and the way the brace should bulge on screen
    ([0, 0], [3, 0], "down", DOWN), ([0, 0], [3, 0], "up", UP),
    ([3, 0], [0, 0], "down", DOWN), ([3, 0], [0, 0], "up", UP),
    ([0, 0], [0, 3], "left", LEFT), ([0, 0], [0, 3], "right", RIGHT),
    ([0, 3], [0, 0], "left", LEFT), ([0, 3], [0, 0], "right", RIGHT),
    ([0, 0], [3, 1], "down", [1, -3]), ([0, 0], [3, 1], "up", [-1, 3]),
    ([0, 0], [3, 1], "right", [1, -3]), ([0, 0], [3, 1], "left", [-1, 3]),
    ([3, 1], [0, 0], "down", [1, -3]), ([3, 1], [0, 0], "left", [-1, 3]),
    ([0, 0], [1, 3], "down", [3, -1]), ([0, 0], [1, 3], "left", [-3, 1]),
    ([-1, 2], [1, -1], "up", [3, 2]), ([-1, 2], [1, -1], "left", [-3, -2]),
    # Running exactly towards the side asked for: a quarter turn clockwise from it
    ([0, 0], [3, 0], "left", UP), ([0, 0], [3, 0], "right", DOWN),
    ([3, 0], [0, 0], "left", UP), ([0, 0], [0, 3], "down", LEFT), ([0, 3], [0, 0], "up", RIGHT),
]


@pytest.mark.render
@pytest.mark.parametrize("start, end, side, bulge", BRACE_SIDES)
@pytest.mark.parametrize("buff", [0, 0.2])
def test_brace_between_points_spans_them_on_the_stated_side(start, end, side, bulge, buff):
    start, end, out = pad(start), pad(end), unit(pad(bulge))
    brace = brace_between(start, end, side, buff=buff)
    assert isinstance(brace, Brace)
    along = unit(end - start)
    points = brace.get_all_points()
    reach = (points - start) @ along
    assert reach.min() == pytest.approx(0, abs=TOL) and reach.max() == pytest.approx(np.linalg.norm(end - start), abs=TOL)
    offsets = (points - start) @ out
    assert offsets.min() == pytest.approx(buff, abs=TOL) and offsets.max() > buff + 0.1
    assert np.dot(brace.get_direction(), out) > 0.9


@pytest.mark.render
def test_brace_between_one_point_and_itself_still_draws_with_its_label():
    group = with_brace_label(brace_between([1, 1, 0], [1, 1, 0]), Tex("0"))
    assert np.isfinite(group.get_all_points()).all()
    assert np.isfinite(group[1].get_center()).all()


@pytest.mark.render
@pytest.mark.parametrize("side", SIDES)
def test_brace_part_spans_the_part_out_beyond_the_whole(side):
    matrix = grid()
    part = matrix_part(matrix, entry=(1, 2))
    brace = brace_part(part, matrix, side, buff=0.1)
    bx0, by0, bx1, by1 = box(brace)
    px0, py0, px1, py1 = box(part)
    mx0, my0, mx1, my1 = box(matrix)
    if side in ("up", "down"):
        assert (bx0, bx1) == pytest.approx((px0, px1), abs=TOL)
        assert by0 == pytest.approx(my1 + 0.1, abs=TOL) if side == "up" else by1 == pytest.approx(my0 - 0.1, abs=TOL)
    else:
        assert (by0, by1) == pytest.approx((py0, py1), abs=TOL)
        assert bx0 == pytest.approx(mx1 + 0.1, abs=TOL) if side == "right" else bx1 == pytest.approx(mx0 - 0.1, abs=TOL)


# Facing the camera

ORIENTATIONS = [(-30, 70), (60, 90), (0, 45, 20), (120, 10), (-90, 180)]


def camera_axes(frame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The camera's right, up and out (towards the viewer), in the scene's coordinates."""
    rotation = frame.get_orientation().as_matrix()
    return rotation[:, 0], rotation[:, 1], rotation[:, 2]


@pytest.mark.parametrize("orientation", ORIENTATIONS)
def test_face_camera_turns_a_dot_to_face_the_camera_and_back(orientation):
    frame = CameraFrame()
    dot = facing_camera(Dot([1, 2, 3], radius=0.3))
    flat = dot.get_points().copy()
    frame.reorient(*orientation)
    face_camera(dot, frame)
    right, up, out = camera_axes(frame)
    # A disc square to the camera's line of sight, where it was, and as wide as ever from there
    assert abs(np.dot(dot.get_unit_normal(refresh=True), out)) == pytest.approx(1, abs=1e-6)
    offsets = dot.get_points() - [1, 2, 3]
    assert np.abs(offsets @ right).max() == pytest.approx(0.3, abs=1e-3)
    assert np.abs(offsets @ up).max() == pytest.approx(0.3, abs=1e-3)
    assert np.abs(offsets @ out).max() == pytest.approx(0, abs=1e-6)
    # Turned again from wherever it is, and back to flat when the camera is
    frame.reorient(10, 30)
    face_camera(dot, frame)
    assert abs(np.dot(dot.get_unit_normal(refresh=True), camera_axes(frame)[2])) == pytest.approx(1, abs=1e-6)
    frame.reorient(0, 0, 0)
    face_camera(dot, frame)
    assert np.allclose(dot.get_points(), flat, atol=1e-6)


def test_face_camera_leaves_what_is_fixed_in_the_frame():
    frame = CameraFrame()
    dot = facing_camera(Dot([1, 1, 0])).fix_in_frame()
    points = dot.get_points().copy()
    frame.reorient(-30, 70)
    face_camera(dot, frame)
    assert np.allclose(dot.get_points(), points)


def test_facing_camera_does_nothing_outside_a_scene():
    dot = facing_camera(Dot([1, 1, 1]))
    points = dot.get_points().copy()
    dot.update(0)
    assert dot.has_updaters() and np.allclose(dot.get_points(), points)
    # Copies keep facing the camera
    assert dot.copy().has_updaters()


@pytest.mark.render
def test_a_dot_label_stays_above_the_dot_as_the_camera_sees_it():
    dot = facing_camera(with_label(Dot([1, 1, 1]), Tex("P"), "up"))
    label = dot.submobjects[-1]
    flat = label.get_all_points().mean(axis=0) - [1, 1, 1]
    assert flat[1] > 0.2
    frame = CameraFrame()
    frame.reorient(-30, 70)
    face_camera(dot, frame)
    # The disc stays put, and the label keeps where it was beside it, as the camera sees it
    assert np.allclose(VMobject().set_points(dot.get_points()).get_center(), [1, 1, 1], atol=TOL)
    offset = label.get_all_points().mean(axis=0) - [1, 1, 1]
    assert np.array(camera_axes(frame)) @ offset == pytest.approx(flat, abs=TOL)


def turn_round_and_back(mob) -> None:
    """Face the camera frame after frame as it goes round, then as it looks straight at the frame again."""
    frame = CameraFrame()
    for theta in np.linspace(0, 360, 90):
        frame.reorient(theta, 60 + 20 * math.sin(math.radians(theta)))
        face_camera(mob, frame)
    frame.reorient(0, 0, 0)
    face_camera(mob, frame)


def test_turning_a_dot_frame_after_frame_never_walks_it_away():
    dot = facing_camera(Dot([1, -2, 0.5], radius=0.2))
    flat = dot.get_points().copy()
    turn_round_and_back(dot)
    assert np.allclose(dot.get_points(), flat, atol=1e-4)


@pytest.mark.render
def test_turning_a_label_frame_after_frame_never_walks_it_away():
    for label in labels_3d()[1]:
        flat = label.get_all_points().copy()
        turn_round_and_back(label)
        assert np.allclose(label.get_all_points(), flat, atol=1e-4)


def labels_3d():
    axes = ThreeDAxes(x_range=[-3, 3, 1], y_range=[-2, 2, 1], z_range=[-1, 2, 1])
    before = len(axes.submobjects)
    with_axis_labels(axes, x_label="x", y_label="y", z_label=R"\zeta")
    return axes, axes.submobjects[before:]


@pytest.mark.render
def test_3d_axis_labels_sit_just_past_the_ends_of_their_axes():
    axes, labels = labels_3d()
    assert len(labels) == 3
    for label, axis in zip(labels, axes.get_axes()):
        end = axis.n2p(axis.x_max)
        along = unit(end - axis.n2p(axis.x_min))
        offset = label.get_center() - end
        # Out along the axis, far enough to clear its end however it is turned
        assert np.linalg.norm(offset - np.dot(offset, along) * along) == pytest.approx(0, abs=TOL)
        assert label.get_all_points().mean(axis=0) == pytest.approx(label.get_center(), abs=0.05)
        assert np.dot(offset, along) >= max(label.get_width(), label.get_height()) / 2 + 0.2
        assert label.has_updaters()
    assert len(with_axis_labels(ThreeDAxes(), z_label="z").submobjects) == len(ThreeDAxes().submobjects) + 1


@pytest.mark.render
@pytest.mark.parametrize("orientation", ORIENTATIONS)
def test_3d_axis_labels_face_the_camera_where_they_are(orientation):
    axes, labels = labels_3d()
    frame = CameraFrame()
    frame.reorient(*orientation)
    right, up, out = camera_axes(frame)
    for label in labels:
        centre, width, height = label.get_all_points().mean(axis=0), label.get_width(), label.get_height()
        face_camera(label, frame)
        offsets = label.get_all_points() - centre
        # Turned where it is, so that turning it again and again never moves it
        assert np.allclose(label.get_all_points().mean(axis=0), centre, atol=1e-5)
        # Flat to the camera, reading left to right and upright as it looks
        assert np.abs(offsets @ out).max() == pytest.approx(0, abs=1e-4)
        assert np.ptp(offsets @ right) == pytest.approx(width, abs=1e-3)
        assert np.ptp(offsets @ up) == pytest.approx(height, abs=1e-3)


# Graphs

AXES_KW = dict(x_range=[-4, 4, 1], y_range=[-2, 3, 1], width=8, height=5)


def graph_coords(axes, graph):
    """Every anchor of the graph's own path, in the axes' coordinates."""
    return np.array([axes.p2c(p) for p in graph.get_anchors()])


def assert_graph_drawable(axes, graph, x_range=None):
    points = graph.get_all_points()
    assert len(points) and np.isfinite(points).all()
    coords = graph_coords(axes, graph)
    lo, hi = x_range or AXES_KW["x_range"][:2]
    assert (coords[:, 0] >= lo - 1e-3).all() and (coords[:, 0] <= hi + 1e-3).all()
    assert (coords[:, 1] >= -2 - 1e-3).all() and (coords[:, 1] <= 3 + 1e-3).all()


@pytest.mark.parametrize("formula, f", [
    ("sin(x)", np.sin),
    ("x^2 / 4 - 1", lambda x: x ** 2 / 4 - 1),
    ("exp(-x^2)", lambda x: np.exp(-x ** 2)),
])
def test_graph_follows_the_function(formula, f):
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, formula)
    assert_graph_drawable(axes, graph)
    coords = graph_coords(axes, graph)
    assert np.allclose(coords[:, 1], f(coords[:, 0]), atol=2e-3)
    assert coords[0, 0] == pytest.approx(-4, abs=1e-3) and coords[-1, 0] == pytest.approx(4, abs=1e-3)
    assert len(graph.get_subpaths()) == 1


def test_graph_starts_where_the_function_does():
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, "sqrt(x)")
    coords = graph_coords(axes, graph)
    assert coords[0, 0] == pytest.approx(0, abs=1e-6)
    assert (coords[:, 0] >= -1e-6).all()
    assert_graph_drawable(axes, graph)


def test_graph_is_clipped_to_the_axes_and_broken_at_poles():
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, "1/x")
    assert_graph_drawable(axes, graph)
    pieces = graph.get_subpaths()
    assert len(pieces) == 2
    left, right = (np.array([axes.p2c(p) for p in piece]) for piece in pieces)
    assert left[:, 0].max() < 0 < right[:, 0].min()
    # Each piece ends on the edge of the axes it runs off
    assert left[-1, 1] == pytest.approx(-2, abs=1e-3) and right[0, 1] == pytest.approx(3, abs=1e-3)
    tangent = function_graph(axes, "tan(x)")
    assert_graph_drawable(axes, tangent)
    assert len(tangent.get_subpaths()) == 3


def test_graph_breaks_at_jumps_but_not_at_steep_parts():
    axes = Axes(**AXES_KW)
    steps = function_graph(axes, "floor(x)", x_range=[-1.5, 2.5])
    # [-1.5, -1), [-1, 0), [0, 1), [1, 2), [2, 2.5]
    assert len(steps.get_subpaths()) == 5
    assert_graph_drawable(axes, steps, x_range=[-1.5, 2.5])
    steep = function_graph(axes, "atan(50 * x)")
    assert len(steep.get_subpaths()) == 1


@pytest.mark.parametrize("formula", ["sqrt(-1 - x^2)", "log(-abs(x) - 1)", "100 + x", "1/0"])
def test_graph_with_nothing_to_draw_is_still_a_mobject(formula):
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, formula)
    points = graph.get_all_points()
    assert len(points) and np.isfinite(points).all()


def test_graph_with_an_empty_range():
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, "x", x_range=[2, -2])
    assert np.isfinite(graph.get_all_points()).all()


def test_graph_keeps_manim_attributes_and_takes_callables():
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, lambda x: x / 2, x_range=[-1, 1])
    assert graph.underlying_function(3) == 1.5
    assert graph.x_range == [-1, 1]
    assert np.allclose(axes.i2gp(0.5, graph), axes.c2p(0.5, 0.25))


@pytest.mark.render
def test_graph_label_is_near_the_end_and_on_screen():
    axes = Axes(**AXES_KW)
    label = Tex(R"\sin x")
    graph = function_graph(axes, "sin(x)", label=label)
    assert label in graph.submobjects
    assert_inside_frame(label, 0.1)
    end = axes.c2p(4, math.sin(4))
    assert np.linalg.norm(label.get_center() - end) < 1.5
    assert label.get_fill_color() == graph.get_stroke_color()


def test_graph_of_a_bad_formula_is_refused():
    with pytest.raises(ExpressionError):
        function_graph(Axes(**AXES_KW), "x +* 2")


def grammar(depth: int = 3):
    leaf = st.sampled_from(["x", "1", "2", "0.5", "pi", "-x", "3"])
    if depth == 0:
        return leaf
    inner = grammar(depth - 1)
    return st.one_of(
        leaf,
        st.tuples(inner, st.sampled_from(["+", "-", "*", "/", "^"]), inner).map(lambda t: f"({t[0]} {t[1]} {t[2]})"),
        st.tuples(st.sampled_from(["sin", "cos", "tan", "sqrt", "log", "exp", "abs", "floor", "asin"]), inner)
        .map(lambda t: f"{t[0]}({t[1]})"),
    )


@settings(max_examples=60, deadline=None)
@given(grammar(), st.sampled_from([None, [-3, 3], [0.5, 1], [-4, 0]]))
def test_property_any_formula_graphs_inside_its_axes(formula, x_range):
    axes = Axes(**AXES_KW)
    graph = function_graph(axes, formula, x_range=x_range)
    points = graph.get_all_points()
    assert len(points) and np.isfinite(points).all()
    if len(graph.get_subpaths()) and graph.get_num_points() > 3:
        assert_graph_drawable(axes, graph, x_range=x_range)


def test_graph_is_a_vmobject():
    assert isinstance(function_graph(Axes(**AXES_KW), "x"), VMobject)
