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
    part_selector(obj, part) -> str    expression selecting `part` of a text-like object built as
                                       ctx.var(obj.id), for highlight steps
"""
from __future__ import annotations

from manim_verbose.scenefile.codegen import CodegenContext
from manim_verbose.scenefile.model import ObjectBase, SceneSpec


def object_expression(obj: ObjectBase, ctx: CodegenContext) -> str:
    raise NotImplementedError


def build_order(scene: SceneSpec) -> list[ObjectBase]:
    raise NotImplementedError


def default_show_style(obj: ObjectBase) -> str:
    raise NotImplementedError


def default_hide_style(obj: ObjectBase) -> str:
    raise NotImplementedError


def part_selector(obj: ObjectBase, part: str, ctx: CodegenContext) -> str:
    raise NotImplementedError
