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

OWNER: steps/render agent. The CodegenContext below is the interface blocks.py works against;
change it only in agreement with the objects agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manim_verbose.scenefile.model import Document, ObjectBase, SceneSpec


@dataclass
class CodegenContext:
    doc: Document
    scene: SceneSpec
    # What each object is right now, as the steps are walked through. A change step replaces
    # an entry here, so that later steps (and a later change) build from the new values.
    objects: dict[str, ObjectBase] = field(default_factory=dict)
    # Folder of the scene file, against which image and svg paths are resolved
    base_dir: Path = field(default_factory=Path.cwd)

    def var(self, obj_id: str) -> str:
        """The Python variable holding an object. Ids are valid identifiers already."""
        return obj_id

    def spec(self, obj_id: str) -> ObjectBase:
        return self.objects[obj_id]


def scene_class_name(scene: SceneSpec) -> str:
    """CamelCase class name for a scene, e.g. 'three_views' -> 'ThreeViews'."""
    raise NotImplementedError


def document_to_python(doc: Document, base_dir: Path | None = None, scene_ids: list[str] | None = None) -> str:
    """The whole module for a document, or for just the scenes named."""
    raise NotImplementedError
