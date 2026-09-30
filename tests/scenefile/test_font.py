"""
That settings.font is the font for every text and caption in a document, that an object
naming its own font keeps it, and that one document's font doesn't carry over into the next
one a process renders, as it would into a server's warm render worker.
"""
from __future__ import annotations

import textwrap

from manim_verbose.scenefile import render
from manim_verbose.scenefile.codegen import document_to_python
from manim_verbose.scenefile.files import load_text
from manim_verbose.scenefile.runtime import MANIM_DEFAULT_FONT, RenderPlan


def doc_from(yaml_text: str):
    doc, problems = load_text(textwrap.dedent(yaml_text))
    assert doc is not None and not [p for p in problems if p.severity == "error"], problems
    return doc


def run(doc):
    job = render.prepare_job(doc, doc.scenes[0].id)
    return render.run_job(job, RenderPlan(still=True, headless=True), 256, 144, 15)


WITH_FONT = """
    settings: {font: DejaVu Serif}
    scenes:
      - id: a
        objects:
          - {id: t, type: text, text: Serif}
          - {id: m, type: text, text: Mono, font: DejaVu Sans Mono}
          - {id: title, type: title, text: Heading}
        steps:
          - {do: show, target: [t, m, title], caption: Words}
"""

WITHOUT_FONT = """
    scenes:
      - id: b
        objects:
          - {id: t, type: text, text: Default}
        steps:
          - {do: show, target: t}
"""


def test_document_font_is_generated_once_per_scene():
    code = document_to_python(doc_from(WITH_FONT))
    assert code.count('default_font = "DejaVu Serif"') == 1
    assert "default_font" not in document_to_python(doc_from(WITHOUT_FONT))


def test_text_takes_the_document_font_unless_it_names_its_own():
    scene = run(doc_from(WITH_FONT))
    assert scene.objects["t"].font == "DejaVu Serif"
    assert scene.objects["m"].font == "DejaVu Sans Mono"
    titles = [m for m in scene.objects["title"].get_family() if hasattr(m, "font")]
    assert titles and all(m.font == "DejaVu Serif" for m in titles)


def test_font_does_not_carry_over_to_the_next_document():
    run(doc_from(WITH_FONT))
    scene = run(doc_from(WITHOUT_FONT))
    assert scene.objects["t"].font == MANIM_DEFAULT_FONT
