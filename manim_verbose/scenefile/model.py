"""
What a scene file is: a video described as data rather than as code.

A document holds scenes, which play one after another. A scene holds objects and steps.
Objects are declared up front and are not on screen until a step shows them (or they are
marked `shown`). Steps run in order, and each takes some time on screen.

    version: 1
    title: Pythagoras
    scenes:
      - id: intro
        objects:
          - {id: tri, type: polygon, points: [[0, 0], [3, 0], [3, 2]], color: BLUE}
          - {id: eq, type: tex, tex: "a^2 + b^2 = c^2", place: top}
        steps:
          - {do: show, target: tri}
          - {do: show, target: eq, caption: "The oldest theorem you know"}
          - {do: highlight, target: eq, part: "c^2"}

These models are the one definition of the format. The json schema which the editor builds
its forms from is generated from them (see schema.py), and validate.py adds the checks a
model can't make on its own, such as a step naming an object which doesn't exist.

Some conventions which hold throughout:

- Positions on the frame are in manim's units: the origin is the centre, x runs across
  roughly [-7.1, 7.1] and y up across [-4, 4].
- Objects which live on a coordinate system (dots, vectors, lines, polygons, graphs) take
  their points in that system's coordinates when `on` names one, and in frame units otherwise.
- Angles are in degrees.
- A color is either a hex string ("#58C4DD") or one of manim's color names ("BLUE", "RED_E").
- Every field carrying `x-widget` in its schema tells the editor which input to draw for it.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator


ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _widget(name: str, **extra: Any) -> dict[str, Any]:
    return {"x-widget": name, **extra}


MAX_RANGE_STEPS = 500


def check_range(value: list[float]) -> list[float]:
    """A range has to be drawable: low to high, in steps which are positive and not too many."""
    if len(value) >= 2 and not value[0] < value[1]:
        raise ValueError("A range goes from the smaller number to the larger, as in [-5, 5]")
    if len(value) == 3:
        if not value[2] > 0:
            raise ValueError("The step of a range has to be more than 0, as in [-5, 5, 1]")
        if (value[1] - value[0]) / value[2] > MAX_RANGE_STEPS:
            raise ValueError(f"That range has more than {MAX_RANGE_STEPS} steps: make the step larger")
    return value


Id = Annotated[str, Field(pattern=ID_PATTERN, max_length=64)]
Point = Annotated[list[float], Field(min_length=2, max_length=3, json_schema_extra=_widget("point"))]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, json_schema_extra=_widget("point"))]
Range = Annotated[list[float], AfterValidator(check_range), Field(min_length=2, max_length=3, json_schema_extra=_widget("range"))]
TexString = Annotated[str, Field(json_schema_extra=_widget("tex"))]
MultilineString = Annotated[str, Field(json_schema_extra=_widget("multiline"))]


def ObjectRef(*types: str) -> Any:
    """
    A reference to another object in the same scene, by id. When types are given, the
    object referred to has to be one of them, which validate.py checks.
    """
    extra = _widget("object-ref")
    if types:
        extra["x-ref-types"] = list(types)
    return Annotated[str, Field(pattern=ID_PATTERN, json_schema_extra=extra)]


AnyRef = ObjectRef()
CoordinateSystemRef = ObjectRef("number_plane", "axes", "axes_3d", "number_line")
Targets = Union[AnyRef, list[AnyRef]]

Edge = Literal[
    "center", "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
]
Side = Literal["up", "down", "left", "right"]


@lru_cache(maxsize=1)
def manim_color_names() -> frozenset[str]:
    from manim_verbose.manim_import import import_manim
    constants = import_manim().constants
    return frozenset(
        name for name, value in vars(constants).items()
        if name.isupper() and isinstance(value, str) and value.startswith("#")
    )


def check_color(value: str) -> str:
    if HEX_COLOR.match(value):
        return value
    if value.upper() in manim_color_names():
        return value.upper()
    raise ValueError(
        f"'{value}' isn't a color. Use a hex code like \"#58C4DD\" or a manim color name like BLUE or RED_E"
    )


Color = Annotated[str, AfterValidator(check_color), Field(json_schema_extra=_widget("color"))]


class Model(BaseModel):
    # nan and inf aren't positions or sizes anything can be drawn at
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# Placement

class Placement(Model):
    """
    Where a free standing object sits on the frame. Give at most one of `at`, `edge` or
    `next_to`; with none of them the object is centred. `shift` then nudges it.

    An edge places the object against that edge and centred along it: `top` is top centre,
    `left` is middle left, and a corner such as `top_left` sets both. This holds for a move
    too, so moving to `top` also centres the object horizontally.

    In a file, `place: top` is short for `place: {edge: top}`, and `place: [1, 2]` for
    `place: {at: [1, 2]}`.
    """
    at: Point2 | None = Field(None, description="Position of the object's centre, in frame units, or in the coordinates of `on`")
    on: CoordinateSystemRef | None = Field(None, description="Read `at` as coordinates on this coordinate system")
    edge: Edge | None = Field(None, description="Push the object against an edge or corner of the frame, centred along it")
    next_to: AnyRef | None = Field(None, description="Put the object beside another one")
    anchor: Literal["center", "tip", "tail", "start", "end"] = Field(
        "center",
        description="Which part of `next_to` to go beside: the tip or tail of a vector, the start or end of a line, or the whole object",
    )
    follow: bool = Field(
        False, description="Stay beside `next_to` while it moves or changes, rather than only where it was at the start"
    )
    side: Side = Field("down", description="Which side of `next_to` to put it on")
    buff: float = Field(0.25, ge=0, description="Gap left against the edge, or against `next_to`")
    shift: Point2 | None = Field(None, description="Moved by this much afterwards, in frame units")

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"edge": data}
        if isinstance(data, (list, tuple)):
            return {"at": list(data)}
        return data

    @model_validator(mode="after")
    def _one_anchor(self):
        given = [name for name in ("at", "edge", "next_to") if getattr(self, name) is not None]
        if len(given) > 1:
            raise ValueError(f"Give only one of at, edge or next_to, not {' and '.join(given)}")
        if self.on is not None and self.at is None:
            raise ValueError("`on` says which coordinates `at` is in, so it needs `at`")
        if self.next_to is None and (self.anchor != "center" or self.follow):
            raise ValueError("`anchor` and `follow` say how to stay beside `next_to`, so they need `next_to`")
        return self


# Objects

class ObjectBase(Model):
    id: Id = Field(description="Name steps use to refer to this object")
    color: Color | None = None
    opacity: float | None = Field(None, ge=0, le=1)
    z: int = Field(0, description="Drawing order; higher is drawn on top")
    shown: bool = Field(False, description="On screen from the start of the scene, without being animated in")
    fixed: bool = Field(
        False, description="Stays put on the screen when the camera moves or turns, as labels in a 3D scene should"
    )


class FreeObject(ObjectBase):
    """An object placed on the frame as a whole, rather than by coordinates."""
    place: Placement | None = None
    scale: float | None = Field(None, gt=0)
    rotate: float | None = Field(None, description="Degrees, counterclockwise")
    backdrop: bool = Field(False, description="Put a dark panel behind the object, so it reads over a grid or other objects")


class PlottedObject(ObjectBase):
    """
    An object whose geometry is given by points, on a coordinate system if `on` names one.
    On a number line a point is [n, height]: n along the line, and a height above it in
    frame units.
    """
    on: CoordinateSystemRef | None = Field(None, description="Coordinate system the points are on; frame units if left out")


def _object_meta(label: str, category: str) -> ConfigDict:
    return ConfigDict(json_schema_extra={"x-label": label, "x-category": category})


class TextObject(FreeObject):
    """Plain text. Line breaks in the text are kept."""
    model_config = _object_meta("Text", "Text & math")
    type: Literal["text"]
    text: MultilineString
    font_size: float = Field(48, gt=0)
    font: str | None = None
    bold: bool = False
    italic: bool = False
    align: Literal["left", "center", "right"] = "center"
    colors: dict[str, Color] = Field(default_factory=dict, description="Color parts of the text: {part: color}")



class TexObject(FreeObject):
    """A LaTeX formula, in math mode."""
    model_config = _object_meta("Equation", "Text & math")
    type: Literal["tex"]
    tex: TexString
    font_size: float = Field(48, gt=0)
    colors: dict[str, Color] = Field(default_factory=dict, description="Color parts of the formula: {tex: color}")



class TitleObject(FreeObject):
    """A heading, at the top of the frame unless placed elsewhere."""
    model_config = _object_meta("Title", "Text & math")
    type: Literal["title"]
    text: str
    font_size: float = Field(60, gt=0)
    underline: bool = True


class QuoteObject(FreeObject):
    """A quotation, with its author beneath it."""
    model_config = _object_meta("Quote", "Text & math")
    type: Literal["quote"]
    text: MultilineString
    author: str | None = None
    font_size: float = Field(40, gt=0)


class BulletsObject(FreeObject):
    """A bulleted list, one item per line."""
    model_config = _object_meta("Bullet list", "Text & math")
    type: Literal["bullets"]
    items: list[str] = Field(min_length=1)
    font_size: float = Field(36, gt=0)
    buff: float = Field(0.3, ge=0, description="Gap between items")


class MatrixObject(FreeObject):
    """A matrix, or a column vector when it has one column. Entries are LaTeX."""
    model_config = _object_meta("Matrix", "Text & math")
    type: Literal["matrix"]
    entries: list[list[Union[str, float]]] = Field(min_length=1)
    bracket: Literal["square", "round"] = "square"
    font_size: float = Field(40, gt=0)
    row_colors: list[Color] = Field(default_factory=list)
    column_colors: list[Color] = Field(default_factory=list)


    @model_validator(mode="after")
    def _rectangular(self):
        widths = {len(row) for row in self.entries}
        if len(widths) != 1 or 0 in widths:
            raise ValueError("Every row of a matrix needs the same number of entries")
        return self


class NumberPlaneObject(FreeObject):
    """A grid with axes, filling the frame unless given a size."""
    model_config = _object_meta("Number plane", "Coordinates")
    type: Literal["number_plane"]
    x_range: Range = Field([-8, 8, 1], description="[min, max, step]")
    y_range: Range = Field([-4, 4, 1], description="[min, max, step]")
    width: float | None = Field(None, gt=0)
    height: float | None = Field(None, gt=0)
    faded: bool = Field(False, description="Draw the grid lines faintly")
    numbers: bool = Field(False, description="Label the axes with numbers")


class AxesObject(FreeObject):
    """A pair of axes."""
    model_config = _object_meta("Axes", "Coordinates")
    type: Literal["axes"]
    x_range: Range = Field([-6, 6, 1])
    y_range: Range = Field([-3, 3, 1])
    width: float | None = Field(None, gt=0)
    height: float | None = Field(None, gt=0)
    numbers: bool = True
    tips: bool = False
    x_label: TexString | None = None
    y_label: TexString | None = None


class Axes3DObject(FreeObject):
    """Three axes. Use a camera step with `orientation` to look at them from an angle."""
    model_config = _object_meta("3D axes", "Coordinates")
    type: Literal["axes_3d"]
    x_range: Range = Field([-5, 5, 1])
    y_range: Range = Field([-5, 5, 1])
    z_range: Range = Field([-3, 3, 1])
    numbers: bool = False
    x_label: TexString | None = Field(None, description="LaTeX label at the end of the x axis, kept facing the camera")
    y_label: TexString | None = Field(None, description="LaTeX label at the end of the y axis, kept facing the camera")
    z_label: TexString | None = Field(None, description="LaTeX label at the end of the z axis, kept facing the camera")


class NumberLineObject(FreeObject):
    """A number line."""
    model_config = _object_meta("Number line", "Coordinates")
    type: Literal["number_line"]
    x_range: Range = Field([-5, 5, 1])
    length: float | None = Field(None, gt=0)
    numbers: bool = True
    tip: bool = False


class DotObject(PlottedObject):
    """A dot at a point."""
    model_config = _object_meta("Dot", "Geometry")
    type: Literal["dot"]
    point: Point
    radius: float = Field(0.08, gt=0)
    label: TexString | None = None
    label_side: Side = "up"


class VectorObject(PlottedObject):
    """An arrow from `tail` to `tip`, from the origin unless a tail is given."""
    model_config = _object_meta("Vector", "Geometry")
    type: Literal["vector"]
    tip: Point
    tail: Point = Field([0, 0])
    thickness: float | None = Field(None, gt=0)
    label: TexString | None = Field(None, description="LaTeX label placed beside the tip, on `label_side`")
    label_side: Side = "right"
    show_coordinates: bool = Field(False, description="Show the tip's coordinates as a column vector beside it")
    coordinate_colors: list[Color] = Field(
        default_factory=list, description="Colors for the coordinates' rows, in order: x, y, z"
    )


class LineObject(PlottedObject):
    """A straight line, or an arrow when `arrow` is set."""
    model_config = _object_meta("Line", "Geometry")
    type: Literal["line"]
    start: Point
    end: Point
    dashed: bool = False
    arrow: bool = False
    thickness: float | None = Field(None, gt=0)


class PolygonObject(PlottedObject):
    """A closed shape through the given points."""
    model_config = _object_meta("Polygon", "Geometry")
    type: Literal["polygon"]
    points: list[Point] = Field(min_length=3)
    fill: Color | None = None
    fill_opacity: float = Field(0.5, ge=0, le=1)


class GraphObject(ObjectBase):
    """
    The graph of a function of x, on a set of axes. The function is written as an
    expression, such as "sin(x)" or "x**2 / 4", using + - * / ** and the usual functions.
    """
    model_config = _object_meta("Function graph", "Coordinates")
    type: Literal["graph"]
    on: ObjectRef("axes", "number_plane")
    function: str = Field(json_schema_extra=_widget("expression"))
    x_range: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    label: TexString | None = None


class CircleObject(FreeObject):
    """A circle."""
    model_config = _object_meta("Circle", "Shapes")
    type: Literal["circle"]
    radius: float = Field(1, gt=0)
    fill: Color | None = None
    fill_opacity: float = Field(0.5, ge=0, le=1)
    thickness: float | None = Field(None, ge=0)


class RectangleObject(FreeObject):
    """A rectangle, with rounded corners if given a corner radius."""
    model_config = _object_meta("Rectangle", "Shapes")
    type: Literal["rectangle"]
    width: float = Field(2, gt=0)
    height: float = Field(1, gt=0)
    corner_radius: float = Field(0, ge=0)
    fill: Color | None = None
    fill_opacity: float = Field(0.5, ge=0, le=1)
    thickness: float | None = Field(None, ge=0)


class SquareObject(FreeObject):
    """A square."""
    model_config = _object_meta("Square", "Shapes")
    type: Literal["square"]
    side: float = Field(2, gt=0)
    fill: Color | None = None
    fill_opacity: float = Field(0.5, ge=0, le=1)
    thickness: float | None = Field(None, ge=0)


class BraceObject(ObjectBase):
    """
    A curly brace, with an optional label: along one side of another object (or of a part of
    it), or between two points, bulging towards `side` of the line between them.
    """
    model_config = _object_meta("Brace", "Annotations")
    type: Literal["brace"]
    target: AnyRef | None = None
    part: str | None = Field(None, description="A piece of the target to pick out: some of its text or formula, or for a matrix \"row 2\", \"column 1\" or \"entry 2 1\" (counting from 1)")
    start: Point | None = Field(None, description="With `end`, brace the stretch between two points instead of an object")
    end: Point | None = None
    on: CoordinateSystemRef | None = Field(None, description="Coordinate system `start` and `end` are on; frame units if left out")
    side: Side = "down"
    label: TexString | None = None
    buff: float = Field(0.1, ge=0)

    @model_validator(mode="after")
    def _target_or_points(self):
        points = self.start is not None or self.end is not None
        if self.target is None and not (self.start is not None and self.end is not None):
            raise ValueError("A brace needs a `target`, or both `start` and `end`")
        if self.target is not None and points:
            raise ValueError("Give a brace either a `target` or `start` and `end`, not both")
        if self.part is not None and self.target is None:
            raise ValueError("`part` picks out a piece of `target`, so it needs `target`")
        if self.on is not None and not points:
            raise ValueError("`on` says which coordinates `start` and `end` are in, so it needs them")
        return self


class BoxObject(ObjectBase):
    """A rectangle drawn around another object."""
    model_config = _object_meta("Box around", "Annotations")
    type: Literal["box"]
    target: AnyRef
    part: str | None = Field(None, description="A piece of the target to pick out: some of its text or formula, or for a matrix \"row 2\", \"column 1\" or \"entry 2 1\" (counting from 1)")
    buff: float = Field(0.15, ge=0)
    corner_radius: float = Field(0, ge=0)
    fill_opacity: float = Field(0, ge=0, le=1)


class AngleObject(PlottedObject):
    """
    The angle at the middle of three points, drawn as an arc between the two lines, or as a
    small square when it is a right angle.
    """
    model_config = _object_meta("Angle", "Geometry")
    type: Literal["angle"]
    points: list[Point] = Field(min_length=3, max_length=3, description="[a, vertex, b]: the angle at the vertex, from a round to b")
    radius: float = Field(0.5, gt=0)
    right_angle: bool = Field(False, description="Draw the square mark of a right angle rather than an arc")
    other_side: bool = Field(False, description="Mark the angle the other way round, the larger one")
    label: TexString | None = None


class ArcObject(PlottedObject):
    """Part of a circle, counterclockwise from `start_angle` to `end_angle`, in degrees."""
    model_config = _object_meta("Arc", "Geometry")
    type: Literal["arc"]
    center: Point = Field([0, 0])
    radius: float = Field(1, gt=0)
    start_angle: float = 0
    end_angle: float = 90
    arrow: bool = Field(False, description="Put an arrow tip on the end")
    thickness: float | None = Field(None, gt=0)


class ImageObject(FreeObject):
    """A picture, from a file next to the scene file."""
    model_config = _object_meta("Image", "Media")
    type: Literal["image"]
    path: str = Field(json_schema_extra=_widget("file", accept="image/*"))
    height: float = Field(3, gt=0)


class SvgObject(FreeObject):
    """A vector drawing, from an .svg file next to the scene file."""
    model_config = _object_meta("SVG drawing", "Media")
    type: Literal["svg"]
    path: str = Field(json_schema_extra=_widget("file", accept=".svg"))
    height: float = Field(2, gt=0)


class GroupObject(FreeObject):
    """
    Several objects handled as one: shown, hidden, moved and highlighted together, and
    optionally arranged in a row or column.
    """
    model_config = _object_meta("Group", "Layout")
    type: Literal["group"]
    members: list[AnyRef] = Field(min_length=1)
    arrange: Literal["none", "row", "column"] = "none"
    buff: float = Field(0.5, ge=0, description="Gap between members when arranged")


AnyObject = Annotated[
    Union[
        TextObject, TexObject, TitleObject, QuoteObject, BulletsObject, MatrixObject,
        NumberPlaneObject, AxesObject, Axes3DObject, NumberLineObject, GraphObject,
        DotObject, VectorObject, LineObject, PolygonObject, AngleObject, ArcObject,
        CircleObject, RectangleObject, SquareObject,
        BraceObject, BoxObject,
        ImageObject, SvgObject,
        GroupObject,
    ],
    Field(discriminator="type"),
]

OBJECT_MODELS: dict[str, type[ObjectBase]] = {
    model.model_fields["type"].annotation.__args__[0]: model
    for model in AnyObject.__origin__.__args__
}


# Steps

class StepBase(Model):
    id: Id | None = Field(None, description="Filled in when the file is loaded, if left out")
    caption: str | None = Field(
        None,
        description="Subtitle shown from this step on, until another step changes it. An empty string clears it",
        json_schema_extra=_widget("multiline"),
    )
    run_time: float | None = Field(None, gt=0, le=600, description="Seconds; each kind of step has its own default")


def _step_meta(label: str) -> ConfigDict:
    return ConfigDict(json_schema_extra={"x-label": label})


class ShowStep(StepBase):
    """Bring objects onto the screen."""
    model_config = _step_meta("Show")
    do: Literal["show"]
    target: Targets
    style: Literal["auto", "write", "draw", "fade", "fade_up", "grow", "pop"] = Field(
        "auto", description="auto picks by kind of object: write for text, draw for shapes, grow for arrows"
    )
    lag: float = Field(0, ge=0, le=1, description="With several targets: 0 starts them together, 1 one after another")


class HideStep(StepBase):
    """Take objects off the screen."""
    model_config = _step_meta("Hide")
    do: Literal["hide"]
    target: Targets
    style: Literal["auto", "fade", "fade_down", "uncreate", "shrink"] = "auto"
    lag: float = Field(0, ge=0, le=1)


class AddStep(StepBase):
    """Put objects on the screen instantly."""
    model_config = _step_meta("Add")
    do: Literal["add"]
    target: Targets


class RemoveStep(StepBase):
    """Take objects off the screen instantly."""
    model_config = _step_meta("Remove")
    do: Literal["remove"]
    target: Targets


class ClearStep(StepBase):
    """Fade out everything on the screen, the caption included."""
    model_config = _step_meta("Clear screen")
    do: Literal["clear"]


class TransformStep(StepBase):
    """
    Turn one object into another. Afterwards `into` is on the screen and `target` is not,
    unless `keep` is set, in which case a copy of `target` is what turns into `into`.
    """
    model_config = _step_meta("Transform")
    do: Literal["transform"]
    target: AnyRef
    into: AnyRef
    style: Literal["auto", "morph", "match", "fade"] = Field(
        "auto", description="match moves matching parts of text or formulas to each other; auto uses it for those"
    )
    keep: bool | Literal["dim"] = Field(
        False, description="Leave `target` on screen and turn a copy of it into `into`; dim leaves it faded to show it's the original"
    )


class ChangeStep(StepBase):
    """
    Animate an object to new property values, such as {color: RED}, {tip: [2, 1]} or
    {text: "new words"}. The object keeps the new values for the rest of the scene.
    """
    model_config = _step_meta("Change")
    do: Literal["change"]
    target: AnyRef
    set: dict[str, Any] = Field(min_length=1, json_schema_extra=_widget("properties"))


class MoveStep(StepBase):
    """Move objects, either to a placement or by an offset."""
    model_config = _step_meta("Move")
    do: Literal["move"]
    target: Targets
    to: Placement | None = None
    by: Point2 | None = None

    @model_validator(mode="after")
    def _to_or_by(self):
        if (self.to is None) == (self.by is None):
            raise ValueError("A move needs exactly one of `to` or `by`")
        return self


class HighlightStep(StepBase):
    """
    Draw attention to an object, or to one part of a text or formula. Every style but
    recolor is momentary; recolor leaves the part in its new color.
    """
    model_config = _step_meta("Highlight")
    do: Literal["highlight"]
    target: AnyRef
    part: str | None = Field(None, description="A piece of the target to pick out: some of its text or formula, or for a matrix \"row 2\", \"column 1\" or \"entry 2 1\" (counting from 1)")
    style: Literal["indicate", "flash", "box", "underline", "wiggle", "recolor"] = "indicate"
    color: Color | None = None


class WaitStep(StepBase):
    """Hold still."""
    model_config = _step_meta("Wait")
    do: Literal["wait"]
    duration: float = Field(1, gt=0, le=600)

    @model_validator(mode="after")
    def _no_run_time(self):
        if self.run_time is not None:
            raise ValueError("A wait takes `duration`, not `run_time`")
        return self


class CameraStep(StepBase):
    """Move the camera: zoom, look at a point or an object, or turn it to look at 3D from an angle."""
    model_config = _step_meta("Camera")
    do: Literal["camera"]
    zoom: float | None = Field(None, gt=0, description="1 is the normal view, 2 twice as close")
    center: Point | None = None
    focus: AnyRef | None = Field(None, description="Centre on this object")
    orientation: Annotated[list[float], Field(min_length=2, max_length=3)] | None = Field(
        None, description="[theta, phi] or [theta, phi, gamma] in degrees, for 3D"
    )
    reset: bool = Field(False, description="Go back to the normal view")

    @model_validator(mode="after")
    def _something_to_do(self):
        if not (self.reset or any(v is not None for v in (self.zoom, self.center, self.focus, self.orientation))):
            raise ValueError("A camera step needs at least one of zoom, center, focus, orientation or reset")
        if self.center is not None and self.focus is not None:
            raise ValueError("Give only one of center or focus")
        return self


class ApplyMatrixStep(StepBase):
    """Apply a linear transformation, given as a matrix, to objects such as a number plane and vectors on it."""
    model_config = _step_meta("Apply matrix")
    do: Literal["apply_matrix"]
    target: Targets
    matrix: list[list[float]]

    @field_validator("matrix")
    @classmethod
    def _square(cls, value):
        n = len(value)
        if n not in (2, 3) or any(len(row) != n for row in value):
            raise ValueError("The matrix has to be 2x2 or 3x3")
        return value


class TogetherStep(StepBase):
    """
    Run several steps at the same time. With `lag` 0 they all start at once and the whole
    lasts as long as the longest; with a lag, each starts `lag` times the length of the one
    before it later than that one did. A `run_time` given here stretches or squeezes the
    whole to fit.
    """
    model_config = _step_meta("Together")
    do: Literal["together"]
    steps: list[AnyStep] = Field(min_length=2)
    lag: float = Field(0, ge=0, le=1, description="0 starts them all at once; above 0 staggers them")

    @field_validator("steps")
    @classmethod
    def _no_waits(cls, value):
        for step in value:
            if isinstance(step, (WaitStep, TogetherStep)):
                raise ValueError(f"A '{step.do}' step can't go inside 'together'")
        return value


AnyStep = Annotated[
    Union[
        ShowStep, HideStep, AddStep, RemoveStep, ClearStep,
        TransformStep, ChangeStep, MoveStep, HighlightStep,
        WaitStep, CameraStep, ApplyMatrixStep, TogetherStep,
    ],
    Field(discriminator="do"),
]
TogetherStep.model_rebuild()

STEP_MODELS: dict[str, type[StepBase]] = {
    model.model_fields["do"].annotation.__args__[0]: model
    for model in AnyStep.__origin__.__args__
}


# Scenes and documents

class CaptionSettings(Model):
    font_size: float = Field(30, gt=0)
    color: Color = "WHITE"
    edge: Literal["bottom", "top"] = "bottom"
    background: bool = Field(True, description="Put a dark band behind captions so they read over anything")


class Settings(Model):
    resolution: Annotated[list[int], Field(min_length=2, max_length=2)] = Field([1920, 1080])
    fps: int = Field(30, ge=1, le=120)
    background: Color | None = Field(None, description="Background color; manim's default if left out")
    font: str | None = Field(
        None, description="Font for all text and captions, unless an object names its own; manim's default if left out"
    )
    captions: CaptionSettings = Field(default_factory=CaptionSettings)


class SceneSpec(Model):
    """One part of the video, with its own objects and steps."""
    id: Id
    title: str | None = None
    background: Color | None = None
    carry: list[Id] = Field(
        default_factory=list,
        description="Objects from the scene before, on screen from the start as that scene left them, and usable here by id",
    )
    objects: list[AnyObject] = Field(default_factory=list)
    steps: list[AnyStep] = Field(default_factory=list)


class Document(Model):
    """A whole video."""
    version: Literal[1] = 1
    title: str = "Untitled"
    description: str | None = Field(None, description="What the video is about, in a sentence or two", json_schema_extra=_widget("multiline"))
    settings: Settings = Field(default_factory=Settings)
    scenes: list[SceneSpec] = Field(min_length=1)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"$id": "https://github.com/Jerome-Joseph-1/manim-verbose/scenefile/v1"},
    )


def iter_steps(steps: list[StepBase]):
    """Every step, including those nested inside 'together', depth first."""
    for step in steps:
        yield step
        if isinstance(step, TogetherStep):
            yield from iter_steps(step.steps)
