"""
Render worker processes, driven directly: they stay alive between calls, report what went
wrong without dying of it, and when they do die, hang, or ignore a cancel, they are killed
(with whatever they started) and replaced.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

import editor_fakes
from editor_fakes import FakeBackend
from manim_verbose.editor.jobs import StillQueue, Superseded, Task
from manim_verbose.editor.workers import (
    RenderException, RenderProblems, WorkerCancelled, WorkerCrashed, WorkerProcess, WorkerTimeout,
)


@pytest.fixture
def worker(tmp_path):
    worker = WorkerProcess(FakeBackend(tmp_path), "test", start_timeout=30, cancel_grace=0.3)
    yield worker
    worker.stop()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def wait_until(condition, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_a_worker_stays_alive_between_calls(worker):
    assert worker.call(editor_fakes.echo, {"value": {"a": [1, 2]}}, timeout=10) == {"a": [1, 2]}
    first = worker.call(editor_fakes.pid, {}, timeout=10)
    assert worker.call(editor_fakes.pid, {}, timeout=10) == first
    assert first != os.getpid()
    assert worker.starts == 1


def test_a_crash_is_reported_and_the_worker_replaced(worker):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    with pytest.raises(WorkerCrashed) as info:
        worker.call(editor_fakes.crash, {"code": 7}, timeout=10)
    assert info.value.exitcode == 7
    after = worker.call(editor_fakes.pid, {}, timeout=10)
    assert after != before
    assert worker.starts == 2


def test_a_call_past_its_time_limit_is_killed(worker):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    started = time.monotonic()
    with pytest.raises(WorkerTimeout) as info:
        worker.call(editor_fakes.sleep_for, {"seconds": 60}, timeout=0.5)
    assert time.monotonic() - started < 5
    assert info.value.seconds == 0.5
    assert wait_until(lambda: not alive(before))
    assert worker.call(editor_fakes.echo, {"value": "fine"}, timeout=10) == "fine"


def test_a_time_limit_holds_however_much_progress_is_reported(worker):
    with pytest.raises(WorkerTimeout):
        worker.call(editor_fakes.chatty_forever, {}, timeout=0.5, progress=lambda f, m: None)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX")
def test_killing_a_worker_kills_what_it_started(worker, tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    with pytest.raises(WorkerTimeout):
        worker.call(editor_fakes.hang_with_child, {"pid_file": str(pid_file)}, timeout=2)
    grandchild = int(pid_file.read_text())
    assert wait_until(lambda: not alive(grandchild)), "the render's own subprocess was left running"


def test_render_errors_come_back_as_problems(worker):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    with pytest.raises(RenderProblems) as info:
        worker.call(editor_fakes.fail_render, {}, timeout=10)
    [problem] = info.value.problems
    assert problem == {"message": "That formula doesn't compile", "loc": ["scenes", 0, "objects", 1, "tex"],
                       "severity": "error", "scene_id": "intro", "item_id": "eq", "path": "scenes[0].objects[1].tex"}
    assert worker.call(editor_fakes.pid, {}, timeout=10) == before, "a render error doesn't cost the process"


@pytest.mark.parametrize("fn, text", [
    (editor_fakes.fail_unexpectedly, "KeyError: 'nothing like this was expected'"),
    (editor_fakes.exit_politely, "SystemExit: 4"),
    (editor_fakes.unpicklable_result, "couldn't be sent back"),
])
def test_unexpected_failures_come_back_with_details(worker, fn, text):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    with pytest.raises(RenderException) as info:
        worker.call(fn, {}, timeout=10)
    assert text in str(info.value)
    assert "Traceback" in info.value.details
    assert worker.call(editor_fakes.pid, {}, timeout=10) == before


def test_progress_is_reported(worker):
    seen = []
    assert worker.call(editor_fakes.with_progress, {"steps": 4}, timeout=10,
                       progress=lambda f, m: seen.append((f, m))) == "finished"
    assert seen == [(0.0, "step 1 of 4"), (0.25, "step 2 of 4"), (0.5, "step 3 of 4"), (0.75, "step 4 of 4")]


def test_a_render_can_be_cancelled(worker):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    seen = []
    with pytest.raises(WorkerCancelled):
        worker.call(editor_fakes.with_progress, {"steps": 1000, "delay": 0.01}, timeout=30,
                    progress=lambda f, m: seen.append(f), cancelled=lambda: len(seen) >= 3)
    assert worker.call(editor_fakes.pid, {}, timeout=10) == before, "a render which stops when asked isn't killed"
    assert worker.call(editor_fakes.with_progress, {"steps": 2}, timeout=10) == "finished", "cancel is reset"


def test_a_render_which_ignores_cancel_is_killed(worker):
    before = worker.call(editor_fakes.pid, {}, timeout=10)
    started = time.monotonic()
    with pytest.raises(WorkerCancelled):
        worker.call(editor_fakes.ignore_cancel, {}, timeout=30, cancelled=lambda: True)
    assert time.monotonic() - started < 5
    assert wait_until(lambda: not alive(before))
    assert worker.call(editor_fakes.echo, {"value": 1}, timeout=10) == 1


def test_a_stopped_worker_stays_stopped(worker):
    pid = worker.call(editor_fakes.pid, {}, timeout=10)
    worker.stop()
    assert wait_until(lambda: not alive(pid))
    assert not worker.is_alive()
    with pytest.raises(WorkerCrashed):
        worker.call(editor_fakes.echo, {"value": 1}, timeout=10)


def test_a_worker_whose_server_dies_exits(tmp_path):
    """The server killed outright never asks its workers to stop; they notice and go."""
    script = textwrap.dedent(f"""
        import os, sys
        sys.path[:0] = {[str(Path(editor_fakes.__file__).parent), os.getcwd()]!r}
        from editor_fakes import FakeBackend, pid
        from manim_verbose.editor.workers import WorkerProcess
        if __name__ == "__main__":
            worker = WorkerProcess(FakeBackend({str(tmp_path)!r}), "orphan")
            print(worker.call(pid, {{}}, timeout=30), flush=True)
            os._exit(0)
    """)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60,
                         cwd=Path(__file__).resolve().parents[2])
    assert out.returncode == 0, out.stderr
    orphan = int(out.stdout.strip())
    assert wait_until(lambda: not alive(orphan), timeout=10), "a worker outlived its server"


def test_an_older_still_request_arriving_late_is_superseded(tmp_path):
    queue = StillQueue(WorkerProcess(FakeBackend(tmp_path), "stills"))
    queue.note(5)
    future = queue.submit(Task(fn=editor_fakes.echo, kwargs={"value": 1}, timeout=10, key="k", seq=3))
    with pytest.raises(Superseded):
        future.result(timeout=1)
    queue.close()
