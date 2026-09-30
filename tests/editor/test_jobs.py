"""
Exports: the job lifecycle (queued, running, then done, failed or cancelled), progress which
only goes forward, cancelling at every stage, and the limits on how many can wait.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import pytest

from manim_verbose.editor.jobs import Job, JobRegistry
from manim_verbose.editor.limits import Limits

FINAL = ("done", "failed", "cancelled")


def export(client, doc, **extra):
    r = client.post("/api/export", json={"document": doc, **extra})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def follow(client, job_id, timeout=20.0) -> list[dict]:
    """Every state the job was seen in, polling until it finishes."""
    seen = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = client.get(f"/api/jobs/{job_id}").json()
        seen.append(state)
        if state["status"] in FINAL:
            return seen
        time.sleep(0.01)
    raise AssertionError(f"job didn't finish: {seen[-1]}")


def wait_for_status(client, job_id, status, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if client.get(f"/api/jobs/{job_id}").json()["status"] == status:
            return
        time.sleep(0.01)
    raise AssertionError(f"job never got to {status}")


def slow(sample, seconds=0.3):
    doc = copy.deepcopy(sample)
    for scene in doc["scenes"]:
        scene["title"] = f"slow:{seconds}"
    return doc


def titled(sample, title, scene=0):
    doc = copy.deepcopy(sample)
    doc["scenes"][scene]["title"] = title
    return doc


def open_gate(backend):
    (Path(backend.folder) / "gate").touch()


def test_an_export_from_start_to_finish(client, sample, backend):
    job_id = export(client, slow(sample), quality="medium")
    seen = follow(client, job_id)
    statuses = [s["status"] for s in seen]
    assert statuses[-1] == "done"
    order = ["queued", "running", "done"]
    assert [order.index(s) for s in statuses] == sorted(order.index(s) for s in statuses)
    assert "running" in statuses
    progress = [s["progress"] for s in seen]
    assert progress == sorted(progress), "progress never goes back"
    assert progress[-1] == 1.0
    assert any(0 < p < 1 for p in progress)
    assert any(s["message"] == "Rendering scene 2 of 2" for s in seen)

    final = seen[-1]
    assert final["job_id"] == job_id
    assert final["problems"] == []
    assert final["output_url"].startswith("/files/exports/lesson-medium-")
    video = client.get(final["output_url"])
    assert video.status_code == 200 and video.content[4:8] == b"ftyp"
    assert backend.calls("video") == [["video", "medium", ["intro", "second"]]]


def test_an_export_defaults_to_hd(client, sample):
    job_id = export(client, sample)
    assert follow(client, job_id)[-1]["output_url"].startswith("/files/exports/lesson-hd-")


def test_an_export_which_fails_says_why(client, sample):
    final = follow(client, export(client, titled(sample, "fail")))[-1]
    assert final["status"] == "failed"
    [p] = final["problems"]
    assert (p["loc"], p["scene_id"], p["item_id"]) == (["scenes", 0, "objects", 0, "tex"], "intro", "hello")
    assert final["output_url"] is None


def test_an_export_which_fails_unexpectedly(client, sample):
    final = follow(client, export(client, titled(sample, "boom")))[-1]
    assert final["status"] == "failed"
    assert "the fake renderer fell over" in final["problems"][0]["message"]


def test_an_export_whose_renderer_crashes_and_the_next_one(client, sample):
    final = follow(client, export(client, titled(sample, "crash")))[-1]
    assert final["status"] == "failed"
    assert "stopped unexpectedly" in final["problems"][0]["message"]
    assert follow(client, export(client, sample))[-1]["status"] == "done"


def test_an_export_past_its_time_limit(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(export_timeout=1, job_workers=1))
    final = follow(client, export(client, titled(sample, "hang")))[-1]
    assert final["status"] == "failed"
    assert "took longer than" in final["problems"][0]["message"]
    assert follow(client, export(client, sample))[-1]["status"] == "done"


def test_cancelling_a_running_export(make_client, scene_file, sample, backend):
    client = make_client(scene_file, Limits(job_workers=1))
    job_id = export(client, slow(sample, 30))
    wait_for_status(client, job_id, "running")
    r = client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    time.sleep(0.2)
    final = client.get(f"/api/jobs/{job_id}").json()
    assert final["status"] == "cancelled" and final["output_url"] is None
    started = time.monotonic()
    assert follow(client, export(client, sample))[-1]["status"] == "done", "the worker is free again"
    assert time.monotonic() - started < 5
    assert not any(p.suffix == ".mp4" and "hd" in p.name and job_id[:8] in p.name
                   for p in (client.app.state.editor.outputs.root / "exports").iterdir())


def test_cancelling_an_export_which_ignores_it(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(job_workers=1, cancel_grace=0.5))
    pool_worker = client.app.state.editor.pool.workers[0]
    job_id = export(client, titled(sample, "nocancel"))
    wait_for_status(client, job_id, "running")
    first_pid = pool_worker.pid
    assert client.delete(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
    assert follow(client, export(client, sample))[-1]["status"] == "done"
    assert pool_worker.pid != first_pid, "the stuck process was killed and replaced"


def test_cancelling_a_queued_export(make_client, scene_file, sample, backend):
    client = make_client(scene_file, Limits(job_workers=1))
    first = export(client, titled(sample, "gate:gate"))
    wait_for_status(client, first, "running")
    second = export(client, sample)
    assert client.get(f"/api/jobs/{second}").json()["status"] == "queued"
    assert client.delete(f"/api/jobs/{second}").json()["status"] == "cancelled"
    open_gate(backend)
    assert follow(client, first)[-1]["status"] == "done"
    time.sleep(0.2)
    assert client.get(f"/api/jobs/{second}").json()["status"] == "cancelled"
    assert len(backend.calls("video")) == 1, "the cancelled export never started"


def test_cancelling_a_finished_export_changes_nothing(client, sample):
    job_id = export(client, sample)
    follow(client, job_id)
    r = client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert client.get(client.get(f"/api/jobs/{job_id}").json()["output_url"]).status_code == 200


def test_unknown_jobs(client):
    for method in ("get", "delete"):
        r = getattr(client, method)("/api/jobs/nope")
        assert r.status_code == 404
        assert r.json()["problems"][0]["message"] == "There's no export with id 'nope'"


def test_bad_exports(client, sample, backend):
    broken = copy.deepcopy(sample)
    broken["scenes"][1]["steps"][0]["target"] = "nothing"
    r = client.post("/api/export", json={"document": broken})
    assert r.status_code == 422, "an error in any scene stops an export"
    assert r.json()["problems"][0]["item_id"] == "second_1"
    r = client.post("/api/export", json={"document": sample, "quality": "4k"})
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == ["quality"]
    assert "'quality' has to be one of" in r.json()["problems"][0]["message"]
    assert backend.calls() == []


def test_too_many_exports_at_once(make_client, scene_file, sample, backend):
    client = make_client(scene_file, Limits(max_pending_exports=2, job_workers=1))
    first = export(client, titled(sample, "gate:gate"))
    export(client, sample)
    r = client.post("/api/export", json={"document": sample})
    assert r.status_code == 429
    assert "already 2 exports" in r.json()["problems"][0]["message"]
    open_gate(backend)
    follow(client, first)


def test_clips_go_ahead_of_waiting_exports(make_client, scene_file, sample, backend):
    client = make_client(scene_file, Limits(job_workers=1))
    first = export(client, titled(sample, "gate:gate"))
    wait_for_status(client, first, "running")
    waiting = export(client, sample)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(1) as pool:
        pending_clip = pool.submit(client.post, "/api/clip", json={"document": sample, "scene_id": "intro"})
        time.sleep(0.2)
        open_gate(backend)
        assert pending_clip.result(timeout=10).status_code == 200
    follow(client, waiting)
    assert [call[0] for call in backend.calls()] == ["video", "clip", "video"]


def test_closing_the_editor_cancels_its_exports(make_client, scene_file, sample):
    client = make_client(scene_file, Limits(job_workers=1))
    editor = client.app.state.editor
    running = export(client, slow(sample, 30))
    wait_for_status(client, running, "running")
    queued = export(client, sample)
    worker = editor.pool.workers[0]
    client.__exit__(None, None, None)
    assert editor.jobs.get(running).status == "cancelled"
    assert editor.jobs.get(queued).status == "cancelled"
    assert not worker.is_alive()


def test_finished_jobs_are_forgotten_beyond_a_limit():
    registry = JobRegistry(keep=2)
    jobs = [Job() for _ in range(4)]
    for job in jobs:
        job.settle("done", "Finished", output_url="/x")
        registry.add(job)
    unfinished = Job()
    registry.add(unfinished)
    assert [j.job_id for j in registry.all()] == [jobs[2].job_id, jobs[3].job_id, unfinished.job_id]


def test_job_progress_only_goes_forward():
    job = Job()
    job.advance(0.5, "ignored: not running yet")
    assert job.progress == 0.0
    job.started()
    for fraction in (0.2, 0.1, -3, 0.6, 7):
        job.advance(fraction, "")
    assert job.progress == 0.99, "only a finished job is at 1"
    assert job.settle("done", "Finished", output_url="/files/exports/x.mp4")
    assert job.progress == 1.0
    assert not job.settle("failed", "too late")
    assert job.status == "done"
