"""
That scene files turn into Python a person could read and manim can run: the whole module for
a fixture compared against code checked by eye, names which can't be used as they stand made
safe, every line mapped back to what it came from, and every kind of step with every option
coming out as code which compiles.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from fake_blocks import blocks_impl, fake_blocks  # noqa: F401  (fixtures)
from steps_helpers import FIXTURES, STEP_CASES, UPDATE_GOLDEN, case_doc, doc_from, fixture_doc, run_scene

from manim_verbose.scenefile.codegen import (
    CodegenError, document_to_python, generate_module, object_names, py_str, scene_class_name, step_caption,
)
from manim_verbose.scenefile.model import SceneSpec


@pytest.mark.parametrize("scene_id, expected", [
    ("three_views", "ThreeViews"),
    ("intro", "Intro"),
    ("scene2", "Scene2"),
    ("_hidden_", "Hidden"),
    ("x", "X"),
    ("already_CamelCase", "AlreadyCamelCase"),
    # Names manimlib or the runtime already use would hide them from the code after
    ("circle", "CircleScene"),
    ("text", "TextScene"),
    ("doc_scene", "DocSceneScene"),
])
def test_scene_class_names(scene_id, expected):
    assert scene_class_name(SceneSpec(id=scene_id)) == expected


def test_scene_classes_are_unique_within_a_document(fake_blocks):
    doc = doc_from("""
        scenes:
          - {id: a_b}
          - {id: aB}
          - {id: A_b}
    """)
    module = generate_module(doc)
    assert list(module.class_names.values()) == ["AB", "AB2", "AB3"]
    assert "SCENES_IN_ORDER = [AB, AB2, AB3]" in module.code


def test_every_step_fixture_matches_the_code_checked_by_eye(fake_blocks):
    """
    The expected code was read through as a person would read it; a change to what is
    generated shows up here as a diff to read again. Refresh with MANIM_VERBOSE_UPDATE_GOLDEN=1.
    """
    doc = fixture_doc("every_step.yaml")
    code = document_to_python(doc, base_dir=FIXTURES)
    expected = FIXTURES / "every_step.expected.py"
    if UPDATE_GOLDEN or not expected.exists():
        expected.write_text(code, encoding="utf-8")
    assert code == expected.read_text(encoding="utf-8")


def test_generated_code_starts_with_the_imports_and_ends_with_the_scene_order(fake_blocks):
    code = document_to_python(fixture_doc("every_step.yaml"))
    lines = code.splitlines()
    assert "from manimlib import *" in lines[:10]
    assert "from manim_verbose.scenefile.runtime import *" in lines[:10]
    assert lines[-1] == "SCENES_IN_ORDER = [Basics, PlaneView]"
    compile(code, "every_step.py", "exec")


def test_only_the_scenes_asked_for(fake_blocks):
    doc = fixture_doc("every_step.yaml")
    code = document_to_python(doc, scene_ids=["plane_view"])
    assert "class PlaneView(DocScene):" in code
    assert "class Basics" not in code


def test_objects_are_built_in_order_and_shown_ones_added_first(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: label, type: text, text: below, place: {next_to: box}}
              - {id: box, type: square, shown: true}
              - {id: dot, type: dot, point: [1, 1], shown: true}
            steps:
              - {id: s1, do: show, target: label}
    """)
    body = [line.strip() for line in document_to_python(doc).splitlines()]
    box = body.index(next(line for line in body if line.startswith("box = ")))
    label = body.index(next(line for line in body if line.startswith("label = ")))
    assert box < label, "what an object is placed beside has to be built first"
    assert "self.add(box, dot)" in body
    assert body.index("self.add(box, dot)") < body.index('with self.step("s1"):')


@pytest.mark.parametrize("obj_id, variable", [
    ("for", "for_"),
    ("class", "class_"),
    ("self", "self_"),
    ("Circle", "Circle_"),
    ("place", "place_"),
    ("np", "np_"),
    ("print", "print_"),
    ("BLUE", "BLUE_"),
    ("DocScene", "DocScene_"),
    ("eq", "eq"),
])
def test_ids_which_would_hide_something_get_a_variable_of_their_own(obj_id, variable):
    assert object_names([obj_id]).get(obj_id, obj_id) == variable


def test_awkward_ids_generate_code_which_runs(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: for, type: circle}
              - {id: Circle, type: square, place: {next_to: for}}
              - {id: Circle_, type: dot, point: [1, 1]}
              - {id: self, type: group, members: [for, Circle]}
            steps:
              - {do: show, target: self}
              - {do: change, target: for, set: {color: RED}}
              - {do: move, target: Circle_, by: [1, 0]}
              - {do: show, target: Circle_}
    """)
    code = document_to_python(doc)
    assert "for_ = self.obj(\"for\", Circle(" in code
    assert "Circle__ = self.obj(\"Circle\"" in code
    assert "self_ = self.obj(\"self\", VGroup(for_, Circle__))" in code
    scene = run_scene(doc)
    assert set(scene.registered_on_screen()) == {"for", "Circle", "Circle_", "self"}


def test_temporaries_steer_clear_of_object_names(fake_blocks):
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: c, type: circle, shown: true}
              - {id: c_new, type: square, shown: true}
            steps:
              - {do: change, target: c, set: {color: RED}}
    """)
    code = document_to_python(doc)
    assert "c_new_2 = Circle(" in code
    assert "self.play(Transform(c, c_new_2), run_time=1)" in code
    run_scene(doc)


def test_every_line_maps_back_to_what_it_came_from(fake_blocks):
    doc = fixture_doc("every_step.yaml")
    module = generate_module(doc)
    lines = module.code.splitlines()
    for number, line in enumerate(lines, start=1):
        ref = module.line_map.get(number)
        text = line.strip()
        if text.startswith("class ") or text.startswith("def construct"):
            assert ref is not None and ref.kind == "scene"
        if " = self.obj(" in text:
            obj_id = text.split('self.obj("')[1].split('"')[0]
            assert ref.kind == "object" and ref.item_id == obj_id
            scene = next(s for s in doc.scenes if s.id == ref.scene_id)
            assert scene.objects[ref.loc[3]].id == obj_id
        if text.startswith("with self.step("):
            step_id = text.split('self.step("')[1].split('"')[0]
            assert ref.kind == "step" and ref.item_id == step_id
            scene = next(s for s in doc.scenes if s.id == ref.scene_id)
            assert scene.steps[ref.loc[3]].id == step_id
        if text.startswith("self.play(") or text.startswith("self.wait("):
            assert ref.kind == "step"


def test_a_step_which_cannot_be_turned_into_code_says_which(fake_blocks, monkeypatch):
    from manim_verbose.scenefile import blocks

    def refuse(obj, ctx):
        if obj.id == "bad":
            raise ValueError("no such font")
        return "Square()"

    monkeypatch.setattr(blocks, "object_expression", refuse)
    doc = doc_from("""
        scenes:
          - id: s
            objects:
              - {id: good, type: square}
              - {id: bad, type: text, text: x}
    """)
    with pytest.raises(CodegenError) as caught:
        generate_module(doc)
    assert caught.value.ref.item_id == "bad"
    assert caught.value.ref.loc == ("scenes", 0, "objects", 1)
    assert "no such font" in caught.value.message


@pytest.mark.parametrize("name", sorted(STEP_CASES))
def test_every_step_kind_and_option_compiles(name, blocks_impl):
    code = document_to_python(case_doc(name))
    compile(code, f"{name}.py", "exec")
    assert code.count("with self.step(") == len(case_doc(name).scenes[0].steps)


def test_captions_in_code(fake_blocks):
    doc = doc_from("""
        settings: {captions: {font_size: 36, color: YELLOW, edge: top, background: false}}
        scenes:
          - id: s
            background: "#102030"
            objects: [{id: t, type: text, text: hi}]
            steps:
              - {id: a, do: show, target: t, caption: 'She said "hi"'}
              - {id: b, do: wait, caption: ""}
              - {id: c, do: clear}
              - {id: d, do: clear, caption: Next}
    """)
    code = document_to_python(doc)
    assert 'caption_style = CaptionStyle(font_size=36, color=YELLOW, edge="top", background=False)' in code
    assert 'default_camera_config = dict(background_color="#102030")' in code
    assert """with self.step("a", caption='She said "hi"'):""" in code
    assert 'with self.step("b", caption=""):' in code
    # A clear takes the caption with it, unless it brings one of its own
    assert 'with self.step("c", caption=""):' in code
    assert 'with self.step("d", caption="Next"):' in code


def test_a_together_takes_the_last_caption_of_the_steps_inside():
    doc = doc_from("""
        scenes:
          - id: s
            objects: [{id: t, type: text, text: hi}, {id: u, type: text, text: ho}]
            steps:
              - {do: together, steps: [{do: show, target: t, caption: one}, {do: show, target: u, caption: two}]}
              - {do: together, caption: own, steps: [{do: hide, target: t, caption: one}, {do: hide, target: u}]}
              - {do: together, steps: [{do: show, target: t}, {do: clear}]}
    """)
    assert [step_caption(step) for step in doc.scenes[0].steps] == ["two", "own", ""]


@pytest.mark.parametrize("text", ['plain', 'with "double" quotes', "with 'single' quotes", "both ' and \"",
                                  "back\\slash", "new\nline", "unicode é ∑ 😀", "\t tab"])
def test_strings_come_out_as_literals_of_themselves(text):
    assert eval(py_str(text)) == text


def test_example_video_generates_code_for_every_scene(blocks_impl, monkeypatch):
    """The ten minute acceptance video is the biggest scene file there is: all of it has to turn into code."""
    from pathlib import Path

    from fake_blocks import object_expression
    from manim_verbose.scenefile import blocks
    from manim_verbose.scenefile.files import load_file
    example = Path(__file__).parents[2] / "examples" / "eola_vectors" / "vectors.yaml"
    if not example.exists():
        pytest.skip("the example scene file isn't in this checkout")
    if blocks_impl == "fake":
        # The stand-in doesn't build every kind of object the example uses; a placeholder
        # does for what it doesn't, since what is being tested here is the steps
        def permissive(obj, ctx):
            try:
                return object_expression(obj, ctx)
            except NotImplementedError:
                return "VGroup(Square(), Square())"
        monkeypatch.setattr(blocks, "object_expression", permissive)
    doc, problems = load_file(example)
    assert doc is not None
    module = generate_module(doc, base_dir=example.parent)
    compile(module.code, "vectors.py", "exec")
    assert len(module.class_names) == len(doc.scenes)
    steps = sum(len(scene.steps) for scene in doc.scenes)
    assert module.code.count("with self.step(") == steps


@pytest.mark.render
def test_generated_module_runs_under_plain_manimgl(fake_blocks, tmp_path):
    """Exported code needs nothing but manimgl: render a frame of it the way a user would."""
    doc = fixture_doc("every_step.yaml")
    source = tmp_path / "exported.py"
    source.write_text(document_to_python(doc, scene_ids=["plane_view"]))
    root = FIXTURES.parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "manimlib", str(source), "PlaneView", "-w", "-s", "-r", "256x144",
         "--video_dir", str(tmp_path / "out")],
        cwd=root, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert (tmp_path / "out" / "PlaneView.png").exists()
