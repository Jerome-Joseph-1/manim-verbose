"""
What generated code runs on: DocScene, the Scene subclass every generated scene derives from,
and the helpers generated code calls. `from manim_verbose.scenefile.runtime import *` gives
generated code everything it needs besides manimlib itself.

OWNER: steps/render agent (layout and expressions, re-exported from here, belong to the
objects agent).

DocScene provides:
    self.obj(id, mob) -> mob             registers a mobject under its scene file id
    with self.step(step_id, caption=None)  marks a step: its start and end time, caption
                                         changes, and where a still or a clip stops
and the machinery render.py drives: stopping after a given step to capture a still with
the pixel bounding box of every registered object on screen, rendering only a range of
steps, and reporting progress.

Import manimlib through manim_verbose.manim_import, never directly (see there for why).
"""
from __future__ import annotations
