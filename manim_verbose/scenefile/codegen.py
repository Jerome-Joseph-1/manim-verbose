"""
Turning a scene file into Python: one manim Scene class per scene, in a module which runs
with manimgl like any hand written one.

This is the only way a scene file becomes a video. Rendering, previews and "export to Python"
all go through the code generated here, so what a user exports is exactly what the editor
showed them. The code is meant to be read: objects become variables named by their ids, and
every step becomes a `with self.step(...)` block holding the calls a person would have written.

    from manimlib import *
    from manim_verbose.scenefile.runtime import *

    class Intro(DocScene):
        def construct(self):
            eq = self.obj("eq", place(Tex(R"a^2 + b^2 = c^2", font_size=48), edge="top"))
            with self.step("intro_1", caption="The oldest theorem you know"):
                self.play(Write(eq), run_time=2)

Who writes what: blocks.py turns an object into the expression which builds it, actions.py
turns a step into the lines which play it, and this module puts those together in order.

Alongside the code comes a map from each line of it back to what in the scene file it came
from (see GeneratedModule), so that when a line fails at render time, a formula LaTeX can't
typeset say, the problem can be reported against that object or step rather than as a line
of Python nobody asked to see.

OWNER: steps/render agent. The CodegenContext below is the interface blocks.py works against;
change it only in agreement with the objects agent.
"""
from __future__ import annotations

import builtins
import keyword
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from manim_verbose.scenefile.model import (
    CaptionSettings, Document, ObjectBase, SceneSpec, StepBase, TogetherStep,
)

# Part of the key rendered scenes are cached under, so that a change to what code is generated
# never serves a video made by the code before it. Bump it with any such change.
GENERATOR_VERSION = 1


@dataclass
class CodegenContext:
    doc: Document
    scene: SceneSpec
    # What each object is right now, as the steps are walked through. A change step replaces
    # an entry here, so that later steps (and a later change) build from the new values.
    objects: dict[str, ObjectBase] = field(default_factory=dict)
    # Folder of the scene file, against which image and svg paths are resolved
    base_dir: Path = field(default_factory=Path.cwd)
    # Variable names for objects whose id can't be one as it stands, see var()
    names: dict[str, str] = field(default_factory=dict)
    # Objects moved some other way than by giving them a new placement, so that a change
    # knows to put their new look where they are now, see actions._change
    displaced: set[str] = field(default_factory=set)
    # Every name taken in the scene's construct method, which temporaries steer clear of
    taken: set[str] = field(default_factory=set)

    def var(self, obj_id: str) -> str:
        """
        The Python variable holding an object. Ids are valid identifiers already, and are
        used as they are unless that would hide something generated code needs: an object
        called `Circle`, `place` or `for` is held in `Circle_`, `place_` or `for_`.
        """
        return self.names.get(obj_id, obj_id)

    def spec(self, obj_id: str) -> ObjectBase:
        return self.objects[obj_id]

    def temp(self, wanted: str) -> str:
        """A name for a temporary variable, as close to `wanted` as isn't already in use."""
        name, count = wanted, 1
        while name in self.taken or name in reserved_names():
            count += 1
            name = f"{wanted}_{count}"
        return name


@dataclass(frozen=True)
class SourceRef:
    """Where a line of generated code came from: a scene, and an object or step in it."""
    scene_id: str
    loc: tuple[str | int, ...]
    item_id: str | None = None
    kind: str = "scene"  # "scene", "object" or "step"


@dataclass
class GeneratedModule:
    code: str
    # Line number (from 1) of each line which came from something in the file
    line_map: dict[int, SourceRef]
    # The class generated for each scene, by scene id
    class_names: dict[str, str]


class CodegenError(Exception):
    """Something in the scene file which could not be turned into code, and where it is."""

    def __init__(self, message: str, ref: SourceRef):
        super().__init__(message)
        self.message = message
        self.ref = ref


def scene_class_name(scene: SceneSpec) -> str:
    """CamelCase class name for a scene, e.g. 'three_views' -> 'ThreeViews'."""
    name = "".join(part[:1].upper() + part[1:] for part in scene.id.split("_") if part)
    if not name or not name[0].isalpha():
        name = "Scene" + name
    if name in reserved_names():
        # A scene called `circle` mustn't hide manim's Circle from the code after it
        name += "Scene"
    return name


def document_to_python(doc: Document, base_dir: Path | None = None, scene_ids: list[str] | None = None) -> str:
    """The whole module for a document, or for just the scenes named."""
    return generate_module(doc, base_dir, scene_ids).code


def generate_module(doc: Document, base_dir: Path | None = None, scene_ids: list[str] | None = None) -> GeneratedModule:
    """The module for a document, with the map from its lines back to the document."""
    writer = _Writer()
    base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
    writer.line('"""')
    writer.line(_docstring_text(doc.title))
    writer.line("")
    writer.line("Generated from a scene file. Every scene is a class; render one with")
    writer.line("    manimgl <this file> <SceneName> -w")
    writer.line('"""')
    writer.line("from manimlib import *")
    writer.line("from manim_verbose.scenefile.runtime import *")

    class_names: dict[str, str] = {}
    used_classes: set[str] = set()
    for index, scene in enumerate(doc.scenes):
        if scene_ids is not None and scene.id not in scene_ids:
            continue
        name = scene_class_name(scene)
        base, count = name, 1
        while name in used_classes:
            count += 1
            name = f"{base}{count}"
        used_classes.add(name)
        class_names[scene.id] = name
        writer.line("")
        writer.line("")
        _write_scene(writer, doc, scene, index, name, base_dir)

    if class_names:
        writer.line("")
        writer.line("")
        writer.line(f"SCENES_IN_ORDER = [{', '.join(class_names.values())}]")
    return GeneratedModule(writer.text(), writer.line_map, class_names)


def _write_scene(writer: _Writer, doc: Document, scene: SceneSpec, index: int, class_name: str, base_dir: Path) -> None:
    from manim_verbose.scenefile import actions, blocks

    scene_loc = ("scenes", index)
    scene_ref = SourceRef(scene.id, scene_loc)
    ctx = CodegenContext(doc=doc, scene=scene, base_dir=base_dir)
    ctx.objects = {obj.id: obj for obj in scene.objects}
    ctx.names = object_names([obj.id for obj in scene.objects])
    ctx.taken = set(ctx.names.values()) | {obj.id for obj in scene.objects}

    writer.ref = scene_ref
    writer.line(f"class {class_name}(DocScene):")
    if scene.title:
        writer.line(f'    """{_docstring_text(scene.title)}"""')
    writer.line(f"    scene_id = {py_str(scene.id)}")
    captions = _caption_style(doc.settings.captions)
    if captions:
        writer.line(f"    caption_style = {captions}")
    background = scene.background or doc.settings.background
    if background:
        writer.line(f"    default_camera_config = dict(background_color={actions.color_code(background)})")
    writer.line("")
    writer.line("    def construct(self):")
    body_start = len(writer.lines)

    object_index = {obj.id: i for i, obj in enumerate(scene.objects)}
    try:
        ordered = blocks.build_order(scene)
    except Exception as err:
        raise CodegenError(_describe(err), scene_ref) from err
    for obj in ordered:
        ref = SourceRef(scene.id, scene_loc + ("objects", object_index[obj.id]), obj.id, "object")
        writer.ref = ref
        try:
            expression = blocks.object_expression(obj, ctx)
        except Exception as err:
            raise CodegenError(_describe(err), ref) from err
        writer.line(f"        {ctx.var(obj.id)} = self.obj({py_str(obj.id)}, {expression})")

    shown = [obj.id for obj in scene.objects if obj.shown]
    if shown:
        writer.ref = scene_ref
        writer.line(f"        self.add({', '.join(ctx.var(obj_id) for obj_id in shown)})")

    if scene.steps and len(writer.lines) > body_start:
        writer.line("")
    for step_index, step in enumerate(scene.steps):
        ref = SourceRef(scene.id, scene_loc + ("steps", step_index), step.id, "step")
        writer.ref = ref
        try:
            lines = actions.step_lines(step, ctx)
        except Exception as err:
            raise CodegenError(_describe(err), ref) from err
        caption = step_caption(step)
        opening = f"        with self.step({py_str(step.id or f'step_{step_index}')}"
        if caption is not None:
            opening += f", caption={py_str(caption)}"
        writer.line(opening + "):")
        for line in lines or ["pass"]:
            writer.line("            " + line)

    if len(writer.lines) == body_start:
        writer.ref = scene_ref
        writer.line("        pass")


def step_caption(step: StepBase) -> str | None:
    """
    The caption a step brings. A together without one of its own takes the last one given by
    a step inside it, those being shown together and so needing the one caption between them.
    """
    if step.caption is not None or not isinstance(step, TogetherStep):
        return step.caption
    captions = [inner.caption for inner in step.steps if inner.caption is not None]
    return captions[-1] if captions else None


def _caption_style(settings: CaptionSettings) -> str | None:
    from manim_verbose.scenefile.actions import color_code, num
    defaults = CaptionSettings()
    args = []
    if settings.font_size != defaults.font_size:
        args.append(f"font_size={num(settings.font_size)}")
    if settings.color != defaults.color:
        args.append(f"color={color_code(settings.color)}")
    if settings.edge != defaults.edge:
        args.append(f"edge={py_str(settings.edge)}")
    if settings.background != defaults.background:
        args.append(f"background={settings.background}")
    return f"CaptionStyle({', '.join(args)})" if args else None


def object_names(ids: list[str]) -> dict[str, str]:
    """Variable names for the ids which can't be used as they are, see CodegenContext.var."""
    names: dict[str, str] = {}
    taken = set(ids)
    for obj_id in ids:
        if obj_id not in reserved_names():
            continue
        name = obj_id + "_"
        while name in taken or name in reserved_names():
            name += "_"
        names[obj_id] = name
        taken.add(name)
    return names


@lru_cache(maxsize=1)
def reserved_names() -> frozenset[str]:
    """
    Names generated code relies on meaning what they mean: Python's keywords and builtins,
    everything `from manimlib import *` and `from ...runtime import *` bring in, and self.
    """
    from manim_verbose.manim_import import import_manim
    manimlib = import_manim()
    from manim_verbose.scenefile import runtime
    names = set(keyword.kwlist) | set(keyword.softkwlist) | set(dir(builtins)) | {"self"}
    for module in (manimlib, runtime):
        exported = getattr(module, "__all__", None)
        names |= set(exported) if exported is not None else {n for n in dir(module) if not n.startswith("_")}
    return frozenset(names)


def py_str(text: str) -> str:
    """A string literal for text, in double quotes where it can be."""
    literal = repr(text)
    if literal.startswith("'") and '"' not in text:
        literal = '"' + literal[1:-1].replace("\\'", "'") + '"'
    return literal


def _docstring_text(text: str) -> str:
    """Text safe to put inside a triple quoted docstring, on one line."""
    text = " ".join(text.split())
    return text.replace("\\", "\\\\").replace('"', '\\"') or "Untitled"


def _describe(err: Exception) -> str:
    if isinstance(err, NotImplementedError):
        return "This can't be turned into code yet" + (f": {err}" if str(err) else "")
    text = str(err) or type(err).__name__
    return re.sub(r"\s+", " ", text).strip()


class _Writer:
    """Lines of code, each noted against the part of the scene file it was written for."""

    def __init__(self):
        self.lines: list[str] = []
        self.line_map: dict[int, SourceRef] = {}
        self.ref: SourceRef | None = None

    def line(self, text: str) -> None:
        for piece in text.split("\n"):
            self.lines.append(piece)
            if self.ref is not None:
                self.line_map[len(self.lines)] = self.ref

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"
