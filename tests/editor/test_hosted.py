"""
Hosted mode (manim_verbose/editor/hosted.py): the harder edges the editor needs before it can
render strangers' documents on a public server.

These use the fake backend (see editor_fakes.py), so they run in seconds and need no GPU. Each
limit and endpoint behaviour is checked on its own, plus the mechanisms (rate limiter,
concurrency gate, output reaper, basic auth) as units.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from editor_fakes import FakeBackend
from manim_verbose.editor.hosted import (
    HostedConfig, OutputReaper, RateLimit, RateLimiter, RenderGate, capped_quality,
)
from manim_verbose.editor.outputs import OutputDir
from manim_verbose.editor.server import create_app


SIMPLE = {
    "version": 1,
    "scenes": [{
        "id": "intro",
        "objects": [{"id": "hello", "type": "text", "text": "Hi"}],
        "steps": [{"do": "show", "target": "hello"}, {"do": "wait", "duration": 1}],
    }],
}


@pytest.fixture
def make_hosted(tmp_path):
    """A TestClient for a hosted app, with the fake backend and the hosted limits actually in
    force (unlike the shared make_client, which pins its own Limits)."""
    clients: list[TestClient] = []
    count = [0]

    def make(config: HostedConfig | None = None, **kwargs) -> TestClient:
        count[0] += 1
        folder = tmp_path / f"backend{count[0]}"
        folder.mkdir()
        path = tmp_path / f"proj{count[0]}" / "video.yaml"
        path.parent.mkdir()
        app = create_app(
            path,
            backend=FakeBackend(folder),
            hosted=config or HostedConfig(),
            start_workers=False,
            static_dir=tmp_path / "no-static",
            output_dir=tmp_path / f"out{count[0]}",
            **kwargs,
        )
        client = TestClient(app, raise_server_exceptions=True)
        client.__enter__()
        client.editor = app.state.editor  # type: ignore[attr-defined]
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def _poll_job(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished")


# --- /api/config -------------------------------------------------------------------------

def test_config_says_local_when_not_hosted(make_client, scene_file):
    body = make_client(scene_file).get("/api/config").json()
    assert body["hosted"] is False
    assert body["storage"] == "server"


def test_config_says_hosted_and_carries_limits(make_hosted):
    body = make_hosted(HostedConfig(max_total_duration=120, max_export_quality="medium")).get("/api/config").json()
    assert body["hosted"] is True
    assert body["storage"] == "browser"
    assert body["limits"]["max_total_duration"] == 120
    assert body["limits"]["max_export_quality"] == "medium"


# --- No document on the server -----------------------------------------------------------

def test_document_endpoints_are_404_in_hosted_mode(make_hosted):
    client = make_hosted()
    assert client.get("/api/document").status_code == 404
    assert client.put("/api/document", json={"document": SIMPLE, "base_revision": 1}).status_code == 404
    assert client.get("/api/timeline?scene_id=intro").status_code == 404
    # ...but the reason is a plain problem, not a stack trace
    assert "browser" in client.get("/api/document").json()["problems"][0]["message"]


def test_templates_and_validation_still_served(make_hosted):
    client = make_hosted()
    assert client.get("/api/catalog").status_code == 200
    assert client.get("/api/schema").status_code == 200
    assert client.post("/api/validate", json={"document": SIMPLE}).status_code == 200
    assert client.get("/api/health").json()["ok"] is True


# --- Rendering still works, statelessly --------------------------------------------------

def test_still_renders_from_the_body(make_hosted):
    body = make_hosted().post(
        "/api/still", json={"document": SIMPLE, "scene_id": "intro", "step_index": 0, "width": 640}
    ).json()
    assert body["width"] == 640
    assert body["image_url"].startswith("/files/stills/")


# --- Document-shape limits ---------------------------------------------------------------

def test_still_width_is_capped(make_hosted):
    client = make_hosted(HostedConfig(max_still_width=1000))
    r = client.post("/api/still", json={"document": SIMPLE, "scene_id": "intro", "step_index": 0, "width": 3000})
    assert r.status_code == 422
    assert r.json()["problems"][0]["loc"] == ["width"]


def test_document_size_limit(make_hosted):
    client = make_hosted(HostedConfig(max_document_bytes=2000))
    big = {"version": 1, "scenes": [{"id": "s", "objects": [
        {"id": f"t{i}", "type": "text", "text": "x" * 100} for i in range(50)
    ], "steps": []}]}
    r = client.post("/api/still", json={"document": big, "scene_id": "s", "step_index": -1, "width": 400})
    assert r.status_code == 413


def test_scene_and_step_limits(make_hosted):
    client = make_hosted(HostedConfig(max_scenes=2, max_steps=3))
    many_scenes = {"version": 1, "scenes": [{"id": f"s{i}", "steps": []} for i in range(5)]}
    r = client.post("/api/still", json={"document": many_scenes, "scene_id": "s0", "step_index": -1, "width": 400})
    assert r.status_code == 422 and r.json()["problems"][0]["loc"] == ["scenes"]

    many_steps = {"version": 1, "scenes": [{"id": "s", "objects": [{"id": "h", "type": "text", "text": "x"}],
                  "steps": [{"do": "wait", "duration": 1} for _ in range(10)]}]}
    r = client.post("/api/still", json={"document": many_steps, "scene_id": "s", "step_index": -1, "width": 400})
    assert r.status_code == 422 and r.json()["problems"][0]["loc"] == ["scenes", 0, "steps"]


def test_uploaded_images_are_refused(make_hosted):
    client = make_hosted()
    for kind in ("image", "svg"):
        doc = {"version": 1, "scenes": [{"id": "s", "objects": [
            {"id": "pic", "type": kind, "path": "a." + ("png" if kind == "image" else "svg")}], "steps": []}]}
        r = client.post("/api/still", json={"document": doc, "scene_id": "s", "step_index": -1, "width": 400})
        assert r.status_code == 422
        assert "uploaded images" in r.json()["problems"][0]["message"].lower() or \
               "images or svg" in r.json()["problems"][0]["message"].lower()


def test_uploads_can_be_allowed_by_config(make_hosted):
    client = make_hosted(HostedConfig(allow_uploads=True))
    doc = {"version": 1, "scenes": [{"id": "s", "objects": [
        {"id": "pic", "type": "image", "path": "a.png"}], "steps": [{"do": "show", "target": "pic"}]}]}
    # It gets past the hosted asset check now (the render itself may still complain, but not the guard)
    r = client.post("/api/still", json={"document": doc, "scene_id": "s", "step_index": -1, "width": 400})
    assert r.status_code == 200


# --- Export caps -------------------------------------------------------------------------

def test_export_quality_is_capped(make_hosted):
    client = make_hosted(HostedConfig(max_export_quality="medium"))
    job_id = client.post("/api/export", json={"document": SIMPLE, "quality": "uhd"}).json()["job_id"]
    done = _poll_job(client, job_id)
    assert done["status"] == "done"
    assert "-medium-" in done["output_url"]  # rendered at the cap, not uhd
    backend: FakeBackend = client.editor.backend  # type: ignore[attr-defined]
    assert backend.calls("video")[0][1] == "medium"


def test_export_total_duration_is_capped(make_hosted):
    client = make_hosted(HostedConfig(max_total_duration=5))
    long_doc = {"version": 1, "scenes": [{"id": "a", "objects": [{"id": "h", "type": "text", "text": "x"}],
                "steps": [{"do": "wait", "duration": 400}]}]}
    r = client.post("/api/export", json={"document": long_doc, "quality": "low"})
    assert r.status_code == 422
    assert "minutes" in r.json()["problems"][0]["message"]


# --- Rate limits -------------------------------------------------------------------------

def test_still_rate_limit(make_hosted):
    client = make_hosted(HostedConfig(still_rate=RateLimit(2, 60)))
    ok = [client.post("/api/still", json={"document": SIMPLE, "scene_id": "intro", "step_index": 0, "width": 300 + i})
          for i in range(2)]
    assert all(r.status_code == 200 for r in ok)
    blocked = client.post("/api/still", json={"document": SIMPLE, "scene_id": "intro", "step_index": 0, "width": 999})
    assert blocked.status_code == 429
    assert "retry_after" in blocked.json()


def test_export_rate_limit(make_hosted):
    client = make_hosted(HostedConfig(export_rate=RateLimit(1, 300)))
    first = client.post("/api/export", json={"document": SIMPLE, "quality": "low"})
    assert first.status_code == 202
    second = client.post("/api/export", json={"document": SIMPLE, "quality": "low"})
    assert second.status_code == 429
    _poll_job(client, first.json()["job_id"])


def test_clip_rate_limit(make_hosted):
    client = make_hosted(HostedConfig(clip_rate=RateLimit(1, 60)))
    first = client.post("/api/clip", json={"document": SIMPLE, "scene_id": "intro", "start_step": 0, "end_step": 0})
    assert first.status_code == 200
    second = client.post("/api/clip", json={"document": SIMPLE, "scene_id": "intro", "start_step": 0, "end_step": 1})
    assert second.status_code == 429


# --- Global concurrency cap --------------------------------------------------------------

def test_concurrent_render_cap_on_clips(make_hosted, tmp_path):
    client = make_hosted(HostedConfig(max_concurrent_renders=1, clip_rate=RateLimit(100, 60)))
    backend: FakeBackend = client.editor.backend  # type: ignore[attr-defined]
    gate_file = Path(backend.folder) / "go"
    # A clip whose scene waits for the gate file: it holds the one render slot until released.
    blocking_doc = {"version": 1, "scenes": [{"id": "hold", "title": "gate:go",
                    "objects": [{"id": "h", "type": "text", "text": "x"}],
                    "steps": [{"do": "show", "target": "h"}]}]}
    result: dict = {}

    def run_blocking():
        result["r"] = client.post("/api/clip", json={"document": blocking_doc, "scene_id": "hold",
                                                     "start_step": 0, "end_step": 0})

    thread = threading.Thread(target=run_blocking)
    thread.start()
    try:
        time.sleep(0.5)  # let the blocking clip take the slot
        second = client.post("/api/clip", json={"document": SIMPLE, "scene_id": "intro",
                                               "start_step": 0, "end_step": 0})
        assert second.status_code == 429
        assert "busy" in second.json()["problems"][0]["message"].lower()
    finally:
        gate_file.write_text("go")
        thread.join(timeout=20)
    assert result["r"].status_code == 200


# --- Output expiry -----------------------------------------------------------------------

def test_output_reaper_removes_old_files_and_keeps_recent(tmp_path):
    outputs = OutputDir(tmp_path / "out")
    old_png = outputs.root / "stills" / ("a" * 64 + ".png")
    old_png.write_bytes(b"x")
    (outputs.root / "stills" / ("a" * 64 + ".json")).write_text("{}")
    fresh_mp4 = outputs.root / "clips" / ("b" * 64 + ".mp4")
    fresh_mp4.write_bytes(b"y")
    partial = outputs.root / "exports" / ".partial-halfway.mp4"
    partial.write_bytes(b"z")

    old_time = time.time() - 7200
    import os
    os.utime(old_png, (old_time, old_time))
    os.utime(old_png.with_suffix(".json"), (old_time, old_time))
    os.utime(partial, (old_time, old_time))

    reaper = OutputReaper(outputs, ttl=3600, interval=999)
    removed = reaper.sweep()
    assert removed == 1
    assert not old_png.exists()
    assert not old_png.with_suffix(".json").exists()  # its sidecar goes too
    assert fresh_mp4.exists()                          # recent files stay
    assert partial.exists()                            # a render in progress is left alone


# --- Basic auth --------------------------------------------------------------------------

def test_basic_auth_guards_the_app(make_hosted):
    client = make_hosted(HostedConfig(password="s3cret"))
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", auth=("anyone", "wrong")).status_code == 401
    assert client.get("/api/config", auth=("anyone", "s3cret")).status_code == 200
    # health stays open, for uptime checks and Cloud Run
    assert client.get("/api/health").status_code == 200


def test_no_auth_when_no_password(make_hosted):
    assert make_hosted(HostedConfig(password=None)).get("/api/config").status_code == 200


# --- Units: the mechanisms on their own --------------------------------------------------

def test_capped_quality():
    config = HostedConfig(max_export_quality="medium")
    assert capped_quality("low", config) == "low"
    assert capped_quality("medium", config) == "medium"
    assert capped_quality("hd", config) == "medium"
    assert capped_quality("uhd", config) == "medium"
    assert capped_quality("nonsense", config) == "medium"


def test_rate_limiter_window_slides():
    limiter = RateLimiter()
    limit = RateLimit(2, 10.0)
    assert limiter.check("ip", "still", limit, now=0.0) is None
    assert limiter.check("ip", "still", limit, now=1.0) is None
    retry = limiter.check("ip", "still", limit, now=2.0)
    assert retry is not None and 7.9 < retry <= 8.0
    # a different address has its own budget
    assert limiter.check("other", "still", limit, now=2.0) is None
    # once the window has passed, room again
    assert limiter.check("ip", "still", limit, now=11.0) is None


def test_render_gate():
    gate = RenderGate(2)
    with gate.hold() as a, gate.hold() as b:
        assert a.ok and b.ok
        with gate.hold() as c:
            assert not c.ok  # full
        assert gate.in_flight == 2
    assert gate.in_flight == 0


def test_hosted_config_from_env_reads_password_and_knobs():
    env = {"MANIM_VERBOSE_HOSTED_PASSWORD": "hunter2",
           "MANIM_VERBOSE_HOSTED_MAX_TOTAL_DURATION": "120",
           "MANIM_VERBOSE_HOSTED_MAX_CONCURRENT_RENDERS": "4"}
    config = HostedConfig.from_env(env)
    assert config.password == "hunter2"
    assert config.max_total_duration == 120
    assert config.max_concurrent_renders == 4


# --- $PORT and host binding (cli.run_hosted) ---------------------------------------------

def test_run_hosted_binds_0000_and_PORT(monkeypatch):
    import manim_verbose.editor.cli as cli
    captured: dict = {}

    class FakeUvicorn:
        def run(self, app, *, host, port, **kwargs):
            captured["host"] = host
            captured["port"] = port

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn())
    monkeypatch.setenv("PORT", "12345")
    args = cli.build_parser().parse_args(["--hosted"])
    assert cli.run_hosted(args) == 0
    assert captured == {"host": "0.0.0.0", "port": 12345}


def test_main_routes_to_hosted_when_env_set(monkeypatch):
    import manim_verbose.editor.cli as cli
    seen = {}
    monkeypatch.setenv("MANIM_VERBOSE_HOSTED", "1")
    monkeypatch.setattr(cli, "run_hosted", lambda args: (seen.__setitem__("hosted", True), 0)[1])
    assert cli.main([]) == 0
    assert seen["hosted"] is True


def test_hosted_document_written_to_yaml_round_trips_for_import():
    # The .yaml a user downloads (see docs/editor/HOSTING.md and the UI storage module) is a
    # canonical scene file; this makes sure such a file loads back as a valid document.
    from manim_verbose.scenefile.files import dump_text, load_text
    from manim_verbose.scenefile.model import Document

    doc = Document.model_validate(SIMPLE)
    text = dump_text(doc, "yaml")
    loaded, problems = load_text(text, "yaml")
    assert loaded is not None
    assert not [p for p in problems if p.severity == "error"]
    assert yaml.safe_load(text)["scenes"][0]["id"] == "intro"
