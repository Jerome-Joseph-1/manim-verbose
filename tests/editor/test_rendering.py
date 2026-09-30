"""
Stills, clips, code and timings through the server, with the fake backend: good and bad
requests, problems landing on the right field, caching, superseding of stale stills, and the
server staying up and answering whatever the renderer does.
"""
from __future__ import annotations

import copy
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from manim_verbose.editor.limits import Limits


def still(client, doc, scene_id="intro", step_index=1, **extra):
    return client.post("/api/still", json={"document": doc, "scene_id": scene_id, "step_index": step_index, **extra})


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def wait_until(condition, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    raise AssertionError("timed out waiting")


@pytest.fixture
def pool():
    with ThreadPoolExecutor(max_workers=4) as executor:
        yield executor


# Stills

def test_a_still(client, sample):
    r = still(client, sample, step_index=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["width"], body["height"]) == (960, 540)
    assert body["image_url"].startswith("/files/stills/") and body["image_url"].endswith(".png")
    assert [o["id"] for o in body["objects"]] == ["hello", "eq"], "drawing order"
    for obj in body["objects"]:
        assert len(obj["bbox"]) == 4 and len(obj["frame_bbox"]) == 4
        assert all(isinstance(v, float) for v in obj["bbox"] + obj["frame_bbox"])
    assert body["problems"] == []
    image = client.get(body["image_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert png_size(image.content) == (960, 540)


def test_a_still_before_the_first_step_and_at_other_sizes(client, sample):
    body = still(client, sample, step_index=-1).json()
    assert body["objects"] == []
    sample["settings"] = {"resolution": [1000, 1000]}
    body = still(client, sample, step_index=0, width=300).json()
    assert (body["width"], body["height"]) == (300, 300)
    assert png_size(client.get(body["image_url"]).content) == (300, 300)


def test_a_still_carries_the_documents_warnings(client, sample):
    sample["scenes"][0]["steps"].append({"do": "show", "target": "hello"})
    body = still(client, sample, step_index=0).json()
    [warning] = body["problems"]
    assert warning["severity"] == "warning"
    assert warning["item_id"] == "intro_5"


def test_stills_are_cached_by_what_decides_them(client, sample, backend):
    assert still(client, sample, step_index=1).status_code == 200
    assert still(client, sample, step_index=1).json()["image_url"] == still(client, sample, step_index=1).json()["image_url"]
    assert len(backend.calls("still")) == 1

    later = copy.deepcopy(sample)
    later["scenes"][0]["steps"][3]["duration"] = 5
    later["scenes"][1]["objects"][0]["side"] = 3
    assert still(client, later, step_index=1).status_code == 200
    assert len(backend.calls("still")) == 1, "later steps and other scenes don't change this frame"

    reordered = copy.deepcopy(sample)
    reordered["scenes"][0]["objects"][0]["font_size"] = 48
    assert still(client, reordered, step_index=1).status_code == 200
    assert len(backend.calls("still")) == 1, "a default written out is the same document"

    for change in (
        lambda d: d["scenes"][0]["steps"][0].update(caption="New"),
        lambda d: d["scenes"][0]["objects"][2].update(color="RED"),
        lambda d: d.update(settings={"background": "#123456"}),
    ):
        changed = copy.deepcopy(sample)
        change(changed)
        assert still(client, changed, step_index=1).status_code == 200
    assert len(backend.calls("still")) == 4
    assert still(client, sample, step_index=2).status_code == 200
    assert still(client, sample, step_index=1, width=480).status_code == 200
    assert len(backend.calls("still")) == 6


def test_the_still_cache_outlives_the_server(make_client, scene_file, sample, backend):
    first = still(make_client(scene_file), sample).json()
    second = still(make_client(scene_file), sample).json()
    assert second == first
    assert len(backend.calls("still")) == 1


def test_replacing_a_picture_on_disk_makes_its_stills_stale(client, scene_file, sample, backend):
    picture = scene_file.parent / "pic.png"
    picture.write_bytes(b"one")
    sample["scenes"][0]["objects"].append({"id": "pic", "type": "image", "path": "pic.png"})
    still(client, sample)
    still(client, sample)
    assert len(backend.calls("still")) == 1
    picture.write_bytes(b"a different picture")
    still(client, sample)
    assert len(backend.calls("still")) == 2


@pytest.mark.parametrize("change, loc, message", [
    ({"scene_id": "intr"}, ["scene_id"], "There's no scene called 'intr' (did you mean 'intro'?). Scenes are: intro, second"),
    ({"step_index": 4}, ["step_index"], "Scene 'intro' has 4 steps, so step_index can be from -1 to 3"),
    ({"step_index": -2}, ["step_index"], "Scene 'intro' has 4 steps, so step_index can be from -1 to 3"),
    ({"step_index": "1"}, ["step_index"], "'step_index' has to be a whole number"),
    ({"step_index": True}, ["step_index"], "'step_index' has to be a whole number"),
    ({"width": 10}, ["width"], "width has to be between 64 and 3840 pixels"),
    ({"width": 100000}, ["width"], "width has to be between 64 and 3840 pixels"),
    ({"scene_id": 3}, ["scene_id"], "'scene_id' has to be text"),
    ({"scene_id": None}, ["scene_id"], "'scene_id' has to be text"),
    ({"document": None}, ["document"], "'document' has to be a JSON object"),
])
def test_bad_still_requests(client, sample, backend, change, loc, message):
    body = {"document": sample, "scene_id": "intro", "step_index": 1, **change}
    r = client.post("/api/still", json=body)
    assert r.status_code == 422, r.text
    assert {"message": message, "loc": loc} in [{"message": p["message"], "loc": p["loc"]} for p in r.json()["problems"]]
    assert backend.calls() == []


def test_a_still_request_missing_things(client, sample):
    r = client.post("/api/still", json={"document": sample})
    assert r.status_code == 422
    assert r.json()["problems"][0]["message"] == "The request needs 'scene_id'"
    r = client.post("/api/still", content=b"{", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["problems"][0]["message"] == "The request isn't valid JSON"


def test_a_still_of_a_scene_with_errors_is_refused_with_its_problems(client, sample, backend):
    sample["scenes"][0]["steps"][1]["target"] = "eqq"
    r = still(client, sample)
    assert r.status_code == 422
    error = next(p for p in r.json()["problems"] if p["severity"] == "error")
    assert error["loc"] == ["scenes", 0, "steps", 1, "target"]
    assert error["scene_id"] == "intro"
    assert error["item_id"] == "intro_2"
    assert backend.calls() == []


def test_a_still_of_an_unreadable_document_is_refused(client, sample):
    sample["scenes"][1]["objects"][0]["sidee"] = 2
    r = still(client, sample)
    assert r.status_code == 422
    [p] = r.json()["problems"]
    assert (p["loc"], p["scene_id"], p["item_id"]) == (["scenes", 1, "objects", 0, "sidee"], "second", "sq")


def test_errors_in_another_scene_dont_stop_a_still(client, sample):
    sample["scenes"][1]["steps"][0]["target"] = "nothing"
    r = still(client, sample, scene_id="intro")
    assert r.status_code == 200
    assert [p["scene_id"] for p in r.json()["problems"]] == ["second"]
    assert still(client, sample, scene_id="second", step_index=0).status_code == 422


def test_a_render_error_lands_on_its_field(client, sample, backend):
    sample["scenes"][0]["title"] = "fail"
    for _ in range(2):
        r = still(client, sample)
        assert r.status_code == 422
        [p] = r.json()["problems"]
        assert p["message"] == "LaTeX couldn't make sense of this formula"
        assert (p["loc"], p["scene_id"], p["item_id"]) == (["scenes", 0, "objects", 0, "tex"], "intro", "hello")
    assert len(backend.calls("still")) == 2, "failures aren't cached"


def test_an_unexpected_render_failure_is_a_500_with_problems(make_client, scene_file, sample):
    client = make_client(scene_file, raise_server_exceptions=False)
    sample["scenes"][0]["title"] = "boom"
    r = still(client, sample)
    assert r.status_code == 500
    [p] = r.json()["problems"]
    assert p["message"] == "Something went wrong while drawing this frame: ValueError: the fake renderer fell over"
    assert p["scene_id"] == "intro" and p["loc"] == ["scenes", 0]
    assert "Traceback" not in r.text
    sample["scenes"][0]["title"] = None
    assert still(client, sample).status_code == 200


def test_a_crashed_renderer_is_replaced(client, sample):
    editor = client.app.state.editor
    assert still(client, sample, step_index=0).status_code == 200
    first_pid = editor.stills.worker.pid
    crashing = copy.deepcopy(sample)
    crashing["scenes"][0]["title"] = "crash"
    r = still(client, crashing)
    assert r.status_code == 500
    assert "stopped unexpectedly" in r.json()["problems"][0]["message"]
    assert still(client, sample, step_index=1).status_code == 200
    assert editor.stills.worker.pid != first_pid


def test_a_still_past_its_time_limit_is_stopped_and_the_server_keeps_answering(make_client, scene_file, sample, pool):
    client = make_client(scene_file, Limits(still_timeout=3))
    hanging = copy.deepcopy(sample)
    hanging["scenes"][0]["title"] = "hang"
    started = time.monotonic()
    pending = pool.submit(still, client, hanging)
    wait_until(lambda: client.app.state.editor.stills.running is not None)
    for _ in range(3):
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/document").status_code == 200
        assert client.post("/api/validate", json={"document": sample}).status_code == 200
    assert not pending.done(), "those were answered while the render hung"
    r = pending.result(timeout=20)
    assert time.monotonic() - started < 15
    assert r.status_code == 422
    [p] = r.json()["problems"]
    assert p["message"].startswith("Drawing this frame took longer than 3 seconds")
    assert (p["loc"], p["scene_id"]) == (["scenes", 0], "intro")
    assert still(client, sample).status_code == 200


def gated(sample):
    """The document, drawn only once the test calls open_gate."""
    doc = copy.deepcopy(sample)
    doc["scenes"][0]["title"] = "gate:gate"
    return doc


def open_gate(backend):
    (Path(backend.folder) / "gate").touch()


def test_a_waiting_still_is_superseded_by_a_newer_one(client, sample, backend, pool):
    stills = client.app.state.editor.stills
    doc = gated(sample)
    first = pool.submit(still, client, doc, step_index=0)
    wait_until(lambda: stills.running is not None)
    second = pool.submit(still, client, doc, step_index=1)
    wait_until(lambda: stills.waiting is not None)
    third = pool.submit(still, client, doc, step_index=2)

    r = second.result(timeout=10)
    assert r.status_code == 409
    assert r.json() == {"superseded": True}
    assert not first.done() and not third.done()

    open_gate(backend)
    assert first.result(timeout=10).status_code == 200
    assert third.result(timeout=10).status_code == 200
    assert [call[2] for call in backend.calls("still")] == [0, 2], "the superseded still was never drawn"


def test_a_still_from_the_cache_supersedes_a_waiting_one(client, sample, backend, pool):
    stills = client.app.state.editor.stills
    assert still(client, sample, step_index=3).status_code == 200
    doc = gated(sample)
    first = pool.submit(still, client, doc, step_index=0)
    wait_until(lambda: stills.running is not None)
    waiting = pool.submit(still, client, doc, step_index=1)
    wait_until(lambda: stills.waiting is not None)
    assert still(client, sample, step_index=3).status_code == 200
    assert waiting.result(timeout=10).status_code == 409
    open_gate(backend)
    assert first.result(timeout=10).status_code == 200


def test_a_request_for_the_still_being_drawn_shares_it(client, sample, backend, pool):
    stills = client.app.state.editor.stills
    doc = gated(sample)
    first = pool.submit(still, client, doc, step_index=0)
    wait_until(lambda: stills.running is not None)
    same = pool.submit(still, client, doc, step_index=0)
    time.sleep(0.2)
    assert stills.waiting is None
    open_gate(backend)
    assert first.result(timeout=10).json()["image_url"] == same.result(timeout=10).json()["image_url"]
    assert len(backend.calls("still")) == 1


def test_many_stills_at_once_all_get_an_answer(client, sample, backend, pool):
    results = list(pool.map(lambda i: still(client, sample, step_index=i % 4 - 1), range(12)))
    assert {r.status_code for r in results} <= {200, 409}
    assert results[-1].status_code in (200, 409)
    assert any(r.status_code == 200 for r in results)
    for r in results:
        if r.status_code == 200:
            assert client.get(r.json()["image_url"]).status_code == 200


# Clips

def clip(client, doc, scene_id="intro", **extra):
    return client.post("/api/clip", json={"document": doc, "scene_id": scene_id, **extra})


def test_a_clip(client, sample, backend):
    r = clip(client, sample, start_step=1, end_step=2)
    assert r.status_code == 200, r.text
    url = r.json()["video_url"]
    assert url.startswith("/files/clips/") and url.endswith(".mp4")
    video = client.get(url)
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert video.content[4:8] == b"ftyp"
    assert backend.calls("clip") == [["clip", "intro", 1, 2]]


def test_clips_are_cached(client, sample, backend):
    assert clip(client, sample).json() == clip(client, sample).json()
    assert clip(client, sample, start_step=0, end_step=3).json() == clip(client, sample).json(), \
        "end_step left out is the last step"
    assert len(backend.calls("clip")) == 1
    clip(client, sample, start_step=2)
    assert len(backend.calls("clip")) == 2


def test_the_same_clip_asked_for_twice_at_once_is_made_once(client, sample, backend, pool):
    doc = gated(sample)
    first = pool.submit(clip, client, doc)
    second = pool.submit(clip, client, doc)
    wait_until(lambda: len(backend.calls("clip")) == 1)
    open_gate(backend)
    assert first.result(timeout=10).json() == second.result(timeout=10).json()
    assert len(backend.calls("clip")) == 1


@pytest.mark.parametrize("change, loc, message", [
    ({"start_step": 4}, ["start_step"], "Scene 'intro' has 4 steps, so start_step can be from 0 to 3"),
    ({"start_step": -1}, ["start_step"], "Scene 'intro' has 4 steps, so start_step can be from 0 to 3"),
    ({"start_step": 2, "end_step": 1}, ["end_step"], "end_step has to be from start_step (2) to 3"),
    ({"end_step": 9}, ["end_step"], "end_step has to be from start_step (0) to 3"),
    ({"scene_id": "nope"}, ["scene_id"], "There's no scene called 'nope'. Scenes are: intro, second"),
    ({"end_step": "2"}, ["end_step"], "'end_step' has to be a whole number"),
])
def test_bad_clip_requests(client, sample, backend, change, loc, message):
    r = client.post("/api/clip", json={"document": sample, "scene_id": "intro", **change})
    assert r.status_code == 422, r.text
    assert [(p["loc"], p["message"]) for p in r.json()["problems"]] == [(loc, message)]
    assert backend.calls() == []


def test_a_clip_of_a_scene_without_steps(client, sample):
    sample["scenes"][1]["steps"] = []
    r = clip(client, sample, scene_id="second")
    assert r.status_code == 422
    assert r.json()["problems"][0]["message"] == "Scene 'second' has no steps to play yet"


def test_a_clip_past_its_time_limit(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(clip_timeout=1))
    hanging = copy.deepcopy(sample)
    hanging["scenes"][0]["title"] = "hang"
    r = clip(client, hanging)
    assert r.status_code == 422
    assert r.json()["problems"][0]["message"].startswith("Drawing this clip took longer than 1 seconds")
    assert clip(client, sample).status_code == 200


def test_a_clip_with_a_render_error(client, sample):
    sample["scenes"][0]["title"] = "fail"
    r = clip(client, sample)
    assert r.status_code == 422
    assert r.json()["problems"][0]["item_id"] == "hello"


def test_stills_and_clips_dont_wait_for_an_export(client, sample, backend):
    exporting = gated(sample)
    job = client.post("/api/export", json={"document": exporting}).json()["job_id"]
    wait_until(lambda: client.get(f"/api/jobs/{job}").json()["status"] == "running")
    assert still(client, sample).status_code == 200
    assert clip(client, sample).status_code == 200
    assert client.get(f"/api/jobs/{job}").json()["status"] == "running"
    open_gate(backend)
    wait_until(lambda: client.get(f"/api/jobs/{job}").json()["status"] == "done")


# Code

def test_code(client, sample):
    r = client.post("/api/code", json={"document": sample})
    assert r.status_code == 200
    assert "class Intro" in r.json()["code"] and "class Second" in r.json()["code"]
    code = client.post("/api/code", json={"document": sample, "scene_id": "second"}).json()["code"]
    assert "class Second" in code and "class Intro" not in code


def test_bad_code_requests(make_client, scene_file, sample):
    client = make_client(scene_file, raise_server_exceptions=False)
    assert client.post("/api/code", json={"document": sample, "scene_id": "x"}).status_code == 422
    broken = copy.deepcopy(sample)
    broken["scenes"][1]["steps"][0]["target"] = "nothing"
    r = client.post("/api/code", json={"document": broken})
    assert r.status_code == 422
    assert r.json()["problems"][0]["item_id"] == "second_1"
    assert client.post("/api/code", json={"document": broken, "scene_id": "intro"}).status_code == 200
    sample["scenes"][0]["title"] = "boom"
    r = client.post("/api/code", json={"document": sample})
    assert r.status_code == 500
    assert "Traceback" not in r.text and r.json()["problems"][0]["message"].startswith("Something went wrong")


# Timeline

def test_timeline_of_the_saved_document(client, sample):
    r = client.get("/api/timeline", params={"scene_id": "intro"})
    assert r.status_code == 200
    assert r.json() == {
        "steps": [
            {"step_id": "intro_1", "index": 0, "start": 0.0, "duration": 1.0},
            {"step_id": "intro_2", "index": 1, "start": 1.0, "duration": 1.0},
            {"step_id": "intro_3", "index": 2, "start": 2.0, "duration": 1.0},
            {"step_id": "intro_4", "index": 3, "start": 3.0, "duration": 2.0},
        ],
        "duration": 5.0,
        "revision": 1,
    }
    sample["scenes"][0]["steps"][0]["run_time"] = 3
    client.put("/api/document", json={"document": sample, "base_revision": 1})
    body = client.get("/api/timeline", params={"scene_id": "intro"}).json()
    assert body["duration"] == 7.0 and body["revision"] == 2


def test_bad_timeline_requests(make_client, scene_file, sample):
    client = make_client(scene_file, raise_server_exceptions=False)
    r = client.get("/api/timeline")
    assert r.status_code == 422
    assert r.json()["problems"][0] == {"message": "The request needs 'scene_id'", "loc": ["scene_id"],
                                       "severity": "error", "scene_id": None, "item_id": None, "path": "scene_id"}
    assert client.get("/api/timeline", params={"scene_id": "outro"}).status_code == 422

    sample["scenes"][0]["title"] = "boom"
    client.put("/api/document", json={"document": sample, "base_revision": 1})
    r = client.get("/api/timeline", params={"scene_id": "intro"})
    assert r.status_code == 500
    assert r.json()["problems"][0]["scene_id"] == "intro"

    scene_file.write_text("scenes: [", encoding="utf-8")
    r = client.get("/api/timeline", params={"scene_id": "intro"})
    assert r.status_code == 422
    assert "isn't valid YAML" in r.json()["problems"][0]["message"]
