"""
Who renders what, when.

Stills have a worker process of their own, so that an export running for minutes never holds
up the picture on the canvas. Only the newest still request matters to someone clicking
through steps, so at most one still waits: a new request supersedes the one waiting before it,
which is answered with `Superseded` rather than drawn. The one being drawn is always finished
(and cached), and a request for exactly the still being drawn shares its result.

Clips and exports share a small pool of other worker processes, fed from one queue in which
clips go before exports, since someone is sitting waiting for a clip. An export is tracked as a
`Job`, whose status, progress and message the editor polls.

Each worker process is driven by a thread of its own here, since a call to a worker blocks
until the render ends; the server's event loop only ever waits on futures.
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
import uuid
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass, field
from typing import Any, Callable

from manim_verbose.editor.workers import WorkerCrashed, WorkerProcess, WorkerTimeout

log = logging.getLogger("manim_verbose.editor")


class Superseded(Exception):
    """A still request dropped because a newer one came in while it waited."""


def _settle(future: Future, result: Any = None, error: BaseException | None = None) -> None:
    try:
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)
    except InvalidStateError:
        pass


@dataclass
class Task:
    """
    One call to a worker. `finish` turns the worker's result into the future's result (filing
    the rendered file away, say), and `discard` cleans up after a call which failed.
    """
    fn: Callable[..., Any]
    kwargs: dict[str, Any]
    timeout: float
    key: str | None = None
    seq: int = 0
    priority: int = 0
    finish: Callable[[Any], Any] | None = None
    discard: Callable[[], None] | None = None
    on_start: Callable[[], None] | None = None
    progress: Callable[[float, str], None] | None = None
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    future: Future = field(default_factory=Future)


def _execute(worker: WorkerProcess, task: Task) -> None:
    """Run a task on a worker, settle its future, and get the worker ready for the next one."""
    try:
        result = worker.call(task.fn, task.kwargs, task.timeout, progress=task.progress,
                             cancelled=task.cancel_requested.is_set)
        if task.finish is not None:
            result = task.finish(result)
        _settle(task.future, result)
    except BaseException as err:
        if task.discard is not None:
            try:
                task.discard()
            except Exception:
                log.exception("cleaning up after a failed render")
        _settle(task.future, error=err)
        if isinstance(err, (WorkerCrashed, WorkerTimeout)) or not worker.is_alive():
            try:
                worker.start()
            except Exception:
                log.exception("restarting a render worker")


class StillQueue:
    def __init__(self, worker: WorkerProcess):
        self.worker = worker
        self._cond = threading.Condition()
        self._waiting: Task | None = None
        self._running: Task | None = None
        self._newest = 0
        self._thread: threading.Thread | None = None
        self._closed = False

    @property
    def waiting(self) -> Task | None:
        return self._waiting

    @property
    def running(self) -> Task | None:
        return self._running

    def start(self) -> None:
        """Start the worker process now, so that it has warmed up by the first request."""
        with self._cond:
            self._ensure_thread()
        self.worker.start()

    def note(self, seq: int) -> None:
        """A request numbered `seq` was answered without drawing (from the cache): it still counts as newer."""
        with self._cond:
            if seq > self._newest:
                self._newest = seq
                self._supersede_waiting()

    def submit(self, task: Task) -> Future:
        """
        Queue a still. Requests are numbered as they arrive (task.seq); one which reaches the
        queue after a newer one did is superseded at once.
        """
        with self._cond:
            if self._closed:
                raise RuntimeError("The server is shutting down")
            self._ensure_thread()
            running = self._running
            if running is not None and task.key is not None and running.key == task.key:
                return running.future
            if task.seq < self._newest:
                _settle(task.future, error=Superseded())
                return task.future
            self._newest = task.seq
            self._supersede_waiting()
            self._waiting = task
            self._cond.notify_all()
            return task.future

    def _supersede_waiting(self) -> None:
        if self._waiting is not None:
            _settle(self._waiting.future, error=Superseded())
            self._waiting = None

    def _ensure_thread(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._serve, name="still-queue", daemon=True)
            self._thread.start()

    def _serve(self) -> None:
        while True:
            with self._cond:
                while self._waiting is None and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                task, self._waiting = self._waiting, None
                if not task.future.set_running_or_notify_cancel():
                    continue
                self._running = task
            try:
                _execute(self.worker, task)
            finally:
                with self._cond:
                    self._running = None

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._supersede_waiting()
            self._cond.notify_all()
        self.worker.stop()


class JobPool:
    """A queue of clips and exports, served by `size` worker processes started as needed."""

    def __init__(self, backend: Any, size: int, start_timeout: float, cancel_grace: float):
        self.workers = [
            WorkerProcess(backend, f"jobs-{i}", start_timeout=start_timeout, cancel_grace=cancel_grace)
            for i in range(max(1, size))
        ]
        self._cond = threading.Condition()
        self._heap: list[tuple[int, int, Task]] = []
        self._order = itertools.count()
        self._threads: list[threading.Thread] = []
        self._closed = False

    def submit(self, task: Task) -> Task:
        with self._cond:
            if self._closed:
                raise RuntimeError("The server is shutting down")
            if not self._threads:
                for worker in self.workers:
                    thread = threading.Thread(target=self._serve, args=(worker,), name=f"{worker.name}-queue",
                                              daemon=True)
                    thread.start()
                    self._threads.append(thread)
            heapq.heappush(self._heap, (task.priority, next(self._order), task))
            self._cond.notify()
        return task

    def cancel(self, task: Task) -> None:
        """A queued task is dropped at once; a running one is asked to stop (see WorkerProcess.call)."""
        task.cancel_requested.set()
        task.future.cancel()

    def _serve(self, worker: WorkerProcess) -> None:
        while True:
            with self._cond:
                while not self._heap and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
                _, _, task = heapq.heappop(self._heap)
                if not task.future.set_running_or_notify_cancel():
                    continue
            if task.on_start is not None:
                task.on_start()
            _execute(worker, task)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            for _, _, task in self._heap:
                task.future.cancel()
            self._heap.clear()
            self._cond.notify_all()
        for worker in self.workers:
            worker.stop()


class Job:
    """An export, as the editor sees it."""

    def __init__(self, task: Task | None = None):
        self.job_id = uuid.uuid4().hex[:16]
        self.created = time.time()
        self.status = "queued"
        self.progress = 0.0
        self.message = "Waiting to start"
        self.output_url: str | None = None
        self.problems: list[dict[str, Any]] = []
        self.task = task
        self._lock = threading.Lock()

    def to_json(self) -> dict[str, Any]:
        with self._lock:
            return {
                "job_id": self.job_id, "status": self.status, "progress": round(self.progress, 4),
                "message": self.message, "output_url": self.output_url, "problems": list(self.problems),
            }

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def started(self) -> None:
        with self._lock:
            if self.status == "queued":
                self.status = "running"
                self.message = "Starting"

    def advance(self, fraction: float, message: str) -> None:
        """Progress only ever goes forward, whatever the renderer reports."""
        with self._lock:
            if self.status != "running":
                return
            self.progress = max(self.progress, min(max(float(fraction), 0.0), 0.99))
            if message:
                self.message = message

    def settle(self, status: str, message: str, output_url: str | None = None,
               problems: list[dict[str, Any]] | None = None) -> bool:
        """Move to a final status, unless already in one. Returns whether it moved."""
        with self._lock:
            if self.status in ("done", "failed", "cancelled"):
                return False
            self.status = status
            self.message = message
            if status == "done":
                self.progress = 1.0
                self.output_url = output_url
            self.problems = problems or []
            return True


class JobRegistry:
    """Exports by id, forgetting the oldest finished ones beyond `keep`."""

    def __init__(self, keep: int):
        self.keep = keep
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            finished = [j for j in self._jobs.values() if j.finished]
            for old in sorted(finished, key=lambda j: j.created)[:max(0, len(finished) - self.keep)]:
                del self._jobs[old.job_id]

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pending(self) -> int:
        with self._lock:
            return sum(not j.finished for j in self._jobs.values())

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())
