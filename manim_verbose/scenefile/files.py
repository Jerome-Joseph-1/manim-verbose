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


def _tidy(value: Any) -> Any:
    """Put id and type (or do) first in every mapping, and write whole numbers without a decimal point."""
    if isinstance(value, dict):
        first = [key for key in ("version", "id", "type", "do") if key in value]
        return {key: _tidy(value[key]) for key in first + [k for k in value if k not in first]}
    if isinstance(value, list):
        return [_tidy(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def dump_text(doc: Document, fmt: str = "yaml") -> str:
    data = to_data(doc)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


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
    """Writes short lists of numbers, like points and ranges, on one line, and long text as blocks."""


def _represent_list(dumper: yaml.SafeDumper, data: list):
    flow = len(data) <= 4 and all(isinstance(x, (int, float, str)) and not isinstance(x, bool) for x in data)
    flow = flow or all(isinstance(x, list) and len(x) <= 4 for x in data) and len(data) <= 4
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


def _represent_str(dumper: yaml.SafeDumper, data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(list, _represent_list)
_Dumper.add_representer(str, _represent_str)
