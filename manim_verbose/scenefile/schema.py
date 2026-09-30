"""
The json schema of the scene file format, generated from the models in model.py.

The editor builds its forms from this, and it can be given to a language model to hold its
output to the format. A copy is kept in schema.json beside this file, and a test fails when
that copy falls behind the models; `manimgl-scene schema --write` brings it up to date.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from manim_verbose.scenefile.model import Document

SCHEMA_PATH = Path(__file__).with_name("schema.json")


def document_schema() -> dict[str, Any]:
    schema = Document.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


def schema_text() -> str:
    return json.dumps(document_schema(), indent=2, sort_keys=False) + "\n"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    path.write_text(schema_text(), encoding="utf-8")
