"""
Objects carried from one scene into the next (a scene's `carry: [ids]`), and the record kept,
as a scene's steps are turned into code, of what they do to its objects: which the carrying
takes, and which also lets a change keep what earlier steps did to the object it changes.

OWNER: steps/render agent.

A carried object starts the next scene on screen exactly as the scene before left it. It is
rebuilt there the way a person would rebuild it: from its values as they ended up (every
change made, recolors kept where the object has a place for them), at the point in the story
where it was last put in place against the objects around it, and then put through whatever
the steps did to it after that which its values can't say. In the new scene's code:

    with self.carried_from("adding"):
        plane = self.obj("plane", NumberPlane(...))
        v = self.obj("v", Arrow(plane.c2p(0, 0), plane.c2p(1, 2), buff=0).set_color(YELLOW))
        self.apply_now(ApplyMatrixOn([[1, 1], [0, 1]], plane), ApplyMatrixOn([[1, 1], [0, 1]], v, plane))
        label = self.obj("label", self.keep_beside(Tex("v"), v, anchor="tip", side="right"))
        self.add(plane, v, label)

What carries:
- every value of the object as the scene before left it: changes, and moves of an object
  standing on its own, which become its placement;
- where it is: moves by an offset or to a place, of anything, alone or in a group; matrices
  applied to it or to the group it is in; following, begun or ended, by placement or by a
  move; and so where a follower ended up;
- how it looks beyond its values: parts recolored which it has no field for (a matrix's
  rows, a title's words), and the dimming of `keep: dim`;
- the order objects are drawn in, among those carried, as the scene before left them on
  screen (from the order they were shown in; `z` still comes first).

What doesn't, by design: objects not carried, the caption, the camera (each scene starts
with the camera where it normally is), and whether a carried object was on screen (carried
objects start on screen; validation warns when one wasn't).

Where the rebuilding can't be exactly what happened, validation warns (see carry_problems):
- an object placed beside another before that other was changed or moved (and not following
  it) is carried beside the other as the other ended up;
- objects moved together as one, not all of them carried, are carried as if the carried ones
  had been moved as one on their own;
- a move to a place beside, or on, an object which isn't carried can't be carried at all.
And one difference is small enough to be left unsaid: a change of how an object looks after
it was moved puts the new look where the old one was centred, while carried it is placed
and then moved, which for a look of another size along the side it is placed against can
differ by up to half the change in size.

Events are kept in one list across the scenes of a document, since what a carried object
went through may have begun scenes before (a scene can carry what the scene before carried).
An object's `built_at` is how many events there had been when it was last put in place; the
events after that which name it are what it went through since.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from manim_verbose.scenefile.model import (
    Document, FreeObject, GroupObject, ObjectBase, Placement, SceneSpec, TitleObject,
)
from manim_verbose.scenefile.validate import Problem, object_refs

if TYPE_CHECKING:
    from manim_verbose.scenefile.codegen import CodegenContext

GEOMETRIC = ("matrix", "shift", "move")


@dataclass
class Event:
    """Something a step did to objects which their values don't record, in the order it happened."""
    kind: str  # "matrix", "shift", "move", "follow" or "unfollow"
    scene_id: str
    step_id: str | None
    # The objects the step named, and every object it acted on (members of groups too)
    named: list[str]
    ids: list[str]
    matrix: list[list[float]] | None = None
    # For a matrix, the coordinate system (or None, the frame) each object was read in
    coords: dict[str, str | None] = field(default_factory=dict)
    offset: list[float] | None = None
    placement: Placement | None = None
    # For a move to a place: the objects named were moved there as one
    together: bool = False


@dataclass
class Look:
    """How an object looks beyond its values: a part recolored, or a dimming."""
    kind: str  # "recolor" or "dim"
    part: str | None = None
    color: str | None = None


@dataclass
class ObjectState:
    built_at: int
    looks: list[Look] = field(default_factory=list)


@dataclass
class History:
    events: list[Event] = field(default_factory=list)
    states: dict[str, ObjectState] = field(default_factory=dict)
    # What is on screen, in the order it is drawn
    on_screen: list[str] = field(default_factory=list)
    # Which object follows which, by id
    following: dict[str, str] = field(default_factory=dict)
    scene_id: str = ""
    step_id: str | None = None

    def now(self) -> int:
        return len(self.events)

    def state(self, obj_id: str) -> ObjectState:
        if obj_id not in self.states:
            self.states[obj_id] = ObjectState(built_at=0)
        return self.states[obj_id]

    def since_built(self, obj_id: str, kinds: tuple[str, ...] = GEOMETRIC) -> list[Event]:
        """The events of these kinds which acted on the object since it was last put in place."""
        built = self.state(obj_id).built_at
        return [e for e in self.events[built:] if e.kind in kinds and obj_id in e.ids]

    def copy(self) -> History:
        return History(
            events=list(self.events),
            states={k: ObjectState(v.built_at, list(v.looks)) for k, v in self.states.items()},
            on_screen=list(self.on_screen), following=dict(self.following),
            scene_id=self.scene_id, step_id=self.step_id,
        )


# What actions.py tells the history as it turns steps into code

def history_of(ctx: CodegenContext) -> History:
    if ctx.history is None:
        ctx.history = History(scene_id=ctx.scene.id)
    return ctx.history


def leaves_of(ctx: CodegenContext, obj_id: str) -> list[str]:
    """The object, and everything in it if it is a group, groups within it included."""
    out = [obj_id]
    obj = ctx.objects.get(obj_id)
    if isinstance(obj, GroupObject):
        for member in obj.members:
            for inner in leaves_of(ctx, member):
                if inner not in out:
                    out.append(inner)
    return out


def note_event(ctx: CodegenContext, kind: str, named: list[str], **values) -> Event:
    history = history_of(ctx)
    ids: list[str] = []
    for obj_id in named:
        for inner in leaves_of(ctx, obj_id):
            if inner not in ids:
                ids.append(inner)
    event = Event(kind, history.scene_id, history.step_id, list(named), ids, **values)
    history.events.append(event)
    return event


def note_built(ctx: CodegenContext, obj_id: str) -> None:
    """The object was just put in place anew, against the objects around it as they are now."""
    history_of(ctx).state(obj_id).built_at = history_of(ctx).now()


def moved_since_built(ctx: CodegenContext, obj_id: str) -> bool:
    return bool(history_of(ctx).since_built(obj_id))


def transformed_since_built(ctx: CodegenContext, obj_id: str) -> bool:
    """
    Whether a matrix has gone over the object, or over the coordinate system it is drawn on,
    since it was last put in place: then a new look for it has to be put through the same
    (see DocScene.transformed_as) to land where it is.
    """
    history = history_of(ctx)
    built = history.state(obj_id).built_at
    on = getattr(ctx.objects.get(obj_id), "on", None)
    watched = {obj_id} | ({on} if on else set())
    return any(e.kind == "matrix" and watched & set(e.ids) for e in history.events[built:])


def note_look(ctx: CodegenContext, obj_id: str, look: Look) -> None:
    history_of(ctx).state(obj_id).looks.append(look)


def clear_looks(ctx: CodegenContext, obj_id: str, kind: str) -> None:
    state = history_of(ctx).state(obj_id)
    state.looks = [look for look in state.looks if look.kind != kind]


def note_shown(ctx: CodegenContext, ids: list[str]) -> None:
    on_screen = history_of(ctx).on_screen
    for obj_id in ids:
        if obj_id in on_screen:
            on_screen.remove(obj_id)
        on_screen.append(obj_id)


def note_hidden(ctx: CodegenContext, ids: list[str]) -> None:
    history = history_of(ctx)
    gone = {inner for obj_id in ids for inner in leaves_of(ctx, obj_id)}
    # A group is on screen only as long as all of it is
    groups = [g for g in history.on_screen if isinstance(ctx.objects.get(g), GroupObject)]
    gone |= {g for g in groups if set(leaves_of(ctx, g)) & gone}
    history.on_screen = [obj_id for obj_id in history.on_screen if obj_id not in gone]


def note_cleared(ctx: CodegenContext) -> None:
    history_of(ctx).on_screen = []


def following_of(ctx: CodegenContext, obj_id: str) -> str | None:
    return history_of(ctx).following.get(obj_id)


def followers_among(ctx: CodegenContext, ids: list[str]) -> list[str]:
    """Of these objects and everything in them, those following something, in order."""
    following = history_of(ctx).following
    out: list[str] = []
    for obj_id in ids:
        for inner in leaves_of(ctx, obj_id):
            if inner in following and inner not in out:
                out.append(inner)
    return out


def note_following(ctx: CodegenContext, obj_id: str, target: str | None) -> None:
    following = history_of(ctx).following
    if target is None:
        following.pop(obj_id, None)
    else:
        following[obj_id] = target


# Walking earlier scenes through, to know how they leave their objects

@dataclass
class SceneEnd:
    """How a scene leaves things: the values of its objects, and their history."""
    objects: dict[str, ObjectBase]
    history: History


def scene_start(doc: Document, index: int, strict: bool = True, cache: dict | None = None) -> SceneEnd:
    """
    What a scene starts from: its carried objects as the scene before left them (values and
    history), and its own objects as declared, put in place at its start. With strict, a step
    of an earlier scene which can't be turned into code raises CodegenError; without, it is
    passed over, for timings and validation of a document which may not render.
    """
    scene = doc.scenes[index]
    if scene.carry and index > 0:
        before = scene_end(doc, index - 1, strict, cache)
        objects = {obj_id: before.objects[obj_id] for obj_id in scene.carry if obj_id in before.objects}
        history = before.history.copy()
        history.states = {obj_id: history.states[obj_id] for obj_id in objects if obj_id in history.states}
        history.following = {f: t for f, t in history.following.items() if f in objects and t in objects}
        order = [obj_id for obj_id in history.on_screen if obj_id in objects]
        history.on_screen = order + [obj_id for obj_id in objects if obj_id not in order]
    else:
        # Nothing comes from before, so the story starts afresh
        objects, history = {}, History()
    history.scene_id, history.step_id = scene.id, None
    for obj in scene.objects:
        objects[obj.id] = obj
        history.states[obj.id] = ObjectState(built_at=history.now())
        place = getattr(obj, "place", None)
        if place is not None and place.follow and place.next_to is not None:
            history.following[obj.id] = place.next_to
        if obj.shown:
            history.on_screen.append(obj.id)
    return SceneEnd(objects, history)


def scene_end(doc: Document, index: int, strict: bool = True, cache: dict | None = None) -> SceneEnd:
    """How a scene leaves its objects, having walked its steps through as codegen would."""
    key = (index, strict)
    if cache is not None and key in cache:
        return cache[key]
    from manim_verbose.scenefile import actions
    from manim_verbose.scenefile.codegen import CodegenError, SourceRef, _describe
    start = scene_start(doc, index, strict, cache)
    scene = doc.scenes[index]
    ctx = _WalkContext(doc=doc, scene=scene, objects=dict(start.objects), history=start.history)
    ctx.displaced = {obj_id for obj_id in ctx.objects if moved_since_built(ctx, obj_id)}
    for step_index, step in enumerate(scene.steps):
        ctx.history.step_id = step.id
        try:
            actions.step_code(step, ctx)
        except Exception as err:
            if strict:
                ref = SourceRef(scene.id, ("scenes", index, "steps", step_index), step.id, "step")
                raise CodegenError(_describe(err), ref) from err
    end = SceneEnd(ctx.objects, ctx.history)
    if cache is not None:
        cache[key] = end
    return end


_walk_class = None


def _WalkContext(**kwargs):
    """A CodegenContext whose code nobody reads: names need not keep clear of manim's, so manim isn't imported."""
    global _walk_class
    if _walk_class is None:
        from manim_verbose.scenefile.codegen import CodegenContext

        class WalkContext(CodegenContext):
            def temp(self, wanted: str) -> str:
                return wanted

        _walk_class = WalkContext
    return _walk_class(**kwargs)


def carried_specs(doc: Document, index: int) -> dict[str, ObjectBase]:
    """The values of the objects a scene carries, as the scene before left them, for timings: never raises."""
    scene = doc.scenes[index]
    if not scene.carry or index == 0:
        return {}
    try:
        return {k: v for k, v in scene_start(doc, index, strict=False, cache={}).objects.items() if k in scene.carry}
    except Exception:
        return {}


# Writing the code which carries objects in

def carried_code(ctx: CodegenContext, index: int, cache: dict | None = None) -> list[tuple[str, str | None]]:
    """
    The lines of the `with self.carried_from(...)` block bringing a scene's carried objects
    in, each with the id of the object it is about (for the line map), or None. ctx is the
    scene's own, its objects and history those scene_start gives.
    """
    from manim_verbose.scenefile.actions import color_code, num, placement_call, point3
    from manim_verbose.scenefile import blocks
    from manim_verbose.scenefile.codegen import build_expression, py_str
    doc, scene = ctx.doc, ctx.scene
    carried = [obj_id for obj_id in scene.carry if obj_id in ctx.objects]
    if not carried:
        return []
    history = history_of(ctx)
    events = history.events
    built = {obj_id: history.state(obj_id).built_at for obj_id in carried}
    # Nothing before what it is built on
    changed = True
    while changed:
        changed = False
        for obj_id in carried:
            for _, ref, _ in object_refs(ctx.objects[obj_id]):
                if ref in built and built[ref] > built[obj_id]:
                    built[obj_id] = built[ref]
                    changed = True
    ranked = {obj.id: rank for rank, obj in enumerate(blocks.build_order(SceneSpec(
        id="carried", objects=[ctx.objects[obj_id] for obj_id in carried])))}
    order = sorted(carried, key=lambda obj_id: (built[obj_id], ranked.get(obj_id, 0)))
    # Parts recolored are picked out exactly only when a formula isolates them, which it
    # does for the parts its scene's highlights name
    looked = [
        {"do": "highlight", "target": obj_id, "part": look.part}
        for obj_id in carried for look in history.state(obj_id).looks
        if look.kind == "recolor" and look.part
    ]
    build_scene = scene.model_copy(update={"steps": [*scene.steps, *(
        SceneSpec.model_validate({"id": "x", "steps": looked}).steps if looked else [])]})
    build_ctx = dataclasses.replace(ctx, scene=build_scene)
    lines: list[tuple[str, str | None]] = [(f"with self.carried_from({py_str(doc.scenes[index - 1].id)}):", None)]
    done: set[str] = set()

    def is_built(obj_id: str | None, point: int) -> bool:
        return obj_id is None or (obj_id in built and built[obj_id] <= point and obj_id in done)

    def build(obj_id: str) -> None:
        spec = ctx.objects[obj_id]
        var = ctx.var(obj_id)
        on = getattr(spec, "on", None)
        extra = ""
        # Built on a coordinate system already through some matrices, it shows them already
        if on in built and any(e.kind == "matrix" and on in e.ids for e in events[built[on]:built[obj_id]]):
            extra = f", on={ctx.var(on)}"
        lines.append((f"    {var} = self.obj({py_str(obj_id)}, {build_expression(spec, build_ctx)}{extra})", obj_id))
        for look in history.state(obj_id).looks:
            if look.kind == "dim":
                lines.append((f"    {var}.fade({num(1 - 0.35)})", obj_id))
            elif look.kind == "recolor" and look.part:
                selector = blocks.part_selector(spec, look.part, build_ctx)
                lines.append((f"    {selector}.set_color({color_code(look.color)})", obj_id))
        done.add(obj_id)

    def top_most(ids: list[str]) -> list[str]:
        inside = {inner for obj_id in ids for inner in leaves_of(ctx, obj_id)[1:]}
        return [obj_id for obj_id in ids if obj_id not in inside]

    def replay(event: Event, point: int) -> None:
        acted = [obj_id for obj_id in event.ids if obj_id in built and is_built(obj_id, point)]
        acted = top_most(acted)
        if not acted:
            return
        first = acted[0]
        if event.kind == "matrix":
            matrix = "[" + ", ".join("[" + ", ".join(num(x) for x in row) + "]" for row in event.matrix) + "]"
            anims = []
            for obj_id in acted:
                coords = _coords_for(ctx, event, obj_id)
                if coords is not None and not is_built(coords, point):
                    continue
                anims.append(f"ApplyMatrixOn({matrix}, {ctx.var(obj_id)}" + (f", {ctx.var(coords)})" if coords else ")"))
            if anims:
                lines.append((f"    self.apply_now({', '.join(anims)})", first))
        elif event.kind == "shift":
            for obj_id in acted:
                lines.append((f"    {ctx.var(obj_id)}.shift({point3(event.offset)})", obj_id))
        elif event.kind == "move":
            refs = [r for r in (event.placement.next_to, event.placement.on) if r]
            if not all(is_built(ref, point) for ref in refs):
                return
            if len(acted) == 1:
                subject = ctx.var(first)
            else:
                subject = ctx.temp("moving")
                lines.append((f"    {subject} = Group({', '.join(ctx.var(obj_id) for obj_id in acted)})", first))
            call = placement_call(f"{subject}.copy()", event.placement, ctx)
            lines.append((f"    {subject}.move_to({call})", first))
        elif event.kind == "follow":
            target = event.placement.next_to
            if not is_built(target, point):
                return
            for obj_id in acted:
                lines.append((f"    self.follow({ctx.var(obj_id)}, {ctx.var(target)}{_follow_args(event.placement)})", obj_id))
        elif event.kind == "unfollow":
            lines.append((f"    self.stop_following({', '.join(ctx.var(obj_id) for obj_id in acted)})", first))

    start = min(built.values())
    for point in range(start, len(events) + 1):
        for obj_id in order:
            if built[obj_id] == point:
                build(obj_id)
        if point < len(events):
            replay(events[point], point)
    shown = [obj_id for obj_id in history.on_screen if obj_id in done]
    shown += [obj_id for obj_id in order if obj_id not in shown]
    lines.append((f"    self.add({', '.join(ctx.var(obj_id) for obj_id in shown)})", None))
    return lines


def _coords_for(ctx: CodegenContext, event: Event, obj_id: str) -> str | None:
    """The coordinate system a matrix was read in for this object: its own, or that of the group named."""
    if obj_id in event.coords:
        return event.coords[obj_id]
    for named in event.named:
        if obj_id in leaves_of(ctx, named):
            return event.coords.get(named)
    return None


def _follow_args(place: Placement) -> str:
    args = ""
    if place.anchor != "center":
        args += f', anchor="{place.anchor}"'
    if place.side != "down":
        args += f', side="{place.side}"'
    return args


# What can't be carried exactly, for validation

def carry_problems(doc: Document) -> list[Problem]:
    """Warnings about carried objects which can't be brought over exactly as they were left, see the module's docstring."""
    problems: list[Problem] = []
    cache: dict = {}
    for index, scene in enumerate(doc.scenes):
        if not scene.carry or index == 0:
            continue
        try:
            start = scene_start(doc, index, strict=False, cache=cache)
        except Exception:
            continue
        history = start.history
        carried = [obj_id for obj_id in scene.carry if obj_id in start.objects]
        for position, obj_id in enumerate(scene.carry):
            if obj_id not in start.objects:
                continue
            loc = ["scenes", index, "carry", position]
            state = history.state(obj_id)
            spec = start.objects[obj_id]
            following = history.following.get(obj_id)
            for _, ref, _ in object_refs(spec):
                if ref in carried and ref != following and history.state(ref).built_at > state.built_at:
                    problems.append(Problem(
                        f"'{obj_id}' was put beside '{ref}' before '{ref}' was changed or moved, so it's "
                        f"carried beside '{ref}' as that ended up rather than where it was", loc, "warning",
                        scene.id, obj_id))
            for event in history.events[state.built_at:]:
                if obj_id not in event.ids:
                    continue
                if event.kind == "move":
                    refs = [r for r in (event.placement.next_to, event.placement.on) if r]
                    missing = [r for r in refs if r not in carried]
                    if missing:
                        problems.append(Problem(
                            f"'{obj_id}' was moved beside '{missing[0]}' in scene '{event.scene_id}', which isn't carried, "
                            f"so that move can't be carried: carry '{missing[0]}' too", loc, "warning", scene.id, obj_id))
                    elif event.together and not all(named in carried for named in event.named):
                        left = next(named for named in event.named if named not in carried)
                        problems.append(Problem(
                            f"'{obj_id}' was moved together with '{left}' in scene '{event.scene_id}', which isn't "
                            f"carried, so it's carried as if moved without it", loc, "warning", scene.id, obj_id))
    return problems


def chain(doc: Document, index: int) -> list[int]:
    """The scenes a scene's objects come from, the scene itself last: back as far as each carries from the one before."""
    out = [index]
    while index > 0 and doc.scenes[index].carry:
        index -= 1
        out.insert(0, index)
    return out


def free_standing(obj: ObjectBase) -> bool:
    """Whether a move can be written into the object's own placement: a free object, not a group."""
    return isinstance(obj, FreeObject) and not isinstance(obj, GroupObject)


def default_placement(obj: ObjectBase) -> Placement:
    """The placement an object without one has: a title at the top, anything else in the middle."""
    return Placement(edge="top") if isinstance(obj, TitleObject) else Placement()
