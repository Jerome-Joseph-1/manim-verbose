"""
Layout checks: finding what a person watching would see as a mistake of layout, without
drawing anything. Something running off the frame, sitting under the captions, or two
unrelated things on top of each other.

    check_layout(doc, scene_id=None, base_dir=None) -> list[Problem]
        Every scene (or the one named), built without drawing, and looked at before its first
        step and after each top level step. Layout problems come back as warnings. A scene
        which can't be built at all (a formula LaTeX refuses, say) comes back as the errors
        saying why, as a render would give them. Results are cached by the scene's content.

How: each scene runs as a still render does (animations skipped, a camera which draws
nothing, see runtime.HeadlessCamera), with its step() wrapped so that before the first step
and after every top level step the box of every registered object on screen is measured.
Everything is measured where it lands on the screen, in the units of the frame the scene
starts with (origin at the centre, y from -4 to 4), through the camera as it stands: so a
zoom, a camera move and a turned 3D camera are all taken into account, by projecting each
point as the renderer would. Captions are not built at all: only the size of their words is
measured (from Pango's layout, see caption_band), which is all the band's size depends on.

What an object is, for this: the pieces it draws which no object registered inside it (a
member of a group, say) draws instead, each of them one of

    text   a letter or symbol, as its box: anything under a Text or Tex (a vector's label,
           say), and every piece of a text-like object (TEXT_KINDS: a matrix's brackets too)
    line   the outline of anything else: lines, arrows, the edges of shapes, even unstroked
           filled ones, since the edge of a fill is as visible as a line
    fill   the inside of a filled shape (or picture) opaque enough to hide what is beneath it

Pieces hardly visible (opacity under VISIBLE) count for nothing.

The checks, each problem a warning:

- off the frame: any part of an object past the frame's edge by more than FRAME_TOLERANCE,
  or all of it outside. FRAME_RULE_SKIPS leaves number planes alone (a grid is meant to run
  past the edges), and axes and number lines while the camera is zoomed, moved or turned.
- under the captions: text of an object in the caption band (more than MIN_OVERLAP of it),
  or lines of it (longer than MIN_CROSSING), while a caption is showing. The band is the
  dark panel behind the words, or the words themselves when captions have no background.
  CAPTION_RULE_SKIPS leaves coordinate systems alone: captions are meant to sit on them.
- collisions: see COLLISIONS. Words and formulas are what a collision spoils, so every
  collision involves text: text on text, a fill drawn over text, a line through text. Lines
  crossing lines and shapes meeting shapes are what geometry is made of, and are left alone,
  as is text on a panel drawn beneath it. EXEMPTIONS lists the pairs let off, and which of
  these each lets them off.

A turned 3D camera is handled by projecting, not by skipping: every point goes through the
camera's projection, so boxes are where things land on the screen, while objects fixed in
the frame (captions, and `fixed: true`) stay where they are.

A problem which lasts for several steps in a row is reported once, naming the first and last
of them; one which goes away and comes back is reported again. A collision is reported on
whichever of the two objects arrived or moved last, since that is most likely the one to
move. A problem's loc is the object (its `carry` entry for one carried from the scene
before), or the object's `place` when the object is where its placement put it: no step has
moved it, and (for the frame and the captions) the camera hasn't moved.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import sys
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from manim_verbose.scenefile.model import (
    ApplyMatrixStep, BoxObject, BraceObject, CameraStep, ChangeStep, Document, GroupObject,
    ImageObject, MoveStep, ObjectBase, SceneSpec, StepBase, TransformStep, iter_steps,
)
from manim_verbose.scenefile.validate import Problem

log = logging.getLogger(__name__)

# Bump with any change to what is found, so that results cached before it aren't served. The
# sources of the package are part of the cache key as well, see _sources_digest.
LAYOUT_CHECK_VERSION = 1

# How far past the frame's edge something may reach before it counts as off it
FRAME_TOLERANCE = 0.05
# Least area of text on text (or text in the caption band), in square units, that counts
MIN_OVERLAP = 0.02
# Least length of line running through text (or through the caption band) that counts
MIN_CROSSING = 0.1
# Spacing of the points lines are followed by; a crossing's length is counted in these
EDGE_STEP = 0.02
# Room around each letter, so that a line between two letters still goes through the word
GLYPH_PAD = 0.03
# Opacity under which something counts as invisible, and over which a fill hides what is under it
VISIBLE = 0.05
COVERING = 0.3
# Spacing of the points text is sampled at, to see how much of it a fill covers
COVER_STEP = 0.04

# Coordinate systems, which everything else is drawn on
BACKGROUND_KINDS = frozenset({"number_plane", "axes", "axes_3d", "number_line"})
# Kinds of object all of whose pieces are text: a matrix's brackets are as much a part of
# the formula as its entries. (Pieces under a Text or Tex are text in any object; a title's
# underline is not, and is a line.)
TEXT_KINDS = frozenset({"text", "tex", "quote", "bullets", "matrix"})
# When the frame check leaves a kind alone: a grid is made to run past the frame's edges, and
# once the camera has zoomed, moved or turned, so are axes and number lines. Anything else
# is checked whatever the camera does.
FRAME_RULE_SKIPS: dict[str, str] = {
    "number_plane": "always",
    "axes": "camera moved", "axes_3d": "camera moved", "number_line": "camera moved",
}
# Kinds the caption check leaves alone: captions are meant to sit over coordinate systems
CAPTION_RULE_SKIPS = BACKGROUND_KINDS
# Kinds of object a label is placed beside: an object placed next_to one of these is its label
SHAPE_KINDS = frozenset({
    "dot", "vector", "line", "polygon", "angle", "arc", "circle", "rectangle", "square",
    "graph", "image", "svg",
})

# (piece of one, piece of the other) -> what a person sees, and the words for it. A fill
# counts only drawn over the text, not beneath it. The first which applies is reported.
COLLISIONS: list[tuple[str, str, str]] = [
    ("text", "text", "{a} and {b} overlap"),
    ("fill", "text", "{a} covers {b}"),
    ("line", "text", "{a} crosses {b}"),
]


# Pairs let off some or all collisions, and why. Each is a name, what it says, a test (given
# the scene's facts and the two ids, in either order), and which rows of COLLISIONS it waives,
# by what of the first object collides: a label beside a shape may touch the shape's lines,
# but not the shape's own text.
ALL = frozenset({"text", "fill", "line"})


@dataclass(frozen=True)
class Exemption:
    name: str
    reason: str
    applies: Callable[["SceneFacts", str, str], bool]
    waives: frozenset = ALL


def _background(facts: "SceneFacts", a: str, b: str) -> bool:
    return facts.kind(a) in BACKGROUND_KINDS or facts.kind(b) in BACKGROUND_KINDS


def _related(name: str) -> Callable[["SceneFacts", str, str], bool]:
    return lambda facts, a, b: name in facts.relations.get(frozenset((a, b)), ())


def _layered(facts: "SceneFacts", a: str, b: str) -> bool:
    spec_a, spec_b = facts.specs.get(a), facts.specs.get(b)
    if spec_a is None or spec_b is None or spec_a.z == spec_b.z:
        return False
    lower = spec_a if spec_a.z < spec_b.z else spec_b
    return _is_filled(lower)


EXEMPTIONS: list[Exemption] = [
    Exemption("background", "number planes, axes and number lines are backgrounds, which anything may sit on", _background),
    Exemption("group", "a group and what it holds are the same things", _related("group")),
    Exemption("annotation", "a box or brace goes around or beside its target", _related("annotation")),
    Exemption("label", "an object placed next to a shape is its label, and may touch the shape's lines",
              _related("label"), frozenset({"line"})),
    Exemption("transform", "what a transform turns into is the same thing as what it started from", _related("transform")),
    Exemption("layered", "objects given different z, the lower one filled, are layered on purpose", _layered),
]


def exemption_for(facts: "SceneFacts", a: str, b: str) -> str | None:
    """The name of the first rule which lets a and b off any collision, if any does."""
    for rule in EXEMPTIONS:
        if rule.applies(facts, a, b):
            return rule.name
    return None


def waived(facts: "SceneFacts", a: str, b: str) -> frozenset:
    """The kinds of collision (rows of COLLISIONS, by their first piece) no rule lets a and b have."""
    out: frozenset = frozenset()
    for rule in EXEMPTIONS:
        if rule.waives - out and rule.applies(facts, a, b):
            out |= rule.waives
    return out


def _is_filled(spec: ObjectBase) -> bool:
    """Whether an object is drawn filled: a shape with a fill, a box with some, a backdrop, a picture."""
    if getattr(spec, "backdrop", False) or isinstance(spec, ImageObject):
        return True
    if isinstance(spec, BoxObject):
        return spec.fill_opacity > 0
    return getattr(spec, "fill", None) is not None and getattr(spec, "fill_opacity", 0) > 0


# What the document says about a scene

@dataclass
class SceneFacts:
    """What the checks need to know about a scene from its scene file, rather than from running it."""
    index: int
    scene: SceneSpec
    specs: dict[str, ObjectBase]
    locs: dict[str, list[str | int]]
    declared: dict[str, int]
    relations: dict[frozenset, set[str]]
    # Per top level step: the objects it moves (so their placement no longer says where they are)
    moves: list[set[str]]
    # Per top level step: whether the camera is off its normal view once the step is done
    camera_moved: list[bool]
    # Per point looked at (the start, then after each step): the caption showing
    captions: list[str]
    step_ids: list[str]

    def kind(self, obj_id: str) -> str | None:
        spec = self.specs.get(obj_id)
        return spec.type if spec is not None else None


def scene_facts(doc: Document, index: int) -> SceneFacts:
    from manim_verbose.scenefile.codegen import step_caption
    scene = doc.scenes[index]
    specs: dict[str, ObjectBase] = {}
    locs: dict[str, list[str | int]] = {}
    declared: dict[str, int] = {}
    for position, obj_id in enumerate(scene.carry):
        spec = _carried_spec(doc, index, obj_id)
        if spec is not None:
            specs[obj_id] = spec
            locs[obj_id] = ["scenes", index, "carry", position]
            declared[obj_id] = -len(scene.carry) + position
    for position, obj in enumerate(scene.objects):
        specs[obj.id] = obj
        locs[obj.id] = ["scenes", index, "objects", position]
        declared[obj.id] = position

    def members(obj_id: str, seen: frozenset = frozenset()) -> set[str]:
        spec = specs.get(obj_id)
        if not isinstance(spec, GroupObject) or obj_id in seen:
            return set()
        out = set()
        for member in spec.members:
            out |= {member} | members(member, seen | {obj_id})
        return out

    relations: dict[frozenset, set[str]] = {}

    def relate(a: str, b: str, name: str) -> None:
        if a != b:
            relations.setdefault(frozenset((a, b)), set()).add(name)

    for obj_id, spec in specs.items():
        for member in members(obj_id):
            relate(obj_id, member, "group")
        if isinstance(spec, (BoxObject, BraceObject)) and spec.target is not None:
            for target in {spec.target} | members(spec.target):
                relate(obj_id, target, "annotation")
        place = getattr(spec, "place", None)
        if place is not None and place.next_to is not None and specs.get(place.next_to) is not None:
            if specs[place.next_to].type in SHAPE_KINDS:
                relate(obj_id, place.next_to, "label")
    for step in iter_steps(scene.steps):
        if isinstance(step, TransformStep):
            for a in {step.target} | members(step.target):
                for b in {step.into} | members(step.into):
                    relate(a, b, "transform")
        next_to = _next_to_of(step)
        if next_to is not None and next_to in specs and specs[next_to].type in SHAPE_KINDS:
            for target in _targets(step):
                relate(target, next_to, "label")

    moves: list[set[str]] = []
    camera_moved: list[bool] = []
    moved_camera = False
    for step in scene.steps:
        moved: set[str] = set()
        for inner in iter_steps([step]):
            if _moves_things(inner):
                for target in _targets(inner):
                    moved |= {target} | members(target)
            if isinstance(inner, CameraStep):
                moved_camera = not (inner.reset and inner.zoom is None and inner.center is None
                                    and inner.focus is None and inner.orientation is None)
        moves.append(moved)
        camera_moved.append(moved_camera)

    captions = [""]
    for step in scene.steps:
        caption = step_caption(step)
        captions.append(captions[-1] if caption is None else caption)
    step_ids = [step.id or f"step_{i}" for i, step in enumerate(scene.steps)]
    return SceneFacts(index, scene, specs, locs, declared, relations, moves, camera_moved, captions, step_ids)


def _carried_spec(doc: Document, index: int, obj_id: str) -> ObjectBase | None:
    """The spec of an object carried into scene `index`, from the scene it was declared in."""
    for earlier in range(index - 1, -1, -1):
        scene = doc.scenes[earlier]
        for obj in scene.objects:
            if obj.id == obj_id:
                return obj
        if obj_id not in scene.carry:
            return None
    return None


def _targets(step: StepBase) -> list[str]:
    target = getattr(step, "target", None)
    if isinstance(target, str):
        return [target]
    return list(target or [])


def _next_to_of(step: StepBase) -> str | None:
    if isinstance(step, MoveStep) and step.to is not None:
        return step.to.next_to
    if isinstance(step, ChangeStep):
        place = step.set.get("place")
        if isinstance(place, dict) and isinstance(place.get("next_to"), str):
            return place["next_to"]
    return None


# Changing any of these moves an object off where its placement put it. (A change of words
# or size leaves it placed as before, so its placement is still the thing to fix.)
_MOVING_CHANGES = frozenset({"place", "scale", "rotate", "tip", "tail", "start", "end", "point", "points", "center"})


def _moves_things(step: StepBase) -> bool:
    if isinstance(step, (MoveStep, ApplyMatrixStep)):
        return True
    return isinstance(step, ChangeStep) and bool(_MOVING_CHANGES & set(step.set))


# Where things are on the screen

@dataclass
class Fill:
    path: Any                       # a matplotlib Path, in screen units
    box: np.ndarray                 # xmin, ymin, xmax, ymax
    order: int                      # place in the drawing order


@dataclass
class Shape:
    """What of one object is on screen, in screen units (the starting frame's: origin at the centre, y from -4 to 4)."""
    glyphs: np.ndarray              # (n, 4) boxes of letters and symbols
    glyph_order: np.ndarray         # (n,) their places in the drawing order
    edges: np.ndarray               # (n, 2) points along every line and outline, EDGE_STEP apart
    fills: list[Fill]
    bbox: np.ndarray | None         # xmin, ymin, xmax, ymax of all of it; None if nothing shows
    signature: tuple = ()           # the same when, and only when, the object hasn't changed on screen


@dataclass
class _Piece:
    glyph_box: np.ndarray | None = None
    edges: np.ndarray | None = None
    polygon: Any = None
    box: np.ndarray | None = None


EMPTY_POINTS = np.zeros((0, 2))


class Measurer:
    """
    Measures what registered objects show, through the camera as it stands, caching each
    piece by its content. `kinds` gives the kind of object each id is, which decides how it
    is measured: number planes not at all (nothing is checked against them), other
    coordinate systems only for their extent, text-like kinds with every piece as text.
    """

    def __init__(self, scene, kinds: dict[str, str | None]):
        from manimlib.constants import FRAME_HEIGHT
        from manimlib.mobject.shape_matchers import BackgroundRectangle
        from manimlib.mobject.svg.string_mobject import StringMobject
        from manimlib.mobject.types.vectorized_mobject import VMobject
        self.scene = scene
        self.kinds = kinds
        self.frame_height = FRAME_HEIGHT
        self.string_class = StringMobject
        self.panel_class = BackgroundRectangle
        self.vmobject_class = VMobject
        self._pieces: dict[tuple, _Piece] = {}

    def shapes(self) -> dict[str, Shape]:
        """The shape of every registered object on screen, by id, from the pieces each one draws itself."""
        scene = self.scene
        ids = [i for i in scene.registered_on_screen() if self.kinds.get(i) != "number_plane"]
        order = scene.drawing_order()
        walked = {obj_id: self._leaves(scene.objects[obj_id], self.kinds.get(obj_id) in TEXT_KINDS) for obj_id in ids}
        owner: dict[int, str] = {}
        # The smallest object holding a piece is the one drawing it: a member, not its group
        # (even a group of one, which holds just what its member does)
        for obj_id in sorted(ids, key=lambda i: (-len(walked[i]), self.kinds.get(i) != "group")):
            for leaf, _ in walked[obj_id]:
                owner[id(leaf)] = obj_id
        view = self._view_key()
        return {
            obj_id: self._shape(
                [(leaf, glyph) for leaf, glyph in walked[obj_id] if owner[id(leaf)] == obj_id],
                order, view, extent_only=self.kinds.get(obj_id) in BACKGROUND_KINDS,
            )
            for obj_id in ids
        }

    def _leaves(self, mob, text: bool, out: list | None = None) -> list:
        """Every piece of mob with points, and whether it is text: part of a text or formula, and no backdrop."""
        out = [] if out is None else out
        text = text or isinstance(mob, self.string_class)
        if mob.has_points():
            out.append((mob, text and not isinstance(mob, self.panel_class)))
        for sub in mob.submobjects:
            self._leaves(sub, text, out)
        return out

    def _view_key(self) -> tuple:
        frame = self.scene.frame
        return (frame.get_view_matrix().tobytes(), float(frame.get_scale()), float(frame.get_focal_distance()))

    def _shape(self, leaves: list, order: dict, view: tuple, extent_only: bool = False) -> Shape:
        glyphs, glyph_order, edges, fills, boxes, signature = [], [], [], [], [], []
        for leaf, glyph in leaves:
            visible, covers = self._visibility(leaf)
            if not visible:
                continue
            fixed = leaf.is_fixed_in_frame()
            points = leaf.get_points()
            key = (glyph, fixed, None if fixed else view, len(points), hash(points.tobytes()))
            signature.append((key, covers))
            piece = self._pieces.get(key)
            if piece is None:
                piece = self._pieces[key] = self._piece(leaf, glyph, fixed)
            box = piece.glyph_box if piece.glyph_box is not None else piece.box
            if box is None:
                continue
            boxes.append(box)
            if extent_only:
                continue
            if piece.glyph_box is not None:
                glyphs.append(piece.glyph_box)
                glyph_order.append(order.get(leaf, 0))
                continue
            if piece.edges is not None and len(piece.edges):
                edges.append(piece.edges)
            if covers and piece.polygon is not None:
                fills.append(Fill(piece.polygon, piece.box, order.get(leaf, 0)))
        bbox = None
        if boxes:
            stacked = np.array(boxes, dtype=float)
            bbox = np.array([stacked[:, 0].min(), stacked[:, 1].min(), stacked[:, 2].max(), stacked[:, 3].max()])
        return Shape(
            glyphs=np.array(glyphs, dtype=float).reshape(-1, 4),
            glyph_order=np.array(glyph_order, dtype=int),
            edges=np.concatenate(edges) if edges else EMPTY_POINTS,
            fills=fills,
            bbox=bbox,
            signature=tuple(signature),
        )

    def _visibility(self, leaf) -> tuple[bool, bool]:
        """Whether a piece shows at all, and whether its fill is opaque enough to hide what is under it."""
        if isinstance(leaf, self.vmobject_class):
            fill = float(leaf.get_fill_opacity()) if leaf.has_fill() else 0.0
            widths = leaf.get_stroke_widths()
            stroke = float(leaf.get_stroke_opacities().max()) if len(widths) and widths.max() > 0 else 0.0
            return max(fill, stroke) >= VISIBLE, fill >= COVERING
        opacity = _opacity(leaf)
        return opacity >= VISIBLE, opacity >= COVERING

    def _piece(self, leaf, glyph: bool, fixed: bool) -> _Piece:
        if glyph:
            screen = self.to_screen(leaf.get_points(), fixed)
            return _Piece(glyph_box=_box(screen))
        if isinstance(leaf, self.vmobject_class):
            subpaths = [self.to_screen(path, fixed) for path in leaf.get_subpaths() if len(path)]
            sampled = [_sample_quadratics(path) for path in subpaths]
            sampled = [path for path in sampled if len(path)]
            if not sampled:
                return _Piece()
            points = np.concatenate(sampled)
            return _Piece(edges=points, polygon=_polygon(sampled), box=_box(points))
        # A picture, or anything else drawn as a rectangle of its points
        screen = self.to_screen(leaf.get_points(), fixed)
        box = _box(screen)
        corners = np.array([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]], [box[0], box[1]]])
        outline = _sample_polyline(corners)
        return _Piece(edges=outline, polygon=_polygon([outline]), box=box)

    def to_screen(self, points: np.ndarray, fixed: bool) -> np.ndarray:
        """Where points land on the screen, in the units of the frame the scene starts with."""
        scene = self.scene
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        pixels = scene.frame_to_pixels(points, fixed=fixed)
        width, height = scene.camera.get_pixel_shape()
        return np.column_stack([
            (pixels[:, 0] / width - 0.5) * scene.frame_width,
            (0.5 - pixels[:, 1] / height) * self.frame_height,
        ])


def _opacity(mob) -> float:
    for key in ("opacity", "rgba"):
        try:
            values = np.asarray(mob.data[key], dtype=float)
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        if values.size:
            return float(values.reshape(len(values), -1)[:, -1].max())
    return 1.0


def _box(points: np.ndarray) -> np.ndarray:
    return np.array([points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max()])


def _sample_quadratics(points: np.ndarray) -> np.ndarray:
    """Points along a path of quadratic Béziers (anchor, handle, anchor, ...), about EDGE_STEP apart."""
    if len(points) < 3:
        return points[:1]
    count = (len(points) - 1) // 2
    a, h, b = points[0:2 * count:2], points[1:2 * count:2], points[2:2 * count + 1:2]
    lengths = np.linalg.norm(h - a, axis=1) + np.linalg.norm(b - h, axis=1)
    steps = np.maximum(1, np.ceil(lengths / EDGE_STEP)).astype(int)
    total = int(steps.sum())
    curve = np.repeat(np.arange(count), steps)
    starts = np.repeat(np.cumsum(steps) - steps, steps)
    t = ((np.arange(total) - starts) / np.repeat(steps, steps))[:, None]
    sampled = (1 - t) ** 2 * a[curve] + 2 * t * (1 - t) * h[curve] + t ** 2 * b[curve]
    return np.vstack([sampled, b[-1:]])


def _sample_polyline(corners: np.ndarray) -> np.ndarray:
    pieces = []
    for p, q in zip(corners[:-1], corners[1:]):
        n = max(1, int(math.ceil(np.linalg.norm(q - p) / EDGE_STEP)))
        t = np.arange(n)[:, None] / n
        pieces.append(p + t * (q - p))
    pieces.append(corners[-1:])
    return np.concatenate(pieces)


def _polygon(paths: list[np.ndarray]):
    """The area inside closed paths, as a matplotlib Path (which tells points inside it quickly)."""
    from matplotlib.path import Path as MplPath
    vertices, codes = [], []
    for path in paths:
        if len(path) < 3:
            continue
        vertices.append(path)
        vertices.append(path[:1])
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(path) - 1) + [MplPath.CLOSEPOLY]
    if not vertices:
        return None
    return MplPath(np.concatenate(vertices), codes)


# Measuring overlaps

def _boxes_meet(a: np.ndarray | None, b: np.ndarray | None, pad: float = 0.0) -> bool:
    return (a is not None and b is not None and a[0] < b[2] + pad and b[0] < a[2] + pad
            and a[1] < b[3] + pad and b[1] < a[3] + pad)


def text_overlap(a: np.ndarray, b: np.ndarray) -> float:
    """Area where boxes of one set lie over boxes of the other, summed over pairs."""
    if not len(a) or not len(b):
        return 0.0
    width = np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0])
    height = np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1])
    return float((np.clip(width, 0, None) * np.clip(height, 0, None)).sum())


def line_through(points: np.ndarray, boxes: np.ndarray, pad: float = GLYPH_PAD) -> float:
    """Length of the line sampled by points (EDGE_STEP apart) which runs inside any of boxes."""
    if not len(points) or not len(boxes):
        return 0.0
    area = np.array([boxes[:, 0].min() - pad, boxes[:, 1].min() - pad, boxes[:, 2].max() + pad, boxes[:, 3].max() + pad])
    near = points[(points[:, 0] >= area[0]) & (points[:, 0] <= area[2])
                  & (points[:, 1] >= area[1]) & (points[:, 1] <= area[3])]
    if not len(near):
        return 0.0
    x, y = near[:, 0:1], near[:, 1:2]
    inside = ((x >= boxes[:, 0] - pad) & (x <= boxes[:, 2] + pad)
              & (y >= boxes[:, 1] - pad) & (y <= boxes[:, 3] + pad)).any(axis=1)
    return float(inside.sum()) * EDGE_STEP


def covered(fills: list[Fill], boxes: np.ndarray, order: np.ndarray) -> float:
    """Area of the boxes (letters) under a fill drawn after them, sampled COVER_STEP apart."""
    total = 0.0
    for fill in fills:
        under = boxes[(order < fill.order)]
        under = under[(under[:, 0] < fill.box[2]) & (under[:, 2] > fill.box[0])
                      & (under[:, 1] < fill.box[3]) & (under[:, 3] > fill.box[1])]
        if not len(under):
            continue
        samples = [_grid(box) for box in under]
        points = np.concatenate(samples)
        if len(points):
            total += float(fill.path.contains_points(points).sum()) * COVER_STEP ** 2
    return total


def _grid(box: np.ndarray) -> np.ndarray:
    xs = np.arange(box[0] + COVER_STEP / 2, box[2], COVER_STEP)
    ys = np.arange(box[1] + COVER_STEP / 2, box[3], COVER_STEP)
    if not len(xs) or not len(ys):
        return np.array([[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]])
    gx, gy = np.meshgrid(xs, ys)
    return np.column_stack([gx.ravel(), gy.ravel()])


def collision(a: Shape, b: Shape, waived: frozenset = frozenset()) -> tuple[str, str, str] | None:
    """
    How a and b collide, as (message template, first, second) with first and second each 'a'
    or 'b', or None. Rows of COLLISIONS whose first piece is in `waived` are passed over.
    """
    if not _boxes_meet(a.bbox, b.bbox, GLYPH_PAD):
        return None
    for mine, theirs, template in COLLISIONS:
        if mine in waived:
            continue
        for first, second, x, y in (("a", "b", a, b), ("b", "a", b, a)):
            if mine == "text" and theirs == "text":
                if first == "b":
                    continue
                if text_overlap(x.glyphs, y.glyphs) >= MIN_OVERLAP:
                    return template, first, second
            elif mine == "fill":
                if x.fills and len(y.glyphs) and covered(x.fills, y.glyphs, y.glyph_order) >= MIN_OVERLAP:
                    return template, first, second
            elif mine == "line":
                if line_through(x.edges, y.glyphs) >= MIN_CROSSING:
                    return template, first, second
    return None


# Where the captions are

@dataclass(frozen=True)
class Band:
    box: tuple[float, float, float, float]   # xmin, ymin, xmax, ymax, in screen units
    edge: str


def caption_band(text: str, style, frame_width: float) -> Band | None:
    """
    Where a caption covers the frame, as runtime.DocScene.make_caption lays it out: its
    words wrapped to frame_width - 1.5, no wider than frame_width - 1, and a band behind them
    the frame's width and the words' height plus padding, against the top or bottom edge.
    Without a background, the words alone. The words are measured, not built (see
    caption_words_size), with the font manim is set to use, which DocScene sets.
    """
    from manimlib.constants import FRAME_HEIGHT
    if not text:
        return None
    width, height = caption_words_size(text, style.font_size, frame_width - 1.5)
    if width > frame_width - 1:
        height *= (frame_width - 1) / width
        width = frame_width - 1
    sign = -1 if style.edge == "bottom" else 1
    if style.background:
        band_height = height + 2 * 0.18
        outer = sign * FRAME_HEIGHT / 2
        inner = outer - sign * band_height
        half = (frame_width + 0.2) / 2
        return Band((-half, float(min(outer, inner)), half, float(max(outer, inner))), style.edge)
    centre = sign * (FRAME_HEIGHT / 2 - 0.35 - height / 2)
    pad = 0.1
    box = (-width / 2 - pad, centre - height / 2 - pad, width / 2 + pad, centre + height / 2 + pad)
    return Band(tuple(float(v) for v in box), style.edge)


def caption_words_size(text: str, font_size: float, line_width: float) -> tuple[float, float]:
    """
    Width and height of Text(text, font_size, alignment="CENTER", line_width) in manim units,
    as manim would build it with the font it is set to use, without building it: Pango lays
    the text out as an SVG (which manim caches on disk), and the extent of its glyphs is read
    from that, each glyph's outline measured once.
    """
    from manimlib.config import manim_config
    return _words_size(text, float(font_size), float(line_width), manim_config.text.font)


@lru_cache(maxsize=4096)
def _words_size(text: str, font_size: float, line_width: float, font: str) -> tuple[float, float]:
    from manimlib.mobject.svg.text_mobject import get_text_mob_scale_factor
    box = _svg_extent(_caption_svg(text, font_size, line_width))
    scale = get_text_mob_scale_factor()
    return float((box[2] - box[0]) * scale), float((box[3] - box[1]) * scale)


def _caption_svg(text: str, font_size: float, line_width: float) -> str:
    from manimlib.mobject.svg.text_mobject import Text

    class _Measured(Text):
        # The svg is all that is wanted: skip turning it into mobjects, the slow part
        def init_svg_mobject(self) -> None:
            pass

    return _Measured(text, font_size=font_size, alignment="CENTER", line_width=line_width).svg_string


_USE = re.compile(r"\{http://www\.w3\.org/1999/xlink\}href|href")


def _svg_extent(svg: str) -> tuple[float, float, float, float]:
    """xmin, ymin, xmax, ymax of what an SVG from Pango draws: its glyphs, placed where it uses them."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg)
    glyphs: dict[str, str] = {}
    boxes = []
    simple = True
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if "transform" in element.attrib:
            simple = False
        if tag == "g" and element.get("id"):
            if len(element) == 0:
                glyphs[element.get("id")] = ""  # a space
            elif len(element) == 1 and element[0].tag.endswith("path"):
                glyphs[element.get("id")] = element[0].get("d", "")
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "use":
            href = next((v for k, v in element.attrib.items() if _USE.fullmatch(k)), "")
            d = glyphs.get(href.lstrip("#"))
            if d is None:
                simple = False
                continue
            box = _path_extent(d)
            if box is None:
                continue
            x, y = float(element.get("x", 0)), float(element.get("y", 0))
            boxes.append((box[0] + x, box[1] + y, box[2] + x, box[3] + y))
        elif tag in ("rect", "image", "circle", "ellipse", "line", "polyline", "polygon", "text"):
            simple = False
    if simple and boxes:
        array = np.array(boxes)
        return float(array[:, 0].min()), float(array[:, 1].min()), float(array[:, 2].max()), float(array[:, 3].max())
    return _svg_extent_slowly(svg)


@lru_cache(maxsize=4096)
def _path_extent(d: str) -> tuple[float, float, float, float] | None:
    import svgelements as se
    return se.Path(d).bbox() if d else None


def _svg_extent_slowly(svg: str) -> tuple[float, float, float, float]:
    """The same as _svg_extent, the way manim itself measures an svg's content: slower, but sure of anything."""
    import xml.etree.ElementTree as ET
    import svgelements as se
    root = ET.fromstring(svg)
    root.attrib.clear()
    data = io.BytesIO()
    ET.ElementTree(root).write(data)
    data.seek(0)
    box = se.SVG.parse(data).bbox()
    if box is None:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(v) for v in box)


# Following a scene through

class _Probe:
    """
    Mixed in ahead of a generated scene class: looks at the scene before its first step and
    after every top level step, and skips building captions, whose size is all that matters
    here and is measured separately (see caption_band).
    """

    def layout_start(self, kinds: dict[str, str | None]) -> None:
        self.layout_points: list[dict[str, Shape]] = []
        self.layout_measurer = Measurer(self, kinds)

    @contextmanager
    def step(self, step_id, caption=None):
        if not self.layout_points:
            self.layout_look()
        with super().step(step_id, caption):
            yield
        self.layout_look()

    def layout_look(self) -> None:
        self.layout_points.append(self.layout_measurer.shapes())

    def make_caption(self, text):
        from manimlib.mobject.geometry import Square
        piece = Square(side_length=0.01).set_stroke(width=0).set_fill(opacity=0)
        piece.fix_in_frame()
        # Counted as a caption, so that a clear doesn't take it for something on screen
        parts = getattr(self, "_caption_parts", None)
        if parts is not None:
            parts.update(piece.get_family())
        return (piece,)


def _run_probe(doc: Document, scene_id: str, base_dir: Path | None, kinds: dict[str, str | None]):
    """
    Runs a scene as a still render would (animations skipped, nothing drawn) with _Probe mixed
    in, and hands back the scene as it ended and the shapes seen at each point: the start,
    then after each top level step. `kinds` says what kind of object each id is.
    """
    from manim_verbose.scenefile import render
    from manim_verbose.scenefile.render import RenderError
    from manim_verbose.scenefile.runtime import RenderPlan
    job = render.prepare_job(doc, scene_id, base_dir)
    width, height = doc.settings.resolution
    render.prepare_process()
    try:
        module = render.load_module(job.code)
        scene_class = getattr(module, job.class_name)
        probe_class = type(f"LayoutProbe{scene_class.__name__}", (_Probe, scene_class), {})
        scene = probe_class(plan=RenderPlan(still=True, headless=True), **render.scene_config(width, height, doc.settings.fps))
        scene.layout_start(kinds)
        scene.run()
        if not scene.layout_points:
            scene.layout_look()
    except RenderError:
        raise
    except Exception as err:
        raise job.error_from(err) from None
    return scene, scene.layout_points


@dataclass
class Finding:
    """One problem as it stands at one point; findings with the same key at points in a row are one problem."""
    key: tuple
    rule: str                       # "frame", "caption" or "overlap"
    names: tuple[str, ...]          # the object, or the two colliding, in the order the words name them
    words: str                      # what is wrong, with {a} and {b} for the names
    edges: frozenset = frozenset()  # for the frame: the edges run off, joined up over a stretch


def find_problems(facts: SceneFacts, shapes: dict[str, Shape], band: Band | None,
                  frame: tuple[float, float, float, float], camera_moved: bool = False) -> list[Finding]:
    """
    Every problem at one point, from the shapes of what is on screen then, the caption band
    if a caption shows, and whether the camera is off its normal view.
    """
    found: list[Finding] = []
    ids = sorted((i for i in shapes if shapes[i].bbox is not None), key=lambda i: facts.declared.get(i, 10 ** 6))
    for obj_id in ids:
        shape, kind = shapes[obj_id], facts.kind(obj_id)
        skip = FRAME_RULE_SKIPS.get(kind or "")
        if skip is None or (skip == "camera moved" and not camera_moved):
            off = off_frame(shape.bbox, frame)
            if off == "outside":
                found.append(Finding(("outside", obj_id), "frame", (obj_id,), "{a} is entirely off the frame"))
            elif off:
                found.append(Finding(("frame", obj_id), "frame", (obj_id,), "", frozenset(off)))
        if band is not None and kind not in CAPTION_RULE_SKIPS:
            area = np.array(band.box)[None, :]
            if (text_overlap(shape.glyphs, area) >= MIN_OVERLAP
                    or line_through(shape.edges, area, pad=0.0) >= MIN_CROSSING):
                found.append(Finding(("caption", obj_id), "caption", (obj_id,),
                                     "{a} is under the caption at the " + band.edge + " of the frame"))
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if not _boxes_meet(shapes[a].bbox, shapes[b].bbox, GLYPH_PAD):
                continue
            let_off = waived(facts, a, b)
            if let_off == ALL:
                continue
            hit = collision(shapes[a], shapes[b], let_off)
            if hit is not None:
                words, first, _ = hit
                names = (a, b) if first == "a" else (b, a)
                found.append(Finding(("overlap", frozenset((a, b))), "overlap", names, words))
    return found


EDGE_ORDER = ("top", "bottom", "left", "right")


def off_frame(box: np.ndarray, frame: tuple[float, float, float, float]) -> str | set[str] | None:
    """'outside' when box is wholly off the frame, the edges it runs off by more than FRAME_TOLERANCE, or None."""
    if box[2] <= frame[0] or box[0] >= frame[2] or box[3] <= frame[1] or box[1] >= frame[3]:
        return "outside"
    edges = {
        name for name, beyond in (
            ("left", box[0] < frame[0] - FRAME_TOLERANCE), ("bottom", box[1] < frame[1] - FRAME_TOLERANCE),
            ("right", box[2] > frame[2] + FRAME_TOLERANCE), ("top", box[3] > frame[3] + FRAME_TOLERANCE),
        ) if beyond
    }
    return edges or None


@dataclass
class _Stretch:
    finding: Finding
    first: int
    last: int
    culprit: str


def check_scene(doc: Document, scene_id: str, base_dir: Path | None = None) -> list[Problem]:
    """
    Layout problems in one scene, as warnings, measured afresh (check_layout caches). Raises
    RenderError when the scene can't be built.
    """
    from manim_verbose.scenefile.render import _find_scene
    index, _ = _find_scene(doc, scene_id)
    facts = scene_facts(doc, index)
    scene, points = _run_probe(doc, scene_id, base_dir, {obj_id: facts.kind(obj_id) for obj_id in facts.specs})
    frame = (-scene.frame_width / 2, -4.0, scene.frame_width / 2, 4.0)

    done: list[_Stretch] = []
    open_: dict[tuple, _Stretch] = {}
    changed_at: dict[str, int] = {}
    before: dict[str, tuple] = {}
    for position, shapes in enumerate(points):
        point = position - 1
        for obj_id, shape in shapes.items():
            if before.get(obj_id) != shape.signature:
                changed_at[obj_id] = point
        before = {obj_id: shape.signature for obj_id, shape in shapes.items()}
        text = facts.captions[min(position, len(facts.captions) - 1)]
        band = caption_band(text, scene.caption_style, scene.frame_width) if text else None
        moved = point >= 0 and facts.camera_moved[point]
        now = {finding.key: finding for finding in find_problems(facts, shapes, band, frame, moved)}
        for key in [key for key in open_ if key not in now]:
            done.append(open_.pop(key))
        for key, finding in now.items():
            stretch = open_.get(key)
            if stretch is not None:
                stretch.last = point
                stretch.finding.edges |= finding.edges
                continue
            # Of two colliding, whichever arrived or moved last is the likelier to be out of place
            culprit = max(finding.names, key=lambda i: (changed_at.get(i, -1), facts.declared.get(i, 0)))
            open_[key] = _Stretch(finding, point, point, culprit)
    done.extend(open_.values())
    done.sort(key=lambda s: (s.first, facts.declared.get(s.culprit, 0), s.finding.rule, s.finding.names))
    return [_problem(facts, stretch) for stretch in done]


def _problem(facts: SceneFacts, stretch: _Stretch) -> Problem:
    finding = stretch.finding
    words = finding.words
    if finding.edges:
        edges = [edge for edge in EDGE_ORDER if edge in finding.edges]
        words = f"{{a}} runs off the {' and '.join(edges)} edge{'s' if len(edges) > 1 else ''} of the frame"
    names = {letter: f"'{name}'" for letter, name in zip("ab", finding.names)}
    message = f"{_when(facts, stretch.first, stretch.last)}, {words.format(**names)}"
    loc = list(facts.locs.get(stretch.culprit, ["scenes", facts.index]))
    if _where_placed(facts, stretch.culprit, stretch.first, finding.rule):
        loc.append("place")
    return Problem(message, loc, "warning", facts.scene.id, stretch.culprit)


def _when(facts: SceneFacts, first: int, last: int) -> str:
    """When a problem shows, in the words of the editor's step list (which counts steps from 1)."""
    ids = facts.step_ids

    def step(point: int) -> str:
        return f"step {point + 1} ('{ids[point]}')"

    if first == last:
        return "At the start of the scene" if first < 0 else f"After {step(first)}"
    if first < 0:
        return f"From the start of the scene through {step(last)}"
    return f"After steps {first + 1} to {last + 1} ('{ids[first]}' to '{ids[last]}')"


def _where_placed(facts: SceneFacts, obj_id: str, point: int, rule: str) -> bool:
    """
    Whether an object is where its own `place` put it at a point: it is declared in this scene
    with a placement, no step up to then has moved it, and (for the frame and the captions,
    which are about the screen) the camera is where it started.
    """
    spec = facts.specs.get(obj_id)
    loc = facts.locs.get(obj_id, [])
    if getattr(spec, "place", None) is None or "objects" not in loc:
        return False
    if any(obj_id in facts.moves[i] for i in range(point + 1)):
        return False
    return not (rule != "overlap" and point >= 0 and facts.camera_moved[point])


# The whole document, cached

def check_layout(doc: Document, scene_id: str | None = None, base_dir: Path | None = None) -> list[Problem]:
    """
    Layout problems in every scene of doc, or in the one named, as warnings. A scene which
    can't be built gives the errors saying why instead. Each scene's result is cached by its
    content, in memory and under the render cache (MANIM_VERBOSE_CACHE), so that checking a
    document again only builds the scenes which changed.
    """
    from manim_verbose.scenefile.render import RenderError, _find_scene
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    if scene_id is not None:
        indices = [_find_scene(doc, scene_id)[0]]
    else:
        indices = list(range(len(doc.scenes)))
    problems: list[Problem] = []
    for index in indices:
        scene = doc.scenes[index]
        try:
            problems.extend(_cached_scene(doc, index, base))
        except RenderError as err:
            problems.extend(err.problems)
        except Exception as err:  # never a traceback: a check which fell over is a problem on its scene
            log.exception("Checking the layout of scene %s failed", scene.id)
            problems.append(Problem(
                f"The layout of scene '{scene.id}' couldn't be checked: {err}", ["scenes", index], "error", scene.id,
            ))
    return problems


def check_document_layout(doc: Document, problems: Iterable[Problem], base_dir: Path | None = None) -> list[Problem]:
    """
    Layout problems in the scenes of doc which `problems` (what validation found) has no
    errors in, for `validate --layout`: a scene with errors might not build at all, and
    they are already reported.
    """
    broken = {p.scene_id for p in problems if p.severity == "error"}
    if None in broken:
        return []
    found: list[Problem] = []
    # LaTeX's progress is printed as formulas are first typeset; stdout is kept for results
    with redirect_stdout(sys.stderr):
        for scene in doc.scenes:
            if scene.id not in broken:
                found.extend(check_layout(doc, scene.id, base_dir))
    return found


_memory: dict[str, list[dict[str, Any]]] = {}


def _cached_scene(doc: Document, index: int, base: Path) -> list[Problem]:
    scene = doc.scenes[index]
    key = layout_cache_key(doc, index, base)
    stored = _memory.get(key)
    path = _cache_folder() / f"{key}.json"
    if stored is None and path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = None
    if stored is None:
        problems = check_scene(doc, scene.id, base)
        stored = [_relative(p, index) for p in problems]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f".{path.stem}.{os.getpid()}.json")
            partial.write_text(json.dumps(stored), encoding="utf-8")
            partial.replace(path)
        except OSError:
            log.warning("Couldn't cache the layout of scene %s", scene.id, exc_info=True)
    _memory[key] = stored
    if len(_memory) > 256:
        _memory.pop(next(iter(_memory)))
    return [
        Problem(item["message"], ["scenes", index, *item["loc"]], item["severity"], scene.id, item["item_id"])
        for item in stored
    ]


def _relative(problem: Problem, index: int) -> dict[str, Any]:
    """A problem with its loc taken relative to its scene, so that it holds wherever the scene moves to."""
    loc = list(problem.loc)
    if loc[:2] == ["scenes", index]:
        loc = loc[2:]
    return {"message": problem.message, "loc": loc, "severity": problem.severity, "item_id": problem.item_id}


def _cache_folder() -> Path:
    from manim_verbose.scenefile.render import cache_dir
    return cache_dir() / "layout"


def layout_cache_key(doc: Document, index: int, base: Path) -> str:
    """Everything a scene's layout problems depend on: its code, its data (and that of the scenes it carries from), settings, pictures, and the package itself."""
    from manim_verbose.scenefile.render import prepare_job
    scene = doc.scenes[index]
    job = prepare_job(doc, scene.id, base)
    scenes = [doc.scenes[i].model_dump(mode="json") for i in range(index + 1)] if scene.carry else [job.scene_data]
    assets = {}
    for i in range(0 if scene.carry else index, index + 1):
        paths = [getattr(obj, "path", None) for obj in doc.scenes[i].objects]
        paths += [step.set.get("path") for step in iter_steps(doc.scenes[i].steps) if isinstance(step, ChangeStep)]
        for path_value in paths:
            if isinstance(path_value, str):
                path = base / path_value
                assets[path_value] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
    data = {
        "version": LAYOUT_CHECK_VERSION,
        "sources": _sources_digest(),
        "code": job.code,
        "scenes": scenes,
        "settings": doc.settings.model_dump(mode="json"),
        "assets": assets,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


@lru_cache(maxsize=1)
def _sources_digest() -> str:
    """The package's own source and manim's version: what is measured changes with either."""
    from importlib import metadata
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).resolve().parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    try:
        digest.update(metadata.version("manimgl").encode())
    except metadata.PackageNotFoundError:
        pass
    return digest.hexdigest()[:16]


def clear_memory_cache() -> None:
    """Forget results kept in this process (the files under the render cache stay)."""
    _memory.clear()
