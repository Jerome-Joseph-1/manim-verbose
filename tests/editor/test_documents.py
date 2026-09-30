"""
Loading and saving the scene file through the server: canonical form in the file's own format,
revisions and conflicts (between tabs, and with edits made on disk), atomic saves, and every
way a request can be wrong.
"""
from __future__ import annotations

import copy
import errno
import json
import os
import stat
import sys

import pytest
import yaml

from manim_verbose.editor import documents
from manim_verbose.editor.limits import Limits
from manim_verbose.scenefile.files import dump_text, load_text, to_data


def canonical(data: dict, fmt: str = "yaml") -> str:
    doc, problems = load_text(json.dumps(data), "json")
    assert doc is not None, problems
    return dump_text(doc, fmt)


def test_get_returns_the_canonical_document(make_client, tmp_path):
    path = tmp_path / "hand.yaml"
    path.write_text(
        "# written by hand\n"
        "scenes:\n"
        "  - id: a\n"
        "    objects:\n"
        "      - {id: t, type: text, text: hi, font_size: 48, z: 0}\n"
        "    steps:\n"
        "      - {do: show, target: t}\n",
        encoding="utf-8",
    )
    body = make_client(path).get("/api/document").json()
    assert body["path"] == str(path.resolve())
    assert body["revision"] == 1
    assert body["problems"] == []
    assert body["document"] == {
        "version": 1,
        "scenes": [{"id": "a", "objects": [{"id": "t", "type": "text", "text": "hi"}],
                    "steps": [{"id": "a_1", "do": "show", "target": "t"}]}],
    }
    assert path.read_text(encoding="utf-8").startswith("# written by hand"), "reading must not rewrite the file"


def test_put_saves_yaml_in_canonical_form(client, scene_file, sample):
    sample["title"] = "Changed"
    sample["scenes"][0]["objects"][0]["font_size"] = 48
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == 2
    assert body["document"]["title"] == "Changed"
    assert "font_size" not in body["document"]["scenes"][0]["objects"][0]
    assert scene_file.read_text(encoding="utf-8") == canonical(sample, "yaml")
    assert client.get("/api/document").json()["revision"] == 2


def test_put_saves_json_in_canonical_form(make_client, json_scene_file, sample):
    client = make_client(json_scene_file)
    sample["title"] = "In JSON"
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 200, r.text
    text = json_scene_file.read_text(encoding="utf-8")
    assert text == canonical(sample, "json")
    assert json.loads(text)["title"] == "In JSON"
    assert r.json()["document"] == json.loads(text)


def test_saved_step_ids_and_problems_name_the_steps(client, sample):
    for step in sample["scenes"][0]["steps"]:
        del step["id"]
    sample["scenes"][0]["steps"].append({"do": "hide", "target": "eqq"})
    body = client.put("/api/document", json={"document": sample, "base_revision": 1}).json()
    ids = [step["id"] for step in body["document"]["scenes"][0]["steps"]]
    assert ids == ["intro_1", "intro_2", "intro_3", "intro_4", "intro_5"]
    [error] = [p for p in body["problems"] if p["severity"] == "error"]
    assert error["loc"] == ["scenes", 0, "steps", 4, "target"]
    assert error["path"] == "scenes[0].steps[4].target"
    assert error["scene_id"] == "intro"
    assert error["item_id"] == "intro_5"
    assert "did you mean 'eq'" in error["message"]


def test_a_document_with_errors_is_still_saved(client, scene_file, sample):
    sample["scenes"][0]["steps"][1]["target"] = "nobody"
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 200
    assert r.json()["revision"] == 2
    assert any(p["severity"] == "error" and p["item_id"] == "intro_2" for p in r.json()["problems"])
    assert "nobody" in scene_file.read_text(encoding="utf-8")


def test_an_unreadable_document_is_refused_with_located_problems(client, scene_file, sample):
    before = scene_file.read_bytes()
    sample["scenes"][0]["objects"][1]["fnt_size"] = 3
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 422
    [p] = r.json()["problems"]
    assert p["loc"] == ["scenes", 0, "objects", 1, "fnt_size"]
    assert p["scene_id"] == "intro"
    assert p["item_id"] == "eq"
    assert "did you mean 'font_size'" in p["message"]
    assert scene_file.read_bytes() == before
    assert client.get("/api/document").json()["revision"] == 1


def test_two_tabs_saving_from_the_same_revision_conflict(client, sample):
    tab_a = client.get("/api/document").json()
    tab_b = client.get("/api/document").json()
    a_doc = copy.deepcopy(tab_a["document"])
    a_doc["title"] = "From A"
    assert client.put("/api/document", json={"document": a_doc, "base_revision": tab_a["revision"]}).status_code == 200

    b_doc = copy.deepcopy(tab_b["document"])
    b_doc["title"] = "From B"
    r = client.put("/api/document", json={"document": b_doc, "base_revision": tab_b["revision"]})
    assert r.status_code == 409
    assert r.json()["revision"] == 2
    assert r.json()["document"]["title"] == "From A"
    assert r.json()["problems"] == []

    r = client.put("/api/document", json={"document": b_doc, "base_revision": 2})
    assert r.status_code == 200
    assert r.json()["revision"] == 3


def test_an_edit_on_disk_is_noticed(client, scene_file, sample):
    assert client.get("/api/document").json()["revision"] == 1
    sample["title"] = "Edited in a text editor"
    scene_file.write_text(yaml.safe_dump(sample), encoding="utf-8")
    body = client.get("/api/document").json()
    assert body["revision"] == 2
    assert body["document"]["title"] == "Edited in a text editor"
    assert client.get("/api/document").json()["revision"] == 2, "no change, no new revision"


def test_saving_over_an_edit_on_disk_conflicts(client, scene_file, sample):
    client.get("/api/document")
    on_disk = copy.deepcopy(sample)
    on_disk["title"] = "On disk"
    scene_file.write_text(yaml.safe_dump(on_disk), encoding="utf-8")
    sample["title"] = "In the browser"
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 409
    assert r.json()["document"]["title"] == "On disk"
    assert r.json()["revision"] == 2
    assert "On disk" in scene_file.read_text(encoding="utf-8")


def test_a_file_broken_on_disk_can_be_saved_over(client, scene_file, sample):
    scene_file.write_text("scenes: [unclosed\n", encoding="utf-8")
    body = client.get("/api/document").json()
    assert body["document"] is None
    assert body["revision"] == 2
    assert "isn't valid YAML" in body["problems"][0]["message"]
    r = client.put("/api/document", json={"document": sample, "base_revision": 2})
    assert r.status_code == 200
    assert r.json()["revision"] == 3
    assert load_text(scene_file.read_text(encoding="utf-8"))[1] == []


def test_a_file_which_is_not_utf8(make_client, tmp_path):
    path = tmp_path / "latin.yaml"
    path.write_bytes(b"title: caf\xe9\nscenes: [{id: a}]\n")
    body = make_client(path).get("/api/document").json()
    assert body["document"] is None
    assert "UTF-8" in body["problems"][0]["message"]


def test_a_missing_file_is_created_by_the_first_save(make_client, tmp_path, sample):
    path = tmp_path / "new.json"
    client = make_client(path)
    body = client.get("/api/document").json()
    assert body["document"] is None
    assert body["revision"] == 1
    assert "doesn't exist yet" in body["problems"][0]["message"]
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 200
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Sample"


def test_saving_the_same_document_writes_nothing(client, scene_file):
    scene_file.write_text("# my notes\n" + scene_file.read_text(encoding="utf-8"), encoding="utf-8")
    before = scene_file.read_bytes()
    current = client.get("/api/document").json()
    r = client.put("/api/document", json={"document": current["document"], "base_revision": current["revision"]})
    assert r.status_code == 200
    assert r.json()["revision"] == current["revision"]
    assert scene_file.read_bytes() == before


@pytest.mark.parametrize("broken", ["replace", "fsync"])
def test_a_failed_save_leaves_the_file_whole(client, scene_file, sample, monkeypatch, broken):
    before = scene_file.read_bytes()

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(documents.os, broken, fail)
    sample["title"] = "Never written"
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 500
    [p] = r.json()["problems"]
    assert p["message"].startswith("Couldn't save lesson.yaml: No space left on device")
    assert scene_file.read_bytes() == before
    assert sorted(f.name for f in scene_file.parent.iterdir()) == ["lesson.yaml"], "no temporary file left"

    monkeypatch.undo()
    assert client.get("/api/document").json()["revision"] == 1
    assert client.put("/api/document", json={"document": sample, "base_revision": 1}).status_code == 200
    assert "Never written" in scene_file.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_saving_keeps_the_file_permissions(client, scene_file, sample):
    scene_file.chmod(0o640)
    sample["title"] = "Private"
    assert client.put("/api/document", json={"document": sample, "base_revision": 1}).status_code == 200
    assert stat.S_IMODE(os.stat(scene_file).st_mode) == 0o640


@pytest.mark.parametrize("content, content_type, message, loc", [
    (b'{"document": ', "application/json", "The request isn't valid JSON", []),
    (b'[1, 2]', "application/json", "The request has to be a JSON object", []),
    (b'{"document": {"scenes": []}}', "application/json", "The request needs 'base_revision'", ["base_revision"]),
    (b'{"document": [], "base_revision": 1}', "application/json", "'document' has to be a JSON object", ["document"]),
    (b'{"document": {}, "base_revision": "1"}', "application/json", "'base_revision' has to be a whole number",
     ["base_revision"]),
    (b'{"document": {}, "base_revision": 1.5}', "application/json", "'base_revision' has to be a whole number",
     ["base_revision"]),
    (b'{"document": {}, "base_revision": 1}', "text/plain", "The request has to be a JSON object", []),
])
def test_malformed_saves(client, scene_file, content, content_type, message, loc):
    before = scene_file.read_bytes()
    r = client.put("/api/document", content=content, headers={"content-type": content_type})
    assert r.status_code == 422, r.text
    problems = r.json()["problems"]
    assert any(p["message"] == message and p["loc"] == loc for p in problems), problems
    assert scene_file.read_bytes() == before


def test_documents_over_the_size_limits_are_refused(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(max_scenes=2, max_objects=3, max_steps=5))
    too_many_scenes = copy.deepcopy(sample)
    too_many_scenes["scenes"].append({"id": "third"})
    r = client.put("/api/document", json={"document": too_many_scenes, "base_revision": 1})
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == ["scenes"]
    assert "at most 2" in r.json()["problems"][0]["message"]

    sample["scenes"][0]["objects"].append({"id": "d", "type": "dot", "point": [0, 0]})
    sample["scenes"][1]["steps"].append({"do": "together", "steps": [
        {"do": "show", "target": "sq"}, {"do": "hide", "target": "sq"}]})
    sample["scenes"][1]["steps"] += [{"do": "wait"}, {"do": "wait"}]
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 422
    problems = r.json()["problems"]
    assert [p["loc"] for p in problems] == [["scenes", 0, "objects"], ["scenes", 1, "steps"]]
    assert problems[0]["scene_id"] == "intro"
    assert "6 steps" in problems[1]["message"], "steps inside together count"

    r = client.post("/api/validate", json={"document": sample})
    assert r.status_code == 200
    assert len(r.json()["problems"]) == 2


def test_bodies_over_the_size_limit_are_refused(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(max_body_bytes=2000))
    sample["title"] = "x" * 3000
    r = client.put("/api/document", json={"document": sample, "base_revision": 1})
    assert r.status_code == 413
    assert "at most" in r.json()["problems"][0]["message"]

    def chunks():
        payload = json.dumps({"document": sample, "base_revision": 1}).encode()
        for i in range(0, len(payload), 500):
            yield payload[i:i + 500]

    r = client.put("/api/document", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413, "a body without a Content-Length is counted as it arrives"
    assert "Sample" in scene_file.read_text(encoding="utf-8")


def test_validate(client, sample):
    assert client.post("/api/validate", json={"document": sample}).json() == {"problems": []}

    sample["scenes"][0]["steps"][2]["part"] = "d^2"
    [p] = client.post("/api/validate", json={"document": sample}).json()["problems"]
    assert p["loc"] == ["scenes", 0, "steps", 2, "part"]
    assert p["item_id"] == "intro_3"
    assert p["scene_id"] == "intro"

    sample["scenes"][0]["objects"][0]["type"] = "txt"
    r = client.post("/api/validate", json={"document": sample})
    assert r.status_code == 200, "validate always answers with the problems"
    [p] = r.json()["problems"]
    assert "did you mean 'text'" in p["message"]
    assert p["item_id"] == "hello"

    assert client.post("/api/validate", json={"doc": sample}).status_code == 422
    assert client.post("/api/validate", json={"document": {"scenes": "none"}}).json()["problems"][0]["loc"] == ["scenes"]


def test_the_document_round_trips_through_the_editor(client, sample):
    """What GET gives back, saved unchanged, is what was there: canonical form is stable."""
    first = client.get("/api/document").json()
    assert first["document"] == to_data(load_text(json.dumps(sample), "json")[0])
    second = client.put("/api/document", json={"document": first["document"], "base_revision": 1}).json()
    assert second["document"] == first["document"]
