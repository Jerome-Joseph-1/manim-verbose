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

Time in a DocScene is kept on a grid. Frame k of a scene shows the moment k / fps from the
scene's start, whichever play or wait it falls in, so a scene of nominal length T always
comes to round(T * fps) frames, and a clip of some of its steps holds exactly the frames the
whole scene holds for those steps. Plain manim instead gives every play ceil(run_time * fps)
frames of its own, which drifts from the nominal length by up to a frame per play.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from manim_verbose.manim_import import import_manim

import_manim()

from manimlib.animation.animation import Animation
from manimlib.animation.composition import AnimationGroup
from manimlib.animation.fading import FadeIn, FadeOut
from manimlib.animation.growing import GrowArrow, GrowFromCenter
from manimlib.animation.indication import Flash
from manimlib.animation.transform import ReplacementTransform
from manimlib.constants import BLACK, DOWN, FRAME_HEIGHT, FRAME_WIDTH, OUT, UP, WHITE, YELLOW
from manimlib.mobject.geometry import Arrow, Line, Rectangle
from manimlib.mobject.mobject import Group, Mobject
from manimlib.mobject.svg.text_mobject import Text
from manimlib.mobject.types.vectorized_mobject import VGroup
from manimlib.scene.scene import EndScene, Scene
from manimlib.utils.family_ops import extract_mobject_family_members, recursive_mobject_remove

from manim_verbose.scenefile.layout import *  # noqa: F401,F403  (placement helpers, objects agent)
from manim_verbose.scenefile.expressions import *  # noqa: F401,F403  (safe functions, objects agent)


# Drawn above anything a scene file can ask for with `z`
CAPTION_Z = 1_000_000


@dataclass
class CaptionStyle:
    """How captions look; the defaults are those of the scene file's settings.captions."""
    font_size: float = 30
    color: str = WHITE
    edge: str = "bottom"
    background: bool = True


@dataclass
class RenderPlan:
    """
    What render.py wants of a run beyond playing the scene through. Left at its defaults, a
    DocScene plays exactly as any Scene would, which is how generated code runs under manimgl.
    """
    # Steps before this one run with animations skipped, so that rendering starts from the
    # state they leave without spending any time on them
    first_step: int = 0
    # The scene ends once this step has finished; -1 ends it before the first step
    last_step: int | None = None
    # Skip every animation: only the state where the scene ends matters, as for a still
    still: bool = False
    # Called as frames are written, with the nominal seconds of the scene done so far and
    # the index of the step being played
    progress: Callable[[float, int], None] | None = None


@dataclass
class StepRecord:
    step_id: str
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class StopScene(EndScene):
    """Ends a scene early, where a plan asks it to, the same way manim ends one itself."""


class DocScene(Scene):
    """
    A scene generated from a scene file. Objects are registered under their ids with obj(),
    and each step of the file runs inside `with self.step(...)`, which is what lets a render
    stop after any step, start from any step, and show captions.

    Three things differ from a plain Scene, all so that the file means what it says:

    - Time runs on a grid of frames, see the module's docstring.
    - An object taken off screen during a step is put back, once the step is over, as it was
      when the step first animated it. Uncreate, a shrink or a transform into something else
      leave the mobject they worked on emptied, shrunk or reshaped, and without this showing
      it again later would show that rather than the object.
    - Adding a group whose members are already on screen draws them through the group from
      then on, rather than twice.
    """
    scene_id: str = ""
    caption_style: CaptionStyle = CaptionStyle()
    # How long a caption takes to fade from one to the next, at most
    caption_fade_time: float = 0.5

    def __init__(self, plan: RenderPlan | None = None, **kwargs):
        self.plan = plan or RenderPlan()
        if self.plan.still or self.plan.first_step > 0:
            kwargs["skip_animations"] = True
        super().__init__(**kwargs)
        self.objects: dict[str, Mobject] = {}
        self.step_records: list[StepRecord] = []
        # Nominal seconds since the scene began, advanced by exactly each play's run_time
        self.doc_time: float = 0.0
        self.frames_emitted: int = 0
        self._step_index: int = -1
        self._in_step: bool = False
        self._pending_run_time: float = 0.0
        self._caption: tuple[Mobject, ...] | None = None
        self._caption_text: str = ""
        self._caption_parts: set[Mobject] = set()
        self._next_caption: str | None = None
        self._snapshots: dict[str, Mobject] = {}

    # Objects and steps, which is what generated code calls

    def obj(self, obj_id: str, mobject: Mobject) -> Mobject:
        """Registers a mobject under its id in the scene file, and hands it back."""
        self.objects[obj_id] = mobject
        return mobject

    @contextmanager
    def step(self, step_id: str, caption: str | None = None) -> Iterator[None]:
        """
        One step of the scene file. Its start and end are recorded, a caption given here
        replaces whatever caption is showing (an empty one clears it), and a render asked to
        start at this step or to stop after it does so here.
        """
        index = self._step_index + 1
        plan = self.plan
        if plan.last_step is not None and index > plan.last_step:
            raise StopScene()
        self._step_index = index
        if not plan.still and index == plan.first_step and index > 0:
            self.stop_skipping()
        if caption is not None and caption != self._caption_text:
            self._next_caption = caption
        start = self.doc_time
        self._snapshots = {}
        self._in_step = True
        try:
            yield
        finally:
            self._in_step = False
        if self._next_caption is not None:
            self._set_caption_now(self._next_caption)
        self._restore_departed()
        self.step_records.append(StepRecord(step_id, index, start, self.doc_time))
        if plan.last_step is not None and index >= plan.last_step:
            raise StopScene()

    def everything_on_screen(self) -> Group:
        """Whatever is on screen besides the camera and the captions, as one group."""
        return Group(*(
            mob for mob in self.mobjects
            if mob is not self.frame and not self._is_caption(mob)
        ))

    # What is on screen

    def is_on_screen(self, mobject: Mobject) -> bool:
        """Whether everything this mobject draws is in the scene."""
        drawn = [mob for mob in mobject.get_family() if mob.has_points()]
        if not drawn:
            return False
        in_scene = set(self.get_mobject_family_members())
        return all(mob in in_scene for mob in drawn)

    def registered_on_screen(self) -> list[str]:
        """Ids of the registered objects on screen, in the order they are drawn, bottom first."""
        order = self.drawing_order()
        entries = []
        for obj_id, mob in self.objects.items():
            drawn = [m for m in mob.get_family() if m.has_points()]
            if not drawn or not all(m in order for m in drawn):
                continue
            # An object comes where it starts being drawn, and a group before its members,
            # so that of everything under a click the last listed is the most particular
            entries.append((min(order[m] for m in drawn), -len(drawn), obj_id))
        entries.sort()
        return [obj_id for _, _, obj_id in entries]

    def drawing_order(self) -> dict[Mobject, int]:
        """Every mobject drawn, and its place in the order they are drawn, as Renderer.resolve orders them."""
        drawn = [
            mob for top in self.mobjects if top is not self.frame
            for mob in top.get_family() if mob.has_points()
        ]
        drawn.sort(key=lambda mob: mob.z_index)
        order: dict[Mobject, int] = {}
        for index, mob in enumerate(drawn):
            order.setdefault(mob, index)
        return order

    def object_boxes(self) -> list[tuple[str, tuple[float, float, float, float], tuple[float, float, float, float]]]:
        """
        (id, frame box, pixel box) for every registered object on screen, in drawing order.
        The frame box is in manim units, (xmin, ymin, xmax, ymax); the pixel box is where that
        lands in the picture the camera takes as it stands, (x0, y0, x1, y1) from the top left.
        """
        boxes = []
        for obj_id in self.registered_on_screen():
            mins, _, maxs = self.objects[obj_id].get_bounding_box()
            corners = np.array([
                [x, y, z]
                for x in (mins[0], maxs[0]) for y in (mins[1], maxs[1]) for z in (mins[2], maxs[2])
            ])
            pixels = self.frame_to_pixels(corners)
            frame_box = (float(mins[0]), float(mins[1]), float(maxs[0]), float(maxs[1]))
            pixel_box = (
                float(pixels[:, 0].min()), float(pixels[:, 1].min()),
                float(pixels[:, 0].max()), float(pixels[:, 1].max()),
            )
            boxes.append((obj_id, frame_box, pixel_box))
        return boxes

    def frame_to_pixels(self, points: np.ndarray) -> np.ndarray:
        """
        Where points of the scene land in the picture, in pixels from its top left. This is
        the projection the shaders make (see shaders/inserts/project_point.wgsl), done here
        for points the editor needs to know the place of.
        """
        frame = self.frame
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        homogeneous = np.hstack([points, np.ones((len(points), 1))])
        viewed = homogeneous @ frame.get_view_matrix().T
        rescale = np.array([
            2.0 / FRAME_WIDTH, 2.0 / FRAME_HEIGHT,
            frame.get_scale() / frame.get_focal_distance(),
        ])
        scaled = viewed[:, :3] * rescale
        w = 1.0 - scaled[:, 2]
        ndc = scaled[:, :2] / w[:, None]
        width, height = self.camera.get_pixel_shape()
        return np.column_stack([
            (ndc[:, 0] + 1) / 2 * width,
            (1 - ndc[:, 1]) / 2 * height,
        ])

    # Keeping the scene tidy

    def add(self, *new_mobjects: Mobject):
        held = {
            sm for mob in new_mobjects for sm in mob.get_family()[1:]
        } - set(new_mobjects)
        if held:
            self.mobjects, _ = recursive_mobject_remove(self.mobjects, held)
        return super().add(*new_mobjects)

    def play(self, *proto_animations, run_time: float | None = None, **kwargs):
        if not proto_animations:
            return super().play(*proto_animations, run_time=run_time, **kwargs)
        animations = [self._as_animation(anim) for anim in proto_animations]
        if self._in_step:
            self._snapshot_animated(animations)
        if self._next_caption is not None and self._in_step:
            length = run_time or max(anim.get_run_time() for anim in animations)
            animations += self._caption_transition(self._next_caption, length)
            run_time = length
        return super().play(*animations, run_time=run_time, **kwargs)

    def wait(self, duration: float | None = None, *args, **kwargs):
        if self._next_caption is not None and self._in_step:
            duration = self.default_wait_time if duration is None else duration
            return self.play(*self._caption_transition(self._next_caption, duration), run_time=duration)
        return super().wait(duration, *args, **kwargs)

    @staticmethod
    def _as_animation(anim) -> Animation:
        from manimlib.animation.animation import prepare_animation
        return prepare_animation(anim)

    def _snapshot_animated(self, animations: list[Animation]) -> None:
        """Copies of registered objects about to be animated, taken before anything moves them."""
        animated = set(extract_mobject_family_members([anim.mobject for anim in animations]))
        for obj_id, mob in self.objects.items():
            if obj_id in self._snapshots:
                continue
            family = mob.get_family()
            if any(m in animated for m in family) and self.is_on_screen(mob):
                self._snapshots[obj_id] = mob.copy()

    def _restore_departed(self) -> None:
        for obj_id, snapshot in self._snapshots.items():
            mob = self.objects[obj_id]
            if not self.is_on_screen(mob):
                mob.become(snapshot)
        self._snapshots = {}

    # Captions

    def make_caption(self, text: str) -> tuple[Mobject, ...]:
        """The pieces of a caption: its words, and the band behind them if there is one."""
        style = self.caption_style
        words = Text(text, font_size=style.font_size, alignment="CENTER", line_width=FRAME_WIDTH - 1.5)
        words.set_color(style.color)
        if words.get_width() > FRAME_WIDTH - 1:
            words.set_width(FRAME_WIDTH - 1)
        direction = DOWN if style.edge == "bottom" else UP
        pieces: tuple[Mobject, ...]
        if style.background:
            pad = 0.18
            band = Rectangle(width=FRAME_WIDTH + 0.2, height=words.get_height() + 2 * pad)
            band.set_fill(BLACK, opacity=0.65).set_stroke(width=0)
            band.move_to((FRAME_HEIGHT / 2 - band.get_height() / 2) * direction)
            words.move_to(band)
            pieces = (band, words)
        else:
            words.move_to((FRAME_HEIGHT / 2 - 0.35 - words.get_height() / 2) * direction)
            pieces = (words,)
        # The words by z rather than by the order they were added in, which a crossfade
        # (the band transformed, the words faded) doesn't keep
        for z, piece in enumerate(pieces[::-1]):
            piece.fix_in_frame()
            piece.set_z_index(CAPTION_Z - z)
            self._caption_parts.update(piece.get_family())
        return pieces

    def _is_caption(self, mobject: Mobject) -> bool:
        return any(mob in self._caption_parts for mob in mobject.get_family())

    def _caption_transition(self, text: str, run_time: float) -> list[Animation]:
        """Animations taking the caption on screen to `text`, over the start of a play of run_time."""
        self._next_caption = None
        old = self._caption
        new = self.make_caption(text) if text else None
        self._caption, self._caption_text = new, text
        span = (0, max(min(self.caption_fade_time, run_time), 1e-6))
        anims: list[Animation] = []
        if old is not None and new is not None and len(old) == 2 and len(new) == 2:
            # The band changes height rather than fading, which would dim it in between
            anims.append(ReplacementTransform(old[0], new[0], time_span=span))
            anims.append(FadeOut(old[1], time_span=span))
            anims.append(FadeIn(new[1], time_span=span))
        else:
            anims += [FadeOut(piece, time_span=span) for piece in old or ()]
            anims += [FadeIn(piece, time_span=span) for piece in new or ()]
        for anim in anims:
            anim.run_time = run_time
        return anims

    def _set_caption_now(self, text: str) -> None:
        self._next_caption = None
        if self._caption is not None:
            self.remove(*self._caption)
        self._caption = self.make_caption(text) if text else None
        self._caption_text = text
        if self._caption is not None:
            self.add(*self._caption)

    # Time on a grid of frames

    def get_time_progression(
        self,
        run_time: float,
        n_iterations: int | None = None,
        desc: str = "",
        override_skip_animations: bool = False,
    ):
        self._pending_run_time = run_time
        if self.skip_animations and not override_skip_animations:
            return [run_time]
        start = self.doc_time
        fps = self.camera.fps
        first = _frame_at(start, fps) + 1
        last = _frame_at(start + run_time, fps)
        times = [min(max(k / fps - start, 0.0), run_time) for k in range(first, last + 1)]
        if times:
            # The last frame of a play shows where it ends, exactly
            times[-1] = run_time
        return self._timed(times, start)

    def _timed(self, times: list[float], start: float) -> Iterator[float]:
        for t in times:
            self._clock = start + t
            yield t

    def post_play(self):
        self.doc_time += self._pending_run_time
        self._pending_run_time = 0.0
        super().post_play()

    def emit_frame(self) -> None:
        if self.skip_animations:
            return
        super().emit_frame()
        self.frames_emitted += 1
        if self.plan.progress is not None:
            self.plan.progress(getattr(self, "_clock", self.doc_time), self._step_index)

    def tear_down(self) -> None:
        # A video has to hold something, so a stretch of steps which takes no time at all
        # (only adds and removes, say) comes out as the one frame they leave behind
        if self.file_writer.write_to_movie and self.frames_emitted == 0 and not self.plan.still:
            self.stop_skipping()
            self.update_frame(force_draw=True)
            self.file_writer.write_frame()
            self.frames_emitted += 1
        super().tear_down()


def _frame_at(seconds: float, fps: float) -> int:
    """The frame showing a moment: the nearest one, halves rounding up, as the grid is laid out."""
    return math.floor(seconds * fps + 0.5 + 1e-9)


# Helpers generated code calls

def Grow(mobject: Mobject, **kwargs) -> Animation:
    """
    Grows an object into view: an arrow from its tail, a group led by an arrow (a labelled
    vector, say) likewise with the rest fading in beside it, anything else from its centre.
    """
    if isinstance(mobject, Line) and mobject.has_points():
        return GrowArrow(mobject, **kwargs)
    members = mobject.submobjects
    if (
        not mobject.has_points() and members
        and isinstance(members[0], Line) and members[0].has_points()
    ):
        rest = members[1:]
        anims = [GrowArrow(members[0])] + [FadeIn(member) for member in rest]
        return AnimationGroup(*anims, group=mobject, **kwargs)
    return GrowFromCenter(mobject, **kwargs)


def FlashOn(mobject: Mobject, color=YELLOW, **kwargs) -> Animation:
    """Flash, with the burst of lines sized to go round the object rather than a point."""
    radius = 0.3 + max(mobject.get_width(), mobject.get_height()) / 2
    return Flash(mobject, color=color, flash_radius=radius, line_length=0.25, **kwargs)


class ApplyMatrixOn(Animation):
    """
    ApplyMatrix, with the matrix read in a coordinate system's own coordinates: about its
    origin, and in its units. That is what a matrix applied to a number plane, and to vectors
    drawn on it, is meant to do, wherever the plane sits and however its axes are scaled.
    Without `coords`, an object which is a coordinate system is taken in its own coordinates,
    and anything else in the frame's.

    Arrows are carried by their two ends, their heads keeping their shape, as a vector does
    in a linear transformation, rather than being sheared along with everything else.
    """
    def __init__(self, matrix, mobject: Mobject, coords: Mobject | None = None, **kwargs):
        if coords is None and hasattr(mobject, "c2p") and hasattr(mobject, "get_axes"):
            coords = mobject
        matrix = np.array(matrix, dtype=float)
        size = matrix.shape[0]
        full = np.identity(3)
        full[:size, :size] = matrix
        origin = np.zeros(3)
        basis = np.identity(3)
        if coords is not None:
            origin = np.array(coords.get_origin(), dtype=float)
            dims = len(coords.get_axes())
            for i in range(min(dims, 3)):
                unit = [0.0] * dims
                unit[i] = 1.0
                basis[:, i] = np.array(coords.c2p(*unit), dtype=float) - origin
            if dims < 3:
                basis[:, 2] = OUT
        self.origin = origin
        self.frame_matrix = basis @ full @ np.linalg.inv(basis)
        super().__init__(mobject, **kwargs)

    def mapped(self, points: np.ndarray, alpha: float) -> np.ndarray:
        """Points moved alpha of the way to where the matrix takes them, straight there as a grid's points go."""
        step = (1 - alpha) * np.identity(3) + alpha * self.frame_matrix
        return self.origin + (np.asarray(points) - self.origin) @ step.T

    def interpolate_submobject(self, submobject: Mobject, starting: Mobject, alpha: float) -> None:
        if isinstance(submobject, Arrow) and starting.has_points():
            ends = self.mapped(np.array([starting.get_start(), starting.get_end()]), alpha)
            submobject.put_start_and_end_on(*ends)
            return
        if not starting.has_points():
            return
        for key in submobject.pointlike_data_keys:
            submobject.data[key] = self.mapped(starting.data[key], alpha)
        submobject.refresh_bounding_box()
