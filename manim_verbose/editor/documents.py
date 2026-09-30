"""
The one scene file the server edits: reading it, saving it, and noticing when it changes.

Every version of the file the server has seen gets a revision number. A browser tab saves by
saying which revision its edits were made to; if that is not the latest, because another tab
saved in between or the file was changed on disk, the save is refused and the tab is handed
what is there now, rather than one of the two sets of changes silently winning. Changes on
disk are noticed by hashing the file whenever the document is asked for or saved, which for a
file of this size costs next to nothing and, unlike modification times, cannot be fooled.

What is written back is the canonical form (see scenefile/files.py), in the file's own format.
Writes go to a temporary file beside the real one which then replaces it, so that a failed or
interrupted save leaves the old file whole.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manim_verbose.scenefile.files import dump_text, format_of, parse_text, to_data
from manim_verbose.scenefile.model import Document, iter_steps
from manim_verbose.scenefile.validate import Problem, assign_step_ids, check_document, validate_data


def read_document(data: Any) -> tuple[Document | None, list[Problem]]:
    """
    Check a document given as data, and give every step an id. The problems are found after
    the ids are given, so that each problem about a step can name it.
    """
    doc, problems = validate_data(data)
    if doc is None:
        return None, problems
    if any(step.id is None for scene in doc.scenes for step in iter_steps(scene.steps)):
        assign_step_ids(doc)
        problems = check_document(doc)
    return doc, problems


def problems_json(problems: list[Problem]) -> list[dict[str, Any]]:
    return [p.to_json() for p in problems]


class Conflict(Exception):
    """A save made against a revision which is no longer the latest."""

    def __init__(self, current: dict[str, Any]):
        self.current = current
        super().__init__("The document changed since it was loaded")


class Unreadable(Exception):
    """A save of something the models can't read as a document at all."""

    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


class SaveFailed(Exception):
    def __init__(self, path: Path, err: OSError):
        self.path = path
        reason = err.strerror or str(err)
        super().__init__(f"Couldn't save {path.name}: {reason}. Your changes are still in the editor")


@dataclass
class Snapshot:
    document: dict[str, Any] | None
    revision: int
    problems: list[Problem]
    doc: Document | None


class DocumentStore:
    """
    The scene file and what the server knows about it. Safe to use from several threads;
    each method holds the store's lock for as long as it runs.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.format = format_of(self.path)
        self.base_dir = self.path.parent
        self.revision = 0
        self._lock = threading.RLock()
        self._digest: str | None = None
        self._doc: Document | None = None
        self._data: dict[str, Any] | None = None
        self._problems: list[Problem] = []
        self.refresh()
        self.revision = max(self.revision, 1)

    def refresh(self) -> bool:
        """Read the file again if it changed since the store last read or wrote it."""
        with self._lock:
            try:
                raw = self.path.read_bytes()
            except FileNotFoundError:
                if self._digest is None:
                    self._problems = [Problem(f"{self.path.name} doesn't exist yet; saving will create it")]
                return False
            except OSError as err:
                self._problems = [Problem(f"Couldn't read {self.path.name}: {err.strerror or err}")]
                return False
            digest = _digest(raw)
            if digest == self._digest:
                return False
            self._digest = digest
            self._load(raw)
            self.revision += 1
            return True

    def _load(self, raw: bytes) -> None:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            self._doc, self._data = None, None
            self._problems = [Problem(f"{self.path.name} isn't a text file (it has to be saved as UTF-8)")]
            return
        data, problems = parse_text(text, self.format)
        doc = None
        if not problems:
            doc, problems = read_document(data)
        self._doc = doc
        self._data = to_data(doc) if doc is not None else None
        self._problems = problems

    def snapshot(self, refresh: bool = True) -> Snapshot:
        with self._lock:
            if refresh:
                self.refresh()
            return Snapshot(self._data, self.revision, list(self._problems), self._doc)

    def save(self, data: Any, base_revision: int) -> Snapshot:
        """
        Save a document made from `base_revision`. Raises Conflict when that isn't the latest
        revision, Unreadable when the models can't read it, and SaveFailed when the disk won't
        take it. A document which reads but has errors is saved all the same. Saving what is
        already there writes nothing and keeps the revision.
        """
        with self._lock:
            self.refresh()
            if base_revision != self.revision:
                raise Conflict(self._current_json())
            doc, problems = read_document(data)
            if doc is None:
                raise Unreadable(problems)
            canonical = to_data(doc)
            if self._doc is not None and canonical == self._data and self.path.exists():
                return Snapshot(self._data, self.revision, list(self._problems), self._doc)
            text = dump_text(doc, self.format).encode("utf-8")
            try:
                atomic_write(self.path, text)
            except OSError as err:
                raise SaveFailed(self.path, err) from err
            self._digest = _digest(text)
            self._doc, self._data, self._problems = doc, canonical, problems
            self.revision += 1
            return Snapshot(self._data, self.revision, list(problems), doc)

    def _current_json(self) -> dict[str, Any]:
        return {"document": self._data, "revision": self.revision, "problems": problems_json(self._problems)}


def atomic_write(path: Path, content: bytes) -> None:
    """
    Replace a file's content all at once: written to a temporary file in the same folder,
    flushed to disk, then renamed over the original. The file keeps its permissions.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            mode = path.stat().st_mode & 0o7777
        except FileNotFoundError:
            mode = 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            tmp.unlink()
        raise


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
