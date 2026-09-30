"""
Objects to code: for each kind of object in the scene file, the Python expression which
builds it as a manim mobject, styled and placed.

OWNER: objects agent.

Interface used by codegen.py and actions.py (keep these signatures):

    object_expression(obj, ctx) -> str
        One Python expression building the object: the mobject itself, then color, opacity,
        z, scale and rotation, then placement (via layout.place). It may refer to objects
        built before it through ctx.var(id), and to anything in manimlib and in
        manim_verbose.scenefile.runtime's namespace (which re-exports layout and expressions).

    build_order(scene) -> list[ObjectBase]
        The scene's objects in an order where everything an object refers to (next_to, on,
        brace and box targets, group members) comes before it. validate.py has already
        rejected cycles.

    default_show_style(obj) -> str     one of write, draw, fade, grow; what "show" with style auto uses
    default_hide_style(obj) -> str     one of fade, uncreate, shrink; what "hide" with style auto uses
    part_selector(obj, part, ctx) -> str
                                       expression selecting `part` of a text-like object built as
                                       ctx.var(obj.id), for highlight steps

What comes out is the code a person would write with manimlib, such as
`Arrow(plane.c2p(0, 0), plane.c2p(1, 2), buff=0).set_color(YELLOW)`, falling back on the
helpers in layout.py only where manimlib has no one-expression way to say it. The shapes of
what gets built, for code which acts on objects afterwards:

    text, tex                a Text / Tex
    title                    a Text, or with_underline's VGroup(text, line) when underlined
    quote                    VGroup(text) or VGroup(text, author); the quote is [0]
    bullets                  a VGroup of Texts, one per item
    matrix                   a Matrix
    number_plane, axes       a NumberPlane / Axes (VGroups, with c2p)
    axes_3d, number_line     a ThreeDAxes / NumberLine
    graph                    a VMobject, with any label as a submobject
    dot                      a Dot, with any label as a submobject
    vector                   an Arrow; label and coordinates are submobjects, so get_start,
                             get_end and GrowArrow still work
    line                     a Line, DashedLine or (with arrow) Arrow
    polygon, circle, rectangle, square
                             a Polygon / Circle / Rectangle or RoundedRectangle / Square
    brace                    a Brace, or VGroup(brace, label)
    box                      a SurroundingRectangle
    image                    an ImageMobject (not a VMobject)
    svg                      an SVGMobject
    group                    a VGroup of its members, or a Group if any member is an image

With `backdrop`, number planes, axes, 3D axes and matrices keep their type, the panel being
their first submobject; anything else becomes VGroup(panel, object) (Group for an image), the
object itself being [1]. part_selector and points on a number line look past the panel. With
`fixed`, the whole object is fixed in the frame (fix_in_frame), so it ignores camera moves.

Text a user typed is written into the code with repr (or as a raw string where that reads
better and round-trips exactly), so nothing typed can become code. Characters which can't be
drawn at all (control characters other than tab and line breaks, lone surrogates) are left
out, since Pango and LaTeX both refuse them.
"""
from __future__ import annotations

import ast
import heapq
import math
import re
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

from manim_verbose.scenefile.expressions import check_expression
from manim_verbose.scenefile.model import (
    HEX_COLOR, Axes3DObject, AxesObject, BoxObject, BraceObject, BulletsObject, CircleObject, DotObject,
    FreeObject, GraphObject, GroupObject, HighlightStep, ImageObject, LineObject, MatrixObject,
    NumberLineObject, NumberPlaneObject, ObjectBase, PolygonObject, QuoteObject, RectangleObject,
    SceneSpec, SquareObject, SvgObject, TexObject, TextObject, TitleObject, VectorObject,
    iter_steps, manim_color_names,
)
from manim_verbose.scenefile.validate import object_refs

if TYPE_CHECKING:
    # Only for annotations: codegen.py imports this module, so importing it back here would be circular
    from manim_verbose.scenefile.codegen import CodegenContext

__all__ = [
    "object_expression", "build_order", "default_show_style", "default_hide_style", "part_selector",
    "displayable", "LABEL_FONT_SIZE",
]

# Sizes of the small formulas attached to other objects: labels on dots, vectors, braces and graphs
LABEL_FONT_SIZE = 36

SIDE_NAMES = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT"}

# Characters Pango's markup and LaTeX both refuse: C0 controls but tab and newline, DEL and
# the C1 controls, lone surrogates, and the two noncharacters XML rules out
_UNDRAWABLE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff￾￿]")


def displayable(text: str) -> str:
    """text with what can't be drawn left out, and line breaks written \\n whichever way they came."""
    return _UNDRAWABLE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


# Writing values as code

def _num(value: float) -> str:
    """A number as Python source: 2 rather than 2.0, and never nan or inf, which aren't literals."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{value} isn't a number that can be drawn")
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


def _nums(values: Iterable[float]) -> str:
    return ", ".join(_num(v) for v in values)


def _list(values: Iterable[float]) -> str:
    return f"[{_nums(values)}]"


def _literal(text: str, prefix: str = "") -> str:
    """
    text as a string literal in double quotes, with an R prefix when asked, provided that
    reads back as exactly text; repr of it otherwise. repr always round-trips, so whatever
    text holds, the code it lands in keeps its shape. Without the R, a backslash would start
    an escape (or, as in "\\s", an invalid one Python warns about), so such text gets repr.
    """
    if text.isprintable() and (prefix or "\\" not in text):
        candidate = f'{prefix}"{text}"'
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                node = ast.parse(candidate, mode="eval").body
            except (SyntaxError, Warning):
                node = None
        if isinstance(node, ast.Constant) and node.value == text:
            return candidate
    return repr(text)


def _str(text: str) -> str:
    """Plain text as a string literal which reads back as exactly that text (less what can't be drawn)."""
    return _literal(displayable(text))


def _tex(text: str) -> str:
    """A LaTeX string as a literal: a raw string, R"\\frac{a}{b}", when it holds a backslash."""
    text = displayable(text)
    return _literal(text, "R" if "\\" in text else "")


def _color(value: str) -> str:
    """A color as code: the manim constant for a name, such as BLUE, or the hex string."""
    if HEX_COLOR.match(value):
        return _literal(value)
    name = value.upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", name) and name in manim_color_names():
        return name
    raise ValueError(f"'{value}' isn't a color")


def _color_map(colors: dict[str, str], literal: Callable[[str], str]) -> str:
    return "{" + ", ".join(f"{literal(part)}: {_color(color)}" for part, color in colors.items()) + "}"


def _font_name(font: str | None) -> str | None:
    """A font family name, keeping only characters font names use, since it goes into Pango's markup unescaped."""
    if not font:
        return None
    cleaned = re.sub(r"[^\w .,-]", "", font).strip()
    return cleaned or None


def _call(name: str, *args: str | None) -> str:
    return f"{name}({', '.join(a for a in args if a)})"


def _kw(name: str, value: str) -> str:
    return f"{name}={value}"


def _decimal_places(*values: float) -> int:
    """Decimal places needed to write every one of values, at most 3, for numbering an axis."""
    places = 0
    for value in values:
        for digits in range(4):
            if abs(round(value, digits) - value) < 1e-9:
                break
        places = max(places, digits)
    return places


def _range_numbers(values: Sequence[float]) -> tuple[float, ...]:
    return (values[0], values[2]) if len(values) > 2 else (values[0],)


# Looking things up

def _spec(ctx: CodegenContext, obj_id: str) -> ObjectBase:
    if obj_id in ctx.objects:
        return ctx.spec(obj_id)
    for obj in ctx.scene.objects:
        if obj.id == obj_id:
            return obj
    raise ValueError(f"There's no object called '{obj_id}' in scene '{ctx.scene.id}'")


def _var(ctx: CodegenContext, obj_id: str) -> str:
    _spec(ctx, obj_id)
    name = ctx.var(obj_id)
    if not name.isidentifier():
        raise ValueError(f"'{obj_id}' can't be used as a name in code")
    return name


def _wrapped(obj: ObjectBase) -> bool:
    """
    Whether the object is built as VGroup(backdrop, object) by with_backdrop, so that the
    object itself is [1]. Coordinate systems and matrices keep their own type instead.
    """
    return bool(getattr(obj, "backdrop", False)) and obj.type not in ("number_plane", "axes", "axes_3d", "matrix")


def _system(ctx: CodegenContext, obj_id: str) -> str:
    """The coordinate system called obj_id, as code, looking past a backdrop around a number line."""
    var = _var(ctx, obj_id)
    return f"{var}[1]" if _wrapped(_spec(ctx, obj_id)) else var


def _point(values: Sequence[float], on: str | None, ctx: CodegenContext) -> str:
    """
    A point given in the coordinates of the system `on`, or in frame units when there is
    none, as code: plane.c2p(1, 2), line.n2p(3) or [1, 2, 0].
    """
    if on is None:
        coords = list(values) + [0] * (3 - len(values))
        return _list(coords)
    system = _spec(ctx, on)
    var = _system(ctx, on)
    if system.type == "number_line":
        # [n, height]: n along the line, then height above it (and z out of the frame) in frame units
        expr = f"{var}.n2p({_num(values[0])})"
        for value, direction in zip(values[1:], ("UP", "OUT")):
            if float(value) != 0:
                sign = "+" if value > 0 else "-"
                expr += f" {sign} {_num(abs(value))} * {direction}"
        return expr
    return f"{var}.c2p({_nums(values)})"


def _highlight_parts(obj: ObjectBase, ctx: CodegenContext) -> list[str]:
    """Every part of obj some highlight step in the scene picks out, in order, once each."""
    parts: list[str] = []
    for step in iter_steps(ctx.scene.steps):
        if isinstance(step, HighlightStep) and step.target == obj.id and step.part:
            part = displayable(step.part)
            if part and part not in parts:
                parts.append(part)
    return parts


def _is_vectorized(obj_id: str, ctx: CodegenContext, seen: frozenset[str] = frozenset()) -> bool:
    """Whether the object is built as a VMobject, so that it can go in a VGroup."""
    if obj_id in seen:
        return True
    obj = _spec(ctx, obj_id)
    if isinstance(obj, ImageObject):
        return False
    if isinstance(obj, GroupObject):
        return all(_is_vectorized(m, ctx, seen | {obj_id}) for m in obj.members)
    return True


# Builders: each returns the expression making the object, and which of color and opacity
# it has already dealt with (the rest are applied the same way for every kind)

Built = tuple[str, set[str]]


def _text(obj: TextObject, ctx: CodegenContext) -> Built:
    args = [_str(obj.text)]
    if obj.font_size != 48:
        args.append(_kw("font_size", _num(obj.font_size)))
    font = _font_name(obj.font)
    if font:
        args.append(_kw("font", _literal(font)))
    if obj.bold:
        args.append("weight=BOLD")
    if obj.italic:
        args.append("slant=ITALIC")
    if obj.align != "center":
        args.append(_kw("alignment", _literal(obj.align.upper())))
    if obj.colors:
        args.append(_kw("t2c", _color_map(obj.colors, _str)))
    # fill_color rather than a later set_color, which would paint over the colored parts
    if obj.color:
        args.append(_kw("fill_color", _color(obj.color)))
    return _call("Text", *args), {"color"}


def _tex_object(obj: TexObject, ctx: CodegenContext) -> Built:
    args = [_tex(obj.tex)]
    if obj.font_size != 48:
        args.append(_kw("font_size", _num(obj.font_size)))
    if obj.colors:
        args.append(_kw("t2c", _color_map(obj.colors, _tex)))
    # Parts a highlight picks out are isolated, which is what makes selecting them exact
    parts = [p for p in _highlight_parts(obj, ctx) if p in displayable(obj.tex) and p not in obj.colors]
    if parts:
        args.append(_kw("isolate", "[" + ", ".join(_tex(p) for p in parts) + "]"))
    if obj.color:
        args.append(_kw("fill_color", _color(obj.color)))
    return _call("Tex", *args), {"color"}


def _title(obj: TitleObject, ctx: CodegenContext) -> Built:
    text = _call("Text", _str(obj.text), _kw("font_size", _num(obj.font_size)))
    return (f"with_underline({text})" if obj.underline else text), set()


QUOTE_MARKS = "\"'“”‘’«»„"


def _quote(obj: QuoteObject, ctx: CodegenContext) -> Built:
    words = displayable(obj.text)
    if not words or words[0] not in QUOTE_MARKS:
        words = f"“{words}”"
    quote = _call("Text", _literal(words), _kw("font_size", _num(obj.font_size)), "slant=ITALIC")
    # An author which comes to nothing once what can't be drawn is left out is no author
    if not displayable(obj.author or ""):
        return f"VGroup({quote})", set()
    author = _call("Text", _str(f"— {obj.author}"), _kw("font_size", _num(round(obj.font_size * 0.75, 2))))
    return f"VGroup({quote}, {author}).arrange(DOWN, aligned_edge=RIGHT, buff=0.3)", set()


def _bullets(obj: BulletsObject, ctx: CodegenContext) -> Built:
    items = []
    for item in obj.items:
        args = [_str(f"• {item}"), _kw("font_size", _num(obj.font_size))]
        if "\n" in displayable(item):
            args.append('alignment="LEFT"')
        items.append(_call("Text", *args))
    return f"VGroup({', '.join(items)}).arrange(DOWN, aligned_edge=LEFT, buff={_num(obj.buff)})", set()


def _matrix_entry(entry: str | float) -> str:
    if isinstance(entry, str):
        return _tex(entry)
    return _literal(_num(entry))


def _matrix(obj: MatrixObject, ctx: CodegenContext) -> Built:
    rows = ", ".join("[" + ", ".join(_matrix_entry(e) for e in row) + "]" for row in obj.entries)
    expr = f"Matrix([{rows}], element_config=dict(font_size={_num(obj.font_size)}))"
    if obj.bracket == "round":
        expr = f"with_round_brackets({expr})"
    # The color first, so that row and column colors are painted over it
    if obj.color:
        expr += f".set_color({_color(obj.color)})"
    if obj.row_colors:
        expr = f"with_row_colors({expr}, {', '.join(_color(c) for c in obj.row_colors)})"
    if obj.column_colors:
        expr += f".set_column_colors({', '.join(_color(c) for c in obj.column_colors)})"
    return expr, {"color"}


def _with_numbers(expr: str, *ranges: Sequence[float]) -> str:
    places = _decimal_places(*(v for r in ranges for v in _range_numbers(r)))
    extra = f", num_decimal_places={places}" if places else ""
    return f"with_numbers({expr}{extra})"


def _number_plane(obj: NumberPlaneObject, ctx: CodegenContext) -> Built:
    args = [_kw("x_range", _list(obj.x_range)), _kw("y_range", _list(obj.y_range))]
    if obj.width:
        args.append(_kw("width", _num(obj.width)))
    if obj.height:
        args.append(_kw("height", _num(obj.height)))
    if obj.color or obj.faded:
        color = _color(obj.color) if obj.color else "BLUE_D"
        opacity = "0.35" if obj.faded else "1"
        args.append(f"background_line_style=dict(stroke_color={color}, stroke_width=2, stroke_opacity={opacity})")
    if obj.faded:
        args.append("faded_line_style=dict(stroke_width=1, stroke_opacity=0.1)")
    expr = _call("NumberPlane", *args)
    if obj.numbers:
        expr = _with_numbers(expr, obj.x_range, obj.y_range)
    return expr, {"color"}


def _axes(obj: AxesObject, ctx: CodegenContext) -> Built:
    args = [_kw("x_range", _list(obj.x_range)), _kw("y_range", _list(obj.y_range))]
    if obj.width:
        args.append(_kw("width", _num(obj.width)))
    if obj.height:
        args.append(_kw("height", _num(obj.height)))
    if obj.tips:
        args.append("axis_config=dict(include_tip=True)")
    expr = _call("Axes", *args)
    if obj.numbers:
        expr = _with_numbers(expr, obj.x_range, obj.y_range)
    if obj.x_label is not None or obj.y_label is not None:
        labels = [
            _kw(name, _tex(value)) for name, value in (("x_label", obj.x_label), ("y_label", obj.y_label))
            if value is not None
        ]
        expr = _call("with_axis_labels", expr, *labels)
    return expr, set()


def _axes_3d(obj: Axes3DObject, ctx: CodegenContext) -> Built:
    expr = _call(
        "ThreeDAxes",
        _kw("x_range", _list(obj.x_range)), _kw("y_range", _list(obj.y_range)), _kw("z_range", _list(obj.z_range)),
    )
    if obj.numbers:
        expr = _with_numbers(expr, obj.x_range, obj.y_range)
    return expr, set()


def _number_line(obj: NumberLineObject, ctx: CodegenContext) -> Built:
    args = [_kw("x_range", _list(obj.x_range))]
    if obj.length:
        args.append(_kw("width", _num(obj.length)))
    if obj.numbers:
        args.append("include_numbers=True")
        places = _decimal_places(*_range_numbers(obj.x_range))
        if places:
            args.append(f"decimal_number_config=dict(num_decimal_places={places})")
    if obj.tip:
        args.append("include_tip=True")
    return _call("NumberLine", *args), set()


def _graph(obj: GraphObject, ctx: CodegenContext) -> Built:
    problem = check_expression(obj.function)
    if problem:
        raise ValueError(f"The function of '{obj.id}' can't be drawn: {problem}")
    args = [_var(ctx, obj.on), _literal(obj.function)]
    if obj.x_range is not None:
        args.append(_kw("x_range", _list(obj.x_range)))
    if obj.label is not None:
        args.append(_kw("label", _call("Tex", _tex(obj.label), _kw("font_size", str(LABEL_FONT_SIZE)))))
    return _call("function_graph", *args), set()


def _label(tex: str, font_size: int = LABEL_FONT_SIZE) -> str:
    return _call("Tex", _tex(tex), _kw("font_size", str(font_size)))


def _dot(obj: DotObject, ctx: CodegenContext) -> Built:
    args = [_point(obj.point, obj.on, ctx)]
    if obj.radius != 0.08:
        args.append(_kw("radius", _num(obj.radius)))
    expr = _call("Dot", *args)
    if obj.label is not None:
        expr = _call("with_label", expr, _label(obj.label), _literal(obj.label_side))
    return expr, set()


def _vector(obj: VectorObject, ctx: CodegenContext) -> Built:
    args = [_point(obj.tail, obj.on, ctx), _point(obj.tip, obj.on, ctx), "buff=0"]
    if obj.thickness is not None:
        args.append(_kw("thickness", _num(obj.thickness)))
    expr = _call("Arrow", *args)
    if obj.label is not None:
        expr = _call("with_tip_label", expr, _label(obj.label), _literal(obj.label_side))
    if obj.show_coordinates:
        expr = _call("with_coordinates", expr, _list(obj.tip))
    return expr, set()


def _line(obj: LineObject, ctx: CodegenContext) -> Built:
    start, end = _point(obj.start, obj.on, ctx), _point(obj.end, obj.on, ctx)
    width = obj.thickness
    if obj.arrow and not obj.dashed:
        return _call("Arrow", start, end, "buff=0", _kw("thickness", _num(width)) if width is not None else None), set()
    expr = _call("DashedLine" if obj.dashed else "Line", start, end)
    if width is not None:
        expr += f".set_stroke(width={_num(width)})"
    if obj.arrow:
        expr += ".add_tip()"
    return expr, set()


def _shape_style(obj) -> str:
    """
    Outline and fill of a closed shape. The outline takes the object's color, or the fill's
    when only a fill is given; opacity fades both, the fill on top of its own fill_opacity.
    """
    out = ""
    stroke_color = obj.color or obj.fill
    stroke = []
    if stroke_color:
        stroke.append(_color(stroke_color))
    thickness = getattr(obj, "thickness", None)
    if thickness is not None:
        stroke.append(_kw("width", _num(thickness)))
    if obj.opacity is not None:
        stroke.append(_kw("opacity", _num(obj.opacity)))
    if stroke:
        out += f".set_stroke({', '.join(stroke)})"
    if obj.fill is not None:
        opacity = obj.fill_opacity * (1 if obj.opacity is None else obj.opacity)
        out += f".set_fill({_color(obj.fill)}, opacity={_num(round(opacity, 6))})"
    return out


def _polygon(obj: PolygonObject, ctx: CodegenContext) -> Built:
    points = ", ".join(_point(p, obj.on, ctx) for p in obj.points)
    return f"Polygon({points})" + _shape_style(obj), {"color", "opacity"}


def _circle(obj: CircleObject, ctx: CodegenContext) -> Built:
    return f"Circle(radius={_num(obj.radius)})" + _shape_style(obj), {"color", "opacity"}


def _rectangle(obj: RectangleObject, ctx: CodegenContext) -> Built:
    size = f"width={_num(obj.width)}, height={_num(obj.height)}"
    if obj.corner_radius > 0:
        # A radius past half the shorter side would make the corners cross over
        radius = min(obj.corner_radius, 0.5 * min(obj.width, obj.height))
        expr = f"RoundedRectangle({size}, corner_radius={_num(radius)})"
    else:
        expr = f"Rectangle({size})"
    return expr + _shape_style(obj), {"color", "opacity"}


def _square(obj: SquareObject, ctx: CodegenContext) -> Built:
    return f"Square(side_length={_num(obj.side)})" + _shape_style(obj), {"color", "opacity"}


def _brace(obj: BraceObject, ctx: CodegenContext) -> Built:
    expr = _call("Brace", _var(ctx, obj.target), SIDE_NAMES[obj.side], _kw("buff", _num(obj.buff)))
    if obj.label is not None:
        expr = _call("with_brace_label", expr, _label(obj.label))
    return expr, set()


def _box(obj: BoxObject, ctx: CodegenContext) -> Built:
    args = [_var(ctx, obj.target), _kw("buff", _num(obj.buff))]
    if obj.color:
        args.append(_kw("color", _color(obj.color)))
    expr = _call("SurroundingRectangle", *args)
    if obj.corner_radius > 0:
        expr += f".round_corners({_num(obj.corner_radius)})"
    if obj.opacity is not None:
        expr += f".set_stroke(opacity={_num(obj.opacity)})"
    if obj.fill_opacity > 0:
        opacity = obj.fill_opacity * (1 if obj.opacity is None else obj.opacity)
        expr += f".set_fill({_color(obj.color) if obj.color else 'YELLOW'}, opacity={_num(round(opacity, 6))})"
    return expr, {"color", "opacity"}


def _file(path: str, ctx: CodegenContext) -> str:
    return _literal((Path(ctx.base_dir) / path.replace("\\", "/")).as_posix())


def _image(obj: ImageObject, ctx: CodegenContext) -> Built:
    # An image keeps its own colors: color is only for drawings
    return f"ImageMobject({_file(obj.path, ctx)}, height={_num(obj.height)})", {"color"}


def _svg(obj: SvgObject, ctx: CodegenContext) -> Built:
    return f"SVGMobject({_file(obj.path, ctx)}, height={_num(obj.height)})", set()


def _group(obj: GroupObject, ctx: CodegenContext) -> Built:
    members = list(dict.fromkeys(obj.members))
    kind = "VGroup" if all(_is_vectorized(m, ctx) for m in members) else "Group"
    expr = f"{kind}({', '.join(_var(ctx, m) for m in members)})"
    if obj.arrange != "none":
        direction = "RIGHT" if obj.arrange == "row" else "DOWN"
        expr += f".arrange({direction}, buff={_num(obj.buff)})"
    return expr, set()


BUILDERS: dict[str, Callable[[ObjectBase, CodegenContext], Built]] = {
    "text": _text, "tex": _tex_object, "title": _title, "quote": _quote, "bullets": _bullets,
    "matrix": _matrix, "number_plane": _number_plane, "axes": _axes, "axes_3d": _axes_3d,
    "number_line": _number_line, "graph": _graph, "dot": _dot, "vector": _vector, "line": _line,
    "polygon": _polygon, "circle": _circle, "rectangle": _rectangle, "square": _square,
    "brace": _brace, "box": _box, "image": _image, "svg": _svg, "group": _group,
}

# Kinds made of many parts whose opacities differ on purpose (a plane's faint grid lines, a
# group's members): opacity scales them all with fade rather than setting one value for all
FADED_BY_OPACITY = {"number_plane", "group"}


def object_expression(obj: ObjectBase, ctx: CodegenContext) -> str:
    try:
        builder = BUILDERS[obj.type]
    except KeyError:
        raise ValueError(f"There's no kind of object called '{obj.type}'") from None
    expr, handled = builder(obj, ctx)
    if obj.color is not None and "color" not in handled:
        expr += f".set_color({_color(obj.color)})"
    if obj.opacity is not None and "opacity" not in handled:
        # Only VMobject.fade returns the mobject; a Group's (one holding an image) returns None
        if obj.type in FADED_BY_OPACITY and _is_vectorized(obj.id, ctx):
            expr += f".fade({_num(round(1 - obj.opacity, 6))})"
        else:
            expr += f".set_opacity({_num(obj.opacity)})"
    # After color and opacity, which would otherwise repaint the panel, and before scale and
    # rotation, so the panel turns with what it is behind
    if isinstance(obj, FreeObject) and obj.backdrop:
        expr = f"with_backdrop({expr})"
    if obj.z:
        expr += f".set_z_index({int(obj.z)})"
    if isinstance(obj, FreeObject):
        if obj.scale is not None and obj.scale != 1:
            expr += f".scale({_num(obj.scale)})"
        if obj.rotate:
            expr += f".rotate({_num(obj.rotate)} * DEGREES)"
    if obj.fixed:
        expr += ".fix_in_frame()"
    if isinstance(obj, FreeObject):
        expr = _placed(expr, obj, ctx)
    return expr


def _placed(expr: str, obj: FreeObject, ctx: CodegenContext) -> str:
    placement = obj.place
    if placement is None:
        if isinstance(obj, TitleObject):
            return f'place({expr}, edge="top")'
        # Everything is built centred already, and a group left alone stays where its members are
        return expr
    args = [expr]
    if placement.at is not None:
        args.append(_kw("at", _list(placement.at)))
        if placement.on is not None:
            args.append(_kw("on", _system(ctx, placement.on)))
    elif placement.edge is not None:
        args.append(_kw("edge", _literal(placement.edge)))
    elif placement.next_to is not None:
        args.append(_kw("next_to", _var(ctx, placement.next_to)))
        if placement.side != "down":
            args.append(_kw("side", _literal(placement.side)))
    if placement.buff != 0.25:
        args.append(_kw("buff", _num(placement.buff)))
    if placement.shift is not None:
        args.append(_kw("shift", _list(placement.shift)))
    return _call("place", *args)


# Order, styles and parts

def build_order(scene: SceneSpec) -> list[ObjectBase]:
    """
    The scene's objects with each after everything it refers to, and otherwise in the order
    the file lists them. Should a cycle have got past validation, its objects come last, in
    file order, rather than being dropped.
    """
    objects = list(scene.objects)
    first = {}
    for index, obj in enumerate(objects):
        first.setdefault(obj.id, index)
    waiting_on = [
        {first[ref] for _, ref, _ in object_refs(obj) if ref in first and first[ref] != index}
        for index, obj in enumerate(objects)
    ]
    needed_by: dict[int, list[int]] = {i: [] for i in range(len(objects))}
    for index, deps in enumerate(waiting_on):
        for dep in deps:
            needed_by[dep].append(index)
    ready = [i for i, deps in enumerate(waiting_on) if not deps]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        index = heapq.heappop(ready)
        order.append(index)
        for later in needed_by[index]:
            waiting_on[later].discard(index)
            if not waiting_on[later]:
                heapq.heappush(ready, later)
    placed = set(order)
    order += [i for i in range(len(objects)) if i not in placed]
    return [objects[i] for i in order]


SHOW_STYLES = {
    "text": "write", "tex": "write", "title": "write", "quote": "write", "bullets": "write", "matrix": "write",
    "number_plane": "draw", "axes": "draw", "axes_3d": "draw", "number_line": "draw", "graph": "draw",
    "line": "draw", "polygon": "draw", "circle": "draw", "rectangle": "draw", "square": "draw",
    "brace": "draw", "box": "draw",
    "dot": "grow", "vector": "grow",
    "image": "fade", "svg": "fade", "group": "fade",
}

HIDE_STYLES = {
    "graph": "uncreate", "line": "uncreate", "polygon": "uncreate", "circle": "uncreate",
    "rectangle": "uncreate", "square": "uncreate", "brace": "uncreate", "box": "uncreate",
    "dot": "shrink",
}


def default_show_style(obj: ObjectBase) -> str:
    """write for text and formulas, draw for shapes and coordinate systems, grow for dots, vectors and arrows, fade for the rest."""
    if isinstance(obj, LineObject) and obj.arrow:
        return "grow"
    return SHOW_STYLES.get(obj.type, "fade")


def default_hide_style(obj: ObjectBase) -> str:
    """uncreate for outlines and curves, shrink for dots, fade for everything else."""
    return HIDE_STYLES.get(obj.type, "fade")


def part_selector(obj: ObjectBase, part: str, ctx: CodegenContext) -> str:
    """
    An expression for the glyphs of `part` within the text-like object built as
    ctx.var(obj.id), such as eq["c^2"]: every place the part occurs, as a VGroup of VGroups.
    Formulas isolate the parts their highlights name (see _tex_object), which is what
    makes this exact for them; plain text is exact without that.
    """
    var = _var(ctx, obj.id) + ("[1]" if _wrapped(obj) else "")
    if isinstance(obj, TexObject):
        return f"{var}[{_tex(part)}]"
    if isinstance(obj, TextObject) or (isinstance(obj, TitleObject) and not obj.underline):
        return f"{var}[{_str(part)}]"
    if isinstance(obj, (TitleObject, QuoteObject)):
        return f"{var}[0][{_str(part)}]"
    raise ValueError(
        f"Only parts of text, formulas, titles and quotes can be picked out, and '{obj.id}' is a {obj.type}"
    )
