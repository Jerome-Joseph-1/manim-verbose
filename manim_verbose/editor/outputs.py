"""
The server's output folder: rendered stills, preview clips and exported videos.

    <output dir>/stills/<key>.png     a still, with <key>.json beside it holding its object boxes
    <output dir>/clips/<key>.mp4      a preview clip
    <output dir>/exports/<name>.mp4   an exported video

Stills and clips are named by a hash of everything that decides what they look like (see
`cache_key`), which makes the folder itself the cache: a still asked for twice is drawn once,
even across restarts of the server. Only the newest few thousand are kept. Renders are written
under a temporary name and renamed into place when finished, so a half written file is never
served.

Nothing outside this folder is ever served; `resolve` is the one way a request's path becomes
a file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from typing import Any

import appdirs

KINDS = {"stills": ".png", "clips": ".mp4", "exports": ".mp4"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")
KEY = re.compile(r"^[0-9a-f]{64}$")
PARTIAL_PREFIX = ".partial-"


def default_output_dir(scene_file: Path) -> Path:
    """A folder in the user's cache for each scene file, so that scene folders stay tidy."""
    scene_file = scene_file.resolve()
    tag = hashlib.sha256(str(scene_file).encode()).hexdigest()[:12]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", scene_file.stem)[:40] or "scene"
    return Path(appdirs.user_cache_dir("manim-verbose")) / "editor" / f"{stem}-{tag}"


def cache_key(*parts: Any) -> str:
    text = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def file_stamps(scene: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """
    Size and modification time of each file a scene's objects draw (images, svgs), so that
    replacing a picture on disk makes its stills stale.
    """
    paths = set()
    for obj in scene.get("objects", []):
        if isinstance(obj.get("path"), str):
            paths.add(obj["path"])
    for step in scene.get("steps", []):
        changes = step.get("set")
        if isinstance(changes, dict) and isinstance(changes.get("path"), str):
            paths.add(changes["path"])
    stamps = {}
    for rel in sorted(paths):
        try:
            info = (base_dir / rel).stat()
            stamps[rel] = [info.st_size, info.st_mtime_ns]
        except (OSError, ValueError):
            stamps[rel] = None
    return stamps


class OutputDir:
    def __init__(self, root: str | Path, cached_stills: int = 2000, cached_clips: int = 200):
        self.root = Path(root).expanduser().resolve()
        for kind in KINDS:
            (self.root / kind).mkdir(parents=True, exist_ok=True)
        self._caps = {"stills": cached_stills, "clips": cached_clips}
        self._lock = threading.Lock()
        self._stills: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._stored = {"stills": 0, "clips": 0}
        self._clean_partials()
        for kind in self._caps:
            self.prune(kind)

    def dir(self, kind: str) -> Path:
        return self.root / kind

    @staticmethod
    def url(kind: str, name: str) -> str:
        return f"/files/{kind}/{name}"

    def partial(self, kind: str) -> Path:
        """A fresh temporary path for a render in progress; nothing serves these."""
        return self.root / kind / f"{PARTIAL_PREFIX}{uuid.uuid4().hex}{KINDS[kind]}"

    def resolve(self, kind: str, name: str) -> Path | None:
        """The file a /files/{kind}/{name} request names, or None if it names nothing servable."""
        suffix = KINDS.get(kind)
        if suffix is None or not NAME.match(name) or ".." in name or not name.endswith(suffix):
            return None
        folder = (self.root / kind).resolve()
        try:
            path = (folder / name).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if path.parent != folder or not path.is_file():
            return None
        return path

    # Stills

    def still(self, key: str) -> dict[str, Any] | None:
        """A cached still's response (image_url, width, height, objects), or None."""
        with self._lock:
            entry = self._stills.get(key)
            if entry is not None:
                self._stills.move_to_end(key)
        png = self.root / "stills" / f"{key}.png"
        if entry is None:
            meta = self.root / "stills" / f"{key}.json"
            try:
                entry = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if not isinstance(entry, dict) or not png.is_file():
                return None
            self._remember(key, entry)
        elif not png.is_file():
            with self._lock:
                self._stills.pop(key, None)
            return None
        with suppress(OSError):
            os.utime(png)
        return dict(entry)

    def store_still(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        """File a finished render (data from backend.run_still) under its key; returns the response."""
        rendered = Path(data["path"])
        png = self.root / "stills" / f"{key}.png"
        os.replace(rendered, png)
        entry = {
            "image_url": self.url("stills", png.name),
            "width": data["width"],
            "height": data["height"],
            "objects": data["objects"],
        }
        meta = self.root / "stills" / f"{key}.json"
        tmp = meta.with_name(f"{PARTIAL_PREFIX}{uuid.uuid4().hex}.json")
        tmp.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(tmp, meta)
        self._remember(key, entry)
        self._count_store("stills")
        return dict(entry)

    def _remember(self, key: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self._stills[key] = entry
            self._stills.move_to_end(key)
            while len(self._stills) > self._caps["stills"]:
                self._stills.popitem(last=False)

    # Clips

    def clip(self, key: str) -> str | None:
        path = self.root / "clips" / f"{key}.mp4"
        if not path.is_file():
            return None
        with suppress(OSError):
            os.utime(path)
        return self.url("clips", path.name)

    def store_clip(self, key: str, data: dict[str, Any]) -> str:
        path = self.root / "clips" / f"{key}.mp4"
        os.replace(Path(data["path"]), path)
        self._count_store("clips")
        return self.url("clips", path.name)

    # Exports

    def store_export(self, rendered: Path, name: str) -> str:
        path = self.root / "exports" / name
        os.replace(rendered, path)
        return self.url("exports", name)

    # Housekeeping

    def discard(self, path: str | Path | None) -> None:
        if path:
            with suppress(OSError):
                Path(path).unlink()

    def _count_store(self, kind: str) -> None:
        with self._lock:
            self._stored[kind] += 1
            due = self._stored[kind] % 50 == 0
        if due:
            self.prune(kind)

    def prune(self, kind: str) -> None:
        """Delete the least recently used renders of a kind beyond the number kept."""
        folder = self.root / kind
        suffix = KINDS[kind]
        entries = []
        with suppress(OSError):
            for path in folder.iterdir():
                if path.suffix == suffix and KEY.match(path.stem):
                    with suppress(OSError):
                        entries.append((path.stat().st_mtime, path))
        excess = len(entries) - self._caps[kind]
        if excess <= 0:
            return
        entries.sort()
        for _, path in entries[:excess]:
            with suppress(OSError):
                path.unlink()
            if kind == "stills":
                with suppress(OSError):
                    path.with_suffix(".json").unlink()
                with self._lock:
                    self._stills.pop(path.stem, None)

    def _clean_partials(self, older_than: float = 3600.0) -> None:
        """Renders left half done by a server which was killed."""
        cutoff = time.time() - older_than
        for kind in KINDS:
            with suppress(OSError):
                for path in (self.root / kind).iterdir():
                    if path.name.startswith(PARTIAL_PREFIX):
                        with suppress(OSError):
                            if path.stat().st_mtime < cutoff:
                                path.unlink()
