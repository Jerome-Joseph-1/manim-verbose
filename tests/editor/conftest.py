"""
Fixtures for the editor server's tests: a scene file in a temporary folder, and apps serving it
with the fake backend from editor_fakes.py.

Tests marked `render` use the real renderer, and skip themselves until it exists.
"""
from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path

import pytest
import yaml

warnings.filterwarnings("ignore", message=".*httpx.*starlette.testclient.*")
warnings.filterwarnings("ignore", message=".*starlette.testclient.*httpx.*")

from fastapi.testclient import TestClient  # noqa: E402

from editor_fakes import FakeBackend  # noqa: E402
from manim_verbose.editor.limits import Limits  # noqa: E402
from manim_verbose.editor.server import create_app  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "render: uses the real renderer (software Vulkan); slow")
    config.addinivalue_line("markers", "needs(*names): functions of scenefile/render.py a render test needs")


SAMPLE = {
    "version": 1,
    "title": "Sample",
    "scenes": [
        {
            "id": "intro",
            "objects": [
                {"id": "hello", "type": "text", "text": "Hello"},
                {"id": "eq", "type": "tex", "tex": "a^2 + b^2 = c^2", "place": {"edge": "top"}},
                {"id": "c", "type": "circle", "radius": 1, "color": "BLUE"},
            ],
            "steps": [
                {"id": "intro_1", "do": "show", "target": "hello"},
                {"id": "intro_2", "do": "show", "target": "eq"},
                {"id": "intro_3", "do": "highlight", "target": "eq", "part": "c^2"},
                {"id": "intro_4", "do": "wait", "duration": 2},
            ],
        },
        {
            "id": "second",
            "objects": [{"id": "sq", "type": "square"}],
            "steps": [{"id": "second_1", "do": "show", "target": "sq", "run_time": 1.5}],
        },
    ],
}


@pytest.fixture
def sample() -> dict:
    return copy.deepcopy(SAMPLE)


@pytest.fixture
def scene_file(tmp_path) -> Path:
    path = tmp_path / "project" / "lesson.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(SAMPLE, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def json_scene_file(tmp_path) -> Path:
    path = tmp_path / "project" / "lesson.json"
    path.parent.mkdir()
    path.write_text(json.dumps(SAMPLE, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def backend(tmp_path) -> FakeBackend:
    folder = tmp_path / "backend"
    folder.mkdir()
    return FakeBackend(folder)


@pytest.fixture
def make_client(tmp_path, backend):
    """Make a TestClient (already entered) for a scene file; everything is shut down afterwards."""
    clients = []

    def make(path: Path, limits: Limits | None = None, raise_server_exceptions: bool = True, **kwargs) -> TestClient:
        kwargs.setdefault("output_dir", tmp_path / "out")
        kwargs.setdefault("backend", backend)
        kwargs.setdefault("start_workers", False)
        kwargs.setdefault("static_dir", tmp_path / "no-static")
        app = create_app(path, limits=limits or Limits(worker_start_timeout=30), **kwargs)
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client, scene_file) -> TestClient:
    return make_client(scene_file)
