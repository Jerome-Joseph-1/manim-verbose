"""
A stand-in for blocks.py (objects to code) and layout.place, for testing steps and rendering
while the real ones are being written. It covers a handful of kinds (text, tex, circle,
square, rectangle, dot, vector, line, number_plane, group) with plain manim calls, which is all
a step needs of an object.

Tests ask for one of two fixtures:

    blocks_impl   the real blocks once they work (they stop raising NotImplementedError),
                  this stand-in until then, so the same tests run against the real thing
                  after integration
    fake_blocks   always this stand-in, for tests whose expected output (generated code,
                  golden images) would otherwise change with every change to how objects look

Either gives back "real" or "fake".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from manim_verbose.scenefile import blocks, layout
from manim_verbose.scenefile.codegen import CodegenContext, py_str
from manim_verbose.scenefile.model import (
    Document, FreeObject, ObjectBase, PlottedObject, SceneSpec, TextObject,
)
from manim_verbose.scenefile.validate import object_refs

EDGES = {
    "top": "UP", "bottom": "DOWN", "left": "LEFT", "right": "RIGHT",
    "top_left": "UL", "top_right": "UR", "bottom_left": "DL", "bottom_right": "DR",
}
SIDES = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT"}


def num(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else repr(value)


def color(value: str) -> str:
    return f'"{value}"' if value.startswith("#") else value


def point(obj: PlottedObject, coords: list[float], ctx: CodegenContext) -> str:
    if obj.on is not None:
        return f"{ctx.var(obj.on)}.c2p({', '.join(num(c) for c in coords)})"
    padded = list(coords) + [0] * (3 - len(coords))
    return "[" + ", ".join(num(c) for c in padded) + "]"


def t2c(obj) -> str:
    if not obj.colors:
        return ""
    return ", t2c={" + ", ".join(f"{py_str(k)}: {color(v)}" for k, v in obj.colors.items()) + "}"


def object_expression(obj: ObjectBase, ctx: CodegenContext) -> str:
    kind = obj.type
    if kind == "text":
        base = f"Text({py_str(obj.text)}, font_size={num(obj.font_size)}{t2c(obj)})"
    elif kind == "tex":
        base = f"Tex({py_str(obj.tex)}, font_size={num(obj.font_size)}{t2c(obj)})"
    elif kind == "circle":
        base = f"Circle(radius={num(obj.radius)})"
    elif kind == "square":
        base = f"Square(side_length={num(obj.side)})"
    elif kind == "rectangle":
        base = f"Rectangle(width={num(obj.width)}, height={num(obj.height)})"
    elif kind == "dot":
        base = f"Dot({point(obj, obj.point, ctx)}, radius={num(obj.radius)})"
    elif kind == "vector":
        base = f"Arrow({point(obj, obj.tail, ctx)}, {point(obj, obj.tip, ctx)}, buff=0)"
    elif kind == "line":
        name = "Arrow" if obj.arrow else ("DashedLine" if obj.dashed else "Line")
        extra = ", buff=0" if obj.arrow else ""
        base = f"{name}({point(obj, obj.start, ctx)}, {point(obj, obj.end, ctx)}{extra})"
    elif kind == "number_plane":
        base = f"NumberPlane(x_range={list(obj.x_range)}, y_range={list(obj.y_range)})"
    elif kind == "group":
        base = f"VGroup({', '.join(ctx.var(m) for m in obj.members)})"
        if obj.arrange != "none":
            base += f".arrange({'RIGHT' if obj.arrange == 'row' else 'DOWN'}, buff={num(obj.buff)})"
    else:
        raise NotImplementedError(f"the stand-in blocks don't build {kind} objects")

    chain = ""
    if obj.color is not None:
        chain += f".set_color({color(obj.color)})"
    fill = getattr(obj, "fill", None)
    if fill is not None:
        chain += f".set_fill({color(fill)}, opacity={num(obj.fill_opacity)})"
    if obj.opacity is not None:
        chain += f".set_opacity({num(obj.opacity)})"
    if obj.z:
        chain += f".set_z_index({obj.z})"
    if isinstance(obj, FreeObject):
        if obj.scale is not None:
            chain += f".scale({num(obj.scale)})"
        if obj.rotate is not None:
            chain += f".rotate({num(obj.rotate)} * DEG)"
        place = obj.place
        if place is not None:
            if place.at is not None:
                chain += f".move_to([{num(place.at[0])}, {num(place.at[1])}, 0])"
            elif place.edge == "center":
                chain += ".center()"
            elif place.edge in ("top", "bottom", "left", "right"):
                chain += f".to_edge({EDGES[place.edge]}, buff={num(place.buff)})"
            elif place.edge is not None:
                chain += f".to_corner({EDGES[place.edge]}, buff={num(place.buff)})"
            elif place.next_to is not None:
                chain += f".next_to({ctx.var(place.next_to)}, {SIDES[place.side]}, buff={num(place.buff)})"
            if place.shift is not None:
                chain += f".shift([{num(place.shift[0])}, {num(place.shift[1])}, 0])"
    return base + chain


def build_order(scene: SceneSpec) -> list[ObjectBase]:
    by_id = {obj.id: obj for obj in scene.objects}
    done: dict[str, ObjectBase] = {}

    def visit(obj: ObjectBase):
        if obj.id in done:
            return
        for _, ref, _ in object_refs(obj):
            if ref in by_id:
                visit(by_id[ref])
        done[obj.id] = obj

    for obj in scene.objects:
        visit(obj)
    return list(done.values())


def default_show_style(obj: ObjectBase) -> str:
    if obj.type in ("text", "tex"):
        return "write"
    if obj.type == "vector" or (obj.type == "line" and obj.arrow):
        return "grow"
    if obj.type == "group":
        return "fade"
    return "draw"


def default_hide_style(obj: ObjectBase) -> str:
    return "fade"


def part_selector(obj: ObjectBase, part: str, ctx: CodegenContext) -> str:
    return f"{ctx.var(obj.id)}[{py_str(part)}]"


def place(mob, at=None, edge=None, next_to=None, side="down", buff=0.25, shift=None):
    """layout.place as far as the stand-in needs it: the move step's `to` calls it at runtime."""
    from manimlib import DL, DOWN, DR, LEFT, RIGHT, UL, UP, UR
    directions = {
        "top": UP, "bottom": DOWN, "left": LEFT, "right": RIGHT,
        "top_left": UL, "top_right": UR, "bottom_left": DL, "bottom_right": DR,
        "up": UP, "down": DOWN,
    }
    if at is not None:
        mob.move_to([at[0], at[1], 0])
    elif edge == "center":
        mob.center()
    elif edge in ("top", "bottom", "left", "right"):
        mob.to_edge(directions[edge], buff=buff)
    elif edge is not None:
        mob.to_corner(directions[edge], buff=buff)
    elif next_to is not None:
        mob.next_to(next_to, directions[side], buff=buff)
    else:
        mob.center()
    if shift is not None:
        mob.shift([shift[0], shift[1], 0])
    return mob


FAKES = {
    "object_expression": object_expression,
    "build_order": build_order,
    "default_show_style": default_show_style,
    "default_hide_style": default_hide_style,
    "part_selector": part_selector,
}


def real_blocks_ready() -> bool:
    """Whether blocks.py (and layout.place) have been written, rather than still raising."""
    if not hasattr(layout, "place"):
        return False
    probe = SceneSpec(id="probe", objects=[TextObject(id="t", type="text", text="x")])
    ctx = CodegenContext(doc=Document(scenes=[probe]), scene=probe, objects={"t": probe.objects[0]}, base_dir=Path.cwd())
    try:
        blocks.build_order(probe)
        blocks.object_expression(probe.objects[0], ctx)
        blocks.default_show_style(probe.objects[0])
        blocks.default_hide_style(probe.objects[0])
        blocks.part_selector(probe.objects[0], "x", ctx)
    except NotImplementedError:
        return False
    return True


def use_fake_blocks(monkeypatch) -> None:
    from manim_verbose.scenefile import runtime
    for name, fake in FAKES.items():
        monkeypatch.setattr(blocks, name, fake)
    if not hasattr(layout, "place"):
        monkeypatch.setattr(runtime, "place", place, raising=False)


@pytest.fixture
def blocks_impl(monkeypatch) -> str:
    if real_blocks_ready():
        return "real"
    use_fake_blocks(monkeypatch)
    return "fake"


@pytest.fixture
def fake_blocks(monkeypatch) -> str:
    use_fake_blocks(monkeypatch)
    return "fake"
