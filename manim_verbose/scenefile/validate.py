"""
Checking a scene file, and saying what is wrong with it in words its author can act on.

Two passes. The models catch anything wrong with one object or step taken alone, and their
errors are reworded here, since "extra_forbidden at scenes.0.objects.2.text.fnt_size" is no
help to someone who has never seen Python. Then the document as a whole is checked for what
no single model can see: names which are used twice or never declared, a step referring to
an object of the wrong kind, a highlight of a part a formula doesn't contain, objects
placed next to each other in a circle.

Every problem carries where it is twice over: `loc`, the path into the document as data, and
`scene_id` with `item_id`, which survive steps being added and removed around it, so the
editor can put the message beside the field it is about.
"""
from __future__ import annotations

import difflib
from functools import lru_cache
from dataclasses import dataclass, field, asdict
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ValidationError

from manim_verbose.scenefile.expressions import check_expression
from manim_verbose.scenefile.model import (
    Document, SceneSpec, ObjectBase, StepBase, Placement,
    OBJECT_MODELS, STEP_MODELS, ID_PATTERN,
    TextObject, TexObject, TitleObject, QuoteObject, BulletsObject,
    GroupObject, BraceObject, BoxObject, ImageObject, SvgObject, GraphObject,
    ShowStep, HideStep, AddStep, RemoveStep, ClearStep, TransformStep,
    ChangeStep, MoveStep, HighlightStep, CameraStep, ApplyMatrixStep, TogetherStep,
    iter_steps,
)

Loc = list[str | int]
Severity = Literal["error", "warning"]

# Kinds of object a `part` can be picked out of, and the field holding the string searched
PART_FIELDS: dict[type, str] = {
    TextObject: "text",
    TexObject: "tex",
    TitleObject: "text",
    QuoteObject: "text",
}


@dataclass
class Problem:
    message: str
    loc: Loc = field(default_factory=list)
    severity: Severity = "error"
    scene_id: str | None = None
    item_id: str | None = None

    @property
    def path(self) -> str:
        return format_loc(self.loc)

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "path": self.path}

    def __str__(self) -> str:
        where = self.path or "document"
        return f"{self.severity}: {where}: {self.message}"


def format_loc(loc: Iterable[str | int]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def validate_data(data: Any) -> tuple[Document | None, list[Problem]]:
    """
    Check a document given as plain data, as read from a file. Returns the document, or None
    when it could not be read at all, along with every problem found. A document is returned
    whenever the models accept it, even if the whole-document checks found errors, so that
    callers can decide for themselves what to do with a document which is merely wrong.
    """
    if not isinstance(data, dict):
        return None, [Problem("A scene file has to be a mapping, with `scenes` at the top level")]
    try:
        doc = Document.model_validate(data)
    except ValidationError as err:
        return None, [reword(error, data) for error in err.errors(include_url=False)]
    return doc, check_document(doc)


def has_errors(problems: Iterable[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)


# Rewording the models' errors

def reword(error: dict[str, Any], data: Any) -> Problem:
    loc, kinds = _clean_loc(error["loc"], data)
    kind = kinds[-1] if kinds else "document"
    field_name = next((p for p in reversed(loc) if isinstance(p, str)), None)
    etype = error["type"]
    ctx = error.get("ctx") or {}
    value = error.get("input")

    if etype == "missing":
        message = f"{_a(kind)} needs '{field_name}'"
    elif etype == "extra_forbidden":
        model = _model_for_kind(kind)
        message = f"'{field_name}' isn't something {_a(kind)} has"
        if model is not None:
            message += _did_you_mean(field_name, [n for n in model.model_fields])
    elif etype == "union_tag_invalid":
        tag = ctx.get("tag")
        if ctx.get("discriminator") == "'do'":
            message = f"There's no step called '{tag}'" + _did_you_mean(tag, STEP_MODELS)
            message += ". Steps are: " + ", ".join(STEP_MODELS)
        else:
            message = f"There's no kind of object called '{tag}'" + _did_you_mean(tag, OBJECT_MODELS)
            message += ". Kinds are: " + ", ".join(OBJECT_MODELS)
    elif etype == "union_tag_not_found":
        if ctx.get("discriminator") == "'do'":
            message = "Every step needs `do`, saying what it does, such as `do: show`"
        else:
            message = "Every object needs `type`, saying what it is, such as `type: text`"
    elif etype == "literal_error":
        message = f"'{value}' isn't allowed here; use one of {ctx.get('expected')}"
    elif etype == "string_pattern_mismatch" and ctx.get("pattern") == ID_PATTERN:
        message = f"'{value}' can't be a name: use letters, digits and _, not starting with a digit"
    elif etype == "value_error":
        message = str(ctx.get("error") or error["msg"]).removeprefix("Value error, ")
    elif etype in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        bound = next(iter(ctx.values()))
        words = {
            "greater_than": "more than", "greater_than_equal": "at least",
            "less_than": "less than", "less_than_equal": "at most",
        }[etype]
        message = f"'{field_name}' has to be {words} {bound}"
    elif etype in ("too_short", "too_long"):
        message = _length_message(field_name, etype, ctx)
    elif etype in ("float_type", "float_parsing", "int_type", "int_parsing", "int_from_float"):
        message = f"'{field_name}' has to be a number" + (" with no decimal point" if "int" in etype else "")
    elif etype in ("string_type",):
        message = f"'{field_name}' has to be text"
    elif etype in ("bool_type", "bool_parsing"):
        message = f"'{field_name}' has to be true or false"
    elif etype in ("list_type",):
        message = f"'{field_name}' has to be a list"
    elif etype in ("dict_type", "model_type", "model_attributes_type"):
        message = f"'{field_name}' has to be a mapping of names to values" if field_name else "Expected a mapping"
    else:
        message = error["msg"]

    scene_id, item_id = _ids_at(loc, data)
    return Problem(message, loc, "error", scene_id, item_id)


def _clean_loc(raw_loc: tuple, data: Any) -> tuple[Loc, list[str]]:
    """
    Pydantic puts the tag of a tagged union into the location, as in
    ('scenes', 0, 'objects', 2, 'text', 'font_size'), and wraps other unions in segments
    naming the type tried. Walk the data alongside the location and keep only what indexes
    into it, noting what kind of thing each level is on the way.
    """
    loc: Loc = []
    kinds: list[str] = []
    node = data
    expect_tag = None
    for part in raw_loc:
        if expect_tag is not None and part == expect_tag:
            # The tag pydantic adds after an item of a tagged union, not a field of it
            expect_tag = None
            continue
        expect_tag = None
        if isinstance(node, list) and isinstance(part, int) and part < len(node):
            node = node[part]
            loc.append(part)
            if isinstance(node, dict):
                if "type" in node:
                    kinds.append(f"{node['type']} object")
                    expect_tag = node["type"]
                elif "do" in node:
                    kinds.append(f"{node['do']} step")
                    expect_tag = node["do"]
                elif loc[-2:-1] == ["scenes"]:
                    kinds.append("scene")
        elif isinstance(node, dict) and isinstance(part, str) and part in node:
            node = node[part]
            loc.append(part)
            if part == "place":
                kinds.append("placement")
            elif part == "settings":
                kinds.append("settings")
        elif isinstance(node, dict) and isinstance(part, str):
            is_union_wrapper = any(c in part for c in "[]()") or part in ("str", "list[str]")
            if not is_union_wrapper:
                # A field which isn't there: the location of something missing
                loc.append(part)
        # Anything else is a union wrapper around a value, not a place in the data
    return loc, kinds


def _model_for_kind(kind: str) -> type[BaseModel] | None:
    name, _, what = kind.rpartition(" ")
    if what == "object":
        return OBJECT_MODELS.get(name)
    if what == "step":
        return STEP_MODELS.get(name)
    return {"placement": Placement, "scene": SceneSpec, "document": Document}.get(kind)


def _a(kind: str) -> str:
    if kind == "document":
        return "the document"
    return ("an " if kind[0] in "aeiou" else "a ") + kind


def _did_you_mean(word: str | None, options: Iterable[str]) -> str:
    if not word:
        return ""
    close = difflib.get_close_matches(word, list(options), n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _length_message(field_name: str | None, etype: str, ctx: dict[str, Any]) -> str:
    if field_name in ("point", "tip", "tail", "start", "end", "center", "at", "shift", "by"):
        return f"'{field_name}' is a point, written [x, y] or [x, y, z]"
    if field_name in ("x_range", "y_range", "z_range"):
        return f"'{field_name}' is written [min, max] or [min, max, step]"
    if etype == "too_short":
        return f"'{field_name}' needs at least {ctx.get('min_length')} item(s)"
    return f"'{field_name}' can have at most {ctx.get('max_length')} item(s)"


def _ids_at(loc: Loc, data: Any) -> tuple[str | None, str | None]:
    scene_id = item_id = None
    node = data
    for part in loc:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and "id" in node:
            if scene_id is None and ("objects" in node or "steps" in node):
                scene_id = node["id"]
            else:
                item_id = node["id"]
    return scene_id, item_id


# Whole document checks

def check_document(doc: Document) -> list[Problem]:
    problems: list[Problem] = []
    seen_scenes: set[str] = set()
    seen_steps: set[str] = set()
    for s_index, scene in enumerate(doc.scenes):
        sloc: Loc = ["scenes", s_index]
        if scene.id in seen_scenes:
            problems.append(Problem(f"Two scenes are called '{scene.id}'", sloc + ["id"], scene_id=scene.id))
        seen_scenes.add(scene.id)
        problems.extend(SceneChecker(scene, sloc, seen_steps).run())
    return problems


class SceneChecker:
    def __init__(self, scene: SceneSpec, loc: Loc, seen_steps: set[str]):
        self.scene = scene
        self.loc = loc
        self.seen_steps = seen_steps
        self.objects: dict[str, ObjectBase] = {}
        self.problems: list[Problem] = []

    def run(self) -> list[Problem]:
        self.check_objects()
        self.check_steps()
        self.check_on_screen()
        return self.problems

    def problem(self, message: str, loc: Loc, item_id: str | None = None, severity: Severity = "error"):
        self.problems.append(Problem(message, loc, severity, self.scene.id, item_id))

    # Objects

    def check_objects(self):
        for index, obj in enumerate(self.scene.objects):
            loc = self.loc + ["objects", index]
            if obj.id in self.objects:
                self.problem(f"Two objects in this scene are called '{obj.id}'", loc + ["id"], obj.id)
            self.objects[obj.id] = obj
        for index, obj in enumerate(self.scene.objects):
            loc = self.loc + ["objects", index]
            for ref_loc, ref, types in object_refs(obj):
                self.check_ref(ref, types, loc + ref_loc, obj.id)
                if ref == obj.id:
                    self.problem(f"'{obj.id}' can't refer to itself", loc + ref_loc, obj.id)
            if isinstance(obj, (ImageObject, SvgObject)):
                self.check_path(obj.path, loc + ["path"], obj.id)
            if isinstance(obj, GraphObject):
                self.check_function(obj.function, loc + ["function"], obj.id)
        self.check_cycles()

    def check_ref(self, ref: str, types: list[str] | None, loc: Loc, item_id: str | None) -> bool:
        if ref not in self.objects:
            message = f"There's no object called '{ref}' in scene '{self.scene.id}'"
            message += _did_you_mean(ref, self.objects)
            self.problem(message, loc, item_id)
            return False
        if types and self.objects[ref].type not in types:
            kinds = " or ".join(t.replace("_", " ") for t in types)
            self.problem(f"'{ref}' is a {self.objects[ref].type.replace('_', ' ')}, but this needs a {kinds}", loc, item_id)
            return False
        return True

    def check_path(self, path: str, loc: Loc, item_id: str):
        parts = PurePosixPath(path.replace("\\", "/")).parts
        if PureWindowsPath(path).is_absolute() or path.startswith("/") or ".." in parts:
            self.problem("Files have to be in the scene file's folder or below it, given as a relative path", loc, item_id)

    def check_function(self, function: Any, loc: Loc, item_id: str | None):
        message = check_expression(function)
        if message is not None:
            self.problem(message, loc, item_id)

    def check_cycles(self):
        deps = {obj.id: {ref for _, ref, _ in object_refs(obj) if ref in self.objects} for obj in self.scene.objects}
        state: dict[str, int] = {}

        def visit(node: str, trail: list[str]) -> bool:
            if state.get(node) == 1:
                cycle = trail[trail.index(node):] + [node]
                index = next(i for i, o in enumerate(self.scene.objects) if o.id == node)
                self.problem(
                    "These objects are each placed by another, in a circle: " + " -> ".join(cycle),
                    self.loc + ["objects", index], node,
                )
                return True
            if state.get(node) == 2:
                return False
            state[node] = 1
            for dep in sorted(deps.get(node, ())):
                if visit(dep, trail + [node]):
                    return True
            state[node] = 2
            return False

        for obj in self.scene.objects:
            if visit(obj.id, []):
                break

    # Steps

    def check_steps(self):
        for index, step in enumerate(self.scene.steps):
            self.check_step(step, self.loc + ["steps", index])

    def check_step(self, step: StepBase, loc: Loc):
        if step.id is not None:
            if step.id in self.seen_steps:
                self.problem(f"Two steps are called '{step.id}'", loc + ["id"], step.id)
            self.seen_steps.add(step.id)
        for ref_loc, ref, types in step_refs(step):
            self.check_ref(ref, types, loc + ref_loc, step.id)
        if isinstance(step, HighlightStep) and step.part is not None and step.target in self.objects:
            self.check_part(step, loc)
        if isinstance(step, ChangeStep) and step.target in self.objects:
            self.check_change(step, loc)
        if isinstance(step, TogetherStep):
            for index, inner in enumerate(step.steps):
                self.check_step(inner, loc + ["steps", index])

    def check_part(self, step: HighlightStep, loc: Loc):
        target = self.objects[step.target]
        field_name = PART_FIELDS.get(type(target))
        if field_name is None:
            self.problem(
                f"Only parts of text, formulas, titles and quotes can be highlighted, and '{step.target}' is a {target.type}",
                loc + ["part"], step.id,
            )
        elif step.part not in getattr(target, field_name):
            self.problem(f"'{step.part}' doesn't appear in '{step.target}'", loc + ["part"], step.id)

    def check_change(self, step: ChangeStep, loc: Loc):
        target = self.objects[step.target]
        model = type(target)
        for key in step.set:
            if key in ("id", "type"):
                self.problem(f"A change can't alter '{key}'", loc + ["set", key], step.id)
            elif key not in model.model_fields:
                self.problem(
                    f"'{key}' isn't something a {target.type} has" + _did_you_mean(key, model.model_fields),
                    loc + ["set", key], step.id,
                )
        if isinstance(target, GraphObject) and isinstance(step.set.get("function"), str):
            self.check_function(step.set["function"], loc + ["set", "function"], step.id)
        merged = {**target.model_dump(exclude_defaults=True), **step.set, "id": target.id, "type": target.type}
        try:
            model.model_validate(merged)
        except ValidationError as err:
            for error in err.errors(include_url=False):
                problem = reword(error, merged)
                if problem.loc and problem.loc[0] in step.set and problem.loc[0] in model.model_fields:
                    self.problem(problem.message, loc + ["set"] + problem.loc, step.id)

    # What is on screen when

    def check_on_screen(self):
        """
        Follow the steps through, tracking what is on screen, and warn about steps which act
        on something that isn't there. These are warnings rather than errors, since manim
        mostly copes, just not the way the author meant.
        """
        on_screen = self.with_groups({obj.id for obj in self.scene.objects if obj.shown})
        for index, step in enumerate(self.scene.steps):
            on_screen = self.with_groups(self.follow(step, self.loc + ["steps", index], on_screen))

    def with_groups(self, on_screen: set[str]) -> set[str]:
        """A group is on screen when all its members are, however they got there."""
        out = set(on_screen)
        groups = [obj for obj in self.scene.objects if isinstance(obj, GroupObject)]
        changed = True
        while changed:
            changed = False
            for group in groups:
                shown = all(m in out for m in group.members)
                if shown and group.id not in out:
                    out.add(group.id)
                    changed = True
                elif not shown and group.id in out:
                    out.discard(group.id)
                    changed = True
        return out

    def follow(self, step: StepBase, loc: Loc, on_screen: set[str]) -> set[str]:
        def members(ref: str) -> set[str]:
            obj = self.objects.get(ref)
            out = {ref}
            if isinstance(obj, GroupObject):
                for m in obj.members:
                    out |= members(m)
            return out

        def warn_absent(ref: str, field_name: str = "target"):
            if ref in self.objects and ref not in on_screen:
                self.problem(f"'{ref}' isn't on screen at this point", loc + [field_name], step.id, "warning")

        after = set(on_screen)
        if isinstance(step, (ShowStep, AddStep)):
            for ref in _as_list(step.target):
                if ref in on_screen:
                    self.problem(f"'{ref}' is already on screen", loc + ["target"], step.id, "warning")
                after |= members(ref)
        elif isinstance(step, (HideStep, RemoveStep)):
            for ref in _as_list(step.target):
                warn_absent(ref)
                after -= members(ref)
        elif isinstance(step, ClearStep):
            after = set()
        elif isinstance(step, TransformStep):
            warn_absent(step.target)
            if not step.keep:
                after -= members(step.target)
            after |= members(step.into)
        elif isinstance(step, (ChangeStep, HighlightStep)):
            warn_absent(step.target)
        elif isinstance(step, (MoveStep, ApplyMatrixStep)):
            for ref in _as_list(step.target):
                warn_absent(ref)
        elif isinstance(step, TogetherStep):
            for index, inner in enumerate(step.steps):
                after |= self.follow(inner, loc + ["steps", index], on_screen) - on_screen
                if isinstance(inner, (HideStep, RemoveStep)):
                    for ref in _as_list(inner.target):
                        after -= members(ref)
                elif isinstance(inner, TransformStep) and not inner.keep:
                    after -= members(inner.target)
                elif isinstance(inner, ClearStep):
                    after = set()
        return after


def _as_list(target: str | list[str]) -> list[str]:
    return [target] if isinstance(target, str) else list(target)


def object_refs(obj: ObjectBase) -> list[tuple[Loc, str, list[str] | None]]:
    """Every reference an object makes to another: (where in the object, id, kinds allowed)."""
    refs: list[tuple[Loc, str, list[str] | None]] = []
    place = getattr(obj, "place", None)
    if place is not None and place.next_to is not None:
        refs.append((["place", "next_to"], place.next_to, None))
    if place is not None and place.on is not None:
        refs.append((["place", "on"], place.on, _ref_types(Placement, "on")))
    on = getattr(obj, "on", None)
    if on is not None:
        refs.append((["on"], on, _ref_types(type(obj), "on")))
    if isinstance(obj, (BraceObject, BoxObject)):
        refs.append((["target"], obj.target, None))
    if isinstance(obj, GroupObject):
        refs.extend((["members", i], m, None) for i, m in enumerate(obj.members))
    return refs


def step_refs(step: StepBase) -> list[tuple[Loc, str, list[str] | None]]:
    refs: list[tuple[Loc, str, list[str] | None]] = []
    target = getattr(step, "target", None)
    if isinstance(target, str):
        refs.append((["target"], target, None))
    elif isinstance(target, list):
        refs.extend((["target", i], t, None) for i, t in enumerate(target))
    if isinstance(step, TransformStep):
        refs.append((["into"], step.into, None))
    if isinstance(step, CameraStep) and step.focus is not None:
        refs.append((["focus"], step.focus, None))
    if isinstance(step, MoveStep) and step.to is not None and step.to.next_to is not None:
        refs.append((["to", "next_to"], step.to.next_to, None))
    if isinstance(step, MoveStep) and step.to is not None and step.to.on is not None:
        refs.append((["to", "on"], step.to.on, _ref_types(Placement, "on")))
    return refs


@lru_cache(maxsize=None)
def _ref_types(model: type[BaseModel], field_name: str) -> list[str] | None:
    schema = model.model_json_schema()
    prop = schema.get("properties", {}).get(field_name, {})
    for candidate in [prop, *prop.get("anyOf", [])]:
        if "x-ref-types" in candidate:
            return candidate["x-ref-types"]
    return None


def assign_step_ids(doc: Document) -> Document:
    """Give every step without an id one, unique across the document."""
    taken = {step.id for scene in doc.scenes for step in iter_steps(scene.steps) if step.id}
    for scene in doc.scenes:
        count = 0
        for step in iter_steps(scene.steps):
            if step.id is None:
                while True:
                    count += 1
                    candidate = f"{scene.id}_{count}"
                    if candidate not in taken:
                        break
                step.id = candidate
                taken.add(candidate)
    return doc
