"""
What the tests of steps and rendering share: documents from YAML, running a scene with its
animations skipped to look at what is on screen, reading frames back out of videos, and
comparing pictures.

Golden images and the expected generated code are refreshed by running the tests with
MANIM_VERBOSE_UPDATE_GOLDEN=1, after which the new files are to be looked at before they
are committed.
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import numpy as np
import pytest

from manim_verbose.scenefile import render
from manim_verbose.scenefile.files import load_file, load_text
from manim_verbose.scenefile.model import Document
from manim_verbose.scenefile.validate import has_errors

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden"
UPDATE_GOLDEN = os.environ.get("MANIM_VERBOSE_UPDATE_GOLDEN") == "1"

# Small enough to render quickly on a shared CPU, big enough to see what happened
TINY_SETTINGS = "settings: {resolution: [256, 144], fps: 15}\n"


def doc_from(yaml_text: str, tiny: bool = True) -> Document:
    """A document from YAML, which has to be free of errors; small and at 15 fps unless told otherwise."""
    text = textwrap.dedent(yaml_text)
    if tiny and "settings:" not in text:
        text = TINY_SETTINGS + text
    doc, problems = load_text(text)
    assert doc is not None and not has_errors(problems), [str(p) for p in problems]
    return doc


def fixture_doc(name: str) -> Document:
    doc, problems = load_file(FIXTURES / name)
    assert doc is not None and not has_errors(problems), [str(p) for p in problems]
    return doc


def run_scene(doc: Document, scene_id: str | None = None, last_step: int | None = None, width: int = 256):
    """
    Runs a scene with every animation skipped, to after `last_step` (all of it when None),
    and hands back the DocScene as it was left, ready to be looked at.
    """
    from manim_verbose.scenefile.runtime import RenderPlan
    scene_id = scene_id or doc.scenes[0].id
    job = render.prepare_job(doc, scene_id)
    doc_width, doc_height = doc.settings.resolution
    height = round(width * doc_height / doc_width)
    return render.run_job(job, RenderPlan(still=True, last_step=last_step), width, height, doc.settings.fps)


def video_frames(path: str | Path) -> list[np.ndarray]:
    import av
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24").astype(np.int16) for frame in container.decode(video=0)]


def frame_count(path: str | Path) -> int:
    import av
    with av.open(str(path)) as container:
        return sum(1 for _ in container.decode(video=0))


def image(path: str | Path) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def difference(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """The largest difference of any channel of any pixel, and the mean over all of them."""
    assert a.shape == b.shape, (a.shape, b.shape)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return int(diff.max()), float(diff.mean())


def away_from_edges(reference: np.ndarray, other: np.ndarray, contrast: int = 24, reach: int = 1) -> int:
    """
    How many pixels differ noticeably (by more than `contrast`) where the reference isn't
    changing color, in the spirit of tests/render_compare.py: two renders are never going to
    agree exactly along the edge of a shape, and are expected to everywhere else.
    """
    from scipy import ndimage
    size = 2 * reach + 1
    spread = np.zeros(reference.shape[:2])
    for channel in range(3):
        plane = reference[:, :, channel].astype(float)
        spread = np.maximum(spread, ndimage.maximum_filter(plane, size) - ndimage.minimum_filter(plane, size))
    edges = spread > 8
    diff = np.abs(reference.astype(np.int16) - other.astype(np.int16)).max(axis=2)
    return int(((diff > contrast) & ~edges).sum())


@pytest.fixture
def render_cache(tmp_path, monkeypatch) -> Path:
    """A cache of rendered scenes of the test's own, so that nothing is found from before."""
    path = tmp_path / "cache"
    monkeypatch.setenv("MANIM_VERBOSE_CACHE", str(path))
    return path


@pytest.fixture
def lossless(monkeypatch):
    """Videos written in process keep every pixel as drawn, so frames can be compared exactly."""
    from manimlib.config import manim_config
    monkeypatch.setitem(manim_config.file_writer, "video_codec", "libx264rgb")
    monkeypatch.setitem(manim_config.file_writer, "pixel_format", "rgb24")
    monkeypatch.setitem(manim_config.file_writer, "crf", 0)


# One scene with an object of each kind the stand-in blocks cover, and a step of every kind
# with every option worth telling apart, each run on its own after a few steps setting the
# scene. STEP_CASES maps a name to (steps before it, the step itself).
CASE_OBJECTS = """
objects:
  - {id: t, type: text, text: "Hello there", place: top}
  - {id: eq, type: tex, tex: "a^2 + b^2 = c^2"}
  - {id: eq2, type: tex, tex: "c^2 = a^2 + b^2", place: [0, -2]}
  - {id: c, type: circle, radius: 0.5, color: BLUE, place: [-3, 0]}
  - {id: sq, type: square, side: 1, color: GREEN, place: [3, 0]}
  - {id: d, type: dot, point: [0, 2], color: RED}
  - {id: g, type: group, members: [c, sq]}
  - {id: plane, type: number_plane}
  - {id: v, type: vector, on: plane, tip: [1, 2], color: YELLOW}
"""

SHOWN = "[{do: add, target: [t, eq, g]}]"
STEP_CASES: dict[str, tuple[str, str]] = {
    "show_auto": ("[]", "{do: show, target: eq}"),
    "show_write": ("[]", "{do: show, target: t, style: write}"),
    "show_draw": ("[]", "{do: show, target: c, style: draw}"),
    "show_fade": ("[]", "{do: show, target: sq, style: fade}"),
    "show_fade_up": ("[]", "{do: show, target: t, style: fade_up}"),
    "show_grow_vector": ("[{do: add, target: plane}]", "{do: show, target: v, style: grow}"),
    "show_grow_shape": ("[]", "{do: show, target: sq, style: grow}"),
    "show_pop": ("[]", "{do: show, target: d, style: pop}"),
    "show_many": ("[]", "{do: show, target: [c, sq, d]}"),
    "show_many_lagged": ("[]", "{do: show, target: [c, sq, d], lag: 0.5, run_time: 2}"),
    "show_group": ("[]", "{do: show, target: g}"),
    "hide_auto": (SHOWN, "{do: hide, target: eq}"),
    "hide_fade_down": (SHOWN, "{do: hide, target: t, style: fade_down}"),
    "hide_uncreate": (SHOWN, "{do: hide, target: c, style: uncreate}"),
    "hide_shrink": (SHOWN, "{do: hide, target: sq, style: shrink}"),
    "hide_many_lagged": (SHOWN, "{do: hide, target: [t, eq], lag: 1}"),
    "hide_group": (SHOWN, "{do: hide, target: g}"),
    "add": ("[]", "{do: add, target: [t, d]}"),
    "add_held": ("[]", "{do: add, target: d, run_time: 1}"),
    "remove": (SHOWN, "{do: remove, target: eq}"),
    "remove_member": (SHOWN, "{do: remove, target: c}"),
    "clear": (SHOWN, "{do: clear}"),
    "transform_auto_tex": (SHOWN, "{do: transform, target: eq, into: eq2}"),
    "transform_morph": (SHOWN, "{do: transform, target: c, into: d, style: morph}"),
    "transform_match_shapes": (SHOWN, "{do: transform, target: sq, into: d, style: match}"),
    "transform_fade": (SHOWN, "{do: transform, target: t, into: eq2, style: fade}"),
    "transform_keep": (SHOWN, "{do: transform, target: eq, into: eq2, keep: true}"),
    "transform_keep_fade": (SHOWN, "{do: transform, target: c, into: d, style: fade, keep: true}"),
    "change_color": (SHOWN, "{do: change, target: c, set: {color: RED}}"),
    "change_text": (SHOWN, "{do: change, target: t, set: {text: Goodbye}}"),
    "change_tex": (SHOWN, "{do: change, target: eq, set: {tex: \"a + b = c\"}}"),
    "change_place": (SHOWN, "{do: change, target: t, set: {place: bottom}}"),
    "change_group": (SHOWN, "{do: change, target: g, set: {arrange: column, buff: 0.2}}"),
    "move_by": (SHOWN, "{do: move, target: t, by: [1, -1]}"),
    "move_by_many": (SHOWN, "{do: move, target: [t, eq], by: [0, 1]}"),
    "move_to_edge": (SHOWN, "{do: move, target: eq, to: bottom}"),
    "move_to_point": (SHOWN, "{do: move, target: eq, to: [2, 1]}"),
    "move_to_next_to": (SHOWN, "{do: move, target: eq, to: {next_to: t, side: down, buff: 0.5}}"),
    "move_to_shifted": (SHOWN, "{do: move, target: t, to: {edge: left, shift: [0.5, 0]}}"),
    "move_to_on_plane": ("[{do: add, target: [plane, eq]}]", "{do: move, target: eq, to: {at: [2, 1], on: plane}}"),
    "move_to_many": (SHOWN, "{do: move, target: [t, eq], to: bottom_right}"),
    "move_group": (SHOWN, "{do: move, target: g, by: [0, -1]}"),
    "highlight_indicate": (SHOWN, "{do: highlight, target: eq}"),
    "highlight_indicate_part": (SHOWN, "{do: highlight, target: eq, part: \"c^2\", color: RED}"),
    "highlight_flash": (SHOWN, "{do: highlight, target: c, style: flash}"),
    "highlight_box": (SHOWN, "{do: highlight, target: eq, part: \"b^2\", style: box, color: GREEN}"),
    "highlight_underline": (SHOWN, "{do: highlight, target: t, style: underline}"),
    "highlight_wiggle": (SHOWN, "{do: highlight, target: sq, style: wiggle}"),
    "highlight_recolor": (SHOWN, "{do: highlight, target: eq, part: \"a^2\", style: recolor, color: \"#FF8800\"}"),
    "highlight_recolor_whole": (SHOWN, "{do: highlight, target: t, style: recolor}"),
    "wait": (SHOWN, "{do: wait, duration: 0.5}"),
    "camera_zoom": (SHOWN, "{do: camera, zoom: 2}"),
    "camera_center": (SHOWN, "{do: camera, center: [1, 1]}"),
    "camera_focus": (SHOWN, "{do: camera, zoom: 1.5, focus: sq}"),
    "camera_orientation": (SHOWN, "{do: camera, orientation: [-30, 70]}"),
    "camera_orientation_gamma": (SHOWN, "{do: camera, orientation: [-30, 70, 10], zoom: 1}"),
    "camera_reset": ("[{do: add, target: t}, {do: camera, zoom: 3, center: [1, 1]}]", "{do: camera, reset: true}"),
    "apply_matrix_plane": ("[{do: add, target: [plane, v]}]", "{do: apply_matrix, target: [plane, v], matrix: [[1, 1], [0, 1]]}"),
    "apply_matrix_frame": (SHOWN, "{do: apply_matrix, target: sq, matrix: [[2, 0], [0, 1]]}"),
    "apply_matrix_3d": (SHOWN, "{do: apply_matrix, target: c, matrix: [[1, 0, 0], [0, 2, 0], [0, 0, 1]]}"),
    "together": ("[]", "{do: together, steps: [{do: show, target: t}, {do: show, target: c, run_time: 2}]}"),
    "together_lagged": ("[]", "{do: together, lag: 0.5, steps: [{do: show, target: t}, {do: show, target: [c, sq]}, {do: show, target: d}]}"),
    "together_run_time": (SHOWN, "{do: together, run_time: 3, steps: [{do: move, target: t, by: [0, -1]}, {do: hide, target: eq}]}"),
    "together_instant": (SHOWN, "{do: together, steps: [{do: add, target: d}, {do: remove, target: eq}, {do: highlight, target: t}]}"),
    "together_all_instant": (SHOWN, "{do: together, steps: [{do: add, target: d}, {do: remove, target: eq}]}"),
    "together_change": (SHOWN, "{do: together, steps: [{do: change, target: c, set: {color: YELLOW}}, {do: change, target: sq, set: {side: 2}}]}"),
    "together_camera": (SHOWN, "{do: together, steps: [{do: camera, zoom: 2}, {do: highlight, target: eq, style: flash}]}"),
    "together_clear": (SHOWN, "{do: together, steps: [{do: clear}, {do: show, target: d}]}"),
    "caption": ("[]", "{do: show, target: t, caption: \"A caption\"}"),
    "caption_on_wait": ("[]", "{do: wait, duration: 1, caption: \"Waiting\"}"),
    "caption_on_add": ("[]", "{do: add, target: t, caption: \"Added\"}"),
}


def case_doc(name: str) -> Document:
    """The document for one of STEP_CASES: its steps setting the scene, then the step, last."""
    before, step = STEP_CASES[name]
    steps = [*_yaml_items(before), step]
    text = (
        "settings: {resolution: [256, 144], fps: 15}\n"
        + "scenes:\n  - id: case\n"
        + textwrap.indent(CASE_OBJECTS.strip(), "    ") + "\n"
        + "    steps:\n" + "".join(f"      - {s}\n" for s in steps)
    )
    return doc_from(text, tiny=False)


def _yaml_items(text: str) -> list[str]:
    import yaml
    return [yaml.safe_dump(item, default_flow_style=True, width=1000).strip() for item in yaml.safe_load(text)]
