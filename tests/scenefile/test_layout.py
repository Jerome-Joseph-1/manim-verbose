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
    DOWN, FRAME_HEIGHT, FRAME_WIDTH, LEFT, RIGHT, UP, Arrow, Axes, BackgroundRectangle, Brace, Dot, Group,
    ImageMobject, Matrix, NumberLine, NumberPlane, Rectangle, Tex, Text, VGroup, VMobject,
)
from PIL import Image  # noqa: E402

from manim_verbose.scenefile import layout  # noqa: E402
from manim_verbose.scenefile.expressions import ExpressionError  # noqa: E402
from manim_verbose.scenefile.layout import (  # noqa: E402
    EDGES, function_graph, place, set_frame_shape, frame_shape, with_axis_labels, with_backdrop, with_brace_label,
    with_coordinates, with_label, with_numbers, with_round_brackets, with_row_colors, with_tip_label,
    with_underline,
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
