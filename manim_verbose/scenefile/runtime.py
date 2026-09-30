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
    self.keep_beside(mob, next_to, anchor=, side=, buff=, shift=) -> mob
    self.follow(mob, target, anchor=, side=) / self.stop_following(*mobs)
                                         an object which stays beside another, see "Following"
    self.changed(old, new, ...) -> new   the object a change step built takes the old one's place
    self.transformed_as(old, new, on=) -> new
                                         a new look, transformed the way the old one has been
    with self.carried_from(scene_id):    objects brought over from the scene before, see carry.py
    self.apply_now(*animations)          animations played out at once, taking no time
and the machinery render.py drives: stopping after a given step to capture a still with
the pixel bounding box of every registered object on screen, rendering only a range of
steps, and reporting progress.

Following. An object placed beside another with `follow` keeps to the point of it it was
placed against, the tip or tail of a vector, the start or end of a line or arc, or for the
whole object the middle of the side it is beside, for as long as both are on screen. It
keeps its offset from that point exactly (it is moved by as much as the point moves, once a
frame, after the animations of that frame), so it stays beside its target through moves,
changes, matrices and transforms, played alone or together with anything else, and while it
is being drawn or faded in itself. While either of the two is off screen the follower stays
where it is: a hidden target moving, or coming back as it was after being transformed into
something else, doesn't drag it along; once both are on screen again it catches up. Moving
the follower some other way (a move, a matrix) ends its following.

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

from manimlib.animation.animation import Animation, prepare_animation
from manimlib.animation.composition import AnimationGroup
from manimlib.animation.creation import DrawBorderThenFill, ShowCreation, ShowIncreasingSubsets
from manimlib.animation.fading import FadeIn, FadeOut, FadeTransform, VFadeIn
from manimlib.animation.growing import GrowArrow, GrowFromCenter, GrowFromPoint
from manimlib.animation.indication import Flash
from manimlib.animation.transform import ReplacementTransform, Transform
from manimlib.animation.transform_matching_parts import TransformMatchingParts
from manimlib.camera.camera import Camera
from manimlib.camera.camera_frame import CameraFrame
from manimlib.config import manim_config
from manimlib.constants import BLACK, DOWN, FRAME_HEIGHT, FRAME_WIDTH, LEFT, OUT, RIGHT, UP, WHITE, YELLOW
from manimlib.mobject.geometry import Arrow, Line, Rectangle, TipableVMobject
from manimlib.mobject.mobject import Group, Mobject, Point
from manimlib.mobject.svg.text_mobject import Text
from manimlib.scene.scene import EndScene, Scene
from manimlib.utils.family_ops import extract_mobject_family_members, recursive_mobject_remove

from manim_verbose.scenefile.layout import *  # noqa: F401,F403  (placement helpers, objects agent)
from manim_verbose.scenefile.layout import place, set_frame_shape
from manim_verbose.scenefile.expressions import *  # noqa: F401,F403  (safe functions, objects agent)


# Drawn above anything a scene file can ask for with `z`
CAPTION_Z = 1_000_000

# How long something done at once inside a play is taken to last, so that it has a moment of
# its own among the rest: an add or a remove whose turn comes part way through a together
INSTANT = 1e-6

# What `keep: dim` leaves the original of a transform at: its opacities times this
DIM_OPACITY = 0.35

SIDE_DIRECTIONS = {"up": UP, "down": DOWN, "left": LEFT, "right": RIGHT}

# Manim's own default font, as configured when this module was first imported
MANIM_DEFAULT_FONT = manim_config.text.font


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
    # Draw nothing at all, with a camera which needs no graphics device, for runs which only
    # want to know what the steps leave where, or how many frames they would come to
    headless: bool = False
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

    Where it differs from a plain Scene, it does so that the file means what it says:

    - Time runs on a grid of frames, see the module's docstring.
    - An object taken off screen during a step (hidden, cleared, or transformed into another)
      is put back, once the step is over, as it was before. Uncreate, a shrink or a transform
      leave the mobject they worked on emptied, shrunk or reshaped, and without this showing
      it again later would show that rather than the object.
    - Only steps which show things put them on screen. Manim adds whatever is animated to
      the scene, so a change, move or highlight of a hidden object would otherwise show it.
    - Adding a group whose members are already on screen draws them through the group from
      then on, rather than twice, and the camera's frame is never taken into a group.
    - Once the camera turns away from looking straight at the frame, arrows turn to face it.
    - The frame takes the shape of the picture, so that one which isn't 16:9 isn't stretched.
      Run by plain manimgl, which knows nothing of the scene file, a scene whose picture
      isn't 16:9 (doc_resolution) keeps the size manimgl asks for along its shorter side and
      takes the scene file's shape.
    - Objects placed with `follow` stay beside what they follow, see "Following" above.
    - A change leaves the object as the new look built for it, in every way (the parts of a
      new text are the new text's), and as transformed as the old one was.
    """
    scene_id: str = ""
    caption_style: CaptionStyle = CaptionStyle()
    # Font for text which doesn't name its own, from the scene file's settings.font
    default_font: str | None = None
    # How long a caption takes to fade from one to the next, at most
    caption_fade_time: float = 0.5
    # The scene file's resolution, where it isn't 16:9, for a render by plain manimgl
    doc_resolution: tuple[int, int] | None = None

    def __init__(self, plan: RenderPlan | None = None, **kwargs):
        # Asked for by the machinery below as soon as Scene.__init__ runs
        self._follows: dict[str, _Follow] = {}
        self._pending_follows: dict[int, tuple[Mobject, _Follow]] = {}
        self._playing: list[Animation] = []
        self._replaying = False
        if plan is None and self.doc_resolution is not None:
            kwargs["camera_config"] = self._manimgl_camera_config(kwargs.get("camera_config"))
        self.plan = plan or RenderPlan()
        # Text reads its default font from manim's configuration as it is built. Set it for
        # every scene, back to manim's own when this one names none, since a process which
        # renders one scene file after another would otherwise carry a font over
        manim_config.text.font = self.default_font or MANIM_DEFAULT_FONT
        if self.plan.still or self.plan.first_step > 0:
            kwargs["skip_animations"] = True
        if self.plan.headless:
            # Scene.__init__ makes its camera from the Camera named in its own module
            import manimlib.scene.scene as scene_module
            real = scene_module.Camera
            scene_module.Camera = HeadlessCamera
            try:
                super().__init__(**kwargs)
            finally:
                scene_module.Camera = real
        else:
            super().__init__(**kwargs)
        self._fit_frame_to_picture()
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
        # The matrices applied to each object so far, as one map of the frame, see transformed_as
        self._maps: dict[str, np.ndarray] = {}
        # Ids of the objects carried over from the scene before
        self.carried_ids: list[str] = []

    def _manimgl_camera_config(self, given: dict | None) -> dict:
        """
        The camera plain manimgl gets: the resolution it asks for (from -l, --hd and the like)
        along the shorter side, and the scene file's shape, since everything was laid out for
        a frame of that shape.
        """
        config = dict(given or {})
        asked = config.get("resolution") or manim_config.camera.resolution
        if isinstance(asked, str):
            from ast import literal_eval
            asked = literal_eval(asked)
        short = min(int(asked[0]), int(asked[1]))
        width, height = self.doc_resolution
        scale = short / min(width, height)
        config["resolution"] = (max(2, round(width * scale / 2) * 2), max(2, round(height * scale / 2) * 2))
        return config

    def _fit_frame_to_picture(self) -> None:
        """
        Makes the frame the shape of the picture. Manim's frame is 16:9 whatever size a
        picture is drawn at, and its projection is fixed to that too, so a picture of any
        other shape (a portrait video, say) would come out stretched. The frame keeps its
        height of 8 units and takes the picture's width, and layout places objects in it.
        """
        width, height = self.camera.default_pixel_shape
        self.frame_width = FRAME_HEIGHT * width / height
        set_frame_shape(self.frame_width, FRAME_HEIGHT)
        if abs(self.frame_width - FRAME_WIDTH) < 1e-6:
            return
        frame = self.frame
        frame.set_width(self.frame_width, stretch=True)
        frame.__class__ = _FittedFrame
        frame.default_shape = (self.frame_width, FRAME_HEIGHT)
        camera = self.camera
        refresh = camera.refresh_uniforms
        frame_width = self.frame_width

        def refresh_uniforms() -> None:
            refresh()
            if camera.gpu is not None:
                camera.gpu.frame_uniforms.update(frame_rescale_factors=(
                    2.0 / frame_width, 2.0 / FRAME_HEIGHT, frame.get_scale() / frame.get_focal_distance(),
                ))

        camera.refresh_uniforms = refresh_uniforms

    # Objects and steps, which is what generated code calls

    def obj(self, obj_id: str, mobject: Mobject) -> Mobject:
        """Registers a mobject under its id in the scene file, and hands it back."""
        self.objects[obj_id] = mobject
        pending = self._pending_follows.pop(id(mobject), None)
        if pending is not None:
            self._start_following(obj_id, pending[1])
        return mobject

    def id_of(self, mobject: Mobject) -> str | None:
        """The id a mobject is registered under, if it is."""
        for obj_id, mob in self.objects.items():
            if mob is mobject:
                return obj_id
        return None

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

    def is_on_screen(self, mobject: Mobject, in_scene: set[Mobject] | None = None) -> bool:
        """Whether everything this mobject draws is in the scene."""
        drawn = [mob for mob in mobject.get_family() if mob.has_points()]
        if not drawn:
            return False
        if in_scene is None:
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
            pixels = self.frame_to_pixels(corners, fixed=self.objects[obj_id].is_fixed_in_frame())
            frame_box = (float(mins[0]), float(mins[1]), float(maxs[0]), float(maxs[1]))
            pixel_box = (
                float(pixels[:, 0].min()), float(pixels[:, 1].min()),
                float(pixels[:, 0].max()), float(pixels[:, 1].max()),
            )
            boxes.append((obj_id, frame_box, pixel_box))
        return boxes

    def frame_to_pixels(self, points: np.ndarray, fixed: bool = False) -> np.ndarray:
        """
        Where points of the scene land in the picture, in pixels from its top left. This is
        the projection the shaders make (see shaders/inserts/project_point.wgsl), done here
        for points the editor needs to know the place of. Points of an object fixed in the
        frame are where they would be with the camera where it started, whatever it has done
        since, as the shaders take them.
        """
        frame = self.frame
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        homogeneous = np.hstack([points, np.ones((len(points), 1))])
        viewed = homogeneous if fixed else homogeneous @ frame.get_view_matrix().T
        rescale = np.array([
            2.0 / self.frame_width, 2.0 / FRAME_HEIGHT,
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
        # The camera's frame stays where it is, first and on its own, even when an animation
        # moving it is grouped with others (as a together groups them) and the group added
        new_mobjects = tuple(piece for mob in new_mobjects for piece in self._without_frame(mob))
        held = {
            sm for mob in new_mobjects for sm in mob.get_family()[1:]
        } - set(new_mobjects) - {self.frame}
        if held:
            self.mobjects, _ = recursive_mobject_remove(self.mobjects, held)
        return super().add(*new_mobjects)

    def draw_frame(self, dt: float = 0, force_draw: bool = False) -> None:
        if force_draw or not self.skip_animations:
            self._turn_arrows_to_camera()
        super().draw_frame(dt, force_draw)

    def _turn_arrows_to_camera(self) -> None:
        """
        An arrow is a flat shape, which seen edge on from a turned camera all but vanishes; so
        once the camera has turned away from looking straight down at the frame, every arrow
        is turned about its own length to face it before a frame is drawn, as 3D scenes of
        vectors do. A camera which hasn't turned leaves arrows as they are.
        """
        if np.allclose(self.frame.get_orientation().as_quat(), [0, 0, 0, 1]):
            return
        for mob in self.get_mobject_family_members():
            if isinstance(mob, Arrow) and mob.has_points() and not mob.is_fixed_in_frame():
                mob.set_perpendicular_to_camera(self.frame)

    def _without_frame(self, mobject: Mobject) -> list[Mobject]:
        """A mobject, or where it holds the camera's frame, what it holds besides."""
        if mobject is self.frame:
            return [] if self.frame in self.mobjects else [mobject]
        if self.frame not in mobject.get_family():
            return [mobject]
        return [piece for sub in mobject.submobjects for piece in self._without_frame(sub)]

    def play(self, *proto_animations, run_time: float | None = None, **kwargs):
        if not proto_animations:
            return super().play(*proto_animations, run_time=run_time, **kwargs)
        animations = [self._as_animation(anim) for anim in proto_animations]
        given = list(animations)
        if self._in_step:
            self._snapshot_animated(animations)
        if self._next_caption is not None and self._in_step:
            length = run_time or max(anim.get_run_time() for anim in animations)
            animations += self._caption_transition(self._next_caption, length)
            run_time = length
        leaves = list(_leaves(animations))
        for anim in leaves:
            if isinstance(anim, _AtItsTime):
                anim.scene = self
        self._playing = leaves
        try:
            result = super().play(*animations, run_time=run_time, **kwargs)
        except Exception as err:
            # Which of the animations it went wrong in, for render.py to name the step inside
            # a together it came from, see problems_from_exception
            if getattr(err, "docscene_path", None) is None:
                err.docscene_path = _failing_path(err, given)
            raise
        finally:
            self._playing = []
        self._note_matrices(leaves)
        return result

    def update_mobjects(self, dt: float) -> None:
        super().update_mobjects(dt)
        # After the animations of the frame and the objects' own updaters, so that what
        # follows is put beside where its target has just got to
        self._keep_followers_beside()

    # Following, see the module's docstring

    def keep_beside(
        self, mobject: Mobject, next_to: Mobject, anchor: str = "center", side: str = "down",
        buff: float = 0.25, shift=None,
    ) -> Mobject:
        """Puts mobject beside next_to (at its anchor, see beside), and keeps it there from now on."""
        beside(mobject, next_to, anchor=anchor, side=side, buff=buff, shift=shift)
        return self.follow(mobject, next_to, anchor=anchor, side=side)

    def follow(self, mobject: Mobject, target: Mobject, anchor: str = "center", side: str = "down") -> Mobject:
        """From now on, mobject keeps where it is relative to the anchor of target, whenever both are on screen."""
        rule = _Follow(self.id_of(target) or target, anchor, side, anchor_point(target, anchor, side))
        follower = self.id_of(mobject)
        if follower is None:
            # Not registered yet, as while its object is being built: obj() takes it up
            self._pending_follows[id(mobject)] = (mobject, rule)
        else:
            self._start_following(follower, rule)
        return mobject

    def stop_following(self, *mobjects: Mobject) -> None:
        """These no longer follow anything: they have been moved some other way."""
        for mobject in mobjects:
            follower = self.id_of(mobject)
            if follower in self._follows:
                if self._replaying:
                    self._keep_followers_beside()
                del self._follows[follower]
            self._pending_follows.pop(id(mobject), None)

    def following(self) -> dict[str, str]:
        """Which object follows which, by id."""
        return {
            follower: rule.target if isinstance(rule.target, str) else "?"
            for follower, rule in self._follows.items()
        }

    def _start_following(self, follower: str, rule: _Follow) -> None:
        # Two which followed each other would push each other along for ever: the newer
        # following gives way
        target, seen = rule.target, set()
        while isinstance(target, str) and target not in seen:
            if target == follower:
                self._follows.pop(follower, None)
                return
            seen.add(target)
            ahead = self._follows.get(target)
            target = ahead.target if ahead is not None else None
        self._follows[follower] = rule

    def _following_order(self) -> list[str]:
        """Followers after whatever they follow, so that a chain of them moves in one frame."""
        order: list[str] = []
        placed: set[str] = set()

        def visit(follower: str, depth: int) -> None:
            if follower in placed or depth > len(self._follows):
                return
            target = self._follows[follower].target
            if isinstance(target, str) and target in self._follows:
                visit(target, depth + 1)
            placed.add(follower)
            order.append(follower)

        for follower in list(self._follows):
            visit(follower, 0)
        return order

    def _keep_followers_beside(self) -> None:
        if not self._follows:
            return
        # While objects carried over are being brought to how the scene before left them,
        # nothing is on screen yet, and followers catch up regardless
        in_scene = None if self._replaying else set(self.get_mobject_family_members())
        for follower_id in self._following_order():
            rule = self._follows[follower_id]
            follower = self.objects.get(follower_id)
            target = self.objects.get(rule.target) if isinstance(rule.target, str) else rule.target
            if follower is None or target is None:
                continue
            if in_scene is not None and not (self.is_on_screen(follower, in_scene) and self.is_on_screen(target, in_scene)):
                continue
            try:
                point = anchor_point(target, rule.anchor, rule.side)
            except ValueError:
                continue
            delta = point - rule.point
            if not np.all(np.isfinite(delta)) or np.allclose(delta, 0, atol=1e-9):
                continue
            rule.point = point
            follower.shift(delta)
            self._carry_along(follower, delta)

    def _carry_along(self, mobject: Mobject, delta: np.ndarray) -> None:
        """
        What the animations playing keep of mobject (the copy they start from, the shape they
        head for, an outline being drawn) moved along with it, so that a follower being
        written, faded in or changed while its target moves is drawn beside it throughout,
        rather than put back where it began by the next frame of its own animation.
        """
        members = set(mobject.get_family())
        for anim in self._playing:
            root = anim.mobject
            family = root.get_family()
            if root in members:
                index = None
            elif mobject in family:
                index = next(i for i, mob in enumerate(family) if mob is mobject)
            else:
                continue
            for ref in _references(anim):
                if index is None:
                    ref.shift(delta)
                else:
                    ref_family = ref.get_family()
                    if len(ref_family) == len(family):
                        ref_family[index].shift(delta)

    # Changes, matrices and objects carried over

    def transformed_as(self, old: Mobject, new: Mobject, on: Mobject | None = None) -> Mobject:
        """
        `new` put through the matrices `old` has been through, less those its coordinate
        system `on` has been through, which a new look built on it shows already. This is how
        a change keeps an object as a matrix left it: the new look lands where the old one
        is, as distorted.
        """
        old_id = self.id_of(old)
        mapping = self._maps.get(old_id, _IDENTITY) if old_id is not None else _IDENTITY
        if on is not None:
            on_id = self.id_of(on)
            base = self._maps.get(on_id, _IDENTITY) if on_id is not None else _IDENTITY
            mapping = mapping @ np.linalg.inv(base)
        if not np.allclose(mapping, _IDENTITY, atol=1e-9):
            map_mobject(new, mapping)
        return new

    def changed(self, old: Mobject, new: Mobject, on: Mobject | None = None, placed: bool = False) -> Mobject:
        """
        After a change: `new`, the look built for the object, takes the place of `old`
        everywhere (on screen, in any group holding it, under its id), so that whatever comes
        next finds the new look's own parts, the words of a new text say. The Transform just
        played left old looking like new, so nothing shows. Where the object was placed anew
        it is as transformed as its coordinate system `on`, and follows only what its new
        placement says.
        """
        obj_id = self.id_of(old)
        if obj_id is None or new is old:
            return new
        # Anything which moved old along during the change (following) moved new's likeness
        delta = old.get_center() - new.get_center()
        if np.all(np.isfinite(delta)) and not np.allclose(delta, 0, atol=1e-9):
            new.shift(delta)
        for index, mob in enumerate(self.mobjects):
            if mob is old:
                self.mobjects[index] = new
        for parent in list(old.parents):
            for index, mob in enumerate(parent.submobjects):
                if mob is old:
                    parent.replace_submobject(index, new)
        self.objects[obj_id] = new
        self.id_to_mobject_map.update({id(sm): sm for sm in new.get_family()})
        pending = self._pending_follows.pop(id(new), None)
        if pending is not None:
            rule = pending[1]
            target = self.objects.get(rule.target) if isinstance(rule.target, str) else rule.target
            rule.point = anchor_point(target, rule.anchor, rule.side)
            self._start_following(obj_id, rule)
        elif placed:
            self._follows.pop(obj_id, None)
        if placed:
            on_id = self.id_of(on) if on is not None else None
            self._maps[obj_id] = self._maps.get(on_id, _IDENTITY).copy() if on_id is not None else _IDENTITY.copy()
        return new

    def apply_now(self, *animations) -> None:
        """
        Animations played out at once, taking no time and drawing nothing: how objects carried
        over from the scene before are put through the matrices that scene applied to them.
        """
        anims = [prepare_animation(anim) for anim in animations]
        for anim in anims:
            anim.begin()
        for anim in anims:
            anim.finish()
        self._note_matrices(list(_leaves(anims)))
        if self._replaying:
            self._keep_followers_beside()

    @contextmanager
    def carried_from(self, scene_id: str) -> Iterator[None]:
        """
        Objects carried over from scene `scene_id`: built, brought to the state that scene
        left them in and put on screen inside the block, before the first step. Followers
        among them catch up with what they follow as they go, on screen or not.
        """
        before = set(self.objects)
        self._replaying = True
        try:
            yield
            self._keep_followers_beside()
        finally:
            self._replaying = False
        self.carried_ids = [obj_id for obj_id in self.objects if obj_id not in before]

    def _note_matrices(self, animations: list[Animation]) -> None:
        """Every registered object an ApplyMatrixOn just went over has that map added to its own, see transformed_as."""
        noted: set[str] = set()
        for anim in animations:
            if not isinstance(anim, ApplyMatrixOn):
                continue
            family = {id(member) for member in anim.mobject.get_family()}
            mapping = anim.frame_map()
            for obj_id, mob in self.objects.items():
                if obj_id not in noted and id(mob) in family:
                    noted.add(obj_id)
                    self._maps[obj_id] = mapping @ self._maps.get(obj_id, _IDENTITY)

    def wait(self, duration: float | None = None, *args, **kwargs):
        if self._next_caption is not None and self._in_step:
            duration = self.default_wait_time if duration is None else duration
            return self.play(*self._caption_transition(self._next_caption, duration), run_time=duration)
        return super().wait(duration, *args, **kwargs)

    def begin_animations(self, animations) -> None:
        """
        As Scene's, except that only animations which bring something on screen (writing,
        drawing, fading or growing it in, or transforming into it) leave it there. Manim adds
        whatever is animated to the scene, so without this a change, move or highlight of an
        object which isn't on screen would show it, when all it should do is update it for
        whenever it is shown.
        """
        before = set(self.get_mobject_family_members())
        # Taken before the animations begin, since beginning a transform can give an object
        # new pieces (to match what it is turning into), which are on screen if it is
        hidden = {mob for obj in self.objects.values() for mob in obj.get_family()} - before
        super().begin_animations(animations)
        introduced = set(extract_mobject_family_members(_introduced_by(animations)))
        stray = [
            mob for mob in self.get_mobject_family_members()
            if mob in hidden and mob not in introduced and mob.has_points()
        ]
        if stray:
            self.remove(*stray)

    @staticmethod
    def _as_animation(anim) -> Animation:
        from manimlib.animation.animation import prepare_animation
        return prepare_animation(anim)

    def _snapshot_animated(self, animations: list[Animation]) -> None:
        """
        Copies of the registered objects these animations take off screen, taken before they
        start on them. Only those: an object changed, moved or recolored while it is hidden
        is meant to keep what was done to it.
        """
        departing = set(extract_mobject_family_members(_taken_away_by(animations)))
        if not departing:
            return
        for obj_id, mob in self.objects.items():
            if obj_id not in self._snapshots and any(m in departing for m in mob.get_family()):
                self._snapshots[obj_id] = mob.copy()

    def _restore_departed(self) -> None:
        if self._snapshots:
            in_scene = set(self.get_mobject_family_members())
            for obj_id, snapshot in self._snapshots.items():
                mob = self.objects[obj_id]
                if not self.is_on_screen(mob, in_scene):
                    mob.become(snapshot)
        self._snapshots = {}

    # Captions

    def make_caption(self, text: str) -> tuple[Mobject, ...]:
        """The pieces of a caption: its words, and the band behind them if there is one."""
        style = self.caption_style
        frame_width = self.frame_width
        words = Text(text, font_size=style.font_size, alignment="CENTER", line_width=frame_width - 1.5)
        words.set_color(style.color)
        if words.get_width() > frame_width - 1:
            words.set_width(frame_width - 1)
        direction = DOWN if style.edge == "bottom" else UP
        pieces: tuple[Mobject, ...]
        if style.background:
            pad = 0.18
            band = Rectangle(width=frame_width + 0.2, height=words.get_height() + 2 * pad)
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


class _FittedFrame(CameraFrame):
    """A camera frame whose normal view is the shape of the picture, rather than manim's 16:9."""
    default_shape: tuple[float, float] = (FRAME_WIDTH, FRAME_HEIGHT)

    def to_default_state(self):
        self.set_shape(*self.default_shape)
        self.center()
        self.set_orientation(self.default_orientation)
        return self


class HeadlessCamera(Camera):
    """
    A camera which draws nothing and so needs no graphics device: everything about where the
    frame is and how big a picture of it would be, and no pictures.
    """

    def init_renderer(self) -> None:
        self.gpu = None
        self.renderer = None

    def init_target(self) -> None:
        self.pixel_shape = tuple(self.default_pixel_shape)

    def capture(self, *mobjects: Mobject) -> None:
        pass

    def refresh_uniforms(self) -> None:
        pass

    def get_image(self):
        from PIL import Image
        return Image.new("RGBA", self.pixel_shape)


def _taken_away_by(animations) -> list[Mobject]:
    """What these animations take off screen: whatever they remove, and whatever they turn into something else."""
    found: list[Mobject] = []
    for anim in animations:
        if isinstance(anim, TransformMatchingParts):
            found.append(anim.source)
        elif isinstance(anim, AnimationGroup):
            found += _taken_away_by(anim.animations)
            if anim.is_remover():
                found.append(anim.mobject)
        elif isinstance(anim, FadeTransform):
            found.append(anim.mobject[0])
        elif anim.is_remover() or (isinstance(anim, Transform) and anim.replace_mobject_with_target_in_scene):
            found.append(anim.mobject)
    return found


def _introduced_by(animations) -> list[Mobject]:
    """What these animations bring on screen, as opposed to whatever else they move about."""
    found: list[Mobject] = []
    for anim in animations:
        if isinstance(anim, TransformMatchingParts):
            found.append(anim.target)
        elif isinstance(anim, AnimationGroup):
            found += _introduced_by(anim.animations)
        elif isinstance(anim, FadeTransform):
            found.append(anim.to_add_on_completion)
        elif isinstance(anim, Transform) and anim.replace_mobject_with_target_in_scene:
            found.append(anim.target_mobject)
        elif anim.is_remover():
            continue
        elif isinstance(anim, (DrawBorderThenFill, ShowCreation, FadeIn, VFadeIn, GrowFromPoint, ShowIncreasingSubsets)):
            found.append(anim.mobject)
    return found


def _frame_at(seconds: float, fps: float) -> int:
    """The frame showing a moment: the nearest one, halves rounding up, as the grid is laid out."""
    return math.floor(seconds * fps + 0.5 + 1e-9)


def _leaves(animations) -> Iterator[Animation]:
    """The animations inside these, groups opened up."""
    for anim in animations:
        if isinstance(anim, AnimationGroup):
            yield from _leaves(anim.animations)
        else:
            yield anim


def _references(anim: Animation) -> list[Mobject]:
    """What an animation keeps of its mobject to work from: its starting copy, its target, an outline."""
    try:
        kept = anim.get_all_mobjects()
    except AttributeError:
        return []
    out: list[Mobject] = []
    for mob in kept:
        if mob is not None and mob is not anim.mobject and all(mob is not other for other in out):
            out.append(mob)
    return out


def _path_to(target: Animation, animations, prefix: tuple[int, ...] = ()) -> tuple[int, ...] | None:
    for index, anim in enumerate(animations):
        if anim is target:
            return prefix + (index,)
        if isinstance(anim, AnimationGroup):
            found = _path_to(target, anim.animations, prefix + (index,))
            if found is not None:
                return found
    return None


def _failing_path(err: BaseException, animations: list[Animation]) -> tuple[int, ...] | None:
    """
    Where the animation a play went wrong in is among those it was given: the index of one
    given to it, then of one inside that, and so on. None where it went wrong elsewhere.
    """
    found: list[Animation] = []
    tb = err.__traceback__
    while tb is not None:
        candidate = tb.tb_frame.f_locals.get("self")
        if isinstance(candidate, Animation):
            found.append(candidate)
        tb = tb.tb_next
    for anim in reversed(found):
        path = _path_to(anim, animations)
        if path is not None:
            return path
    return None


@dataclass
class _Follow:
    """One object following another, see DocScene.follow."""
    # The id of what is followed, or the mobject itself where it isn't registered
    target: str | Mobject
    anchor: str
    side: str
    # Where the point followed was when the follower was last put beside it
    point: np.ndarray


# Anchors: the point of an object something is placed beside

def anchor_point(mobject: Mobject, anchor: str = "center", side: str = "down") -> np.ndarray:
    """
    The point of mobject something placed beside it keeps to: the tip or tail of a vector,
    the end or start of a line or arc, and for the whole object ("center") the middle of the
    side something is beside it on.
    """
    if anchor == "center":
        try:
            direction = SIDE_DIRECTIONS[side]
        except KeyError:
            raise ValueError(f"'{side}' isn't a side: use one of {', '.join(SIDE_DIRECTIONS)}") from None
        return np.array(mobject.get_critical_point(direction), dtype=float)
    line = _line_of(mobject)
    if anchor in ("tip", "end"):
        return np.array(line.get_end(), dtype=float)
    if anchor in ("tail", "start"):
        return np.array(line.get_start(), dtype=float)
    raise ValueError(f"'{anchor}' isn't an anchor: use one of center, tip, tail, start or end")


def _line_of(mobject: Mobject) -> TipableVMobject:
    """The line, arrow or arc an object is or leads with: a labelled vector, or one with a backdrop, is a group."""
    for mob in mobject.get_family():
        if isinstance(mob, TipableVMobject) and mob.has_points():
            return mob
    raise ValueError(f"A {type(mobject).__name__} has no start or end to be beside")


def beside(
    mobject: Mobject, next_to: Mobject, anchor: str = "center", side: str = "down",
    buff: float = 0.25, shift=None,
) -> Mobject:
    """
    place(mobject, next_to=...), except that with an anchor other than "center" it goes
    beside that point of next_to (its tip or tail, start or end) rather than the whole of it.
    """
    if anchor == "center":
        return place(mobject, next_to=next_to, side=side, buff=buff, shift=shift)
    return place(mobject, next_to=Point(anchor_point(next_to, anchor)), side=side, buff=buff, shift=shift)


_IDENTITY = np.identity(4)


def map_mobject(mobject: Mobject, mapping: np.ndarray) -> Mobject:
    """
    A mobject put through a map of the frame (4x4, homogeneous) as ApplyMatrixOn puts it:
    arrows by their two ends, keeping their heads' shape, everything else point by point.
    """
    linear, offset = mapping[:3, :3], mapping[:3, 3]

    def apply(points: np.ndarray) -> np.ndarray:
        return np.asarray(points, dtype=float) @ linear.T + offset

    for sub in mobject.get_family():
        if not sub.has_points():
            continue
        if isinstance(sub, Arrow):
            sub.put_start_and_end_on(*apply(np.array([sub.get_start(), sub.get_end()])))
            continue
        for key in sub.pointlike_data_keys:
            sub.data[key] = apply(sub.data[key])
        sub.refresh_bounding_box()
    return mobject


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


class _AtItsTime(Animation):
    """
    Something done at once, the moment its turn comes among the animations of a LaggedStart
    or AnimationGroup, and then run_time of nothing. Adds and removes inside a lagged
    together are these, so that they happen when their place in the together comes round.

    The scene playing it hands itself over before it starts (see DocScene.play). With no
    run_time it lasts INSTANT, so that it still has a moment of its own: AnimationGroup never
    says when something lasting no time at all has come.
    """

    def __init__(self, mobject: Mobject, run_time: float = 0.0, **kwargs):
        super().__init__(mobject, run_time=max(float(run_time), INSTANT), **kwargs)
        self.scene: Scene | None = None
        self.done = False

    def begin(self) -> None:
        self.done = False

    def interpolate(self, alpha: float) -> None:
        if alpha > 0 and not self.done and self.scene is not None:
            self.done = True
            self.act(self.scene)

    def finish(self) -> None:
        self.interpolate(1.0)

    def act(self, scene: Scene) -> None:
        raise NotImplementedError

    def get_all_mobjects(self) -> tuple[Mobject, ...]:
        return (self.mobject,)

    def update_reference_mobjects(self, dt: float, frame_rate: float | None = None) -> None:
        pass

    def clean_up_from_scene(self, scene: Scene) -> None:
        pass


class Add(_AtItsTime):
    """Puts something on screen at once when its turn comes in a play, as `add` inside a lagged together."""

    def act(self, scene: Scene) -> None:
        scene.add(self.mobject)


class Remove(_AtItsTime):
    """Takes something off screen at once when its turn comes in a play, as `remove` inside a lagged together."""

    def __init__(self, mobject: Mobject, run_time: float = 0.0, **kwargs):
        super().__init__(mobject, run_time=run_time, remover=True, **kwargs)

    def act(self, scene: Scene) -> None:
        scene.remove(self.mobject)


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

    def frame_map(self) -> np.ndarray:
        """Where this takes the frame, all the way, as a 4x4 homogeneous matrix."""
        mapping = np.identity(4)
        mapping[:3, :3] = self.frame_matrix
        mapping[:3, 3] = self.origin - self.frame_matrix @ self.origin
        return mapping

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
