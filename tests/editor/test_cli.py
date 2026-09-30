"""
manimgl-editor: making a starter file, choosing a port, warning about listening beyond this
computer, and a real run: the server starts, answers, and shuts down with its workers.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from manim_verbose.editor import cli
from manim_verbose.editor.server import LOCAL_HOSTS
from manim_verbose.scenefile.files import load_file

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def children(pid: int) -> set[int]:
    found = set()
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                stat = (entry / "stat").read_text()
            except OSError:
                continue
            if int(stat.rsplit(")", 1)[1].split()[1]) == pid:
                found.add(int(entry.name))
    return found


def alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_the_editor_starts_answers_and_stops(tmp_path):
    scene = tmp_path / "my video.yaml"
    port = free_port()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), os.environ.get("PYTHONPATH", "")])}
    process = subprocess.Popen(
        [sys.executable, "-m", "manim_verbose.editor.cli", str(scene), "--port", str(port), "--no-browser",
         "--output-dir", str(tmp_path / "out")],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 60
        while True:
            assert process.poll() is None, process.communicate()
            try:
                health = httpx.get(f"{base}/api/health", timeout=2)
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "the server never answered"
                time.sleep(0.2)
        assert health.status_code == 200 and health.json()["ok"] is True

        document = httpx.get(f"{base}/api/document").json()
        assert document["path"] == str(scene.resolve())
        assert document["document"]["title"] == "My first video"
        assert document["problems"] == []
        assert load_file(scene)[1] == []
        assert httpx.get(f"{base}/").status_code == 200
        assert httpx.get(f"{base}/api/health", headers={"host": "evil.example"}).status_code == 400

        workers = set()
        deadline = time.monotonic() + 30
        while not workers and time.monotonic() < deadline:
            workers = {pid for pid in children(process.pid)
                       if "manim-editor" in Path(f"/proc/{pid}/cmdline").read_text(errors="replace")
                       or "multiprocessing" in Path(f"/proc/{pid}/cmdline").read_text(errors="replace")}
            time.sleep(0.1)
        assert workers, "the still worker is started with the server"
    finally:
        process.send_signal(signal.SIGINT)
        try:
            out, err = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            raise AssertionError(f"the editor didn't stop on Ctrl+C\n{err}")
    assert process.returncode == 0, err
    assert f"Created {scene.resolve()}" in out
    assert f"The editor is at http://127.0.0.1:{port}/" in out
    assert "Stopped the editor" in out
    assert "Traceback" not in err
    deadline = time.monotonic() + 10
    while any(alive(pid) for pid in workers) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not any(alive(pid) for pid in workers), "a worker outlived the editor"


@pytest.fixture
def run(monkeypatch):
    """Run main() in this process, with the server itself replaced by a recorder."""
    record = {}

    def fake_create_app(path, **kwargs):
        record["path"], record["kwargs"] = path, kwargs
        return object()

    opened = []
    record["opened"] = opened

    def fake_serve(self, sockets=None):
        """Listen for a moment, long enough for the browser to be sent to the server."""
        record["port"] = sockets[0].getsockname()[1]
        deadline = time.monotonic() + (5 if "--no-browser" not in record["args"] else 0)
        while not opened and time.monotonic() < deadline:
            time.sleep(0.02)
        sockets[0].close()

    monkeypatch.setattr("manim_verbose.editor.server.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.Server.run", fake_serve)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    def main(*args):
        record["args"] = [str(a) for a in args]
        record["code"] = cli.main(record["args"])
        return record

    return main


@pytest.mark.parametrize("name", ["new.yaml", "new.json"])
def test_a_missing_file_starts_as_the_starter(run, tmp_path, capsys, name):
    path = tmp_path / name
    record = run(path, "--port", 0, "--no-browser")
    assert record["code"] == 0
    doc, problems = load_file(path)
    assert problems == [] and doc.title == "My first video"
    assert record["path"] == path.resolve()
    assert record["kwargs"]["allowed_hosts"] == LOCAL_HOSTS
    assert f"Created {path.resolve()}" in capsys.readouterr().out
    assert record["opened"] == []


def test_an_existing_file_is_left_alone(run, scene_file, capsys, tmp_path):
    before = scene_file.read_bytes()
    record = run(scene_file, "--port", 0, "--no-browser", "--output-dir", tmp_path / "renders")
    assert record["code"] == 0
    assert scene_file.read_bytes() == before
    assert record["kwargs"]["output_dir"] == tmp_path / "renders"
    assert "Created" not in capsys.readouterr().out


def test_the_browser_is_opened_once_the_server_listens(run, scene_file):
    record = run(scene_file, "--port", 0)
    assert record["opened"] == [f"http://127.0.0.1:{record['port']}/"]


def test_listening_beyond_this_computer_is_warned_about(run, scene_file, capsys):
    record = run(scene_file, "--host", "0.0.0.0", "--port", 0, "--no-browser")
    assert record["code"] == 0
    err = capsys.readouterr().err
    assert "WARNING: listening on 0.0.0.0" in err
    assert "lesson.yaml" in err
    assert record["kwargs"]["allowed_hosts"] is None


@pytest.mark.parametrize("args, message", [
    (["notes.txt"], "a scene file's name ends in .yaml, .yml or .json"),
    (["missing/folder/x.yaml"], "doesn't exist"),
])
def test_bad_files(run, tmp_path, capsys, monkeypatch, args, message):
    monkeypatch.chdir(tmp_path)
    assert run(*args)["code"] == 2
    assert message in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_a_folder_is_not_a_scene_file(run, tmp_path, capsys):
    (tmp_path / "x.yaml").mkdir()
    assert run(tmp_path / "x.yaml")["code"] == 2
    assert "is a folder" in capsys.readouterr().err


def test_a_port_in_use(run, scene_file, capsys, monkeypatch):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        assert run(scene_file, "--port", port, "--no-browser")["code"] == 1
        assert f"couldn't listen on 127.0.0.1:{port}" in capsys.readouterr().err

        monkeypatch.setattr(cli, "DEFAULT_PORT", port)
        sock = cli.bind("127.0.0.1", None)
        try:
            assert port < sock.getsockname()[1] < port + cli.PORTS_TO_TRY, "the next free port"
        finally:
            sock.close()


@pytest.mark.parametrize("host, local", [
    ("127.0.0.1", True), ("localhost", True), ("::1", True), ("[::1]", True), ("127.0.0.2", True),
    ("0.0.0.0", False), ("::", False), ("192.168.1.5", False), ("example.com", False),
])
def test_which_hosts_are_local(host, local):
    assert cli.is_local_host(host) is local


def test_python_dash_m_runs_it():
    out = subprocess.run([sys.executable, "-m", "manim_verbose.editor", "--help"], cwd=ROOT, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "--no-browser" in out.stdout and "--output-dir" in out.stdout
