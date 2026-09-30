"""
What the server hands out as files: renders from its output folder and nothing else, the
built editor with a fallback to index.html for its routes, a page saying how to build the
editor when it isn't built, and answers only for requests addressed to this computer.
"""
from __future__ import annotations

import os
import sys

import pytest

from manim_verbose.editor.outputs import OutputDir
from manim_verbose.editor.server import LOCAL_HOSTS

SECRET = b"the contents of a private file"


@pytest.fixture
def planted(tmp_path, scene_file):
    """Private files next to the output folder, next to its kinds, and next to the scene file."""
    out = tmp_path / "out"
    for folder in (tmp_path, out, scene_file.parent):
        folder.mkdir(exist_ok=True)
        (folder / "secret.png").write_bytes(SECRET)
        (folder / "secret.mp4").write_bytes(SECRET)
    return out


TRAVERSALS = [
    "/files/stills/../secret.png",
    "/files/stills/..%2Fsecret.png",
    "/files/stills/%2e%2e%2fsecret.png",
    "/files/stills/%2E%2E/secret.png",
    "/files/stills/..%5Csecret.png",
    "/files/stills/..%2F..%2Fsecret.png",
    "/files/stills/..%2F..%2Fproject%2Fsecret.png",
    "/files/..%2Fsecret.png/x",
    "/files/%2e%2e/secret.png",
    "/files/./secret.png",
    "/files/secret.png",
    "/files/exports/%2e%2e%2f%2e%2e%2fsecret.mp4",
    "/files/stills/%2Fetc%2Fpasswd",
    "/files/stills/secret.png%00.png",
    "/files/stills/.partial-0.png",
    "/files/other/secret.png",
    "/files/stills/..",
    "/files/stills/.",
    "/files//secret.png",
    "/project/secret.png",
    "/../secret.png",
    "/%2e%2e/secret.png",
    "/%2e%2e%2fproject%2fsecret.png",
]


@pytest.mark.parametrize("url", TRAVERSALS)
def test_nothing_outside_the_output_folder_is_served(make_client, scene_file, planted, url):
    client = make_client(scene_file)
    r = client.get(url)
    assert SECRET not in r.content
    if url.startswith("/files"):
        assert r.status_code == 404, (url, r.status_code)
        assert "problems" in r.json()


def test_rendered_files_are_served_and_only_of_their_kind(client, sample, planted):
    url = client.post("/api/still", json={"document": sample, "scene_id": "intro"}).json()["image_url"]
    r = client.get(url)
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    name = url.rsplit("/", 1)[1]
    assert client.get(f"/files/clips/{name}").status_code == 404
    assert client.get(f"/files/exports/{name}").status_code == 404
    assert client.get(url.replace(".png", ".json")).status_code == 404, "metadata isn't served"
    assert client.get("/files/stills/0000000000000000000000000000000000000000000000000000000000000000.png").status_code == 404


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_a_link_out_of_the_output_folder_is_not_followed(make_client, scene_file, planted, tmp_path):
    client = make_client(scene_file)
    link = planted / "stills" / ("a" * 64 + ".png")
    os.symlink(tmp_path / "secret.png", link)
    r = client.get(f"/files/stills/{link.name}")
    assert r.status_code == 404
    assert SECRET not in r.content


@pytest.mark.parametrize("kind, name", [
    ("stills", "../x.png"), ("stills", "/etc/passwd"), ("stills", "a/b.png"), ("stills", "C:\\x.png"),
    ("stills", ".hidden.png"), ("stills", "x.PNG.txt"), ("stills", ""), ("stills", "x" * 300 + ".png"),
    ("..", "x.png"), ("", "x.png"), ("stills/..", "x.png"), ("exports", "..mp4"),
])
def test_output_names_which_resolve_to_nothing(tmp_path, kind, name):
    outputs = OutputDir(tmp_path / "out")
    assert outputs.resolve(kind, name) is None


def test_without_a_built_editor_the_page_says_how_to_build_it(client):
    for path in ("/", "/scenes/intro"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "cd editor-ui &amp;&amp; npm install &amp;&amp; npm run build" in r.text


@pytest.fixture
def built(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>editor</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('editor')", encoding="utf-8")
    (tmp_path / "outside.js").write_text("secret()", encoding="utf-8")
    return static


def test_the_built_editor_is_served_with_a_fallback_for_its_routes(make_client, scene_file, built):
    client = make_client(scene_file, static_dir=built)
    r = client.get("/")
    assert r.status_code == 200 and "<title>editor</title>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    r = client.get("/assets/app.js")
    assert r.status_code == 200 and "console.log" in r.text
    assert "javascript" in r.headers["content-type"]
    assert "<title>editor</title>" in client.get("/scenes/intro/steps/3").text
    assert client.get("/assets/missing.js").status_code == 404
    for url in ("/../outside.js", "/%2e%2e/outside.js", "/assets/%2e%2e/%2e%2e/outside.js", "/..%2Foutside.js"):
        assert "secret()" not in client.get(url).text, url


def test_unknown_api_paths_are_json_problems(make_client, scene_file, built):
    client = make_client(scene_file, static_dir=built)
    for url in ("/api/nothing", "/api", "/files", "/files/stills"):
        r = client.get(url)
        assert r.status_code == 404, url
        assert r.json()["problems"][0]["message"].startswith("There's nothing at")
    r = client.post("/api/health")
    assert r.status_code == 405
    assert r.json()["problems"][0]["message"] == "POST isn't something /api/health answers to"
    r = client.delete("/api/document")
    assert r.status_code == 405


@pytest.mark.parametrize("host, ok", [
    ("localhost:8765", True), ("127.0.0.1:8765", True), ("[::1]:8765", True), ("localhost", True),
    ("LOCALHOST:1", True), ("evil.example:8765", False), ("127.0.0.1.evil.example", False),
    ("localhost.evil.example:8765", False), ("", False),
])
def test_requests_must_be_addressed_to_this_computer(make_client, scene_file, host, ok):
    client = make_client(scene_file, allowed_hosts=LOCAL_HOSTS)
    r = client.get("/api/document", headers={"host": host})
    if ok:
        assert r.status_code == 200
    else:
        assert r.status_code == 400
        assert "document" not in r.json()
        assert "only answers requests addressed to the computer it runs on" in r.json()["problems"][0]["message"]
