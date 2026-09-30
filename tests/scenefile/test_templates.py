"""
The templates a new scene file can start from (manim_verbose/templates/): each one is a
finished, valid document in canonical form, with a title, a description and a thumbnail the
gallery can show, lasting as long as a short video should, and its code runs. Then the two
commands which use them, `manimgl-scene templates` and `manimgl-scene new`.

Running a template's scene needs LaTeX when it has formulas, so those runs are marked render,
as CI's fast job has no LaTeX. The welcome template, which new files in the editor start as,
has to render without LaTeX, and so does the blank one.
"""
from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from manim_verbose.scenefile import cli, render
from manim_verbose.scenefile.codegen import document_to_python
from manim_verbose.scenefile.files import dump_text, load_file, to_data
from manim_verbose.scenefile.model import iter_steps
from manim_verbose.scenefile.runtime import RenderPlan

TEMPLATES = Path(cli.__file__).resolve().parents[1] / "templates"
REPO = Path(__file__).resolve().parents[2]

EXPECTED = {
    "blank", "welcome", "equation_steps", "function_graph", "geometry_proof",
    "vectors_and_matrices", "number_line", "lesson_intro",
}
# The templates new users see first, which have to work whatever is installed
NO_LATEX = {"blank", "welcome"}

THUMBNAIL_SIZE = (480, 270)
THUMBNAIL_BUDGET = 60 * 1024
# A template is a short video: long enough to show how things are done, short enough to change
SHORTEST, LONGEST = 20.0, 90.0
# Captions longer than this wrap onto a second line, which covers more of the picture
CAPTION_CHARACTERS = 90

LATEX_KINDS = {"tex", "matrix", "brace", "axes", "axes_3d", "graph"}
LATEX_FIELDS = ("label", "x_label", "y_label", "z_label")


def names() -> list[str]:
    return sorted(path.stem for path in TEMPLATES.glob("*.yaml"))


def load(name: str):
    doc, problems = load_file(TEMPLATES / f"{name}.yaml")
    assert doc is not None, [str(p) for p in problems]
    return doc, problems


def uses_latex(doc) -> bool:
    """Whether building a document's objects runs LaTeX: formulas, matrices, braces, axes' numbers and labels do."""
    for scene in doc.scenes:
        for obj in scene.objects:
            if obj.type in LATEX_KINDS:
                return True
            if any(getattr(obj, field, None) for field in LATEX_FIELDS):
                return True
            if getattr(obj, "show_coordinates", False) or getattr(obj, "bracket", "square") == "round":
                return True
            if obj.type in ("number_line", "number_plane") and obj.numbers:
                return True
    return False


def latex_marked(template_names):
    """Template names as parameters, those whose scenes need LaTeX marked render."""
    return [
        pytest.param(name, marks=pytest.mark.render) if uses_latex(load(name)[0]) else name
        for name in template_names
    ]


# The set of templates

def test_every_template_is_there():
    assert set(names()) >= EXPECTED
    assert cli.template_names() == names()


def test_the_templates_new_users_see_first_need_no_latex():
    for name in NO_LATEX:
        assert not uses_latex(load(name)[0]), name


def test_new_files_in_the_editor_start_as_the_welcome_template():
    from manim_verbose.editor.starter import STARTER_YAML
    assert STARTER_YAML == (TEMPLATES / "welcome.yaml").read_text(encoding="utf-8")


def test_the_package_ships_the_templates():
    config = configparser.ConfigParser(interpolation=None)
    config.read(REPO / "setup.cfg", encoding="utf-8")
    patterns = config["options.package_data"]["manim_verbose"].split()
    assert "templates/*.yaml" in patterns and "templates/*.png" in patterns


# Each template

@pytest.mark.parametrize("name", names())
def test_valid_with_no_warnings(name):
    _, problems = load(name)
    assert problems == [], [str(p) for p in problems]


@pytest.mark.parametrize("name", names())
def test_in_canonical_form(name):
    doc, _ = load(name)
    assert (TEMPLATES / f"{name}.yaml").read_text(encoding="utf-8") == dump_text(doc, "yaml")


@pytest.mark.parametrize("name", names())
def test_has_a_title_and_a_description_for_the_gallery(name):
    doc, _ = load(name)
    assert doc.title and doc.title != "Untitled"
    assert doc.description and len(doc.description) >= 60
    # The description says what the template is for and what to change first
    assert re.search(r"\bchang(e|ing)\b", doc.description, re.IGNORECASE), doc.description
    assert all(scene.title for scene in doc.scenes)


@pytest.mark.parametrize("name", names())
def test_has_a_thumbnail_within_its_budget(name):
    path = TEMPLATES / f"{name}.png"
    assert path.exists(), f"{name}.png is missing"
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == THUMBNAIL_SIZE
    assert path.stat().st_size <= THUMBNAIL_BUDGET


@pytest.mark.parametrize("name", names())
def test_looks_like_the_others(name):
    doc, _ = load(name)
    assert doc.settings.background == "BLACK"
    assert doc.settings.font == "CMU Serif"
    assert doc.settings.resolution == [1920, 1080]
    for scene in doc.scenes:
        assert scene.background is None
        for obj in scene.objects:
            # Names a beginner can read, rather than t1 or obj_2
            assert not re.fullmatch(r"[A-Za-z]{1,3}_?\d+", obj.id), obj.id


@pytest.mark.parametrize("name", names())
def test_lasts_as_long_as_a_short_video(name):
    doc, _ = load(name)
    duration = render.document_duration(doc)
    if name == "blank":
        assert 0 < duration <= 10
    else:
        assert SHORTEST <= duration <= LONGEST, duration


@pytest.mark.parametrize("name", names())
def test_captions_are_short_plain_words(name):
    doc, _ = load(name)
    captions = [step.caption for scene in doc.scenes for step in iter_steps(scene.steps) if step.caption]
    assert captions
    for caption in captions:
        assert len(caption) <= CAPTION_CHARACTERS, caption
        # Plain words: no LaTeX, which a caption would show as it is
        assert "\\" not in caption and "$" not in caption, caption


@pytest.mark.parametrize("name", names())
def test_captions_stay_up_long_enough_to_read(name):
    """At least 3 seconds, and 0.3 seconds a word: until the next caption, a clear, or the scene's end."""
    doc, _ = load(name)
    for scene in doc.scenes:
        timings = render.timeline(doc, scene.id)
        pairs = list(zip(timings, scene.steps))
        changes = [timing.start for timing, step in pairs if step.caption is not None]
        clears = [timing.start + timing.duration for timing, step in pairs if step.do == "clear"]
        end = render.scene_duration(doc, scene.id)
        for timing, step in pairs:
            if not step.caption:
                continue
            gone = min([t for t in changes + clears if t > timing.start] + [end])
            needed = max(3.0, 0.3 * len(step.caption.split()))
            assert gone - timing.start >= needed - 1e-9, f"{scene.id}/{step.id}: {step.caption!r}"


@pytest.mark.parametrize("name", names())
def test_every_step_has_its_timing_written_down(name):
    """A template is copied and changed, so how long each step takes is there to be seen and changed."""
    doc, _ = load(name)
    for scene in doc.scenes:
        for step in scene.steps:
            if step.do not in ("wait", "together", "add", "remove"):
                assert step.run_time is not None, f"{scene.id}/{step.id}"


@pytest.mark.parametrize("name", names())
def test_code_compiles(name):
    doc, _ = load(name)
    code = document_to_python(doc, base_dir=TEMPLATES)
    compile(code, f"{name}.py", "exec")
    for scene in doc.scenes:
        assert scene.id in code


@pytest.mark.parametrize("name", latex_marked(names()))
def test_every_scene_runs(name):
    doc, _ = load(name)
    for scene in doc.scenes:
        job = render.prepare_job(doc, scene.id, TEMPLATES)
        ran = render.run_job(job, RenderPlan(still=True, headless=True), 256, 144, 15)
        assert [record.step_id for record in ran.step_records] == [step.id for step in scene.steps]
        assert set(ran.objects) == {obj.id for obj in scene.objects}


# manimgl-scene templates and new

def test_templates_lists_names_titles_and_descriptions(capsys):
    assert cli.main(["templates"]) == 0
    out = capsys.readouterr().out
    for name in names():
        doc, _ = load(name)
        assert re.search(rf"^{name}\s+{re.escape(doc.title)}$", out, re.MULTILINE), name
        assert doc.description.split()[0] in out


def test_new_starts_from_the_blank_template(tmp_path, capsys):
    target = tmp_path / "lesson.yaml"
    assert cli.main(["new", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == (TEMPLATES / "blank.yaml").read_text(encoding="utf-8")
    assert "blank" in capsys.readouterr().out


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
@pytest.mark.parametrize("name", ["welcome", "function_graph"])
def test_new_writes_a_copy_in_the_files_own_format(tmp_path, name, suffix):
    target = tmp_path / f"copy{suffix}"
    assert cli.main(["new", str(target), "--template", name]) == 0
    doc, problems = load_file(target)
    assert problems == []
    assert to_data(doc) == to_data(load(name)[0])
    text = target.read_text(encoding="utf-8")
    if suffix == ".json":
        json.loads(text)
    assert text == dump_text(doc, "json" if suffix == ".json" else "yaml")


def test_new_makes_the_folder_it_goes_in(tmp_path):
    target = tmp_path / "videos" / "week 1" / "intro.yaml"
    assert cli.main(["new", str(target), "-t", "lesson_intro"]) == 0
    assert load_file(target)[1] == []


def test_new_leaves_an_existing_file_alone(tmp_path, capsys):
    target = tmp_path / "mine.yaml"
    target.write_text("my own work\n", encoding="utf-8")
    assert cli.main(["new", str(target), "-t", "welcome"]) == 1
    assert target.read_text(encoding="utf-8") == "my own work\n"
    assert "--force" in capsys.readouterr().err


def test_new_replaces_an_existing_file_when_forced(tmp_path):
    target = tmp_path / "mine.yaml"
    target.write_text("my own work\n", encoding="utf-8")
    assert cli.main(["new", str(target), "-t", "welcome", "--force"]) == 0
    assert target.read_text(encoding="utf-8") == (TEMPLATES / "welcome.yaml").read_text(encoding="utf-8")


def test_new_with_a_template_which_isnt_there(tmp_path, capsys):
    target = tmp_path / "a.yaml"
    assert cli.main(["new", str(target), "-t", "wellcome"]) == 2
    err = capsys.readouterr().err
    assert "There's no template called 'wellcome' (did you mean 'welcome'?)" in err
    assert all(name in err for name in names())
    assert not target.exists()


def test_new_needs_a_scene_file_name(tmp_path, capsys):
    target = tmp_path / "lesson.txt"
    assert cli.main(["new", str(target)]) == 2
    assert ".yaml, .yml or .json" in capsys.readouterr().err
    assert not target.exists()
