"""
What the editor offers to add: every kind of object and step, with a name for people, a
category to group it under, a sentence on what it is, and a template to start from.

Names, categories and descriptions come from the models (`x-label`, `x-category` and the
docstring), so that they are written once, beside the definition. Templates are written by hand
here, since a good starting point ("Some text", a vector pointing somewhere) is a matter of
taste rather than of the format. A template has no `id`, which the editor gives it, and leaves
each reference to another object as "", for the editor to fill in from the selection or leave
for the user to pick. A test drops every template into a document, fills those in, and checks
it validates, and fails for a kind of object or step which has no template.
"""
from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any

from manim_verbose.scenefile.model import OBJECT_MODELS, STEP_MODELS

OBJECT_TEMPLATES: dict[str, dict[str, Any]] = {
    "text": {"type": "text", "text": "Some text"},
    "tex": {"type": "tex", "tex": "e^{i\\pi} + 1 = 0"},
    "title": {"type": "title", "text": "A title"},
    "quote": {"type": "quote", "text": "Imagination is more important than knowledge.", "author": "Albert Einstein"},
    "bullets": {"type": "bullets", "items": ["The first point", "The second point"]},
    "matrix": {"type": "matrix", "entries": [[1, 0], [0, 1]]},
    "number_plane": {"type": "number_plane"},
    "axes": {"type": "axes"},
    "axes_3d": {"type": "axes_3d"},
    "number_line": {"type": "number_line"},
    "graph": {"type": "graph", "on": "", "function": "sin(x)"},
    "dot": {"type": "dot", "point": [1, 1]},
    "vector": {"type": "vector", "tip": [2, 1]},
    "line": {"type": "line", "start": [-2, 0], "end": [2, 0]},
    "polygon": {"type": "polygon", "points": [[-1, -1], [1, -1], [0, 1]]},
    "angle": {"type": "angle", "points": [[2, 0], [0, 0], [1, 1.5]]},
    "arc": {"type": "arc", "radius": 1, "start_angle": 0, "end_angle": 90, "arrow": True},
    "circle": {"type": "circle", "radius": 1},
    "rectangle": {"type": "rectangle", "width": 3, "height": 2},
    "square": {"type": "square", "side": 2},
    "brace": {"type": "brace", "target": "", "side": "down"},
    "box": {"type": "box", "target": ""},
    "image": {"type": "image", "path": "picture.png"},
    "svg": {"type": "svg", "path": "drawing.svg"},
    "group": {"type": "group", "members": ["", ""], "arrange": "row"},
}

STEP_TEMPLATES: dict[str, dict[str, Any]] = {
    "show": {"do": "show", "target": ""},
    "hide": {"do": "hide", "target": ""},
    "add": {"do": "add", "target": ""},
    "remove": {"do": "remove", "target": ""},
    "clear": {"do": "clear"},
    "transform": {"do": "transform", "target": "", "into": ""},
    "change": {"do": "change", "target": "", "set": {"color": "YELLOW"}},
    "move": {"do": "move", "target": "", "by": [1, 0]},
    "highlight": {"do": "highlight", "target": ""},
    "wait": {"do": "wait", "duration": 1},
    "camera": {"do": "camera", "zoom": 1.5},
    "apply_matrix": {"do": "apply_matrix", "target": "", "matrix": [[1, 1], [0, 1]]},
    "together": {"do": "together", "steps": [{"do": "show", "target": ""}, {"do": "show", "target": ""}]},
}


@lru_cache(maxsize=1)
def catalog() -> dict[str, list[dict[str, Any]]]:
    objects = []
    for kind, model in OBJECT_MODELS.items():
        extra = model.model_config.get("json_schema_extra") or {}
        objects.append({
            "type": kind,
            "label": extra.get("x-label", kind.replace("_", " ").capitalize()),
            "category": extra.get("x-category", "Other"),
            "description": describe(model),
            "template": OBJECT_TEMPLATES.get(kind, {"type": kind}),
        })
    steps = []
    for kind, model in STEP_MODELS.items():
        extra = model.model_config.get("json_schema_extra") or {}
        steps.append({
            "do": kind,
            "label": extra.get("x-label", kind.replace("_", " ").capitalize()),
            "description": describe(model),
            "template": STEP_TEMPLATES.get(kind, {"do": kind}),
        })
    return {"objects": objects, "steps": steps}


def describe(model: type) -> str:
    """A model's docstring as prose: lines joined within a paragraph, paragraphs kept apart."""
    doc = inspect.cleandoc(model.__doc__ or "")
    paragraphs = [" ".join(line.strip() for line in block.splitlines()) for block in doc.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)
