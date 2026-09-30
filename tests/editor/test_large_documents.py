"""
The server with a document the size of a real ten minute video: loading, validating and saving
it stay well under a second, since the editor does all three on every edit.

Timings are the best of a few tries, so that a busy machine doesn't fail them by chance.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
import yaml

from large_document import large_document

ROOT = Path(__file__).resolve().parents[2]
EOLA = ROOT / "examples" / "eola_vectors" / "vectors.yaml"


def best_of(tries: int, action) -> float:
    best = float("inf")
    for _ in range(tries):
        started = time.perf_counter()
        action()
        best = min(best, time.perf_counter() - started)
    return best


def check_quick(client, scene_id: str) -> None:
    body = client.get("/api/document").json()
    assert body["document"] is not None, body["problems"]
    assert not [p for p in body["problems"] if p["severity"] == "error"], body["problems"][:5]
    document = body["document"]
    state = {"revision": body["revision"]}

    def get():
        assert client.get("/api/document").status_code == 200

    def validate_and_save():
        assert client.post("/api/validate", json={"document": document}).status_code == 200
        document["title"] = document.get("title", "") + "."
        r = client.put("/api/document", json={"document": document, "base_revision": state["revision"]})
        assert r.status_code == 200, r.text
        state["revision"] = r.json()["revision"]

    def still():
        r = client.post("/api/still", json={"document": document, "scene_id": scene_id, "step_index": 5})
        assert r.status_code == 200, r.text

    assert best_of(3, get) < 0.5
    assert best_of(3, validate_and_save) < 1.0
    still()
    assert best_of(3, still) < 0.5, "a still from the cache, with the document checked first"


def test_a_long_video_stays_quick(make_client, tmp_path):
    doc = large_document()
    assert sum(len(scene["steps"]) for scene in doc["scenes"]) > 240
    path = tmp_path / "long.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    check_quick(make_client(path), "s3")


def test_the_eola_example_stays_quick(make_client, tmp_path):
    if not EOLA.exists():
        pytest.skip(f"{EOLA.relative_to(ROOT)} isn't in this checkout")
    path = tmp_path / "vectors.yaml"
    shutil.copy(EOLA, path)
    for extra in EOLA.parent.iterdir():
        if extra.is_file() and extra != EOLA:
            shutil.copy(extra, tmp_path / extra.name)
    client = make_client(path)
    scene_id = client.get("/api/document").json()["document"]["scenes"][0]["id"]
    check_quick(client, scene_id)
