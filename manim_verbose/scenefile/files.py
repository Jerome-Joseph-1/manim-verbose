"""
Reading scene files from disk and writing them back.

A scene file is YAML or JSON, told apart by its extension (.yaml, .yml or .json). Either way
what is written back is the canonical form: defaults left out, so that a file says only what
its author chose, and every step given an id, so that the editor can keep hold of a step while
others are added and removed around it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from manim_verbose.scenefile.model import Document
from manim_verbose.scenefile.validate import Problem, assign_step_ids, validate_data


class SceneFileError(Exception):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


def parse_text(text: str, fmt: str = "yaml") -> tuple[Any, list[Problem]]:
    try:
        if fmt == "json":
            return json.loads(text), []
        return yaml.load(text, Loader=_Loader), []
    except json.JSONDecodeError as err:
        return None, [Problem(f"This isn't valid JSON: {err.msg} (line {err.lineno}, column {err.colno})")]
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        what = getattr(err, "problem", None) or str(err)
        return None, [Problem(f"This isn't valid YAML: {what}{where}")]


def format_of(path: str | Path) -> str:
    return "json" if Path(path).suffix.lower() == ".json" else "yaml"


def load_text(text: str, fmt: str = "yaml") -> tuple[Document | None, list[Problem]]:
    data, problems = parse_text(text, fmt)
    if problems:
        return None, problems
    doc, problems = validate_data(data)
    if doc is not None:
        assign_step_ids(doc)
    return doc, problems


def load_file(path: str | Path) -> tuple[Document | None, list[Problem]]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        return None, [Problem(f"Couldn't read {path}: {err.strerror}")]
    return load_text(text, format_of(path))


def load_document(path: str | Path) -> Document:
    """Load a scene file, raising SceneFileError if it has any errors (warnings are fine)."""
    doc, problems = load_file(path)
    if doc is None or any(p.severity == "error" for p in problems):
        raise SceneFileError([p for p in problems if p.severity == "error"])
    return doc


def to_data(doc: Document) -> dict[str, Any]:
    data = doc.model_dump(mode="json", exclude_defaults=True)
    return _tidy({"version": doc.version, **data})


# What a reader wants first and last in a mapping; everything else keeps the models' order
_FIRST = ("version", "id", "title", "type", "do", "target", "into")
_LAST = ("color", "opacity", "z", "shown", "fixed", "place", "scale", "rotate", "backdrop", "run_time", "caption")


def _tidy(value: Any, key: str | None = None) -> Any:
    """
    Arrange data the way a person would write it: id and kind first, styling, timing and
    captions last, placements back in their short forms (`place: top`, `place: [1, 2]`), and
    whole numbers without a decimal point.
    """
    if isinstance(value, dict):
        if key in ("place", "to") and set(value) == {"edge"}:
            return value["edge"]
        if key in ("place", "to") and set(value) == {"at"}:
            return _tidy(value["at"])
        first = [k for k in _FIRST if k in value]
        last = [k for k in _LAST if k in value and k not in first]
        middle = [k for k in value if k not in first and k not in last]
        return {k: _tidy(value[k], k) for k in first + middle + last}
    if isinstance(value, list):
        return [_tidy(item, key) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def dump_text(doc: Document, fmt: str = "yaml") -> str:
    data = to_data(doc)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10_000)


def save_file(doc: Document, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dump_text(doc, format_of(path)), encoding="utf-8")
    tmp.replace(path)


# YAML 1.1, which PyYAML follows, reads on, off, yes and no as true and false, so that
# `on: plane` would come through as {True: "plane"}, and a caption reading "no" as False.
# Scene files follow YAML 1.2 here: only true and false are booleans.
_BOOL = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


def _without_yaml11_bools(cls):
    cls.yaml_implicit_resolvers = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    cls.add_implicit_resolver("tag:yaml.org,2002:bool", _BOOL, list("tTfF"))
    return cls


@_without_yaml11_bools
class _Loader(yaml.SafeLoader):
    pass


@_without_yaml11_bools
class _Dumper(yaml.SafeDumper):
    """
    Writes anything short on one line, the way a person would type it: points and ranges
    as [1, 2], and a step or a small object as {id: a_1, do: show, target: eq}. Anything
    longer, or holding text of several lines, is written out a field per line.
    """


FLOW_WIDTH = 96


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float)) or (isinstance(value, str) and "\n" not in value)


def _flow_length(value: Any) -> int | None:
    """Length of `value` written on one line, or None if it shouldn't be."""
    if _is_scalar(value):
        text = str(value)
        quoted = isinstance(value, str) and (text == "" or any(c in text for c in ",:{}[]#&*!|>'\"%@`") or text != text.strip())
        return len(text) + (2 if quoted else 0)
    if isinstance(value, list):
        parts = [_flow_length(item) for item in value]
    elif isinstance(value, dict):
        parts = []
        for k, v in value.items():
            n = _flow_length(v)
            parts.append(None if n is None else len(str(k)) + 2 + n)
    else:
        return None
    if any(p is None for p in parts):
        return None
    return 2 + sum(parts) + 2 * max(len(parts) - 1, 0)


def _flow(value: Any) -> bool:
    length = _flow_length(value)
    return length is not None and length <= FLOW_WIDTH


def _represent_list(dumper: yaml.SafeDumper, data: list):
    flow = all(_is_scalar(x) for x in data) and _flow(data)
    flow = flow or all(isinstance(x, list) and all(_is_scalar(y) for y in x) for x in data) and _flow(data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=bool(data) and flow)


def _represent_dict(dumper: yaml.SafeDumper, data: dict):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=bool(data) and _flow(data))


def _represent_str(dumper: yaml.SafeDumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(list, _represent_list)
_Dumper.add_representer(dict, _represent_dict)
_Dumper.add_representer(str, _represent_str)
