"""
Render worker processes: where manim actually runs, away from the server.

Rendering happens in separate processes for three reasons. Importing manim and setting up its
renderer takes a second or more, so a process which stays alive between renders answers a
still request far faster than a fresh one would. A render can crash the process it runs in, or
run forever, and the server has to keep answering either way. And the one thing which reliably
stops a render stuck in native code is killing its process.

A `WorkerProcess` owns one such process, started with the spawn method so that it begins clean
whatever the server has imported or started. It runs one call at a time: the parent sends a
function and its arguments, the worker runs `function(backend, progress=..., cancel=...,
**arguments)` and sends back the result, or what went wrong. A call which runs past its time
limit has its process killed, and a process which dies is started again for the next call.
Killing takes the process's children with it (ffmpeg, LaTeX), since each worker leads its own
process group.

Calls block, so the server makes them from threads of its own (see jobs.py), never from the
event loop.
"""
from __future__ import annotations

import atexit
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
import traceback
import weakref
from contextlib import suppress
from typing import Any, Callable

from manim_verbose.editor.backend import is_cancellation, render_error_problems

log = logging.getLogger("manim_verbose.editor")

POLL_INTERVAL = 0.05


class WorkerError(Exception):
    """A render which didn't finish, for a reason to do with its process rather than the document."""


class WorkerCrashed(WorkerError):
    def __init__(self, exitcode: int | None):
        self.exitcode = exitcode
        super().__init__(f"The render process stopped unexpectedly (exit code {exitcode})")


class WorkerTimeout(WorkerError):
    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f"The render took longer than {seconds:g} seconds and was stopped")


class WorkerCancelled(WorkerError):
    def __init__(self):
        super().__init__("The render was cancelled")


class RenderProblems(Exception):
    """The render reported problems with the document (a RenderError, in the worker)."""

    def __init__(self, problems: list[dict[str, Any]]):
        self.problems = problems
        super().__init__("; ".join(p.get("message", "") for p in problems))


class RenderException(Exception):
    """Something unexpected went wrong inside the render; `details` has the worker's traceback."""

    def __init__(self, message: str, details: str):
        self.details = details
        super().__init__(message)


_live: "weakref.WeakSet[WorkerProcess]" = weakref.WeakSet()


class WorkerProcess:
    def __init__(self, backend: Any, name: str = "worker", start_timeout: float = 120.0,
                 cancel_grace: float = 5.0):
        self.backend = backend
        self.name = name
        self.start_timeout = start_timeout
        self.cancel_grace = cancel_grace
        self._context = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._process = None
        self._conn = None
        self._cancel_event = None
        self._ready = False
        self._closed = False
        self.starts = 0
        _live.add(self)

    @property
    def pid(self) -> int | None:
        process = self._process
        return process.pid if process is not None else None

    def is_alive(self) -> bool:
        process = self._process
        return process is not None and process.is_alive()

    def start(self) -> None:
        """Start the process if it isn't running. Doesn't wait for it to be ready."""
        with self._lock:
            if self._closed or (self._process is not None and self._process.is_alive()):
                return
            self._discard()
            parent_conn, child_conn = self._context.Pipe()
            cancel_event = self._context.Event()
            process = self._context.Process(
                target=worker_main,
                args=(child_conn, self.backend, cancel_event, os.getpid()),
                name=f"manim-editor-{self.name}",
            )
            process.start()
            child_conn.close()
            self._process, self._conn, self._cancel_event = process, parent_conn, cancel_event
            self._ready = False
            self.starts += 1
            log.debug("started %s worker, pid %s", self.name, process.pid)

    def call(self, fn: Callable[..., Any], kwargs: dict[str, Any], timeout: float,
             progress: Callable[[float, str], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> Any:
        """
        Run `fn(backend, progress=..., cancel=..., **kwargs)` in the worker and return what it
        returns. Raises RenderProblems or RenderException for what went wrong inside, and
        WorkerTimeout, WorkerCrashed or WorkerCancelled when the process had to be given up on.
        `cancelled` is polled while the call runs; once it returns True the worker's cancel()
        starts returning True, and the process is killed if the call hasn't ended
        `cancel_grace` seconds later.
        """
        self.start()
        if self._closed:
            raise WorkerCrashed(None)
        self._wait_ready()
        conn, cancel_event = self._conn, self._cancel_event
        if conn is None or cancel_event is None:
            raise self._crashed()
        cancel_event.clear()
        try:
            conn.send((fn, kwargs))
        except (OSError, EOFError):
            raise self._crashed()
        deadline = time.monotonic() + timeout
        cancel_deadline = None
        while True:
            try:
                ready = conn.poll(POLL_INTERVAL)
            except (OSError, EOFError):
                raise self._crashed()
            if ready:
                try:
                    message = conn.recv()
                except (OSError, EOFError):
                    raise self._crashed()
                kind = message[0]
                if kind == "ok":
                    return message[1]
                if kind == "cancelled":
                    raise WorkerCancelled()
                if kind == "render_error":
                    raise RenderProblems(message[1])
                if kind != "progress":
                    raise RenderException(message[1], message[2])
                if progress is not None and cancel_deadline is None:
                    progress(message[1], message[2])
            elif not self.is_alive():
                raise self._crashed()
            now = time.monotonic()
            if cancel_deadline is None and cancelled is not None and cancelled():
                cancel_event.set()
                cancel_deadline = now + self.cancel_grace
            if cancel_deadline is not None and now >= cancel_deadline:
                self.kill()
                raise WorkerCancelled()
            if now >= deadline:
                log.warning("%s worker ran past %gs; killing it", self.name, timeout)
                self.kill()
                raise WorkerTimeout(timeout)

    def _wait_ready(self) -> None:
        if self._ready:
            return
        conn = self._conn
        if conn is None:
            raise self._crashed()
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            try:
                if conn.poll(POLL_INTERVAL):
                    message = conn.recv()
                    if message[0] == "ready":
                        self._ready = True
                        return
            except (OSError, EOFError):
                raise self._crashed()
            if not self.is_alive():
                raise self._crashed()
        self.kill()
        raise WorkerTimeout(self.start_timeout)

    def _crashed(self) -> WorkerCrashed:
        process = self._process
        exitcode = None
        if process is not None:
            process.join(timeout=1)
            exitcode = process.exitcode
        if not self._closed:
            log.warning("%s worker stopped unexpectedly (exit code %s)", self.name, exitcode)
        self.kill()
        return WorkerCrashed(exitcode)

    def kill(self) -> None:
        """Kill the process and everything it started, at once."""
        with self._lock:
            process = self._process
            if process is not None and process.pid is not None and process.is_alive():
                _kill_tree(process.pid)
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
            self._discard()

    def stop(self, timeout: float = 3.0) -> None:
        """Ask the process to finish, and kill it if it doesn't within `timeout`. It isn't started again."""
        self._closed = True
        process, conn = self._process, self._conn
        if process is not None and process.is_alive() and conn is not None:
            with suppress(OSError, EOFError, ValueError):
                conn.send(None)
            process.join(timeout=timeout)
        self.kill()

    def _discard(self) -> None:
        if self._conn is not None:
            with suppress(OSError):
                self._conn.close()
        if self._process is not None:
            with suppress(ValueError, AssertionError):
                self._process.close()
        self._process = self._conn = self._cancel_event = None
        self._ready = False


def _kill_tree(pid: int) -> None:
    if hasattr(os, "killpg"):
        with suppress(OSError):
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
                return
    with suppress(OSError):
        os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)


@atexit.register
def _kill_all() -> None:
    """Workers aren't daemonic (renders may start processes of their own), so don't leave any behind."""
    for worker in list(_live):
        with suppress(Exception):
            worker.kill()


# In the worker process

def worker_main(conn, backend: Any, cancel_event, parent_pid: int) -> None:
    if hasattr(os, "setsid"):
        with suppress(OSError):
            os.setsid()
    with suppress(ValueError, OSError):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    _exit_with_parent(parent_pid)
    try:
        backend.warm()
    except Exception:
        traceback.print_exc()
    conn.send(("ready", os.getpid()))
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            break
        if message is None:
            break
        fn, kwargs = message
        reply = _run(fn, backend, kwargs, conn, cancel_event)
        try:
            conn.send(reply)
        except (OSError, EOFError):
            break
        except Exception as err:
            conn.send(("error", f"The render's result couldn't be sent back: {err}", traceback.format_exc()))


def _run(fn, backend, kwargs, conn, cancel_event) -> tuple:
    def progress(fraction: float, message: str = "") -> None:
        conn.send(("progress", float(fraction), str(message)))

    try:
        return ("ok", fn(backend, progress=progress, cancel=cancel_event.is_set, **kwargs))
    except (Exception, SystemExit) as err:
        if is_cancellation(err):
            return ("cancelled",)
        problems = render_error_problems(err)
        if problems is not None:
            return ("render_error", problems)
        return ("error", f"{type(err).__name__}: {err}", traceback.format_exc())


def _exit_with_parent(parent_pid: int) -> None:
    """A worker whose server has gone (killed, say, so it never asked the worker to stop) stops too."""
    def watch():
        while True:
            time.sleep(1.0)
            if os.getppid() != parent_pid:
                with suppress(Exception):
                    sys.stderr.flush()
                os._exit(0)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()
