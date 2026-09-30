"""
Steps to code: for each kind of step, the lines of Python which play it, inside the scene's
construct method.

OWNER: steps/render agent.

    step_lines(step, ctx) -> list[str]
        The body of the step's `with self.step(...)` block. May update ctx.objects (a change
        step records the object's new values there), and records in ctx.history what the
        step did to objects which their values don't say (see carry.py).
    default_run_time(step, ctx) -> float
        How long a step takes when it doesn't say. timeline() in render.py uses the same
        numbers, so durations can be known without rendering anything.

Every kind of step comes down to the same three parts (see StepCode): lines which happen at
once before anything moves, the animations which play, and lines which happen at once
afterwards. A step on its own plays its animations in one `self.play(...)`; a `together` step
gathers the animations of each step inside it into one play of its own, which is why the
parts are kept apart until the last moment. That play is written one step's animation to a
line, so that a failure in one of them is laid at that step's door rather than the together's.

Adds and removes inside a together happen when their turn comes. With no lag they all come
at the start, before anything moves. With a lag, each step inside starts `lag` times the
length of the one before it after that one did, and an add or remove which comes after
something taking time happens at the moment its turn comes, as an Add or Remove among the
animations; given a run_time, it holds its place for that long before the next one starts,
as any other step inside would. Without one it takes no time, and the next starts with it.

Every play is given its run_time explicitly, whatever manim's own default for the animation
would have been, so that how long a step takes is decided here and nowhere else.
"""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from typing import NamedTuple

from manim_verbose.scenefile import blocks, carry
from manim_verbose.scenefile.carry import Look
from manim_verbose.scenefile.codegen import CodegenContext, build_expression
from manim_verbose.scenefile.model import (
    AddStep, ApplyMatrixStep, CameraStep, ChangeStep, ClearStep, GroupObject,
    HideStep, HighlightStep, ImageObject, MatrixObject, MoveStep, ObjectBase, Placement, RemoveStep,
    ShowStep, StepBase, TogetherStep, TransformStep, WaitStep,
)
from manim_verbose.scenefile.validate import PART_FIELDS, parse_matrix_part

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
POSITION_FIELDS = {"place", "point", "tip", "tail", "start", "end", "points", "on", "target", "members", "arrange",
                   "center"}
# How much `keep: dim` fades the original of a transform: to 0.35 of its opacity, runtime.DIM_OPACITY
DIM_FADE = 0.65


# Animations as source text

@dataclass
class Anim:
    """
    An animation written as Python, kept in two halves so that keyword arguments such as
    run_time can still be added: a call, `Write(eq)`, takes them before its closing
    parenthesis, and a builder, `eq.animate.shift(UP)`, right after `.animate`.

    A group a together makes (LaggedStart or AnimationGroup) keeps the animations it lays out
    as pieces, each with how long it lasts, so that they can be written one to a line.
    """
    head: str
    args: list[str] = field(default_factory=list)
    chain: str | None = None
    # The step inside a together this came from, as the path of indices down to it
    origin: tuple[int, ...] = ()
    pieces: list[tuple[Anim, float]] = field(default_factory=list)

    @classmethod
    def call(cls, name: str, *args: str) -> Anim:
        return cls(name, list(args))

    @classmethod
    def builder(cls, mobject: str, chain: str) -> Anim:
        return cls(f"{mobject}.animate", chain=chain)

    @classmethod
    def group(cls, name: str, pieces: list[tuple[Anim, float]], *args: str) -> Anim:
        return cls(name, list(args), pieces=list(pieces))

    def text(self, **kwargs: str) -> str:
        extra = [f"{key}={value}" for key, value in kwargs.items()]
        if self.chain is not None:
            return self.head + (f"({', '.join(extra)})" if extra else "") + self.chain
        pieces = [piece.timed(length) for piece, length in self.pieces]
        return f"{self.head}({', '.join(pieces + self.args + extra)})"

    def timed(self, length: float) -> str:
        """The animation lasting `length`, as a piece of a group: an add or remove taking no time says none."""
        if length <= 0 and self.head in ("Add", "Remove"):
            return self.text()
        return self.text(run_time=num(length))


class CodeLine(NamedTuple):
    """A line of a step's code, and where it came from."""
    text: str
    # The step inside a together it came from, as the path of indices down to it; () for the step itself
    origin: tuple[int, ...] = ()
    # For the lines of a play written over several: where the animation on the line is among
    # those of the play (the index of one given to it, then of one inside that), which is how
    # a failure while playing is traced back to it, see render.problems_from_exception
    piece: tuple[int, ...] | None = None
    # Whether the line is the first of such a play, the one a failure while playing is reported on
    opens_play: bool = False


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
        """The one play of the step on one line, or a wait where it has nothing to animate but takes time."""
        lines = self.play_lines()
        return "\n".join(line.text for line in lines) if lines else None

    def play_lines(self) -> list[CodeLine]:
        """
        The play of the step, or a wait where it has nothing to animate but takes time. On
        one line where its animations all come from one step; otherwise one to a line.
        """
        if not self.anims:
            return [CodeLine(f"self.wait({num(self.duration)})")] if self.duration > 0 else []
        origins = {anim.origin for anim in self.anims} | {
            piece.origin for anim in self.anims for piece, _ in anim.pieces
        }
        if len(origins) == 1:
            if len(self.anims) > 1 and self.lag > 0:
                inner = self.lagged()
            else:
                inner = ", ".join(anim.text() for anim in self.anims)
            return [CodeLine(f"self.play({inner}, run_time={num(self.duration)})", next(iter(origins)))]
        if len(self.anims) == 1:
            # One group laid out by a together: its pieces one to a line inside it
            group = self.anims[0]
            lines = [CodeLine(f"self.play({group.head}(", (), (0,), opens_play=True)]
            for inner, (piece, length) in enumerate(group.pieces):
                lines.append(CodeLine(f"    {piece.timed(length)},", piece.origin, (0, inner)))
            lines.extend(CodeLine(f"    {arg},") for arg in group.args)
            lines.append(CodeLine(f"), run_time={num(self.duration)})"))
            return lines
        lines = [CodeLine("self.play(", opens_play=True)]
        for index, anim in enumerate(self.anims):
            if len({piece.origin for piece, _ in anim.pieces}) > 1:
                lines.append(CodeLine(f"    {anim.head}(", (), (index,)))
                for inner, (piece, length) in enumerate(anim.pieces):
                    lines.append(CodeLine(f"        {piece.timed(length)},", piece.origin, (index, inner)))
                lines.extend(CodeLine(f"        {arg},") for arg in anim.args)
                lines.append(CodeLine("    ),"))
            else:
                lines.append(CodeLine(f"    {anim.text()},", anim.origin, (index,)))
        lines.append(CodeLine(f"    run_time={num(self.duration)},"))
        lines.append(CodeLine(")"))
        return lines

    def lagged(self) -> str:
        # Each piece is given the same length, which the play then stretches to the step's,
        # so that the stagger comes out as asked whatever manim's defaults for them are
        pieces = ", ".join(anim.text(run_time="1") for anim in self.anims)
        return f"LaggedStart({pieces}, lag_ratio={num(self.lag)})"

    def as_anim(self) -> Anim:
        """All of this step's animations as one, which takes a run_time, for a together."""
        if len(self.anims) == 1:
            return self.anims[0]
        pieces = [(anim, 1.0) for anim in self.anims]
        if self.lag > 0:
            group = Anim.group("LaggedStart", pieces, f"lag_ratio={num(self.lag)}")
        else:
            group = Anim.group("AnimationGroup", pieces)
        group.origin = self.anims[0].origin
        return group

    def lines(self) -> list[str]:
        return [line.text for line in self.lines_from()]

    def lines_from(self) -> list[CodeLine]:
        """The lines, each with where it came from, see CodeLine."""
        before = [CodeLine(text, path) for text, path in zip(self.before, self.before_from or [()] * len(self.before))]
        after = [CodeLine(text, path) for text, path in zip(self.after, self.after_from or [()] * len(self.after))]
        return [*before, *self.play_lines(), *after]


# The interface

def step_lines(step: StepBase, ctx: CodegenContext) -> list[str]:
    return step_code(step, ctx).lines()


def step_lines_from(step: StepBase, ctx: CodegenContext) -> list[CodeLine]:
    """step_lines, each line with where it came from, for codegen's line map."""
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
    """How long a step inside a together takes: an add or remove its run_time if it gives one, else none."""
    if isinstance(step, (AddStep, RemoveStep)):
        return step.run_time or 0.0
    return step_duration(step, ctx)


def _staggered(each: float, count: int, lag: float) -> float:
    """How long `count` animations of `each` seconds take, each starting `lag` of the way through the one before."""
    return round(each * (1 + (count - 1) * lag), 3)


def _together_time(durations: list[float], lag: float) -> float:
    """
    How long steps played together take, laid out as AnimationGroup lays them out. Steps
    which take no time take no part in the layout: the next one starts with them.
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
    carry.note_shown(ctx, targets_of(step))
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
    carry.note_hidden(ctx, targets_of(step))
    return StepCode(anims=anims, lag=step.lag)


def _add(step: AddStep, ctx: CodegenContext) -> StepCode:
    carry.note_shown(ctx, targets_of(step))
    return StepCode(before=[f"self.add({_vars(ctx, targets_of(step))})"])


def _remove(step: RemoveStep, ctx: CodegenContext) -> StepCode:
    carry.note_hidden(ctx, targets_of(step))
    return StepCode(before=[f"self.remove({_vars(ctx, targets_of(step))})"])


def _clear(step: ClearStep, ctx: CodegenContext) -> StepCode:
    carry.note_cleared(ctx)
    return StepCode(anims=[Anim.call("FadeOut", "self.everything_on_screen()")])


def _transform(step: TransformStep, ctx: CodegenContext) -> StepCode:
    source, into = ctx.spec(step.target), ctx.spec(step.into)
    a, b = ctx.var(step.target), ctx.var(step.into)
    style = step.style
    if style == "auto":
        style = "match" if source.type in TEXT_KINDS and into.type in TEXT_KINDS else "morph"
    if style == "morph":
        name = "TransformFromCopy" if step.keep else "ReplacementTransform"
        anims = [Anim.call(name, a, b)]
    else:
        start = f"{a}.copy()" if step.keep else a
        if style == "match":
            if source.type in TEXT_KINDS and into.type in TEXT_KINDS:
                name = "TransformMatchingTex" if source.type == into.type == "tex" else "TransformMatchingStrings"
            else:
                name = "TransformMatchingShapes"
            anims = [Anim.call(name, start, b)]
        elif style == "fade":
            anims = [Anim.call("FadeTransform", start, b)]
        else:
            raise ValueError(f"No such way to transform: {style}")
    if step.keep == "dim":
        # The original stays, faded, while its copy turns into the other: fade multiplies
        # every opacity it has, so an outline stays an outline
        anims.append(Anim.builder(a, f".fade({num(DIM_FADE)})"))
        carry.note_look(ctx, step.target, Look("dim"))
    if not step.keep:
        carry.note_hidden(ctx, [step.target])
    carry.note_shown(ctx, [step.into])
    return StepCode(anims=anims)


def _change(step: ChangeStep, ctx: CodegenContext) -> StepCode:
    """
    The object is built again from its values with the change made, into a variable of its
    own, and the one on screen is transformed into that, which then takes its place (see
    DocScene.changed). The new values are what later steps build from, see
    CodegenContext.objects.

    A change which says nothing of where the object is leaves it where it is: where it has
    been moved the new look is centred on it, and where a matrix has distorted it (or the
    coordinate system it is drawn on) the new look goes through the same. What steps did to
    how it looks which its values don't hold (a part recolored, a dimming) is done again.
    """
    target = step.target
    obj = ctx.spec(target)
    var = ctx.var(target)
    new = changed_spec(obj, step.set)
    positioned = bool(set(step.set) & POSITION_FIELDS)
    displaced = target in ctx.displaced
    transformed = carry.transformed_since_built(ctx, target)
    history = carry.history_of(ctx)
    build_ctx = ctx
    before = []
    if isinstance(new, GroupObject):
        # A group is built from its members, and building one moves them (arranging them,
        # for one), so the new look is built from copies, which the members then become
        copies = {member: ctx.temp(f"{ctx.var(member)}_copy") for member in dict.fromkeys(new.members)}
        before.append(f"{', '.join(copies.values())} = {', '.join(f'{ctx.var(m)}.copy()' for m in copies)}")
        build_ctx = dataclasses.replace(ctx, names={**ctx.names, **copies})
    temp = ctx.temp(f"{var}_new")
    before.append(f"{temp} = {build_expression(new, build_ctx)}")
    if "opacity" in step.set:
        carry.clear_looks(ctx, target, "dim")
    looks_ctx = dataclasses.replace(ctx, names={**ctx.names, target: temp})
    for look in history.state(target).looks:
        if look.kind == "dim":
            before.append(f"{temp}.fade({num(DIM_FADE)})")
        elif look.kind == "recolor" and look.part and part_exists(new, look.part):
            before.append(f"{blocks.part_selector(new, look.part, looks_ctx)}.set_color({color_code(look.color)})")
    on = getattr(new, "on", None)
    if transformed and not positioned:
        before.append(f"{temp} = self.transformed_as({var}, {temp}" + (f", on={ctx.var(on)})" if on else ")"))
    if displaced and not positioned:
        # Moved since it was placed, so the new look goes where the object now is
        before.append(f"{temp}.move_to({var})")
    after = []
    if not isinstance(new, GroupObject):
        args = ""
        if positioned and (transformed or target in history.following):
            args = (f", on={ctx.var(on)}" if on and transformed else "") + ", placed=True"
        after.append(f"{var} = self.changed({var}, {temp}{args})")
    ctx.objects[target] = new
    if positioned:
        ctx.displaced.discard(target)
    if "place" in step.set:
        place = getattr(new, "place", None)
        carry.note_following(ctx, target, place.next_to if place is not None and place.follow else None)
    if positioned or not (displaced or transformed):
        # Built again against the objects around it as they are now
        carry.note_built(ctx, target)
    return StepCode(before=before, anims=[Anim.call("Transform", var, temp)], after=after)


def changed_spec(obj: ObjectBase, changes: dict) -> ObjectBase:
    """An object's values with a change made, as validate.check_change merges them."""
    merged = {**obj.model_dump(exclude_defaults=True), **changes, "id": obj.id, "type": obj.type}
    return type(obj).model_validate(merged)


def part_exists(obj: ObjectBase, part: str) -> bool:
    """Whether a part a highlight picked out is still there to pick out in these values."""
    if isinstance(obj, MatrixObject):
        parsed = parse_matrix_part(part)
        rows, columns = len(obj.entries), len(obj.entries[0]) if obj.entries else 0
        if parsed is None:
            return any(part == str(entry) for row in obj.entries for entry in row)
        kind, first, second = parsed
        if kind == "row":
            return 1 <= first <= rows
        if kind == "column":
            return 1 <= first <= columns
        return 1 <= first <= rows and 1 <= second <= columns
    field_name = PART_FIELDS.get(type(obj))
    return field_name is not None and part in str(getattr(obj, field_name, ""))


def _move(step: MoveStep, ctx: CodegenContext) -> StepCode:
    ids = targets_of(step)
    names = [ctx.var(obj_id) for obj_id in ids]
    before: list[str] = []
    after: list[str] = []
    # Moved some other way than by following, anything following stops
    stopping = carry.followers_among(ctx, ids)
    if stopping:
        before.append(f"self.stop_following({', '.join(ctx.var(obj_id) for obj_id in stopping)})")
        for obj_id in stopping:
            carry.note_following(ctx, obj_id, None)
    if step.by is not None:
        offset = point3(step.by)
        anims = [Anim.builder(name, f".shift({offset})") for name in names]
        kept = [obj_id for obj_id in ids if not _shift_placement(ctx, obj_id, step.by, obj_id in stopping)]
        _note_unfollowed(ctx, [obj_id for obj_id in stopping if obj_id in kept or obj_id not in ids])
        if kept:
            carry.note_event(ctx, "shift", kept, offset=list(step.by))
            for obj_id in kept:
                _note_displaced(ctx, obj_id)
        return StepCode(before=before, anims=anims)
    to = step.to
    if len(names) == 1:
        subject = names[0]
    else:
        subject = ctx.temp("moving")
        before.append(f"{subject} = Group({', '.join(names)})")
    anims = [Anim.builder(subject, f".move_to({placement_call(f'{subject}.copy()', to, ctx)})")]
    if len(ids) == 1 and _replace_placement(ctx, ids[0], to):
        _note_unfollowed(ctx, [obj_id for obj_id in stopping if obj_id != ids[0]])
    else:
        _note_unfollowed(ctx, stopping)
        carry.note_event(ctx, "move", ids, placement=to, together=len(ids) > 1)
        for obj_id in ids:
            _note_displaced(ctx, obj_id)
        if to.follow:
            carry.note_event(ctx, "follow", ids, placement=to)
    if to.follow:
        for obj_id in ids:
            after.append(f"self.follow({ctx.var(obj_id)}, {ctx.var(to.next_to)}{_follow_args(to)})")
            carry.note_following(ctx, obj_id, to.next_to)
    return StepCode(before=before, anims=anims, after=after)


def _replace_placement(ctx: CodegenContext, obj_id: str, to: Placement) -> bool:
    """
    A free standing object moved on its own to a placement takes that placement as its own,
    and is put in place anew there, unless a matrix has distorted it (whose shape a
    placement can't say): then the move is kept as it was, see carry.py.
    """
    obj = ctx.spec(obj_id)
    if not carry.free_standing(obj) or carry.transformed_since_built(ctx, obj_id):
        return False
    ctx.objects[obj_id] = obj.model_copy(update={"place": to})
    ctx.displaced.discard(obj_id)
    carry.note_built(ctx, obj_id)
    return True


def _shift_placement(ctx: CodegenContext, obj_id: str, by: list[float], was_following: bool) -> bool:
    """
    A free standing object with a placement of its own, which nothing has moved since it
    was put in place, takes a move by an offset into that placement's shift. One which was
    following stops, and is put in place anew where it has followed to.
    """
    obj = ctx.spec(obj_id)
    if not carry.free_standing(obj) or obj.place is None or carry.moved_since_built(ctx, obj_id):
        return False
    shift = obj.place.shift or [0.0, 0.0]
    place = obj.place.model_copy(update={"shift": [shift[0] + by[0], shift[1] + by[1]], "follow": False})
    ctx.objects[obj_id] = obj.model_copy(update={"place": place})
    if was_following:
        carry.note_built(ctx, obj_id)
    return True


def _note_unfollowed(ctx: CodegenContext, ids: list[str]) -> None:
    """Following which ended some way the objects' values can't say, as an event, see carry.py."""
    kept = []
    for obj_id in ids:
        obj = ctx.objects.get(obj_id)
        place = getattr(obj, "place", None)
        if place is not None and place.follow and carry.free_standing(obj):
            # Its placement says it follows: that stops, and it is put in place where it is
            ctx.objects[obj_id] = obj.model_copy(update={"place": place.model_copy(update={"follow": False})})
            if not carry.moved_since_built(ctx, obj_id):
                carry.note_built(ctx, obj_id)
                continue
        kept.append(obj_id)
    if kept:
        carry.note_event(ctx, "unfollow", kept)


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
    """
    A recolor lasts, so it becomes part of what a later change builds the object from: its
    color, or the color of a part where the object keeps colors of parts. Anywhere else (a
    part of a matrix, of a title) it is noted as a look of the object, done again on it
    whenever it is built again, see carry.py.
    """
    if part is None:
        update = {"color": color}
        if "colors" in type(obj).model_fields:
            update["colors"] = {}
        ctx.objects[obj.id] = obj.model_copy(update=update)
        carry.clear_looks(ctx, obj.id, "recolor")
    elif "colors" in type(obj).model_fields:
        ctx.objects[obj.id] = obj.model_copy(update={"colors": {**obj.colors, part: color}})
    else:
        carry.note_look(ctx, obj.id, Look("recolor", part, color))


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
    ids = targets_of(step)
    before = []
    stopping = carry.followers_among(ctx, ids)
    if stopping:
        before.append(f"self.stop_following({', '.join(ctx.var(obj_id) for obj_id in stopping)})")
        for obj_id in stopping:
            carry.note_following(ctx, obj_id, None)
        _note_unfollowed(ctx, stopping)
    anims = []
    coords_of: dict[str, str | None] = {}
    for obj_id in ids:
        obj = ctx.spec(obj_id)
        on = getattr(obj, "on", None)
        coords = on if on is not None and ctx.spec(on).type in COORDINATE_KINDS else None
        coords_of[obj_id] = coords
        anims.append(Anim.call("ApplyMatrixOn", matrix, ctx.var(obj_id), *([ctx.var(coords)] if coords else [])))
    carry.note_event(ctx, "matrix", ids, matrix=[list(row) for row in step.matrix], coords=coords_of)
    for obj_id in ids:
        _note_displaced(ctx, obj_id)
    return StepCode(before=before, anims=anims)


def _together(step: TogetherStep, ctx: CodegenContext) -> StepCode:
    """
    One play for all the steps inside. Each step's animations are kept to that step's own
    length within it; where every piece lasts equally long and nothing is staggered they are
    simply played side by side, which is how a person would have written it. Adds and
    removes happen when their turn comes, see the module's docstring.
    """
    parts = [step_code(inner, ctx) for inner in step.steps]
    for inner, part in zip(step.steps, parts):
        part.duration = _inner_duration(inner, ctx)
    duration = step.run_time if step.run_time is not None else _together_time([p.duration for p in parts], step.lag)
    code = StepCode(duration=duration)
    pieces: list[tuple[Anim, float]] = []
    moving: list[StepCode] = []
    timed = 0  # adds and removes waiting their turn among the animations
    started = False  # whether something taking time has started, after which an add waits its turn
    for index, (inner, part) in enumerate(zip(step.steps, parts)):
        if isinstance(inner, (AddStep, RemoveStep)) and (part.duration > 0 or (step.lag > 0 and started)):
            name = "Add" if isinstance(inner, AddStep) else "Remove"
            piece = Anim.call(name, _vars(ctx, targets_of(inner)))
            piece.origin = (index,)
            pieces.append((piece, part.duration))
            timed += 1
            started = started or part.duration > 0
            continue
        code.before.extend(part.before)
        code.before_from.extend((index, *path) for path in (part.before_from or [()] * len(part.before)))
        code.after.extend(part.after)
        code.after_from.extend((index, *path) for path in (part.after_from or [()] * len(part.after)))
        if not part.anims or part.duration <= 0:
            continue
        for anim in part.anims:
            anim.origin = (index, *anim.origin)
            for piece, _ in anim.pieces:
                piece.origin = (index, *piece.origin)
        moving.append(part)
        started = True
        if step.lag > 0 or (part.lag > 0 and len(part.anims) > 1):
            pieces.append((part.as_anim(), part.duration))
        else:
            # Starting together inside something starting together, so they start together
            pieces.extend((anim, part.duration) for anim in part.anims)
    if not pieces:
        return code
    if len(moving) == 1 and not timed and step.run_time is None:
        # Only one step inside moves anything: it plays as it would on its own
        code.anims, code.lag, code.duration = moving[0].anims, moving[0].lag, moving[0].duration
        return code
    if step.lag == 0 and len({length for _, length in pieces}) == 1:
        code.anims = [anim for anim, _ in pieces]
        return code
    if step.lag > 0:
        code.anims = [Anim.group("LaggedStart", pieces, f"lag_ratio={num(step.lag)}")]
    else:
        code.anims = [Anim.group("AnimationGroup", pieces)]
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
            system = ctx.spec(place.on)
            # A number line with a backdrop is built as VGroup(panel, line), see blocks.py
            inside = "[1]" if system.type == "number_line" and getattr(system, "backdrop", False) else ""
            args.append(f"on={ctx.var(place.on)}{inside}")
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


def placement_call(subject: str, place: Placement, ctx: CodegenContext) -> str:
    """
    Code putting `subject` where a Placement says: layout.place, or where it is beside a
    point of another object (the tip of a vector, say), runtime.beside.
    """
    if place.next_to is not None and place.anchor != "center":
        args = f', anchor="{place.anchor}"'
        if place.side != "down":
            args += f', side="{place.side}"'
        if place.buff != 0.25:
            args += f", buff={num(place.buff)}"
        if place.shift is not None:
            args += f", shift={point_list(place.shift)}"
        return f"beside({subject}, {ctx.var(place.next_to)}{args})"
    return f"place({subject}{placement_args(place, ctx)})"


def _follow_args(place: Placement) -> str:
    args = ""
    if place.anchor != "center":
        args += f', anchor="{place.anchor}"'
    if place.side != "down":
        args += f', side="{place.side}"'
    return args


def point_list(point: list[float]) -> str:
    return "[" + ", ".join(num(c) for c in point) + "]"
