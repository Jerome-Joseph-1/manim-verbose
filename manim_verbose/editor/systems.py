"""
Where each coordinate system is in a still, so that the editor can turn a drag on the picture
into coordinates on a number plane, a set of axes or a number line.

A still comes back with `coordinate_systems`, one entry for each number plane, set of axes,
3D axes and number line on screen:

    {"id": "plane", "type": "number_plane",
     "origin": [480.0, 270.0],     # pixels of the image where (0, 0) is
     "x_unit": [60.0, 0.0],        # how far, in pixels, one unit along x goes
     "y_unit": [0.0, -60.0],       # ... along y (for a number line: one frame unit up)
     "z_unit": null}               # ... along z, for 3D axes

so that a point (x, y) of the system lands at origin + x * x_unit + y * y_unit, which the
editor inverts to go the other way. It is measured on the scene as the still left it, through
the same projection as the object boxes, so a camera move or a transform of the plane is
accounted for.

The still itself is made by scenefile/render.render_still, unchanged; this module only keeps
hold of the scene it ran (by wrapping render.run_job for the length of the call, in the worker
process drawing the still) to measure it afterwards. Measuring never fails a still: a system
which can't be measured is left out.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("manim_verbose.editor")


@dataclass
class StillWithSystems:
    path: Path
    width: int
    height: int
    objects: list[Any]
    coordinate_systems: list[dict[str, Any]] = field(default_factory=list)


def render_still_with_systems(doc, scene_id: str, step_index: int, out_png: Path, width: int, base_dir: Path):
    from manim_verbose.scenefile import render
    captured: list[Any] = []
    original = render.run_job

    def run_and_keep(*args, **kwargs):
        scene = original(*args, **kwargs)
        captured.append(scene)
        return scene

    render.run_job = run_and_keep
    try:
        result = render.render_still(doc, scene_id, step_index, out_png, width=width, base_dir=base_dir)
    finally:
        render.run_job = original
    systems: list[dict[str, Any]] = []
    if captured:
        try:
            systems = measure_systems(captured[-1])
        except Exception:
            log.exception("measuring the coordinate systems of a still failed")
    return StillWithSystems(result.path, result.width, result.height, list(result.objects), systems)


def _system_of(mob) -> tuple[str, Any] | None:
    """The kind of coordinate system a registered object is, and the mobject to measure."""
    from manimlib.mobject.coordinate_systems import Axes, NumberPlane, ThreeDAxes
    from manimlib.mobject.number_line import NumberLine
    if isinstance(mob, ThreeDAxes):
        return "axes_3d", mob
    if isinstance(mob, NumberPlane):
        return "number_plane", mob
    if isinstance(mob, Axes):
        return "axes", mob
    if isinstance(mob, NumberLine):
        return "number_line", mob
    # A number line with a backdrop is VGroup(panel, line)
    subs = list(getattr(mob, "submobjects", []))
    if len(subs) == 2 and isinstance(subs[1], NumberLine) and not isinstance(subs[0], NumberLine):
        return "number_line", subs[1]
    return None


def measure_systems(scene) -> list[dict[str, Any]]:
    import numpy as np
    out = []
    for obj_id in scene.registered_on_screen():
        found = _system_of(scene.objects[obj_id])
        if found is None:
            continue
        kind, mob = found
        try:
            if kind == "number_line":
                origin = np.asarray(mob.n2p(0), dtype=float)
                points = [origin, np.asarray(mob.n2p(1), dtype=float), origin + np.array([0.0, 1.0, 0.0])]
            elif kind == "axes_3d":
                points = [np.asarray(mob.c2p(*c), dtype=float) for c in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))]
            else:
                points = [np.asarray(mob.c2p(*c), dtype=float) for c in ((0, 0), (1, 0), (0, 1))]
            pixels = scene.frame_to_pixels(np.array(points), fixed=mob.is_fixed_in_frame())
        except Exception:
            log.exception("measuring coordinate system %s failed", obj_id)
            continue
        if not np.all(np.isfinite(pixels)):
            continue
        origin_px = pixels[0, :2]

        def unit(i: int) -> list[float]:
            return [round(float(v), 4) for v in pixels[i, :2] - origin_px]

        out.append({
            "id": obj_id,
            "type": kind,
            "origin": [round(float(v), 4) for v in origin_px],
            "x_unit": unit(1),
            "y_unit": unit(2),
            "z_unit": unit(3) if kind == "axes_3d" else None,
        })
    return out


def systems_data(result: Any) -> list[dict[str, Any]]:
    """The coordinate systems of a still result as plain data; [] for a result without any."""
    raw = result.get("coordinate_systems") if isinstance(result, dict) else getattr(result, "coordinate_systems", None)
    out = []
    for entry in raw or []:
        try:
            out.append({
                "id": str(entry["id"]),
                "type": str(entry["type"]),
                "origin": [float(v) for v in entry["origin"]][:2],
                "x_unit": [float(v) for v in entry["x_unit"]][:2],
                "y_unit": [float(v) for v in entry["y_unit"]][:2] if entry.get("y_unit") is not None else None,
                "z_unit": [float(v) for v in entry["z_unit"]][:2] if entry.get("z_unit") is not None else None,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out
