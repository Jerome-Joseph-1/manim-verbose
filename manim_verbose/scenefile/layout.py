"""
Placement helpers which generated code calls at runtime: putting a mobject against an edge,
beside another, at a point, arranging a group. Kept as plain functions returning the mobject,
so that generated code reads as one expression per object.

OWNER: objects agent. Re-exported by runtime.py, so generated code can call these unqualified.

    place(mob, at=None, edge=None, next_to=None, side="down", buff=0.25, shift=None, on=None) -> mob

Alongside place are the few builders generated code needs where manimlib has no way of making
something in one expression: a label added to a dot or beside a vector's tip, a matrix with
round brackets, axes with their numbers, the graph of a typed formula, a dark panel behind
an object. Each takes the mobject it works on first and returns it (or the group it made), so
they nest like the rest.

Everything is measured against the frame the scene starts with: frame_shape() is manim's
default frame unless the scene has said otherwise with set_frame_shape, which a scene of an
unusual aspect ratio has to do before building its objects.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np

from manim_verbose.manim_import import import_manim

import_manim()

from manimlib.constants import DL, DOWN, DR, FRAME_HEIGHT, FRAME_WIDTH, LEFT, ORIGIN, OUT, RIGHT, UL, UP, UR, YELLOW
from manimlib.mobject.coordinate_systems import CoordinateSystem
from manimlib.mobject.matrix import Matrix
from manimlib.mobject.mobject import Group, Mobject
from manimlib.mobject.shape_matchers import BackgroundRectangle, Underline
from manimlib.mobject.svg.tex_mobject import Tex
from manimlib.mobject.types.vectorized_mobject import VGroup, VMobject

from manim_verbose.scenefile.expressions import SafeFunction, safe_function

__all__ = [
    "place", "frame_shape", "set_frame_shape", "SIDES", "EDGES",
    "with_underline", "with_label", "with_tip_label", "with_coordinates", "with_brace_label",
    "with_round_brackets", "with_row_colors", "with_numbers", "with_axis_labels", "with_backdrop",
    "point_on", "function_graph",
]

SIDES: dict[str, np.ndarray] = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT}
EDGES: dict[str, np.ndarray] = {
    "center": ORIGIN, "top": UP, "bottom": DOWN, "left": LEFT, "right": RIGHT,
    "top_left": UL, "top_right": UR, "bottom_left": DL, "bottom_right": DR,
}

_frame_shape: tuple[float, float] | None = None


def frame_shape() -> tuple[float, float]:
    """Width and height of the frame objects are placed in, in manim units."""
    return _frame_shape or (FRAME_WIDTH, FRAME_HEIGHT)


def set_frame_shape(width: float, height: float) -> None:
    """Use a frame of this size from now on, as a scene whose resolution isn't 16:9 has."""
    global _frame_shape
    _frame_shape = (float(width), float(height))


def _direction(side: str | Sequence[float]) -> np.ndarray:
    if isinstance(side, str):
        try:
            return SIDES[side]
        except KeyError:
            raise ValueError(f"'{side}' isn't a side: use one of {', '.join(SIDES)}") from None
    vect = np.zeros(3)
    vect[:len(side)] = side
    return vect


def _point(value: Sequence[float]) -> np.ndarray:
    point = np.zeros(3)
    point[:len(value)] = value
    return point


def point_on(system: Mobject, coords: Sequence[float]) -> np.ndarray:
    """
    Where coordinates on a coordinate system are in the frame: c2p for axes and planes, and
    for a number line [n, height], n along the line and height above it in frame units.
    """
    if hasattr(system, "c2p"):
        return system.c2p(*coords)
    if hasattr(system, "n2p"):
        point = system.n2p(coords[0])
        for value, direction in zip(coords[1:], (UP, OUT)):
            point = point + value * direction
        return point
    raise TypeError(f"{type(system).__name__} isn't a coordinate system")


# Placement

def place(
    mob: Mobject,
    at: Sequence[float] | None = None,
    edge: str | None = None,
    next_to: Mobject | None = None,
    side: str = "down",
    buff: float = 0.25,
    shift: Sequence[float] | None = None,
    on: Mobject | None = None,
) -> Mobject:
    """
    Put mob where a scene file's `place` says, and return it. With none of at, edge and
    next_to it is centred.

    `at` is the centre, in frame units, or in the coordinates of `on` when it is given.
    An edge puts mob against that edge and centred along it (top centre, middle left, and a
    corner both ways), keeping the whole of it inside the frame, `buff` in from the border,
    and shrinking it if it wouldn't otherwise fit. Beside another object, mob keeps clear of
    that object and is only slid along that side if it would stick out of the frame.
    """
    anchors = [name for name, value in (("at", at), ("edge", edge), ("next_to", next_to)) if value is not None]
    if len(anchors) > 1:
        raise ValueError(f"Give only one of at, edge or next_to, not {' and '.join(anchors)}")
    if on is not None and at is None:
        raise ValueError("`on` says which coordinates `at` is in, so it needs `at`")
    if at is not None:
        mob.move_to(point_on(on, at) if on is not None else _point(at))
    elif edge is not None:
        if edge not in EDGES:
            raise ValueError(f"'{edge}' isn't an edge: use one of {', '.join(EDGES)}")
        if edge == "center":
            mob.move_to(ORIGIN)
        else:
            _against_edge(mob, EDGES[edge], buff)
    elif next_to is not None:
        direction = _direction(side)
        mob.next_to(next_to, direction, buff=buff)
        _slide_inside(mob, axes=[i for i in (0, 1) if direction[i] == 0], buff=buff)
    else:
        mob.move_to(ORIGIN)
    if shift is not None:
        mob.shift(_point(shift))
    return mob


def _against_edge(mob: Mobject, direction: np.ndarray, buff: float):
    width, height = frame_shape()
    room = np.array([width - 2 * buff, height - 2 * buff])
    size = np.array([mob.get_width(), mob.get_height()])
    too_big = [r / s for r, s in zip(room, size) if s > r > 0]
    if too_big:
        mob.scale(min(too_big) * (1 - 1e-6))
    for dim in (0, 1):
        limit = (width, height)[dim] / 2 - buff
        low, high = mob.get_bounding_box()[0][dim], mob.get_bounding_box()[2][dim]
        if direction[dim] > 0:
            mob.shift((limit - high) * _unit(dim))
        elif direction[dim] < 0:
            mob.shift((-limit - low) * _unit(dim))
        else:
            mob.shift(-(low + high) / 2 * _unit(dim))


def _slide_inside(mob: Mobject, axes: Sequence[int], buff: float):
    """Slide mob along the given axes until it is inside the frame, or centre it on them if it can't fit."""
    shape = frame_shape()
    for dim in axes:
        limit = shape[dim] / 2 - buff
        low, high = mob.get_bounding_box()[0][dim], mob.get_bounding_box()[2][dim]
        if high - low > 2 * limit:
            mob.shift(-(low + high) / 2 * _unit(dim))
        elif low < -limit:
            mob.shift((-limit - low) * _unit(dim))
        elif high > limit:
            mob.shift((limit - high) * _unit(dim))


def _unit(dim: int) -> np.ndarray:
    vect = np.zeros(3)
    vect[dim] = 1
    return vect


def _overlap(a: Mobject, b: Mobject, gap: float = 0.0) -> bool:
    (ax0, ay0, _), _, (ax1, ay1, _) = a.get_bounding_box()
    (bx0, by0, _), _, (bx1, by1, _) = b.get_bounding_box()
    return ax0 < bx1 + gap and bx0 < ax1 + gap and ay0 < by1 + gap and by0 < ay1 + gap


# Composition

def with_underline(mob: Mobject, buff: float = 0.15) -> VGroup:
    """mob with a line under it, as a group of the two: [0] is mob, [1] the line."""
    return VGroup(mob, Underline(mob, buff=buff))


def with_label(mob: Mobject, label: Mobject, side: str = "up", buff: float = 0.15) -> Mobject:
    """mob with label added to it as a submobject, beside it on `side`."""
    label.next_to(mob, _direction(side), buff=buff)
    mob.add(label)
    return mob


def with_tip_label(arrow: Mobject, label: Mobject, side: str = "right", buff: float = 0.15) -> Mobject:
    """An arrow with label added to it, beside its tip on `side`."""
    label.next_to(arrow.get_end(), _direction(side), buff=buff)
    arrow.add(label)
    return arrow


def with_coordinates(
    arrow: Mobject,
    coordinates: Sequence[str | float] | Mobject,
    buff: float = 0.2,
    font_size: float = 30,
) -> Mobject:
    """
    An arrow with its coordinates added beyond its tip, as a column matrix unless given as a
    mobject already. They carry on in the direction the arrow points, so they never sit on
    the arrow itself, and move further out if they would cover a label added before them.
    """
    if not isinstance(coordinates, Mobject):
        entries = [[c if isinstance(c, str) else _number_text(c)] for c in coordinates]
        coordinates = Matrix(entries, v_buff=0.3, element_config=dict(font_size=font_size))
    start, end = arrow.get_start(), arrow.get_end()
    direction = _compass(end - start)
    coordinates.next_to(end, direction, buff=buff)
    for other in arrow.submobjects:
        if _overlap(coordinates, other, gap=0.05):
            coordinates.next_to(other, direction, buff=buff)
    arrow.add(coordinates)
    return arrow


def _number_text(value: float) -> str:
    """2 rather than 2.0, as a person would write a coordinate."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _compass(vect: np.ndarray) -> np.ndarray:
    """The nearest of the eight directions manim's next_to reads, such as RIGHT or UR, for a vector in the plane."""
    if np.hypot(vect[0], vect[1]) < 1e-6:
        return RIGHT
    k = round(math.atan2(vect[1], vect[0]) / (math.pi / 4))
    angle = k * math.pi / 4
    return np.array([round(math.cos(angle)), round(math.sin(angle)), 0.0])


def with_brace_label(brace: Mobject, label: Mobject, buff: float = 0.15) -> VGroup:
    """A brace and its label at the brace's tip, as a group: [0] is the brace, [1] the label."""
    brace.put_at_tip(label, buff=buff)
    return VGroup(brace, label)


def with_round_brackets(matrix: VMobject) -> VMobject:
    """A Matrix with its square brackets swapped for round ones of the same size."""
    # A group made afresh, since Matrix.rows sits outside the matrix's family and keeps the
    # bounding box it had before the matrix was centred
    entries = VGroup(*matrix.elements)
    parens = Tex(R"\left(\begin{array}{c}" + len(matrix.get_rows()) * R"\quad \\" + R"\end{array}\right)")
    half = len(parens) // 2
    new = VGroup(VGroup(*parens[:half]), VGroup(*parens[half:]))
    for bracket, old, side in zip(new, matrix.brackets, (LEFT, RIGHT)):
        gap = abs(old.get_edge_center(-side)[0] - entries.get_edge_center(side)[0])
        bracket.set_height(old.get_height())
        bracket.next_to(entries, side, buff=gap)
        bracket.match_style(old)
    matrix.remove(*matrix.brackets)
    matrix.add(*new)
    matrix.brackets = new
    matrix.draw_fills_together_if_disjoint()
    return matrix


def with_backdrop(mob: Mobject, buff: float = 0.15, opacity: float = 0.75) -> Mobject:
    """
    mob with a panel of the background color behind it, so it reads over a grid, as part of
    it so that it moves and fades along. Coordinate systems and matrices take the panel as
    their first submobject and stay what they were, so c2p and get_rows still work; anything
    else becomes a group of the two, the panel [0] and mob [1], since a panel added inside a
    text would throw out the indices its parts are found by, and one added inside a shape
    with an outline of its own would be drawn over that outline.
    """
    backdrop = BackgroundRectangle(mob, buff=buff, fill_opacity=opacity)
    if isinstance(mob, (CoordinateSystem, Matrix)):
        mob.add_to_back(backdrop)
        return mob
    return (VGroup if isinstance(mob, VMobject) else Group)(backdrop, mob)


def with_row_colors(matrix: VMobject, *colors) -> VMobject:
    """A Matrix with each row colored in turn, as set_column_colors does for columns."""
    for color, row in zip(colors, matrix.get_rows()):
        row.set_color(color)
    return matrix


def with_numbers(axes: Mobject, font_size: float = 24, num_decimal_places: int = 0) -> Mobject:
    """Axes or a number plane with numbers along its x and y axes, leaving out 0."""
    axes.add_coordinate_labels(font_size=font_size, num_decimal_places=num_decimal_places)
    return axes


def with_axis_labels(axes: Mobject, x_label: str | None = None, y_label: str | None = None, font_size: float = 36) -> Mobject:
    """Axes with a formula labelling the end of the x axis, the y axis, or both."""
    if x_label is not None:
        axes.add(axes.get_x_axis_label(x_label, font_size=font_size))
    if y_label is not None:
        axes.add(axes.get_y_axis_label(y_label, font_size=font_size))
    return axes


# Graphs

GRAPH_SAMPLES = 600
BISECTIONS = 40


def function_graph(
    axes: Mobject,
    function: str | Callable[[float], float],
    x_range: Sequence[float] | None = None,
    label: Mobject | None = None,
    color=YELLOW,
) -> VMobject:
    """
    The graph of a function of x on a set of axes, with an optional label near its right
    hand end. The function is a formula such as "sin(x)", read by safe_function, or a callable.

    Only the part inside the axes' y range is drawn, and the curve is broken wherever the
    function has no value (the left half of sqrt(x)), jumps (floor(x)) or runs off to
    infinity (tan(x)), rather than joining the pieces with steep lines. The ends of each
    piece are found by bisection, so sqrt(x) really does start at 0.
    """
    f = function if callable(function) else safe_function(function)
    x_min, x_max = (x_range if x_range is not None else axes.x_range)[:2]
    y_min, y_max = axes.y_range[:2]
    graph = VMobject()
    graph.set_stroke(color, width=4)
    pieces = _graph_pieces(_finite(f), float(x_min), float(x_max), float(y_min), float(y_max))
    for xs, ys in pieces:
        points = np.array([axes.c2p(x, y) for x, y in zip(xs, ys)])
        graph.start_new_path(points[0])
        graph.add_points_as_corners(points[1:])
    if graph.has_points():
        graph.make_smooth(approx=True)
    else:
        origin = axes.c2p(0, 0)
        graph.start_new_path(origin)
        graph.add_line_to(origin)
    graph.underlying_function = f
    graph.x_range = [x_min, x_max]
    if label is not None and pieces:
        xs, ys = pieces[-1]
        label.match_color(graph)
        end = axes.c2p(xs[-1], ys[-1])
        tangent = end - axes.c2p(xs[-2], ys[-2])
        normal = np.array([-tangent[1], tangent[0], 0.0])
        length = np.hypot(normal[0], normal[1])
        normal = normal / length if length > 0 else UP
        if normal[1] < 0:
            normal = -normal
        # Above the curve, and leaning right, past the end
        label.next_to(end, _compass(normal + 0.7 * RIGHT), buff=0.15)
        _slide_inside(label, axes=(0, 1), buff=0.1)
        graph.add(label)
    return graph


def _finite(f: Callable[[float], float]) -> Callable[[float], float]:
    def value(x: float) -> float:
        try:
            y = float(f(x))
        except (ArithmeticError, ValueError, TypeError):
            return math.nan
        return y if math.isfinite(y) else math.nan
    return value


def _graph_pieces(f, x_min: float, x_max: float, y_min: float, y_max: float) -> list[tuple[list[float], list[float]]]:
    """
    Sample f over [x_min, x_max] and split it into pieces which can each be drawn as one
    curve, clipped to [y_min, y_max]. Each piece is a list of xs and a list of ys.
    """
    if not x_max > x_min or not y_max > y_min:
        return []
    xs = np.linspace(x_min, x_max, GRAPH_SAMPLES + 1)
    ys = [f(x) for x in xs]
    height = y_max - y_min

    def inside(y: float) -> bool:
        return y_min <= y <= y_max

    pieces: list[tuple[list[float], list[float]]] = []
    current: tuple[list[float], list[float]] | None = None
    for i, (x, y) in enumerate(zip(xs, ys)):
        if not math.isnan(y) and inside(y):
            if current is None:
                current = ([], [])
                if i > 0:
                    # Coming in from outside: start where the function enters
                    ex, ey = _boundary(f, xs[i - 1], x, y_min, y_max)
                    current[0].append(ex)
                    current[1].append(ey)
            elif _jumps(f, xs[i - 1], x, ys[i - 1], y, height):
                pieces.append(current)
                current = ([], [])
            current[0].append(x)
            current[1].append(y)
        elif current is not None:
            ex, ey = _boundary(f, x, xs[i - 1], y_min, y_max)
            current[0].append(ex)
            current[1].append(ey)
            pieces.append(current)
            current = None
    if current is not None:
        pieces.append(current)
    return [(px, py) for px, py in pieces if len(px) > 1]


def _boundary(f, x_out: float, x_in: float, y_min: float, y_max: float) -> tuple[float, float]:
    """
    Where, between a point outside the drawn region and one inside it, the graph crosses
    its edge: the last point inside, found by bisection, which is on the top or bottom when
    the graph leaves that way and at the end of the function's domain when it stops there.
    """
    last_in = f(x_in)
    for _ in range(BISECTIONS):
        mid = (x_out + x_in) / 2
        y = f(mid)
        if not math.isnan(y) and y_min <= y <= y_max:
            x_in, last_in = mid, y
        else:
            x_out = mid
    return x_in, last_in


def _jumps(f, x0: float, x1: float, y0: float, y1: float, height: float) -> bool:
    """Whether f jumps between x0 and x1, rather than just being steep there."""
    if abs(y1 - y0) < 0.05 * height:
        return False
    for _ in range(BISECTIONS):
        mid = (x0 + x1) / 2
        y = f(mid)
        if math.isnan(y):
            return True
        if abs(y - y0) > abs(y1 - y):
            x1, y1 = mid, y
        else:
            x0, y0 = mid, y
    return abs(y1 - y0) > 0.01 * height
