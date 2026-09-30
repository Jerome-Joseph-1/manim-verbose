"""
What the tests of steps and rendering share: documents from YAML, running a scene with its
animations skipped to look at what is on screen, reading frames back out of videos, and
comparing pictures.

Golden images and the expected generated code are refreshed by running the tests with
MANIM_VERBOSE_UPDATE_GOLDEN=1, after which the new files are to be looked at before they
are committed. How golden images are compared on machines other than the one they were made
on is below, at GOLDEN_MANIFEST.
"""
from __future__ import annotations

import os
import textwrap
from functools import lru_cache
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
    Runs a scene with every animation skipped and nothing drawn (so needing no graphics
    device), to after `last_step` (all of it when None), and hands back the DocScene as it
    was left, ready to be looked at.
    """
    from manim_verbose.scenefile.runtime import RenderPlan
    scene_id = scene_id or doc.scenes[0].id
    job = render.prepare_job(doc, scene_id)
    doc_width, doc_height = doc.settings.resolution
    height = round(width * doc_height / doc_width)
    plan = RenderPlan(still=True, headless=True, last_step=last_step)
    return render.run_job(job, plan, width, height, doc.settings.fps)


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


# Golden images, compared strictly on the machine they were made on and loosely elsewhere
#
# Two renderers never agree about every pixel of a thin line: Mesa's lavapipe from another
# release, another LLVM, another GPU all rasterize a faint grid line or the edge of a glyph a
# little differently, which is no regression. So next to the golden images is a manifest
# recording what drew them (the graphics adapter and driver, LaTeX, Pango, cairo and the
# font text falls back on) and, for each image, the box of every object on screen, which is
# geometry and so the same on any machine.
#
# Where this machine is the one the images were made on, a new picture has to match its
# golden image pixel for pixel away from edges (see compare_strictly). Anywhere else it is
# compared loosely (compare_loosely), in ways a rasterizer can't change but a regression
# does: the same objects in the same places, each drawn with about as much ink and in the
# same colors, and the picture as a whole the same once blurred past the width of a line.

GOLDEN_MANIFEST = GOLDEN / "manifest.json"
# How far, in manim units, an object's box may be from where it was, on another machine,
# where text is laid out by another version of Pango or LaTeX; on the same machine, none
BOX_TOLERANCE = 0.05
# How much more or less ink an object may be drawn with on another machine: thin lines
# come out a little fainter or bolder
INK_RATIO = (0.5, 2.0)
# The share of an object's colored ink a hue has to hold to count as one of its colors,
# and how little of it within HUE_REACH degrees counts as that color being gone
HUE_PRESENT, HUE_GONE, HUE_REACH = 0.15, 0.03, 12.5
# The blurred picture may differ by more than BLUR_LEVEL in no more than this share of it
BLUR_SIGMA, BLUR_LEVEL, BLUR_SHARE = 3.0, 48, 0.005


FINGERPRINT_KEYS = ("adapter", "latex", "pango", "cairo", "text font")


def renderer_fingerprint() -> dict[str, str]:
    """What decides how pictures come out on this machine, beyond this repository's code, as FINGERPRINT_KEYS."""
    return dict(_fingerprint())


@lru_cache(maxsize=1)
def _fingerprint() -> tuple[tuple[str, str], ...]:
    import shutil
    import subprocess

    def first_line(*command: str) -> str:
        if shutil.which(command[0]) is None:
            return "not installed"
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return (result.stdout.strip().splitlines() or ["unknown"])[0]

    try:
        import wgpu
        info = wgpu.gpu.request_adapter_sync(power_preference="high-performance").info
        adapter = f"{info.get('device', '')} | {info.get('description', '')}".strip(" |")
    except Exception as err:  # no adapter at all: then nothing renders anyway
        adapter = f"none ({type(err).__name__})"
    try:
        import manimpango
        pango, cairo = manimpango.pango_version(), manimpango.cairo_version()
    except Exception:
        pango = cairo = "unknown"
    from manimlib.config import manim_config
    return (
        ("adapter", adapter),
        ("latex", first_line("latex", "--version")),
        ("pango", pango),
        ("cairo", cairo),
        ("text font", first_line("fc-match", str(manim_config.text.font))),
    )


def golden_manifest() -> dict:
    import json
    if not GOLDEN_MANIFEST.exists():
        return {"fingerprint": {}, "stills": {}}
    return json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))


def record_golden(name: str, boxes: list) -> None:
    """Notes a golden image's boxes, and what this machine is, in the manifest."""
    import json
    manifest = golden_manifest()
    manifest["fingerprint"] = renderer_fingerprint()
    manifest["stills"][name] = {"boxes": boxes_data(boxes)}
    manifest["stills"] = dict(sorted(manifest["stills"].items()))
    lines = ["{", f' "fingerprint": {json.dumps(manifest["fingerprint"], indent=2)[:-1]} }},', ' "stills": {']
    for index, (still, entry) in enumerate(manifest["stills"].items()):
        boxes = ",\n".join(f"   {json.dumps(box)}" for box in entry["boxes"])
        comma = "," if index < len(manifest["stills"]) - 1 else ""
        lines.append(f'  {json.dumps(still)}: {{"boxes": [\n{boxes}\n  ]}}{comma}')
    lines += [" }", "}"]
    GOLDEN_MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def boxes_data(boxes) -> list[list]:
    """ObjectBoxes as the manifest keeps them: id and frame box, rounded."""
    return [[box.id, *(round(float(v), 4) for v in box.frame_bbox)] for box in boxes]


def fingerprint_differences(recorded: dict[str, str]) -> list[str]:
    """
    How this machine differs from the one golden images were made on, in words; none where
    it is that one. MANIM_VERBOSE_GOLDEN_LOOSE=1 makes any machine count as another, to try
    the loose comparison out.
    """
    here = renderer_fingerprint()
    differences = [
        f"{key}: made with {recorded.get(key, 'nothing recorded')!r}, here {here.get(key)!r}"
        for key in sorted(set(recorded) | set(here)) if recorded.get(key) != here.get(key)
    ]
    if not differences and os.environ.get("MANIM_VERBOSE_GOLDEN_LOOSE") == "1":
        differences.append("MANIM_VERBOSE_GOLDEN_LOOSE=1 asks for the comparison made on other machines")
    return differences


def compare_boxes(reference: list[list], new: list[list], tolerance: float) -> list[str]:
    """Ways the objects on screen differ: some missing or extra, or out of place by more than tolerance."""
    reasons = []
    ref_ids, new_ids = [box[0] for box in reference], [box[0] for box in new]
    if ref_ids != new_ids:
        return [f"the objects on screen were {ref_ids} and are now {new_ids}"]
    for ref, box in zip(reference, new):
        worst = max(abs(a - b) for a, b in zip(ref[1:], box[1:]))
        if worst > tolerance + 1e-4:
            reasons.append(f"'{ref[0]}' has moved: its box was {ref[1:]} and is {box[1:]}")
    return reasons


def compare_strictly(reference: np.ndarray, new: np.ndarray) -> list[str]:
    """The same picture but for the edges of shapes, which never come out exactly alike."""
    worst, mean = difference(reference, new)
    stray = away_from_edges(reference, new)
    if stray or mean >= 1.0:
        return [f"{stray} pixels away from any edge differ, worst by {worst}, by {mean:.2f} on average"]
    return []


def compare_loosely(reference: np.ndarray, new: np.ndarray, pixel_boxes: list) -> list[str]:
    """
    Whether a picture drawn by another renderer shows the same thing: each object (given by
    its box in pixels, (id, x0, y0, x1, y1)) drawn with about as much ink and in the same
    colors, and the whole the same once blurred past the width of a line. Lines drawn a
    fraction of a pixel over or a little bolder pass; an object missing, invisible or
    recolored, or a background of another color, doesn't.
    """
    from scipy import ndimage
    assert reference.shape == new.shape, (reference.shape, new.shape)
    reasons = []
    background = reference[0, 0]
    for obj_id, *box in pixel_boxes:
        ref_part, new_part = _region(reference, box), _region(new, box)
        ref_ink, new_ink = _ink(ref_part, background), _ink(new_part, background)
        if ref_ink > 1 or new_ink > 1:
            ratio = new_ink / max(ref_ink, 1e-9)
            if not INK_RATIO[0] <= ratio <= INK_RATIO[1]:
                reasons.append(f"'{obj_id}' is drawn with {ratio:.2f} times the ink it was")
                continue
        for hue, verb in _hues_changed(ref_part, new_part):
            reasons.append(f"'{obj_id}' {verb} {hue:.0f}° of hue")
    blurred = [
        np.stack([ndimage.gaussian_filter(img[..., c].astype(float), BLUR_SIGMA) for c in range(3)], axis=-1)
        for img in (reference, new)
    ]
    far = (np.abs(blurred[0] - blurred[1]).max(axis=2) > BLUR_LEVEL).mean()
    if far > BLUR_SHARE:
        reasons.append(f"{far:.1%} of the picture differs even blurred")
    return reasons


def _region(img: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    height, width = img.shape[:2]
    return img[max(0, int(y0) - 2):min(height, int(np.ceil(y1)) + 2), max(0, int(x0) - 2):min(width, int(np.ceil(x1)) + 2)]


def _ink(img: np.ndarray, background: np.ndarray) -> float:
    """How much is drawn: the sum over pixels of how far each is from the background, 1 for the farthest."""
    return float((np.abs(img.astype(float) - background).max(axis=2) / 255).sum())


def _hue_shares(img: np.ndarray) -> tuple[np.ndarray, float]:
    """
    How the colored ink of a picture divides between hues, in 72 bins of 5°, weighted by how
    colored each pixel is. Blending with a grey background, as antialiasing does, keeps hue,
    which is what makes this the same whatever draws the edges.
    """
    rgb = img.astype(float) / 255
    top, bottom = rgb.max(axis=2), rgb.min(axis=2)
    chroma = top - bottom
    colored = chroma > 0.2
    if not colored.any():
        return np.zeros(72), 0.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    c = np.maximum(chroma, 1e-9)
    hue = np.where(top == r, ((g - b) / c) % 6, np.where(top == g, (b - r) / c + 2, (r - g) / c + 4)) * 60
    shares, _ = np.histogram(hue[colored], bins=72, range=(0, 360), weights=chroma[colored])
    total = float(shares.sum())
    return shares / total, total


def _hues_changed(reference: np.ndarray, new: np.ndarray) -> list[tuple[float, str]]:
    """Hues holding a good share of the colored ink in one picture and next to none of the other's."""
    ref, ref_mass = _hue_shares(reference)
    now, new_mass = _hue_shares(new)
    if ref_mass < 3 and new_mass < 3:
        return []
    reach = int(HUE_REACH // 5)
    near = [sum(np.roll(shares, k) for k in range(-reach, reach + 1)) for shares in (ref, now)]
    window = [sum(np.roll(shares, k) for k in (-1, 0, 1)) for shares in (ref, now)]
    changed = []
    for present, gone, verb in ((0, 1, "has lost the color at"), (1, 0, "has gained a color at")):
        mass = (ref_mass, new_mass)[gone]
        for index in np.argsort(-window[present])[:3]:
            if window[present][index] >= HUE_PRESENT and (mass < 3 or near[gone][index] < HUE_GONE):
                changed.append((index * 5 + 2.5, verb))
                break
    return changed


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
# scene. STEP_CASES maps a name to (steps before it, the step itself). A case's document
# holds only the objects its steps refer to, so that only the cases about formulas need LaTeX.
CASE_OBJECTS = """
objects:
  - {id: t, type: text, text: "Hello there", place: top}
  - {id: u, type: text, text: "Second line", place: [0, -1]}
  - {id: w, type: text, text: "Hello world", place: [0, 1]}
  - {id: eq, type: tex, tex: "a^2 + b^2 = c^2"}
  - {id: eq2, type: tex, tex: "c^2 = a^2 + b^2", place: [0, -2]}
  - {id: c, type: circle, radius: 0.5, color: BLUE, place: [-3, 0]}
  - {id: sq, type: square, side: 1, color: GREEN, place: [3, 0]}
  - {id: d, type: dot, point: [0, 2], color: RED}
  - {id: g, type: group, members: [c, sq]}
  - {id: plane, type: number_plane}
  - {id: v, type: vector, on: plane, tip: [1, 2], color: YELLOW}
"""

SHOWN = "[{do: add, target: [t, u, g]}]"
TEX = "[{do: add, target: eq}]"
STEP_CASES: dict[str, tuple[str, str]] = {
    "show_auto": ("[]", "{do: show, target: u}"),
    "show_auto_tex": ("[]", "{do: show, target: eq}"),
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
    "hide_auto": (SHOWN, "{do: hide, target: u}"),
    "hide_fade_down": (SHOWN, "{do: hide, target: t, style: fade_down}"),
    "hide_uncreate": (SHOWN, "{do: hide, target: c, style: uncreate}"),
    "hide_shrink": (SHOWN, "{do: hide, target: sq, style: shrink}"),
    "hide_many_lagged": (SHOWN, "{do: hide, target: [t, u], lag: 1}"),
    "hide_group": (SHOWN, "{do: hide, target: g}"),
    "add": ("[]", "{do: add, target: [t, d]}"),
    "add_held": ("[]", "{do: add, target: d, run_time: 1}"),
    "remove": (SHOWN, "{do: remove, target: u}"),
    "remove_member": (SHOWN, "{do: remove, target: c}"),
    "clear": (SHOWN, "{do: clear}"),
    "transform_auto_text": (SHOWN, "{do: transform, target: t, into: w}"),
    "transform_auto_tex": (TEX, "{do: transform, target: eq, into: eq2}"),
    "transform_morph": (SHOWN, "{do: transform, target: c, into: d, style: morph}"),
    "transform_match_shapes": (SHOWN, "{do: transform, target: sq, into: d, style: match}"),
    "transform_fade": (SHOWN, "{do: transform, target: t, into: w, style: fade}"),
    "transform_keep": (SHOWN, "{do: transform, target: t, into: w, keep: true}"),
    "transform_keep_tex": (TEX, "{do: transform, target: eq, into: eq2, keep: true}"),
    "transform_keep_fade": (SHOWN, "{do: transform, target: c, into: d, style: fade, keep: true}"),
    "change_color": (SHOWN, "{do: change, target: c, set: {color: RED}}"),
    "change_text": (SHOWN, "{do: change, target: t, set: {text: Goodbye}}"),
    "change_tex": (TEX, "{do: change, target: eq, set: {tex: \"a + b = c\"}}"),
    "change_place": (SHOWN, "{do: change, target: t, set: {place: bottom}}"),
    "change_group": (SHOWN, "{do: change, target: g, set: {arrange: column, buff: 0.2}}"),
    "move_by": (SHOWN, "{do: move, target: t, by: [1, -1]}"),
    "move_by_many": (SHOWN, "{do: move, target: [t, u], by: [0, 1]}"),
    "move_to_edge": (SHOWN, "{do: move, target: u, to: bottom}"),
    "move_to_point": (SHOWN, "{do: move, target: u, to: [2, 1]}"),
    "move_to_next_to": (SHOWN, "{do: move, target: u, to: {next_to: t, side: down, buff: 0.5}}"),
    "move_to_shifted": (SHOWN, "{do: move, target: t, to: {edge: left, shift: [0.5, 0]}}"),
    "move_to_on_plane": ("[{do: add, target: [plane, u]}]", "{do: move, target: u, to: {at: [2, 1], on: plane}}"),
    "move_to_many": (SHOWN, "{do: move, target: [t, u], to: bottom_right}"),
    "move_group": (SHOWN, "{do: move, target: g, by: [0, -1]}"),
    "highlight_indicate": (SHOWN, "{do: highlight, target: u}"),
    "highlight_indicate_part": (SHOWN, "{do: highlight, target: t, part: there, color: RED}"),
    "highlight_indicate_tex_part": (TEX, "{do: highlight, target: eq, part: \"c^2\", color: RED}"),
    "highlight_flash": (SHOWN, "{do: highlight, target: c, style: flash}"),
    "highlight_box": (SHOWN, "{do: highlight, target: t, part: Hello, style: box, color: GREEN}"),
    "highlight_underline": (SHOWN, "{do: highlight, target: t, style: underline}"),
    "highlight_wiggle": (SHOWN, "{do: highlight, target: sq, style: wiggle}"),
    "highlight_recolor": (SHOWN, "{do: highlight, target: t, part: there, style: recolor, color: \"#FF8800\"}"),
    "highlight_recolor_tex": (TEX, "{do: highlight, target: eq, part: \"a^2\", style: recolor}"),
    "highlight_recolor_whole": (SHOWN, "{do: highlight, target: u, style: recolor}"),
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
    "together_run_time": (SHOWN, "{do: together, run_time: 3, steps: [{do: move, target: t, by: [0, -1]}, {do: hide, target: u}]}"),
    "together_instant": (SHOWN, "{do: together, steps: [{do: add, target: d}, {do: remove, target: u}, {do: highlight, target: t}]}"),
    "together_all_instant": (SHOWN, "{do: together, steps: [{do: add, target: d}, {do: remove, target: u}]}"),
    "together_change": (SHOWN, "{do: together, steps: [{do: change, target: c, set: {color: YELLOW}}, {do: change, target: sq, set: {side: 2}}]}"),
    "together_camera": (SHOWN, "{do: together, steps: [{do: camera, zoom: 2}, {do: highlight, target: u, style: flash}]}"),
    "together_clear": (SHOWN, "{do: together, steps: [{do: clear}, {do: show, target: d}]}"),
    "caption": ("[]", "{do: show, target: t, caption: \"A caption\"}"),
    "caption_on_wait": ("[]", "{do: wait, duration: 1, caption: \"Waiting\"}"),
    "caption_on_add": ("[]", "{do: add, target: t, caption: \"Added\"}"),
}


def case_doc(name: str) -> Document:
    """The document for one of STEP_CASES: its steps setting the scene, then the step, last."""
    import yaml
    from manim_verbose.scenefile.files import parse_text
    from manim_verbose.scenefile.model import iter_steps
    from manim_verbose.scenefile.validate import object_refs, step_refs

    def read(text):
        # The scene file's own reading of YAML, in which `on:` is a key and not true
        return parse_text(text)[0]

    before, step = STEP_CASES[name]
    steps = [*read(before), read(step)]
    objects = {obj["id"]: obj for obj in read(CASE_OBJECTS)["objects"]}
    full = Document.model_validate({"scenes": [{"id": "case", "objects": list(objects.values()), "steps": steps}]})
    by_id = {obj.id: obj for obj in full.scenes[0].objects}
    needed: set[str] = set()

    def need(obj_id: str) -> None:
        if obj_id not in needed:
            needed.add(obj_id)
            for _, ref, _ in object_refs(by_id[obj_id]):
                need(ref)

    for each in iter_steps(full.scenes[0].steps):
        for _, ref, _ in step_refs(each):
            need(ref)
    data = {
        "settings": {"resolution": [256, 144], "fps": 15},
        "scenes": [{"id": "case", "objects": [o for i, o in objects.items() if i in needed], "steps": steps}],
    }
    return doc_from(yaml.safe_dump(data, sort_keys=False), tiny=False)


def case_needs_latex(name: str) -> bool:
    return any(obj.type == "tex" for obj in case_doc(name).scenes[0].objects)


def case_params(names=None) -> list:
    """STEP_CASES as test parameters, those needing LaTeX marked to run with the renderer's tests."""
    return [
        pytest.param(name, marks=pytest.mark.render) if case_needs_latex(name) else name
        for name in sorted(names or STEP_CASES)
    ]
