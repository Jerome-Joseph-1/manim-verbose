"""
The document a new scene file starts as, when `manimgl-editor` is given a file which doesn't
exist yet: a short video which shows off what the format does, for its author to change.

It sticks to objects which render without LaTeX, so that someone's very first preview works
whatever is installed. It is kept here as YAML, as a person would write it, and written out in
canonical form, in the new file's own format.
"""
from __future__ import annotations

from pathlib import Path

from manim_verbose.editor.documents import atomic_write, read_document
from manim_verbose.scenefile.files import dump_text, format_of, parse_text

STARTER_YAML = """\
version: 1
title: My first video
scenes:
  - id: hello
    title: Hello
    objects:
      - {id: greeting, type: text, text: "Hello!", font_size: 72, color: BLUE}
      - {id: hint, type: text, text: "Click anything in the picture to change it", font_size: 30,
         place: {next_to: greeting, side: down, buff: 0.5}}
    steps:
      - {do: show, target: greeting, caption: "A video is made of scenes, and a scene of steps"}
      - {do: show, target: hint, style: fade_up}
      - {do: highlight, target: greeting, style: wiggle}
      - {do: wait, duration: 1}
      - {do: clear}
  - id: shapes
    title: Shapes that move
    objects:
      - {id: circle, type: circle, radius: 1.2, color: BLUE, fill: BLUE, place: [-3, 0]}
      - {id: square, type: square, side: 2, color: YELLOW, fill: YELLOW, place: [3, 0]}
      - {id: arrow, type: line, start: [-1.5, 0], end: [1.5, 0], arrow: true}
    steps:
      - {do: show, target: circle, caption: "Objects wait off screen until a step shows them"}
      - {do: show, target: arrow}
      - {do: transform, target: circle, into: square, keep: true, caption: "One thing can turn into another"}
      - {do: move, target: square, to: {edge: top}}
      - {do: change, target: square, set: {color: GREEN, fill: GREEN}, caption: "Or change color"}
      - {do: wait, duration: 2}
"""


def write_starter(path: str | Path) -> None:
    """Create a scene file holding the starter document, in canonical form."""
    path = Path(path)
    data, problems = parse_text(STARTER_YAML)
    doc, problems = read_document(data)
    if doc is None:
        raise ValueError(f"The starter document is broken: {problems}")
    atomic_write(path, dump_text(doc, format_of(path)).encode("utf-8"))
