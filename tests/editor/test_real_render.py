"""
The server with the real renderer behind it: a still comes back as a PNG with boxes where its
objects are, and an export as an MP4. These need manim's renderer working (software Vulkan is
enough) and take a while, so they are marked `render`; run them alone with `-m render`.

Until scenefile/render.py and codegen.py are implemented these skip themselves, so that they
start counting as soon as the renderer lands.
"""
from __future__ import annotations

import io
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from manim_verbose.editor.server import create_app
from manim_verbose.scenefile import render

pytestmark = pytest.mark.render

DOC = {
    "version": 1,
    "title": "Real render",
    "scenes": [{
        "id": "intro",
        "objects": [
            {"id": "c", "type": "circle", "radius": 1, "color": "BLUE", "fill": "BLUE"},
            {"id": "s", "type": "square", "side": 1.5, "color": "YELLOW", "place": [3, 0]},
        ],
        "steps": [
            {"id": "intro_1", "do": "show", "target": "c", "run_time": 0.5},
            {"id": "intro_2", "do": "show", "target": "s", "run_time": 0.5},
        ],
    }],
}


def skip_unless_implemented(*names: str) -> None:
    for name in names:
        if not callable(getattr(render, name, None)):
            pytest.skip(f"scenefile/render.py has no {name} yet")


def skip_if_not_implemented(problems: list[dict]) -> None:
    if any("NotImplementedError" in p["message"] for p in problems):
        pytest.skip("the renderer isn't implemented yet: " + problems[0]["message"])


@pytest.fixture
def real_client(request, tmp_path):
    """An app with the real renderer; tests say which parts of render.py they need with @needs."""
    skip_unless_implemented(*request.node.get_closest_marker("needs").args)
    path = tmp_path / "real.yaml"
    path.write_text(yaml.safe_dump(DOC, sort_keys=False), encoding="utf-8")
    app = create_app(path, output_dir=tmp_path / "out", static_dir=tmp_path / "no-static")
    with TestClient(app) as client:
        yield client


@pytest.mark.needs("render_still")
def test_a_real_still_has_boxes_where_its_objects_are(real_client):
    r = real_client.post("/api/still", json={"document": DOC, "scene_id": "intro", "step_index": 1, "width": 480})
    if r.status_code == 500:
        skip_if_not_implemented(r.json()["problems"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["width"], body["height"]) == (480, 270)

    from PIL import Image
    image = Image.open(io.BytesIO(real_client.get(body["image_url"]).content))
    assert image.format == "PNG" and image.size == (480, 270)
    assert max(high for _, high in image.convert("RGB").getextrema()) > 0, "the frame isn't blank"

    boxes = {obj["id"]: obj for obj in body["objects"]}
    assert {"c", "s"} <= set(boxes)
    for obj in boxes.values():
        x0, y0, x1, y1 = obj["bbox"]
        assert 0 <= x0 < x1 <= 480 and 0 <= y0 < y1 <= 270, obj
        xmin, ymin, xmax, ymax = obj["frame_bbox"]
        assert xmin < xmax and ymin < ymax
    assert boxes["c"]["bbox"][2] < boxes["s"]["bbox"][0], "the circle is left of the square"
    assert boxes["c"]["frame_bbox"] == pytest.approx([-1, -1, 1, 1], abs=0.15)

    before = real_client.post("/api/still", json={"document": DOC, "scene_id": "intro", "step_index": -1,
                                                  "width": 480}).json()
    assert before["objects"] == []


@pytest.mark.needs("render_clip")
def test_a_real_clip(real_client):
    r = real_client.post("/api/clip", json={"document": DOC, "scene_id": "intro"})
    if r.status_code == 500:
        skip_if_not_implemented(r.json()["problems"])
    assert r.status_code == 200, r.text
    video = real_client.get(r.json()["video_url"]).content
    assert video[4:8] == b"ftyp" and len(video) > 1000


@pytest.mark.needs("render_video")
def test_a_real_export_makes_an_mp4(real_client):
    job_id = real_client.post("/api/export", json={"document": DOC, "quality": "low"}).json()["job_id"]
    deadline = time.monotonic() + 600
    while True:
        state = real_client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "failed", "cancelled"):
            break
        assert time.monotonic() < deadline, state
        time.sleep(0.25)
    if state["status"] == "failed":
        skip_if_not_implemented(state["problems"])
    assert state["status"] == "done", state
    video = real_client.get(state["output_url"]).content
    assert video[4:8] == b"ftyp" and len(video) > 1000


@pytest.mark.needs("timeline", "scene_duration")
def test_real_timeline_and_code(real_client):
    from manim_verbose.scenefile.codegen import document_to_python
    from manim_verbose.scenefile.files import load_file
    doc, _ = load_file(real_client.app.state.editor.store.path)
    try:
        document_to_python(doc)
    except NotImplementedError:
        pytest.skip("codegen isn't implemented yet")
    timeline = real_client.get("/api/timeline", params={"scene_id": "intro"}).json()
    assert [s["step_id"] for s in timeline["steps"]] == ["intro_1", "intro_2"]
    assert timeline["duration"] == pytest.approx(1.0, abs=0.1)
    code = real_client.post("/api/code", json={"document": DOC}).json()["code"]
    assert "from manimlib import" in code and "class Intro" in code
