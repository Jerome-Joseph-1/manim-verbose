"""
POST /api/layout: layout warnings for one scene, from a worker process of their own. With a fake
checker for the request handling, caching and failures, and one test with the real checker
(marked `render`, like the other tests of the real renderer, though it draws nothing).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from editor_fakes import FakeBackend
from manim_verbose.editor import layout_checks
from manim_verbose.editor.limits import Limits
from manim_verbose.editor.server import create_app
from manim_verbose.scenefile.validate import Problem


class LayoutBackend(FakeBackend):
    """The fake backend, with a layout check: an object placed right of x = 7 runs off the frame."""

    def layout(self, doc, scene_id, base_dir):
        index, scene = next((i, s) for i, s in enumerate(doc.scenes) if s.id == scene_id)
        self.record("layout", scene_id)
        self.behave(scene)
        problems = []
        for j, obj in enumerate(scene.objects):
            place = getattr(obj, "place", None)
            if place is not None and place.at is not None and place.at[0] > 7:
                problems.append(Problem(
                    f"At the start of the scene, '{obj.id}' runs off the right edge of the frame",
                    ["scenes", index, "objects", j, "place"], "warning", scene_id, obj.id,
                ))
        return problems


@pytest.fixture
def backend(tmp_path) -> LayoutBackend:
    folder = tmp_path / "backend"
    folder.mkdir()
    return LayoutBackend(folder)


def layout(client, doc, scene_id="intro", **extra):
    return client.post("/api/layout", json={"document": doc, "scene_id": scene_id, **extra})


def off_frame(sample):
    sample["scenes"][0]["objects"][0]["place"] = [7.5, 0]
    return sample


def test_layout_problems_are_warnings_on_the_objects(client, sample):
    r = layout(client, off_frame(sample))
    assert r.status_code == 200, r.text
    assert r.json() == {"problems": [{
        "message": "At the start of the scene, 'hello' runs off the right edge of the frame",
        "severity": "warning",
        "loc": ["scenes", 0, "objects", 0, "place"],
        "path": "scenes[0].objects[0].place",
        "scene_id": "intro",
        "item_id": "hello",
    }]}


def test_a_scene_with_nothing_wrong_has_no_problems(client, sample):
    assert layout(client, sample).json() == {"problems": []}


def test_the_revision_comes_back_as_sent(client, sample):
    assert layout(client, sample, revision=7).json() == {"problems": [], "revision": 7}
    r = layout(client, sample, revision="7")
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == ["revision"]


@pytest.mark.parametrize("body, loc", [
    ({"scene_id": "intro"}, ["document"]),
    ({"document": {"scenes": []}}, ["scene_id"]),
    ({"document": {"scenes": []}, "scene_id": 3}, ["scene_id"]),
])
def test_a_malformed_request_is_refused(client, body, loc):
    r = client.post("/api/layout", json=body)
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == loc


def test_an_unknown_scene_is_refused(client, sample):
    r = layout(client, sample, scene_id="outro")
    assert r.status_code == 422
    [problem] = r.json()["problems"]
    assert problem["loc"] == ["scene_id"]
    assert problem["message"].startswith("There's no scene called 'outro'")


def test_errors_in_the_scene_stop_it_but_errors_elsewhere_dont(client, sample, backend):
    sample["scenes"][1]["steps"][0]["target"] = "nothere"
    r = layout(client, off_frame(sample))
    assert r.status_code == 200, r.text
    assert [p["item_id"] for p in r.json()["problems"]] == ["hello"]
    r = layout(client, sample, scene_id="second")
    assert r.status_code == 422
    assert any(p["loc"] == ["scenes", 1, "steps", 0, "target"] for p in r.json()["problems"])
    assert [call[1] for call in backend.calls("layout")] == ["intro"]


def test_a_document_the_models_cant_read_is_refused(client, sample):
    sample["scenes"][0]["objects"][0]["type"] = "hexagon"
    r = layout(client, sample)
    assert r.status_code == 422
    assert "There's no kind of object called 'hexagon'" in r.json()["problems"][0]["message"]


def test_answers_are_cached_by_the_scenes_content(client, sample, backend):
    assert layout(client, off_frame(sample)).status_code == 200
    assert layout(client, sample).status_code == 200
    assert len(backend.calls("layout")) == 1
    # Another scene's changes don't make this one's answer stale
    sample["scenes"][1]["steps"][0]["run_time"] = 3
    assert layout(client, sample).status_code == 200
    assert len(backend.calls("layout")) == 1
    sample["scenes"][0]["objects"][0]["place"] = [7.6, 0]
    assert layout(client, sample).status_code == 200
    assert len(backend.calls("layout")) == 2


def test_a_scene_carrying_objects_depends_on_the_scene_before(client, sample, backend):
    sample["scenes"][1]["carry"] = ["hello"]
    sample["scenes"][0]["objects"][0]["shown"] = True
    assert layout(client, sample, scene_id="second").status_code == 200
    sample["scenes"][0]["objects"][0]["text"] = "Hello again"
    assert layout(client, sample, scene_id="second").status_code == 200
    assert len(backend.calls("layout")) == 2


def test_the_same_check_asked_for_twice_at_once_runs_once(client, sample, backend):
    sample["scenes"][0]["title"] = "gate:open"
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(layout(client, sample))) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.5)
    (Path(backend.folder) / "open").write_text("")
    for thread in threads:
        thread.join(timeout=60)
    assert [a.status_code for a in answers] == [200, 200]
    assert len(backend.calls("layout")) == 1


def test_a_check_doesnt_wait_on_stills_nor_they_on_it(client, sample, backend):
    sample["scenes"][0]["title"] = "gate:open"
    answer = []
    thread = threading.Thread(target=lambda: answer.append(layout(client, sample)))
    thread.start()
    r = client.post("/api/still", json={"document": sample, "scene_id": "second", "step_index": 0})
    assert r.status_code == 200 and not answer
    (Path(backend.folder) / "open").write_text("")
    thread.join(timeout=60)
    assert answer[0].status_code == 200


def test_a_scene_which_cant_be_built_answers_with_why(client, sample):
    sample["scenes"][0]["title"] = "fail"
    r = layout(client, sample)
    assert r.status_code == 422
    [problem] = r.json()["problems"]
    assert problem["loc"] == ["scenes", 0, "objects", 0, "tex"]
    assert problem["severity"] == "error"


def test_a_crashed_checker_is_restarted(client, sample, backend):
    sample["scenes"][0]["title"] = "crash"
    r = layout(client, sample)
    assert r.status_code == 500
    [problem] = r.json()["problems"]
    assert problem["loc"] == ["scenes", 0] and problem["scene_id"] == "intro"
    assert "stopped unexpectedly" in problem["message"]
    sample["scenes"][0]["title"] = None
    assert layout(client, sample).status_code == 200


def test_a_check_which_runs_too_long_is_stopped(make_client, scene_file, sample, monkeypatch):
    monkeypatch.setattr(layout_checks, "LAYOUT_TIMEOUT", 1.0)
    client = make_client(scene_file)
    sample["scenes"][0]["title"] = "hang"
    r = layout(client, sample)
    assert r.status_code == 422
    [problem] = r.json()["problems"]
    assert problem["message"].startswith("Checking the layout of this scene took longer than 1 seconds")
    sample["scenes"][0]["title"] = None
    assert layout(client, sample).status_code == 200


def test_an_unexpected_failure_is_a_500_with_a_problem(make_client, scene_file, sample):
    client = make_client(scene_file, raise_server_exceptions=False)
    sample["scenes"][0]["title"] = "boom"
    r = layout(client, sample)
    assert r.status_code == 500
    [problem] = r.json()["problems"]
    assert "the fake renderer fell over" in problem["message"]
    assert problem["scene_id"] == "intro"


def test_the_checker_stops_with_the_app(tmp_path, scene_file, backend, sample):
    app = create_app(scene_file, output_dir=tmp_path / "out", backend=backend, start_workers=False,
                     static_dir=tmp_path / "no-static", limits=Limits(worker_start_timeout=30))
    from manim_verbose.editor.workers import _live
    with TestClient(app) as client:
        assert layout(client, sample).status_code == 200
        checkers = [worker for worker in list(_live) if worker.name == "layout" and worker.is_alive()]
        assert len(checkers) == 1
    assert not checkers[0].is_alive()


# The real checker

DOC = {
    "version": 1,
    "title": "Real layout",
    "settings": {"resolution": [256, 144], "fps": 15},
    "scenes": [{
        "id": "intro",
        "objects": [
            {"id": "hello", "type": "text", "text": "Hello world", "place": [7, 0]},
            {"id": "other", "type": "text", "text": "On top", "place": [0, 2]},
            {"id": "again", "type": "text", "text": "On top too", "place": [0.2, 2]},
        ],
        "steps": [
            {"id": "intro_1", "do": "show", "target": "hello"},
            {"id": "intro_2", "do": "show", "target": ["other", "again"], "caption": "Two at once"},
        ],
    }],
}


@pytest.mark.render
def test_the_real_checker(tmp_path, monkeypatch):
    monkeypatch.setenv("MANIM_VERBOSE_CACHE", str(tmp_path / "cache"))
    path = tmp_path / "real.yaml"
    path.write_text(yaml.safe_dump(DOC, sort_keys=False), encoding="utf-8")
    app = create_app(path, output_dir=tmp_path / "out", static_dir=tmp_path / "no-static")
    with TestClient(app) as client:
        r = layout(client, DOC, revision=1)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["revision"] == 1
        assert [(p["item_id"], p["loc"], p["message"]) for p in body["problems"]] == [
            ("hello", ["scenes", 0, "objects", 0, "place"],
             "After steps 1 to 2 ('intro_1' to 'intro_2'), 'hello' runs off the right edge of the frame"),
            ("again", ["scenes", 0, "objects", 2, "place"], "After step 2 ('intro_2'), 'other' and 'again' overlap"),
        ]
        assert all(p["severity"] == "warning" and p["scene_id"] == "intro" for p in body["problems"])
        # A formula LaTeX refuses is an error on its field, as for a still
        broken = {**DOC, "scenes": [{**DOC["scenes"][0], "objects": [
            {"id": "bad", "type": "tex", "tex": "\\frac{1}{", "shown": True}], "steps": []}]}
        r = layout(client, broken)
        assert r.status_code == 422
        [problem] = r.json()["problems"]
        assert (problem["loc"], problem["severity"]) == (["scenes", 0, "objects", 0, "tex"], "error")
