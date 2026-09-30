"""
Steps to code: for each kind of step, the lines of Python which play it, inside the scene's
construct method.

OWNER: steps/render agent.

    step_lines(step, ctx) -> list[str]
        The body of the step's `with self.step(...)` block. May update ctx.objects (a change
        step records the object's new values there).
    default_run_time(step, ctx) -> float
        How long a step takes when it doesn't say. timeline() in render.py uses the same
        numbers, so durations can be known without rendering anything.

Every kind of step comes down to the same three parts (see StepCode): lines which happen at
once before anything moves, the animations which play, and lines which happen at once
afterwards. A step on its own plays its animations in one `self.play(...)`; a `together` step
gathers the animations of each step inside it into one play of its own, which is why the
parts are kept apart until the last moment.

Every play is given its run_time explicitly, whatever manim's own default for the animation
would have been, so that how long a step takes is decided here and nowhere else.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from manim_verbose.scenefile import blocks
from manim_verbose.scenefile.codegen import CodegenContext
from manim_verbose.scenefile.model import (
    AddStep, ApplyMatrixStep, CameraStep, ChangeStep, ClearStep, FreeObject, GroupObject,
    HideStep, HighlightStep, ImageObject, MoveStep, ObjectBase, Placement, RemoveStep,
    ShowStep, StepBase, TogetherStep, TransformStep, WaitStep,
)

# How long each kind of step takes when it doesn't say, in seconds
SHOW_TIMES = {"write": 1.5, "draw": 1.5, "fade": 1.0, "fade_up": 1.0, "grow": 1.0, "pop": 0.75}
HIDE_TIME = 1.0
CLEAR_TIME = 1.0
TRANSFORM_TIME = 1.5
CHANGE_TIME = 1.0
MOVE_TIME = 1.0
HIGHLIGHT_TIMES = {"indicate": 1.0, "flash": 1.0, "box": 1.5, "underline": 1.5, "wiggle": 1.5, "recolor": 1.0}
CAMERA_TIME = 2.0
APPLY_MATRIX_TIME = 2.0

HIGHLIGHT_COLOR = "YELLOW"
TEXT_KINDS = ("text", "tex")
COORDINATE_KINDS = ("number_plane", "axes", "axes_3d")
# Fields which say where an object is, as opposed to what it looks like; a change to one of
# these leaves the object wherever they now put it
POSITION_FIELDS = {"place", "point", "tip", "tail", "start", "end", "points", "on", "target", "members", "arrange"}


# Animations as source text

@dataclass
class Anim:
    """
    An animation written as Python, kept in two halves so that keyword arguments such as
    run_time can still be added: a call, `Write(eq)`, takes them before its closing
    parenthesis, and a builder, `eq.animate.shift(UP)`, right after `.animate`.
    """
    head: str
    args: list[str] = field(default_factory=list)
    chain: str | None = None

    @classmethod
    def call(cls, name: str, *args: str) -> Anim:
        return cls(name, list(args))

    @classmethod
    def builder(cls, mobject: str, chain: str) -> Anim:
        return cls(f"{mobject}.animate", chain=chain)

    def text(self, **kwargs: str) -> str:
        extra = [f"{key}={value}" for key, value in kwargs.items()]
        if self.chain is not None:
            return self.head + (f"({', '.join(extra)})" if extra else "") + self.chain
        return f"{self.head}({', '.join(self.args + extra)})"


@dataclass
class StepCode:
    """What a step comes to, before it is written out as lines: see the module's docstring."""
    before: list[str] = field(default_factory=list)
    anims: list[Anim] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    # How several animations of the step are staggered, from 0 (all at once) to 1 (in turn)
    lag: float = 0.0
    duration: float = 0.0
    # Which step inside a together each line of `before` and `after` came from, as the path
    # of indices down to it; left empty, every line is the step's own
    before_from: list[tuple[int, ...]] = field(default_factory=list)
    after_from: list[tuple[int, ...]] = field(default_factory=list)

    def play_line(self) -> str | None:
        """The one play of the step, or a wait where it has nothing to animate but takes time."""
        if self.anims:
            if len(self.anims) > 1 and self.lag > 0:
                inner = self.lagged()
            else:
                inner = ", ".join(anim.text() for anim in self.anims)
            return f"self.play({inner}, run_time={num(self.duration)})"
        if self.duration > 0:
            return f"self.wait({num(self.duration)})"
        return None

    def lagged(self) -> str:
        # Each piece is given the same length, which the play then stretches to the step's,
        # so that the stagger comes out as asked whatever manim's defaults for them are
        pieces = ", ".join(anim.text(run_time="1") for anim in self.anims)
        return f"LaggedStart({pieces}, lag_ratio={num(self.lag)})"

    def as_anim(self) -> Anim:
        """All of this step's animations as one, which takes a run_time, for a together."""
        if len(self.anims) == 1:
            return self.anims[0]
        pieces = ", ".join(anim.text(run_time="1") for anim in self.anims)
        if self.lag > 0:
            return Anim.call("LaggedStart", pieces, f"lag_ratio={num(self.lag)}")
        return Anim.call("AnimationGroup", pieces)

    def lines(self) -> list[str]:
        return [line for line, _ in self.lines_from()]

    def lines_from(self) -> list[tuple[str, tuple[int, ...]]]:
        """The lines, each with the path to the step inside a together it came from, () for the step itself."""
        play = self.play_line()
        before = zip(self.before, self.before_from or [()] * len(self.before))
        after = zip(self.after, self.after_from or [()] * len(self.after))
        return [*before, *([(play, ())] if play else []), *after]


# The interface

def step_lines(step: StepBase, ctx: CodegenContext) -> list[str]:
    return step_code(step, ctx).lines()


def step_lines_from(step: StepBase, ctx: CodegenContext) -> list[tuple[str, tuple[int, ...]]]:
    """step_lines, each line with the path to the step inside a together it came from, for codegen's line map."""
    return step_code(step, ctx).lines_from()


def default_run_time(step: StepBase, ctx: CodegenContext) -> float:
    if isinstance(step, ShowStep):
        # A target which doesn't exist (in a document with errors, which can still be saved)
        # is timed as a fade, so that timings are there to show whatever state it is in
        styles = [
            _show_style(ctx.objects[obj_id], step.style) if obj_id in ctx.objects else "fade"
            for obj_id in targets_of(step)
        ]
        return _staggered(max(SHOW_TIMES[style] for style in styles), len(styles), step.lag)
    if isinstance(step, HideStep):
        return _staggered(HIDE_TIME, len(targets_of(step)), step.lag)
    if isinstance(step, (AddStep, RemoveStep)):
        return 0.0
    if isinstance(step, ClearStep):
        return CLEAR_TIME
    if isinstance(step, TransformStep):
        return TRANSFORM_TIME
    if isinstance(step, ChangeStep):
        return CHANGE_TIME
    if isinstance(step, MoveStep):
        return MOVE_TIME
    if isinstance(step, HighlightStep):
        return HIGHLIGHT_TIMES[step.style]
    if isinstance(step, WaitStep):
        return step.duration
    if isinstance(step, CameraStep):
        return CAMERA_TIME
    if isinstance(step, ApplyMatrixStep):
        return APPLY_MATRIX_TIME
    if isinstance(step, TogetherStep):
        return _together_time([_inner_duration(inner, ctx) for inner in step.steps], step.lag)
    raise ValueError(f"No such kind of step: {step.do}")


def step_duration(step: StepBase, ctx: CodegenContext) -> float:
    """How long a step takes: what it says, or its kind's default."""
    if isinstance(step, WaitStep):
        return step.duration
    if step.run_time is not None:
        return step.run_time
    return default_run_time(step, ctx)


def _inner_duration(step: StepBase, ctx: CodegenContext) -> float:
    """How long a step inside a together takes: adds and removes happen at its start, whatever they say."""
    if isinstance(step, (AddStep, RemoveStep)):
        return 0.0
    return step_duration(step, ctx)


def _staggered(each: float, count: int, lag: float) -> float:
    """How long `count` animations of `each` seconds take, each starting `lag` of the way through the one before."""
    return round(each * (1 + (count - 1) * lag), 3)


def _together_time(durations: list[float], lag: float) -> float:
    """
    How long steps played together take, laid out as AnimationGroup lays them out. Steps
    which take no time (adds and removes) happen at the start, and don't take part.
    """
    start, end = 0.0, 0.0
    for duration in durations:
        if duration <= 0:
            continue
        end = max(end, start + duration)
        start += lag * duration
    return round(end, 3)


# Each kind of step

def step_code(step: StepBase, ctx: CodegenContext) -> StepCode:
    maker = {
        ShowStep: _show, HideStep: _hide, AddStep: _add, RemoveStep: _remove,
        ClearStep: _clear, TransformStep: _transform, ChangeStep: _change, MoveStep: _move,
        HighlightStep: _highlight, WaitStep: _wait, CameraStep: _camera,
        ApplyMatrixStep: _apply_matrix, TogetherStep: _together,
    }[type(step)]
    code = maker(step, ctx)
    if not isinstance(step, TogetherStep):
        code.duration = step_duration(step, ctx)
    return code


def _show(step: ShowStep, ctx: CodegenContext) -> StepCode:
    anims = [_show_anim(ctx, obj_id, step.style) for obj_id in targets_of(step)]
    return StepCode(anims=anims, lag=step.lag)


def _show_style(obj: ObjectBase, style: str) -> str:
    return blocks.default_show_style(obj) if style == "auto" else style


def _show_anim(ctx: CodegenContext, obj_id: str, style: str) -> Anim:
    obj = ctx.spec(obj_id)
    var = ctx.var(obj_id)
    style = _show_style(obj, style)
    if style in ("write", "draw") and _is_raster(ctx, obj):
        # Only outlines can be written or drawn; a picture fades in
        style = "fade"
    if style == "write":
        return Anim.call("Write", var)
    if style == "draw":
        return Anim.call("ShowCreation", var)
    if style == "fade":
        return Anim.call("FadeIn", var)
    if style == "fade_up":
        return Anim.call("FadeIn", var, "shift=0.5 * UP")
    if style == "grow":
        return Anim.call("Grow", var)
    if style == "pop":
        return Anim.call("GrowFromCenter", var, "rate_func=overshoot")
    raise ValueError(f"No such way to show something: {style}")


def _hide(step: HideStep, ctx: CodegenContext) -> StepCode:
    anims = []
    for obj_id in targets_of(step):
        obj = ctx.spec(obj_id)
        var = ctx.var(obj_id)
        style = blocks.default_hide_style(obj) if step.style == "auto" else step.style
        if style == "uncreate" and _is_raster(ctx, obj):
            style = "fade"
        anims.append({
            "fade": Anim.call("FadeOut", var),
            "fade_down": Anim.call("FadeOut", var, "shift=0.5 * DOWN"),
            "uncreate": Anim.call("Uncreate", var),
            "shrink": Anim.call("ShrinkToCenter", var, "remover=True"),
        }[style])
    return StepCode(anims=anims, lag=step.lag)


def _add(step: AddStep, ctx: CodegenContext) -> StepCode:
    return StepCode(before=[f"self.add({_vars(ctx, targets_of(step))})"])


def _remove(step: RemoveStep, ctx: CodegenContext) -> StepCode:
    return StepCode(before=[f"self.remove({_vars(ctx, targets_of(step))})"])


def _clear(step: ClearStep, ctx: CodegenContext) -> StepCode:
    return StepCode(anims=[Anim.call("FadeOut", "self.everything_on_screen()")])


def _transform(step: TransformStep, ctx: CodegenContext) -> StepCode:
    source, into = ctx.spec(step.target), ctx.spec(step.into)
    a, b = ctx.var(step.target), ctx.var(step.into)
    style = step.style
    if style == "auto":
        style = "match" if source.type in TEXT_KINDS and into.type in TEXT_KINDS else "morph"
    if style == "morph":
        name = "TransformFromCopy" if step.keep else "ReplacementTransform"
        return StepCode(anims=[Anim.call(name, a, b)])
    start = f"{a}.copy()" if step.keep else a
    if style == "match":
        if source.type in TEXT_KINDS and into.type in TEXT_KINDS:
            name = "TransformMatchingTex" if source.type == into.type == "tex" else "TransformMatchingStrings"
        else:
            name = "TransformMatchingShapes"
        return StepCode(anims=[Anim.call(name, start, b)])
    if style == "fade":
        return StepCode(anims=[Anim.call("FadeTransform", start, b)])
    raise ValueError(f"No such way to transform: {style}")


def _change(step: ChangeStep, ctx: CodegenContext) -> StepCode:
    """
    The object is built again from its values with the change made, into a variable of its
    own, and the one on screen is transformed into that. The new values are what later steps
    build from, see CodegenContext.objects.
    """
    obj = ctx.spec(step.target)
    var = ctx.var(step.target)
    new = changed_spec(obj, step.set)
    build_ctx = ctx
    if isinstance(new, GroupObject):
        # A group is built from its members, and building one moves them (arranging them,
        # for one), so the new look is built from copies, which the members then become
        copies = {member: f"{ctx.var(member)}.copy()" for member in new.members}
        build_ctx = dataclasses.replace(ctx, names={**ctx.names, **copies})
    temp = ctx.temp(f"{var}_new")
    before = [f"{temp} = {blocks.object_expression(new, build_ctx)}"]
    if step.target in ctx.displaced and not (set(step.set) & POSITION_FIELDS):
        # Moved since it was placed, so the new look goes where the object now is
        before.append(f"{temp}.move_to({var})")
    ctx.objects[step.target] = new
    return StepCode(before=before, anims=[Anim.call("Transform", var, temp)])


def changed_spec(obj: ObjectBase, changes: dict) -> ObjectBase:
    """An object's values with a change made, as validate.check_change merges them."""
    merged = {**obj.model_dump(exclude_defaults=True), **changes, "id": obj.id, "type": obj.type}
    return type(obj).model_validate(merged)


def _move(step: MoveStep, ctx: CodegenContext) -> StepCode:
    ids = targets_of(step)
    names = [ctx.var(obj_id) for obj_id in ids]
    if step.by is not None:
        offset = point3(step.by)
        anims = [Anim.builder(name, f".shift({offset})") for name in names]
        for obj_id in ids:
            _note_moved(ctx, obj_id, by=step.by)
        return StepCode(anims=anims)
    placement = placement_args(step.to, ctx)
    if len(names) == 1:
        subject, before = names[0], []
    else:
        subject = ctx.temp("moving")
        before = [f"{subject} = Group({', '.join(names)})"]
    anims = [Anim.builder(subject, f".move_to(place({subject}.copy(){placement}))")]
    for obj_id in ids:
        if len(ids) == 1:
            _note_moved(ctx, obj_id, to=step.to)
        else:
            _note_displaced(ctx, obj_id)
    return StepCode(before=before, anims=anims)


def _note_moved(ctx: CodegenContext, obj_id: str, to: Placement | None = None, by: list[float] | None = None) -> None:
    """
    Keeps what later steps build this object from in step with where it now is. A placed
    object keeps its new placement as its own; anything else is noted as moved, so that a
    later change puts its new look where it is rather than where it began.
    """
    obj = ctx.spec(obj_id)
    if isinstance(obj, FreeObject) and not isinstance(obj, GroupObject):
        if to is not None:
            ctx.objects[obj_id] = obj.model_copy(update={"place": to})
            ctx.displaced.discard(obj_id)
            return
        if obj.place is not None:
            shift = obj.place.shift or [0.0, 0.0]
            place = obj.place.model_copy(update={"shift": [shift[0] + by[0], shift[1] + by[1]]})
            ctx.objects[obj_id] = obj.model_copy(update={"place": place})
            return
    _note_displaced(ctx, obj_id)


def _note_displaced(ctx: CodegenContext, obj_id: str) -> None:
    ctx.displaced.add(obj_id)
    obj = ctx.objects.get(obj_id)
    if isinstance(obj, GroupObject):
        for member in obj.members:
            _note_displaced(ctx, member)


def _highlight(step: HighlightStep, ctx: CodegenContext) -> StepCode:
    obj = ctx.spec(step.target)
    subject = ctx.var(step.target)
    if step.part is not None:
        subject = blocks.part_selector(obj, step.part, ctx)
    color = color_code(step.color) if step.color else None
    style = step.style
    if style == "indicate":
        anim = Anim.call("Indicate", subject, *([f"color={color}"] if color else []))
    elif style == "flash":
        anim = Anim.call("FlashOn", subject, *([f"color={color}"] if color else []))
    elif style == "box":
        anim = Anim.call("ShowCreationThenFadeAround", subject, *([f"stroke_color={color}"] if color else []))
    elif style == "underline":
        line = f"Underline({subject}, stroke_color={color or HIGHLIGHT_COLOR})"
        anim = Anim.call("ShowCreationThenFadeOut", line)
    elif style == "wiggle":
        anim = Anim.call("WiggleOutThenIn", subject)
    elif style == "recolor":
        new_color = step.color or HIGHLIGHT_COLOR
        anim = Anim.builder(subject, f".set_color({color_code(new_color)})")
        _note_recolored(ctx, obj, step.part, new_color)
    else:
        raise ValueError(f"No such way to highlight: {style}")
    return StepCode(anims=[anim])


def _note_recolored(ctx: CodegenContext, obj: ObjectBase, part: str | None, color: str) -> None:
    """A recolor lasts, so it becomes part of what a later change builds the object from."""
    if part is None:
        update = {"color": color}
        if "colors" in type(obj).model_fields:
            update["colors"] = {}
        ctx.objects[obj.id] = obj.model_copy(update=update)
    elif "colors" in type(obj).model_fields:
        ctx.objects[obj.id] = obj.model_copy(update={"colors": {**obj.colors, part: color}})


def _wait(step: WaitStep, ctx: CodegenContext) -> StepCode:
    return StepCode()


def _camera(step: CameraStep, ctx: CodegenContext) -> StepCode:
    chain = ""
    if step.reset:
        chain += ".to_default_state()"
    if step.orientation is not None:
        chain += f".reorient({', '.join(num(angle) for angle in step.orientation)})"
    if step.zoom is not None:
        chain += ".set_height(FRAME_HEIGHT)" if step.zoom == 1 else f".set_height(FRAME_HEIGHT / {num(step.zoom)})"
    if step.center is not None:
        chain += f".move_to({point3(step.center)})"
    if step.focus is not None:
        chain += f".move_to({ctx.var(step.focus)})"
    return StepCode(anims=[Anim.builder("self.frame", chain)])


def _apply_matrix(step: ApplyMatrixStep, ctx: CodegenContext) -> StepCode:
    matrix = "[" + ", ".join("[" + ", ".join(num(x) for x in row) + "]" for row in step.matrix) + "]"
    anims = []
    for obj_id in targets_of(step):
        obj = ctx.spec(obj_id)
        on = getattr(obj, "on", None)
        coords = [ctx.var(on)] if on is not None and ctx.spec(on).type in COORDINATE_KINDS else []
        anims.append(Anim.call("ApplyMatrixOn", matrix, ctx.var(obj_id), *coords))
        _note_displaced(ctx, obj_id)
    return StepCode(anims=anims)


def _together(step: TogetherStep, ctx: CodegenContext) -> StepCode:
    """
    One play for all the steps inside. Each step's animations are kept to that step's own
    length within it; where every piece lasts equally long they are simply played side by
    side, which is how a person would have written it.
    """
    parts = [step_code(inner, ctx) for inner in step.steps]
    for inner, part in zip(step.steps, parts):
        part.duration = _inner_duration(inner, ctx)
    before = [line for part in parts for line in part.before]
    after = [line for part in parts for line in part.after]
    before_from = [(i, *path) for i, part in enumerate(parts) for path in (part.before_from or [()] * len(part.before))]
    after_from = [(i, *path) for i, part in enumerate(parts) for path in (part.after_from or [()] * len(part.after))]
    moving = [part for part in parts if part.anims and part.duration > 0]
    duration = step.run_time if step.run_time is not None else _together_time([p.duration for p in parts], step.lag)
    code = StepCode(before=before, after=after, duration=duration, before_from=before_from, after_from=after_from)
    if not moving:
        return code
    if len(moving) == 1 and step.run_time is None:
        code.anims, code.lag, code.duration = moving[0].anims, moving[0].lag, moving[0].duration
        return code
    pieces: list[tuple[Anim, float]] = []
    for part in moving:
        if step.lag > 0 or (part.lag > 0 and len(part.anims) > 1):
            pieces.append((part.as_anim(), part.duration))
        else:
            # Starting together inside something starting together, so they start together
            pieces.extend((anim, part.duration) for anim in part.anims)
    if step.lag == 0 and len({length for _, length in pieces}) == 1:
        code.anims = [anim for anim, _ in pieces]
        return code
    inner = ", ".join(anim.text(run_time=num(length)) for anim, length in pieces)
    if step.lag > 0:
        code.anims = [Anim.call("LaggedStart", inner, f"lag_ratio={num(step.lag)}")]
    else:
        code.anims = [Anim.call("AnimationGroup", inner)]
    return code


# Small things

def targets_of(step: StepBase) -> list[str]:
    target = step.target
    return [target] if isinstance(target, str) else list(target)


def _vars(ctx: CodegenContext, ids: list[str]) -> str:
    return ", ".join(ctx.var(obj_id) for obj_id in ids)


def _is_raster(ctx: CodegenContext, obj: ObjectBase) -> bool:
    """Whether the object is, or holds, a picture rather than outlines."""
    if isinstance(obj, ImageObject):
        return True
    if isinstance(obj, GroupObject):
        return any(_is_raster(ctx, ctx.spec(member)) for member in obj.members if member in ctx.objects)
    return False


def num(value: float | int) -> str:
    """A number as it reads best in code: whole numbers without a decimal point."""
    value = float(value)
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def point3(point: list[float]) -> str:
    """A point of a scene file, [x, y] or [x, y, z], as a 3D point in code."""
    coords = list(point) + [0.0] * (3 - len(point))
    return "[" + ", ".join(num(c) for c in coords) + "]"


_HEX = re.compile(r"^#[0-9a-fA-F]+$")


def color_code(color: str) -> str:
    """A color of a scene file in code: manim's name for it, or the hex string."""
    return f'"{color}"' if _HEX.match(color) else color.upper()


def placement_args(place: Placement, ctx: CodegenContext) -> str:
    """The keyword arguments to layout.place saying the same as a Placement, each after a comma."""
    args = []
    if place.at is not None:
        args.append(f"at={point_list(place.at)}")
        if place.on is not None:
            args.append(f"on={ctx.var(place.on)}")
    if place.edge is not None:
        args.append(f'edge="{place.edge}"')
    if place.next_to is not None:
        args.append(f"next_to={ctx.var(place.next_to)}")
        if place.side != "down":
            args.append(f'side="{place.side}"')
    if place.buff != 0.25:
        args.append(f"buff={num(place.buff)}")
    if place.shift is not None:
        args.append(f"shift={point_list(place.shift)}")
    return "".join(", " + arg for arg in args)


def point_list(point: list[float]) -> str:
    return "[" + ", ".join(num(c) for c in point) + "]"
