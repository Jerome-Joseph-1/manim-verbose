"""
That scene files are checked, and that what is wrong is said in words someone who has never
seen Python could act on. The messages are asserted on, not just the failure, because the
messages are the product here.
"""
from __future__ import annotations

import textwrap

import pytest

from manim_verbose.scenefile.files import dump_text, load_text
from manim_verbose.scenefile.validate import has_errors


def load(yaml_text: str):
    return load_text(textwrap.dedent(yaml_text))


def messages(yaml_text: str) -> list[str]:
    _, problems = load(yaml_text)
    return [f"{p.severity}: {p.path}: {p.message}" for p in problems]


def test_minimal_document_is_fine():
    doc, problems = load("""
        scenes:
          - id: intro
            objects:
              - {id: hello, type: text, text: Hello}
            steps:
              - {do: show, target: hello}
    """)
    assert problems == []
    assert doc.scenes[0].steps[0].id == "intro_1"


@pytest.mark.parametrize("yaml_text, expected", [
    (
        "scenes: [{id: a, objects: [{id: eq, type: tex, tex: x, fnt_size: 3}]}]",
        "error: scenes[0].objects[0].fnt_size: 'fnt_size' isn't something a tex object has (did you mean 'font_size'?)",
    ),
    (
        "scenes: [{id: a, objects: [{id: t, type: txt, text: hi}]}]",
        "error: scenes[0].objects[0]: There's no kind of object called 'txt' (did you mean 'text'?)",
    ),
    (
        "scenes: [{id: a, steps: [{target: x}]}]",
        "error: scenes[0].steps[0]: Every step needs `do`, saying what it does, such as `do: show`",
    ),
    (
        "scenes: [{id: a, objects: [{id: t, type: text}]}]",
        "error: scenes[0].objects[0].text: a text object needs 'text'",
    ),
    (
        "scenes: [{id: a, objects: [{id: v, type: vector, tip: [1]}]}]",
        "error: scenes[0].objects[0].tip: 'tip' is a point, written [x, y] or [x, y, z]",
    ),
    (
        "scenes: [{id: a, objects: [{id: t, type: text, text: hi, color: blu}]}]",
        "error: scenes[0].objects[0].color: 'blu' isn't a color",
    ),
    (
        "scenes: [{id: 1a}]",
        "error: scenes[0].id: '1a' can't be a name",
    ),
])
def test_model_errors_are_reworded(yaml_text, expected):
    found = messages(yaml_text)
    assert any(m.startswith(expected) for m in found), found


def test_whole_document_checks():
    found = messages("""
        scenes:
          - id: intro
            objects:
              - {id: plane, type: number_plane}
              - {id: eq, type: tex, tex: "a^2+b^2=c^2", place: {next_to: lbl}}
              - {id: lbl, type: text, text: hi, place: {next_to: eq}}
              - {id: v, type: vector, tip: [1, 2], on: eq}
              - {id: img, type: image, path: ../secret.png}
              - {id: w, type: vector, tip: [1, 2], on: plane}
            steps:
              - {do: show, target: [plane, w]}
              - {do: highlight, target: eq, part: "d^2"}
              - {do: change, target: w, set: {colour: RED}}
              - {do: hide, target: eqq}
              - {do: show, target: plane}
    """)
    expected = [
        "error: scenes[0].objects[3].on: 'eq' is a tex, but this needs a number plane or axes or axes 3d or number line",
        "error: scenes[0].objects[4].path: Files have to be in the scene file's folder or below it",
        "error: scenes[0].objects[1]: These objects are each placed by another, in a circle: eq -> lbl -> eq",
        "error: scenes[0].steps[1].part: 'd^2' doesn't appear in 'eq'",
        "error: scenes[0].steps[2].set.colour: 'colour' isn't something a vector has (did you mean 'color'?)",
        "error: scenes[0].steps[3].target: There's no object called 'eqq' in scene 'intro' (did you mean 'eq'?)",
        "warning: scenes[0].steps[1].target: 'eq' isn't on screen at this point",
        "warning: scenes[0].steps[4].target: 'plane' is already on screen",
    ]
    for line in expected:
        assert any(m.startswith(line) for m in found), (line, found)
    assert len([m for m in found if "colour" in m]) == 1


def test_yaml_on_and_no_are_not_booleans():
    doc, problems = load("""
        scenes:
          - id: a
            objects:
              - {id: plane, type: number_plane}
              - {id: d, type: dot, point: [1, 1], on: plane}
              - {id: t, type: text, text: no}
    """)
    assert not has_errors(problems), problems
    assert doc.scenes[0].objects[1].on == "plane"
    assert doc.scenes[0].objects[2].text == "no"


def test_canonical_form_round_trips():
    doc, _ = load("""
        title: Round trip
        scenes:
          - id: a
            objects:
              - {id: t, type: text, text: "two\\nlines", place: top, color: blue}
              - {id: v, type: vector, tip: [1, 2]}
            steps:
              - {do: show, target: [t, v]}
              - {do: wait, duration: 2}
    """)
    text = dump_text(doc)
    assert "version: 1" in text.splitlines()[0]
    assert "tip: [1, 2]" in text
    assert "color: BLUE" in text
    again, problems = load_text(text)
    assert problems == []
    assert again == doc
    assert dump_text(again) == text


def test_schema_file_is_up_to_date():
    from manim_verbose.scenefile.schema import SCHEMA_PATH, schema_text
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_text(), (
        "schema.json is out of date: run `manimgl-scene schema --write`"
    )
