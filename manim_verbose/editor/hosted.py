"""
Putting the editor on the public internet, safely.

Run locally, the editor edits one file on disk for one trusted person; the limits in
limits.py are only there to keep a runaway request from freezing it. Run as a public service
(the UI on Vercel, this server on Cloud Run — see docs/editor/HOSTING.md) it renders whatever
strangers send, so it needs harder edges. Hosted mode (``manimgl-editor --hosted``, or
``MANIM_VERBOSE_HOSTED=1`` for a container) turns those on:

- No file on the server. Every render request already carries the whole document, so
  rendering is stateless; the document lives in the browser (localStorage, download/open).
  ``GET``/``PUT /api/document`` and ``/api/timeline`` answer 404, and ``/api/config`` tells
  the UI it is hosted so it switches to browser storage.
- Smaller documents (fewer scenes, steps, bytes), a cap on total video length, and a cap on
  export quality, so no one request asks for hours of rendering.
- Per-IP rate limits on stills, clips and exports, a global cap on concurrent preview
  renders, and shorter per-render time limits.
- Uploaded images and svgs are refused (there is nowhere to put them, and a path must never
  reach the container's own files), and renders read from an empty, isolated folder.
- Rendered files expire and are swept up, so the container's disk can't fill.
- An optional password (HTTP basic auth) to keep a demo private.

This module holds the configuration and the mechanisms; server.py wires them into the app.
Nothing here imports server.py, so there is no cycle: functions return plain problem data and
booleans, and server.py turns them into responses.
"""
from __future__ import annotations

import base64
import logging
import os
import secrets
import tempfile
import threading
import time
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from manim_verbose.editor.limits import Limits
from manim_verbose.editor.outputs import KINDS, OutputDir
from manim_verbose.scenefile.validate import Problem

log = logging.getLogger("manim_verbose.editor")

ENV_FLAG = "MANIM_VERBOSE_HOSTED"
ENV_PASSWORD = "MANIM_VERBOSE_HOSTED_PASSWORD"

# Qualities in order of cost; the hosted cap can't be raised past the highest it names.
_QUALITY_ORDER = ("low", "medium", "hd", "uhd")


def _problem(message: str, loc: list[str | int] | None = None, scene_id: str | None = None,
             item_id: str | None = None) -> dict[str, Any]:
    return Problem(message, list(loc or []), "error", scene_id, item_id).to_json()


@dataclass(frozen=True)
class RateLimit:
    """At most `max_requests` in any window of `per_seconds`."""
    max_requests: int
    per_seconds: float


@dataclass(frozen=True)
class HostedConfig:
    """
    Every knob hosted mode turns. The defaults are sized for Cloud Run's free tier (2 vCPU,
    scale to zero): generous enough to try the editor out, mean enough that no one visitor can
    run the monthly budget down. docs/editor/HOSTING.md explains how to change them.
    """
    enabled: bool = True
    # Document shape (also enforced as request-size limits, so oversize bodies get 413)
    max_document_bytes: int = 512 * 1024
    max_scenes: int = 20
    max_objects: int = 200          # per scene
    max_steps: int = 200            # per scene, counting those inside `together`
    max_total_duration: float = 300.0   # seconds of finished video, across every scene
    # Rendering
    max_still_width: int = 1920
    max_export_quality: str = "medium"   # 720p; never more than this
    still_timeout: float = 30.0
    clip_timeout: float = 120.0
    export_timeout: float = 900.0        # matches Cloud Run's request timeout
    max_concurrent_renders: int = 2      # preview clips (and exports) rendering at once
    max_pending_exports: int = 3
    # Per-IP rate limits
    still_rate: RateLimit = RateLimit(90, 60.0)
    clip_rate: RateLimit = RateLimit(20, 60.0)
    export_rate: RateLimit = RateLimit(6, 300.0)
    # Housekeeping
    output_ttl: float = 3600.0           # a rendered file is served for an hour, then swept up
    reap_interval: float = 300.0
    # Access
    allow_uploads: bool = False
    password: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **overrides: Any) -> "HostedConfig":
        env = os.environ if env is None else env
        values: dict[str, Any] = {"password": (env.get(ENV_PASSWORD) or None)}
        # A handful of knobs are worth setting from the environment for a container
        for name, cast in (("max_total_duration", float), ("max_concurrent_renders", int),
                           ("max_pending_exports", int), ("output_ttl", float)):
            raw = env.get(f"{ENV_FLAG}_{name.upper()}")
            if raw:
                with suppress(ValueError):
                    values[name] = cast(raw)
        values.update(overrides)
        if values.get("max_export_quality") not in (None, *(_QUALITY_ORDER)):
            values.pop("max_export_quality")
        return cls(**values)

    def to_limits(self, base: Limits | None = None) -> Limits:
        """The server-wide limits hosted mode runs with: reuse the existing size, width,
        timeout and export-queue machinery rather than re-checking those by hand."""
        base = base or Limits()
        return replace(
            base,
            max_body_bytes=self.max_document_bytes,
            max_scenes=self.max_scenes,
            max_objects=self.max_objects,
            max_steps=self.max_steps,
            max_still_width=self.max_still_width,
            still_timeout=self.still_timeout,
            clip_timeout=self.clip_timeout,
            export_timeout=self.export_timeout,
            max_pending_exports=self.max_pending_exports,
        )

    def config_json(self) -> dict[str, Any]:
        """What ``/api/config`` tells the UI, so it can switch to browser storage and show
        the right limits."""
        return {
            "hosted": True,
            "storage": "browser",
            "uploads": self.allow_uploads,
            "auth": bool(self.password),
            "limits": {
                "max_document_bytes": self.max_document_bytes,
                "max_scenes": self.max_scenes,
                "max_objects": self.max_objects,
                "max_steps": self.max_steps,
                "max_total_duration": self.max_total_duration,
                "max_still_width": self.max_still_width,
                "max_export_quality": self.max_export_quality,
                "output_ttl": self.output_ttl,
            },
        }


def local_config_json(version: str = "") -> dict[str, Any]:
    """``/api/config`` when the editor runs locally: it edits a file and keeps nothing in the
    browser."""
    return {"hosted": False, "storage": "server", "uploads": True, "auth": False}


def capped_quality(requested: str, config: HostedConfig) -> str:
    """The quality actually rendered: never costlier than the hosted cap."""
    ceiling = config.max_export_quality
    if requested not in _QUALITY_ORDER:
        return ceiling
    if _QUALITY_ORDER.index(requested) <= _QUALITY_ORDER.index(ceiling):
        return requested
    return ceiling


def asset_problems(doc: Any, config: HostedConfig) -> list[dict[str, Any]]:
    """Refuse documents that lean on uploaded files: there is nowhere to upload them, and a
    path must never reach the container's own filesystem."""
    if config.allow_uploads:
        return []
    problems = []
    for s_index, scene in enumerate(doc.scenes):
        for o_index, obj in enumerate(scene.objects):
            if obj.type in ("image", "svg"):
                problems.append(_problem(
                    "The hosted editor can't use uploaded images or SVG files. Remove this object, "
                    "or run the editor on your own computer to use your own files",
                    ["scenes", s_index, "objects", o_index], scene.id, obj.id,
                ))
    return problems


def duration_problems(total: float | None, config: HostedConfig) -> list[dict[str, Any]]:
    """Refuse a document whose finished video would run longer than the cap."""
    if total is None or total <= config.max_total_duration:
        return []
    minutes = config.max_total_duration / 60
    return [_problem(
        f"This video is {total / 60:.1f} minutes long, and the hosted editor renders at most "
        f"{minutes:g} minutes. Shorten it, or split it across files (you can render longer "
        "videos by running the editor on your own computer)",
        ["scenes"],
    )]


def total_duration(editor: Any, doc: Any) -> float | None:
    """The finished video's length in seconds, or None if it can't be worked out (a scene the
    renderer can't time), in which case the render itself will report the problem."""
    try:
        return sum(float(editor.backend.scene_duration(doc, scene.id)) for scene in doc.scenes)
    except Exception:
        return None


# Per-IP rate limiting

def client_ip(request: Any) -> str:
    """The visitor's address. Behind Vercel and Cloud Run the real client is the first hop of
    X-Forwarded-For; fall back to the socket for a direct connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    return client.host if client is not None else "unknown"


class RateLimiter:
    """A sliding window per (address, action). Thread-safe; handlers run in a thread pool."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, ip: str, action: str, limit: RateLimit, now: float | None = None) -> float | None:
        """None if the request is allowed (and counted), otherwise how many seconds until it
        would be."""
        now = time.monotonic() if now is None else now
        cutoff = now - limit.per_seconds
        key = (ip, action)
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit.max_requests:
                return max(0.0, hits[0] + limit.per_seconds - now)
            hits.append(now)
            return None

    def forget_old(self, now: float | None = None, older_than: float = 3600.0) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            for key in list(self._hits):
                hits = self._hits[key]
                while hits and hits[0] <= now - older_than:
                    hits.popleft()
                if not hits:
                    del self._hits[key]


# Global concurrency cap

class RenderGate:
    """A cap on how many preview renders run at once, so a burst can't pin every core. A
    context manager: ``with gate.hold() as ok:`` — ``ok`` is False when the gate is full."""

    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self._in_flight = 0
        self._lock = threading.Lock()

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    def try_acquire(self) -> bool:
        with self._lock:
            if self._in_flight >= self.max_concurrent:
                return False
            self._in_flight += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def hold(self) -> "_Hold":
        return _Hold(self)


class _Hold:
    def __init__(self, gate: RenderGate) -> None:
        self.gate = gate
        self.ok = False

    def __enter__(self) -> "_Hold":
        self.ok = self.gate.try_acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.ok:
            self.gate.release()


# Expiring rendered files

class OutputReaper:
    """Deletes rendered stills, clips and exports older than `ttl`, on a timer and on demand,
    so a long-running container's disk doesn't fill with other people's renders."""

    def __init__(self, outputs: OutputDir, ttl: float, interval: float) -> None:
        self.outputs = outputs
        self.ttl = ttl
        self.interval = max(1.0, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sweep(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cutoff = now - self.ttl
        removed = 0
        for kind in KINDS:
            folder = self.outputs.root / kind
            with suppress(OSError):
                for path in folder.iterdir():
                    if path.name.startswith("."):
                        continue  # a partial render still being written
                    try:
                        old = path.stat().st_mtime < cutoff
                    except OSError:
                        continue
                    if old and _unlink(path):
                        removed += 1
                        if kind == "stills":
                            _unlink(path.with_suffix(".json"))
        if removed:
            log.info("hosted: swept %d expired render(s)", removed)
        return removed

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="output-reaper", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            with suppress(Exception):
                self.sweep()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None


def _unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


# HTTP basic auth

class BasicAuthMiddleware:
    """
    Guard the whole app with one shared password (HTTP basic auth), for keeping a demo
    private. The username is ignored; the password is compared in constant time. Health checks
    (`/api/health`) are left open so an uptime monitor or Cloud Run can reach them.
    """

    def __init__(self, app: Any, password: str, realm: str = "manim editor",
                 exempt: Iterable[str] = ("/api/health",)) -> None:
        self.app = app
        self.password = password
        self.realm = realm
        self.exempt = frozenset(exempt)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path") in self.exempt:
            return await self.app(scope, receive, send)
        if self._authorized(scope):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b'{"problems": [{"message": "This editor is private. Sign in to use it."}]}'
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", f'Basic realm="{self.realm}", charset="UTF-8"'.encode("latin-1")),
        ]})
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, scope: Any) -> bool:
        header = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value.decode("latin-1")
                break
        if not header.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        _, _, supplied = decoded.partition(":")
        return secrets.compare_digest(supplied, self.password)


def isolated_assets_dir() -> Path:
    """An empty folder to render from, so relative image/svg paths in a document (which
    validation already keeps from escaping it) resolve to nothing rather than to the
    container's own files."""
    path = Path(tempfile.mkdtemp(prefix="manim-hosted-assets-")) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ephemeral_output_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="manim-hosted-out-"))
