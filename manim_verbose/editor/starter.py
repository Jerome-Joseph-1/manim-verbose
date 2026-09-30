"""
The document a new scene file starts as, when `manimgl-editor` is given a file which doesn't
exist yet: a short video which shows off what the format does, for its author to change.

It is the "welcome" template (manim_verbose/templates/welcome.yaml), which sticks to objects
which render without LaTeX, so that someone's very first preview works whatever is installed.
It is written out in canonical form, in the new file's own format.
"""
from __future__ import annotations

from pathlib import Path

from manim_verbose.editor.documents import atomic_write, read_document
from manim_verbose.scenefile.files import dump_text, format_of, parse_text

STARTER_YAML = (Path(__file__).resolve().parents[1] / "templates" / "welcome.yaml").read_text(encoding="utf-8")


def write_starter(path: str | Path) -> None:
    """Create a scene file holding the starter document, in canonical form."""
    path = Path(path)
    data, problems = parse_text(STARTER_YAML)
    doc, problems = read_document(data)
    if doc is None:
        raise ValueError(f"The starter document is broken: {problems}")
    atomic_write(path, dump_text(doc, format_of(path)).encode("utf-8"))
