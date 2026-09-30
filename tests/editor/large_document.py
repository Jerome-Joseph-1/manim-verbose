"""
A document the size of a real ten minute video (examples/eola_vectors/vectors.yaml has 11
scenes and about 250 steps), built from the kinds of objects and steps such a video uses, for
checking that the server stays quick with it.
"""
from __future__ import annotations


def large_document(scenes: int = 11, steps_per_scene: int = 23) -> dict:
    return {
        "version": 1,
        "title": "A long video",
        "settings": {"captions": {"font_size": 28}},
        "scenes": [_scene(i, steps_per_scene) for i in range(scenes)],
    }


def _scene(index: int, steps_per_scene: int) -> dict:
    s = f"s{index}"
    objects = [
        {"id": "plane", "type": "number_plane", "faded": True},
        {"id": "title", "type": "title", "text": f"Part {index + 1}"},
        {"id": "v", "type": "vector", "tip": [2, 1], "on": "plane", "color": "YELLOW", "label": "\\vec{v}"},
        {"id": "w", "type": "vector", "tip": [-1, 2], "on": "plane", "color": "PINK", "label": "\\vec{w}"},
        {"id": "tip", "type": "dot", "point": [2, 1], "on": "plane"},
        {"id": "coords", "type": "matrix", "entries": [[2], [1]], "place": {"edge": "top_left"}},
        {"id": "eq", "type": "tex", "tex": "\\vec{v} + \\vec{w} = \\begin{bmatrix} 1 \\\\ 3 \\end{bmatrix}",
         "place": {"edge": "top_right"}, "colors": {"\\vec{v}": "YELLOW", "\\vec{w}": "PINK"}},
        {"id": "note", "type": "text", "text": "Tip to tail", "place": {"next_to": "eq", "side": "down"}},
        {"id": "brace", "type": "brace", "target": "coords", "side": "right", "label": "x, y"},
        {"id": "group", "type": "group", "members": ["v", "w"]},
    ]
    steps = [
        {"do": "show", "target": "title", "caption": f"Part {index + 1} begins"},
        {"do": "show", "target": "plane", "style": "draw", "run_time": 2},
        {"do": "hide", "target": "title"},
    ]
    for r in range(steps_per_scene // 15 + 1):
        steps += [
            {"do": "show", "target": ["v", "tip"], "lag": 0.3, "caption": f"Round {r + 1}: a vector"},
            {"do": "show", "target": "coords"},
            {"do": "show", "target": "brace"},
            {"do": "highlight", "target": "coords", "style": "box"},
            {"do": "show", "target": "w"},
            {"do": "together", "steps": [{"do": "move", "target": "w", "by": [2, 1]},
                                         {"do": "show", "target": "eq"}]},
            {"do": "highlight", "target": "eq", "part": "\\vec{v}", "style": "recolor", "color": "YELLOW"},
            {"do": "show", "target": "note", "style": "fade_up"},
            {"do": "change", "target": "v", "set": {"tip": [3, 2], "color": "GREEN"}, "run_time": 1.5},
            {"do": "apply_matrix", "target": ["plane", "v", "w"], "matrix": [[1, 1], [0, 1]], "run_time": 2},
            {"do": "camera", "zoom": 1.3, "focus": "tip"},
            {"do": "camera", "reset": True},
            {"do": "wait", "duration": 1.5},
            {"do": "hide", "target": ["v", "tip", "w", "coords", "brace", "eq", "note"]},
            {"do": "wait", "duration": 0.5, "caption": ""},
        ]
    steps = steps[:steps_per_scene - 1] + [{"do": "clear"}]
    return {"id": s, "title": f"Part {index + 1}", "objects": objects, "steps": steps}
