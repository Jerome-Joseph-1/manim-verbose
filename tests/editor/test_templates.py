"""
Templates: every scene file in the templates folder is offered by name, with its title,
description and thumbnail; one can be read in full, or saved in place of the document, as a
normal save with a revision (so a stale editor gets a 409, not a lost file).
"""
from __future__ import annotations

import os
import time

import pytest
import yaml

from manim_verbose.editor.templates import TEMPLATES_DIR, Templates
from manim_verbose.scenefile.files import load_file

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def write(folder, name, doc):
    (folder / name).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    write(folder, "equation.yaml", {
        "title": "An equation", "description": "A formula, built up step by step.",
        "scenes": [{"id": "main", "objects": [{"id": "eq", "type": "tex", "tex": "e^{i\\pi} = -1"}],
                    "steps": [{"do": "show", "target": "eq"}]}],
    })
    write(folder, "blank.yaml", {"title": "Blank", "scenes": [{"id": "scene_1"}]})
    (folder / "equation.png").write_bytes(PNG)
    (folder / "broken.yaml").write_text("scenes: [\n  - {id: 1", encoding="utf-8")
    write(folder, "not a name.yaml", {"title": "Bad name", "scenes": [{"id": "s"}]})
    (folder / "notes.txt").write_text("not a template", encoding="utf-8")
    (folder / "orphan.png").write_bytes(PNG)
    return folder


@pytest.fixture
def tclient(make_client, scene_file, folder):
    return make_client(scene_file, templates_dir=folder)


def test_the_list(tclient):
    r = tclient.get("/api/templates")
    assert r.status_code == 200
    assert r.json() == {"templates": [
        {"name": "blank", "title": "Blank", "description": None, "thumbnail_url": None},
        {"name": "equation", "title": "An equation", "description": "A formula, built up step by step.",
         "thumbnail_url": "/api/templates/equation/thumbnail.png"},
    ]}


def test_one_template_in_full(tclient):
    body = tclient.get("/api/templates/equation").json()
    assert body["title"] == "An equation"
    assert body["problems"] == []
    doc = body["document"]
    assert doc["scenes"][0]["objects"][0]["tex"] == "e^{i\\pi} = -1"
    assert doc["scenes"][0]["steps"][0]["id"], "steps come with ids, as documents from the server do"


def test_the_thumbnail(tclient):
    r = tclient.get("/api/templates/equation/thumbnail.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == PNG
    assert tclient.get("/api/templates/blank/thumbnail.png").status_code == 404
    assert tclient.get("/api/templates/orphan/thumbnail.png").status_code == 404, "a picture with no template"


@pytest.mark.parametrize("name", ["missing", "broken", "not a name", "notes", "..%2Fsecret", "%2e%2e", ".hidden", "equation.yaml"])
def test_unknown_templates_are_404(tclient, name):
    r = tclient.get(f"/api/templates/{name}")
    assert r.status_code == 404
    assert r.json()["problems"][0]["message"]


def test_traversal_reaches_nothing(tclient, tmp_path):
    (tmp_path / "secret.yaml").write_text(yaml.safe_dump({"title": "Secret", "scenes": [{"id": "s"}]}), encoding="utf-8")
    (tmp_path / "secret.png").write_bytes(PNG)
    for url in ["/api/templates/..%2Fsecret", "/api/templates/%2e%2e%2fsecret/thumbnail.png",
                "/api/templates/../secret", "/api/templates/..%5Csecret"]:
        r = tclient.get(url)
        assert r.status_code == 404, url
        assert "Secret" not in r.text


def test_applying_a_template_saves_it_as_the_document(tclient, scene_file):
    revision = tclient.get("/api/document").json()["revision"]
    r = tclient.post("/api/templates/equation/apply", json={"base_revision": revision})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == revision + 1
    assert body["document"]["title"] == "An equation"
    on_disk, problems = load_file(scene_file)
    assert on_disk.title == "An equation" and problems == []
    assert tclient.get("/api/document").json()["document"] == body["document"]


def test_applying_to_a_stale_revision_is_a_conflict(tclient, scene_file):
    revision = tclient.get("/api/document").json()["revision"]
    r = tclient.post("/api/templates/equation/apply", json={"base_revision": revision - 1})
    assert r.status_code == 409
    assert r.json()["revision"] == revision
    assert "Sample" in scene_file.read_text(encoding="utf-8")


def test_bad_apply_requests(tclient):
    revision = tclient.get("/api/document").json()["revision"]
    assert tclient.post("/api/templates/missing/apply", json={"base_revision": revision}).status_code == 404
    r = tclient.post("/api/templates/equation/apply", json={"base_revision": str(revision)})
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == ["base_revision"]
    assert tclient.post("/api/templates/equation/apply", json={}).status_code == 422


def test_templates_added_while_running_are_offered(tclient, folder):
    assert len(tclient.get("/api/templates").json()["templates"]) == 2
    write(folder, "later.yaml", {"title": "Later", "scenes": [{"id": "s"}]})
    names = [t["name"] for t in tclient.get("/api/templates").json()["templates"]]
    assert names == ["blank", "equation", "later"]
    # and a changed one is read again
    time.sleep(0.01)
    write(folder, "later.yaml", {"title": "Changed", "scenes": [{"id": "s"}]})
    os.utime(folder / "later.yaml", (time.time() + 5, time.time() + 5))
    assert tclient.get("/api/templates/later").json()["title"] == "Changed"


def test_no_templates_folder_means_an_empty_list(make_client, scene_file, tmp_path):
    client = make_client(scene_file, templates_dir=tmp_path / "nowhere")
    assert client.get("/api/templates").json() == {"templates": []}


def test_the_default_folder_is_the_packages(tmp_path):
    assert Templates().folder == TEMPLATES_DIR
    assert TEMPLATES_DIR.name == "templates" and TEMPLATES_DIR.parent.name == "manim_verbose"


@pytest.mark.parametrize("name", Templates().names() or ["(none yet)"])
def test_every_packaged_template_reads_without_errors(name):
    """The templates shipped with the editor are all readable, titled, and error free."""
    if name == "(none yet)":
        pytest.skip("no templates in manim_verbose/templates yet")
    template = Templates().get(name)
    assert template["title"] and template["title"] != "Untitled", f"{name} needs a title"
    assert template["description"], f"{name} needs a description for the gallery"
    assert [p for p in template["problems"] if p["severity"] == "error"] == []
