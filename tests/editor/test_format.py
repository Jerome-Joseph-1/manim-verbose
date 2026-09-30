"""
What the server says about the format: the schema, the catalog of objects and steps (and that
every template in it makes a valid document), the starter document, and the health check.
"""
from __future__ import annotations

import copy
import json

import pytest

from manim_verbose.editor.catalog import OBJECT_TEMPLATES, STEP_TEMPLATES, catalog
from manim_verbose.editor.documents import read_document
from manim_verbose.editor.starter import STARTER_YAML, write_starter
from manim_verbose.scenefile.files import dump_text, load_file, parse_text
from manim_verbose.scenefile.model import OBJECT_MODELS, STEP_MODELS
from manim_verbose.scenefile.schema import document_schema

REF_FIELDS = {"target", "into", "on", "next_to", "focus", "members"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert isinstance(r.json()["version"], str) and r.json()["version"]


def test_schema_is_the_documents(client):
    body = client.get("/api/schema").json()
    assert body == json.loads(json.dumps(document_schema()))
    assert body["$schema"].startswith("https://json-schema.org/")


def test_catalog_offers_every_kind_with_words_from_the_models(client):
    body = client.get("/api/catalog").json()
    assert [o["type"] for o in body["objects"]] == list(OBJECT_MODELS)
    assert [s["do"] for s in body["steps"]] == list(STEP_MODELS)

    tex = next(o for o in body["objects"] if o["type"] == "tex")
    assert tex["label"] == "Equation"
    assert tex["category"] == "Text & math"
    assert tex["description"] == "A LaTeX formula, in math mode."
    assert tex["template"]["type"] == "tex"

    graph = next(o for o in body["objects"] if o["type"] == "graph")
    assert "\n" not in graph["description"], "lines of a docstring paragraph are joined"
    assert graph["description"].startswith("The graph of a function of x, on a set of axes. The function")

    show = next(s for s in body["steps"] if s["do"] == "show")
    assert show == {"do": "show", "label": "Show", "description": "Bring objects onto the screen.",
                    "template": {"do": "show", "target": ""}}
    assert next(s for s in body["steps"] if s["do"] == "clear")["label"] == "Clear screen"
    for entry in body["objects"] + body["steps"]:
        assert entry["label"] and entry["description"], entry
    for entry in body["objects"]:
        assert entry["category"] in {"Text & math", "Coordinates", "Geometry", "Shapes", "Annotations", "Media",
                                     "Layout"}, entry


def test_every_kind_has_a_hand_written_template():
    assert set(OBJECT_TEMPLATES) == set(OBJECT_MODELS), "add a template to catalog.py for each new kind of object"
    assert set(STEP_TEMPLATES) == set(STEP_MODELS), "add a template to catalog.py for each new kind of step"
    for kind, template in OBJECT_TEMPLATES.items():
        assert template["type"] == kind and "id" not in template
    for kind, template in STEP_TEMPLATES.items():
        assert template["do"] == kind and "id" not in template


def fill_refs(value, ids):
    """Point each reference left blank ("") at an object; `ids` picks the object by field name."""
    if isinstance(value, dict):
        return {key: fill_field(key, item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_refs(item, ids) for item in value]
    return value


def fill_field(key, value, ids):
    if key in REF_FIELDS and value == "":
        return ids[key][0]
    if key in REF_FIELDS and isinstance(value, list) and all(v == "" for v in value):
        return ids[key][:len(value)]
    return fill_refs(value, ids)


HOSTS = [
    {"id": "ax", "type": "axes", "shown": True},
    {"id": "t", "type": "text", "text": "one", "shown": True},
    {"id": "t2", "type": "text", "text": "two", "shown": True, "place": {"edge": "bottom"}},
]
IDS = {"on": ["ax"], "target": ["t"], "into": ["t2"], "next_to": ["t"], "focus": ["t"], "members": ["t", "t2"]}


def blanks(value) -> int:
    if isinstance(value, dict):
        return sum(blanks(v) for v in value.values())
    if isinstance(value, list):
        return sum(blanks(v) for v in value)
    return value == ""


@pytest.mark.parametrize("kind", list(OBJECT_MODELS))
def test_every_object_template_makes_a_valid_document(kind):
    template = catalog()["objects"][list(OBJECT_MODELS).index(kind)]["template"]
    obj = {"id": "added", **fill_refs(copy.deepcopy(template), IDS)}
    assert blanks(obj) == 0, "only references are left blank"
    doc, problems = read_document({"scenes": [{"id": "s", "objects": HOSTS + [obj],
                                               "steps": [{"do": "show", "target": "added"}]}]})
    assert doc is not None, problems
    assert not [p for p in problems if p.severity == "error"], problems


@pytest.mark.parametrize("kind", list(STEP_MODELS))
def test_every_step_template_makes_a_valid_document(kind):
    template = catalog()["steps"][list(STEP_MODELS).index(kind)]["template"]
    step = fill_refs(copy.deepcopy(template), IDS)
    assert blanks(step) == 0, "only references are left blank"
    doc, problems = read_document({"scenes": [{"id": "s", "objects": HOSTS, "steps": [step]}]})
    assert doc is not None, problems
    assert not [p for p in problems if p.severity == "error"], problems


def test_the_starter_document_is_valid_and_needs_no_latex():
    data, problems = parse_text(STARTER_YAML)
    assert problems == []
    doc, problems = read_document(data)
    assert problems == [], "no errors and no warnings either"
    kinds = {obj.type for scene in doc.scenes for obj in scene.objects}
    assert not kinds & {"tex", "matrix", "title", "axes", "graph", "brace"}, kinds
    assert len(doc.scenes) >= 2 and all(scene.steps for scene in doc.scenes)
    assert any(step.caption for scene in doc.scenes for step in scene.steps)


@pytest.mark.parametrize("name", ["new.yaml", "new.yml", "new.json"])
def test_the_starter_is_written_in_canonical_form(tmp_path, name):
    path = tmp_path / name
    write_starter(path)
    doc, problems = load_file(path)
    assert problems == []
    fmt = "json" if name.endswith(".json") else "yaml"
    assert path.read_text(encoding="utf-8") == dump_text(doc, fmt)
    if fmt == "json":
        json.loads(path.read_text(encoding="utf-8"))
