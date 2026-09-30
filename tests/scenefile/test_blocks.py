"""
That every kind of object in a scene file becomes code which builds it, and builds the right
thing: each kind and its options evaluates to a mobject with nothing undrawable in it, where
the file says it should be (checked by bounding boxes and by c2p), styled as asked. Text the
user typed is carried into the code without ever changing the code's shape, however hostile.
Parts of texts and formulas pick out the right glyphs, and objects are built in an order
where everything is made before what refers to it.

Expressions are evaluated the way generated code runs them: in a namespace holding manimlib,
layout and expressions, and every object built before.
"""
from __future__ import annotations

import ast
import math
import re
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from manim_verbose.manim_import import import_manim

import_manim()

from manimlib import (  # noqa: E402
    Arrow, Axes, Brace, Circle, DashedLine, Dot, Group, ImageMobject, Line, Matrix, Mobject, NumberLine,
    NumberPlane, Polygon, Rectangle, RoundedRectangle, SVGMobject, Square, SurroundingRectangle, Tex, Text,
    ThreeDAxes, VGroup, VMobject,
)
from manimlib.constants import FRAME_HEIGHT, FRAME_WIDTH, YELLOW  # noqa: E402
from manimlib.utils.color import color_to_hex  # noqa: E402
from PIL import Image  # noqa: E402

from manim_verbose.scenefile.blocks import (  # noqa: E402
    build_order, default_hide_style, default_show_style, displayable, object_expression, part_selector,
)
from manim_verbose.scenefile.codegen import CodegenContext  # noqa: E402
from manim_verbose.scenefile.files import load_file  # noqa: E402
from manim_verbose.scenefile.model import OBJECT_MODELS, Document, SceneSpec  # noqa: E402
from manim_verbose.scenefile.validate import has_errors, validate_data  # noqa: E402

TOL = 1e-3
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "eola_vectors" / "vectors.yaml"

NAMESPACE: dict = {}
exec("from manimlib import *", NAMESPACE)
exec("from manim_verbose.scenefile.layout import *", NAMESPACE)
exec("from manim_verbose.scenefile.expressions import *", NAMESPACE)

STAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<polygon points="5,0 6.2,3.8 10,3.8 7,6.2 8.1,10 5,7.6 1.9,10 3,6.2 0,3.8 3.8,3.8" fill="#F0C040"/></svg>'
)


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> Path:
    """A folder standing in for a scene file's, holding a picture and a drawing."""
    folder = tmp_path_factory.mktemp("scene folder")
    Image.new("RGB", (60, 40), (40, 90, 160)).save(folder / "pic.png")
    (folder / "sub dir").mkdir()
    Image.new("RGB", (20, 20), (200, 30, 30)).save(folder / "sub dir" / "it's.png")
    (folder / "star.svg").write_text(STAR_SVG)
    return folder


class Built:
    """What building a scene's objects made: each object's mobject and code, by id."""

    def __init__(self, doc: Document, ctx: CodegenContext, mobs: dict, code: dict, namespace: dict):
        self.doc, self.ctx, self.mobs, self.code, self.namespace = doc, ctx, mobs, code, namespace

    def __getitem__(self, obj_id: str):
        return self.mobs[obj_id]

    def eval(self, expr: str):
        return eval(compile(expr, "<test>", "eval"), self.namespace)


def document(objects: list[dict], steps: list[dict] = ()) -> Document:
    doc, problems = validate_data({"scenes": [{"id": "s", "objects": objects, "steps": list(steps)}]})
    assert doc is not None and not has_errors(problems), [str(p) for p in problems]
    return doc


def build(objects: list[dict], steps: list[dict] = (), base_dir: Path | None = None) -> Built:
    doc = document(objects, steps)
    scene = doc.scenes[0]
    ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects}, base_dir=base_dir or Path.cwd())
    namespace = dict(NAMESPACE)
    code = {}
    for obj in build_order(scene):
        expr = object_expression(obj, ctx)
        code[obj.id] = expr
        namespace[ctx.var(obj.id)] = eval(compile(expr, f"<{obj.id}>", "eval"), namespace)
    return Built(doc, ctx, {o.id: namespace[o.id] for o in scene.objects}, code, namespace)


def build_one(obj: dict, *before: dict, steps: list[dict] = (), base_dir: Path | None = None):
    built = build([*before, obj], steps, base_dir)
    return built[obj["id"]], built


def assert_drawable(mob):
    assert isinstance(mob, Mobject)
    for member in mob.get_family():
        assert np.isfinite(member.get_points()).all(), member
    assert np.isfinite(mob.get_bounding_box()).all()


def box(mob):
    low, _, high = mob.get_bounding_box()
    return low[0], low[1], high[0], high[1]


def near(a, b, tol=TOL):
    return np.allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), atol=tol)


LATEX_KINDS = {"tex", "matrix", "brace"}
LATEX_FIELDS = {"label", "x_label", "y_label", "show_coordinates"}


def needs_latex(kind: str, fields: dict, before: list[dict] = ()) -> bool:
    """Whether building this needs LaTeX: formulas, matrices, braces, labels and round brackets do."""
    return (
        kind in LATEX_KINDS
        or bool(LATEX_FIELDS & set(fields))
        or fields.get("bracket") == "round"
        or any(needs_latex(b["type"], b) for b in before)
    )


def latex_marked(cases):
    """
    Cases (kind, fields, objects before it, ...) as pytest params, those needing LaTeX marked
    render, which CI's fast job leaves out.
    """
    return [
        pytest.param(
            *case,
            marks=[pytest.mark.render] if needs_latex(case[0], case[1], case[2]) else [],
            id=case[0] + ":" + ",".join(sorted(case[1]))[:60],
        )
        for case in cases
    ]


# Every kind, with its options

PLANE = {"id": "plane", "type": "number_plane"}
SMALL_PLANE = {"id": "plane", "type": "number_plane", "x_range": [-4, 4, 1], "y_range": [-2, 2, 0.5], "width": 6, "height": 4, "place": [1, 0.5]}
AXES = {"id": "ax", "type": "axes", "x_range": [0, 10, 1], "y_range": [0, 100, 10], "width": 8, "height": 5, "place": [0.5, -0.5]}
AXES_3D = {"id": "ax3", "type": "axes_3d"}
LINE = {"id": "nl", "type": "number_line", "x_range": [0, 4, 0.5], "length": 8, "place": [0, -2]}
WORDS = {"id": "words", "type": "text", "text": "Some words", "place": [2, 1]}
SHAPE = {"id": "sq", "type": "square", "side": 1.5, "place": [-3, 1]}
IMAGE = {"id": "img", "type": "image", "path": "pic.png", "height": 1}

COMMON_FREE = {"color": "YELLOW", "opacity": 0.6, "z": 3, "scale": 1.5, "rotate": 30, "place": "top_left"}
EVERYTHING_FREE = {**COMMON_FREE, "backdrop": True, "fixed": True}
COMMON_PLOTTED = {"color": "RED", "opacity": 0.5, "z": -2, "fixed": True}

CASES: list[tuple[str, dict, list[dict]]] = [
    ("text", {"text": "Hello"}, []),
    ("text", {"text": "two\nlines", "align": "left", "font_size": 30}, []),
    ("text", {"text": "bold italic", "bold": True, "italic": True, "font": "Serif"}, []),
    ("text", {"text": "colored parts", "colors": {"colored": "RED", "parts": "#00FF00"}, "color": "BLUE"}, []),
    ("text", {"text": ""}, []),
    ("text", {"text": "everything", **EVERYTHING_FREE}, []),
    ("text", {"text": "beside", "place": {"next_to": "words", "side": "left", "buff": 0.5}}, [WORDS]),
    ("tex", {"tex": R"a^2 + b^2 = c^2"}, []),
    ("tex", {"tex": R"\frac{1}{2}", "font_size": 30, "colors": {"1": "RED"}}, []),
    ("tex", {"tex": R"e^{i\pi} = -1", **EVERYTHING_FREE}, []),
    ("tex", {"tex": ""}, []),
    ("tex", {"tex": R"x \cdot y", "place": {"at": [2, 1], "on": "plane"}}, [PLANE]),
    ("title", {"text": "A title"}, []),
    ("title", {"text": "No line", "underline": False, "font_size": 40, "place": "bottom"}, []),
    ("title", {"text": "Everything", **EVERYTHING_FREE}, []),
    ("quote", {"text": "To be or not to be", "author": "Shakespeare"}, []),
    ("quote", {"text": "“Already quoted”\nover two lines", "font_size": 30}, []),
    ("quote", {"text": "Quoted", **EVERYTHING_FREE}, []),
    ("bullets", {"items": ["one"]}, []),
    ("bullets", {"items": ["one", "two\nlines", "three"], "font_size": 28, "buff": 0.1}, []),
    ("bullets", {"items": ["a", "b"], **EVERYTHING_FREE}, []),
    ("matrix", {"entries": [[1, 2], [3, 4]]}, []),
    ("matrix", {"entries": [[1.5], [-2]], "bracket": "round", "font_size": 30}, []),
    ("matrix", {"entries": [["a", R"\pi"], [0, "x^2"]], "row_colors": ["RED"], "column_colors": ["GREEN", "BLUE"], "color": "YELLOW"}, []),
    ("matrix", {"entries": [["1", ""]], **EVERYTHING_FREE}, []),
    ("number_plane", {}, []),
    ("number_plane", {"x_range": [-3, 3, 0.5], "y_range": [-2, 2], "width": 6, "height": 4, "faded": True, "numbers": True}, []),
    ("number_plane", {"color": "GREEN", "opacity": 0.5, "place": "right", "backdrop": True}, []),
    ("axes", {}, []),
    ("axes", {"x_range": [0, 1, 0.25], "y_range": [-1, 1, 0.5], "width": 6, "height": 3, "numbers": True, "tips": True,
              "x_label": "t", "y_label": R"\sin t"}, []),
    ("axes", {"numbers": False, **EVERYTHING_FREE}, []),
    ("axes_3d", {}, []),
    ("axes_3d", {"x_range": [-2, 2, 1], "numbers": True, "color": "BLUE", "fixed": True}, []),
    ("number_line", {}, []),
    ("number_line", {"x_range": [-1, 1, 0.25], "length": 10, "tip": True, "numbers": False, "place": "bottom"}, []),
    ("number_line", {"x_range": [0, 3], **EVERYTHING_FREE}, []),
    ("graph", {"on": "ax", "function": "x^2 / 10"}, [AXES]),
    ("graph", {"on": "plane", "function": "1/x", "x_range": [-3, 3], "label": R"\frac{1}{x}", "color": "PINK"}, [PLANE]),
    ("graph", {"on": "ax", "function": "sqrt(x - 5)", **COMMON_PLOTTED}, [AXES]),
    ("dot", {"point": [1, 2]}, []),
    ("dot", {"point": [1, 2, 3]}, []),
    ("dot", {"point": [1, 2], "on": "plane", "radius": 0.2, "label": "A", "label_side": "left"}, [PLANE]),
    ("dot", {"point": [5, 50], "on": "ax", **COMMON_PLOTTED}, [AXES]),
    ("dot", {"point": [1.5, 0.5], "on": "nl", "label": "p"}, [LINE]),
    ("dot", {"point": [1, 2, 1], "on": "ax3"}, [AXES_3D]),
    ("vector", {"tip": [2, 1]}, []),
    ("vector", {"tip": [0, 0]}, []),
    ("vector", {"tip": [2, 1], "tail": [-1, 1], "on": "plane", "label": R"\vec{v}", "show_coordinates": True, "thickness": 5}, [PLANE]),
    ("vector", {"tip": [3, 60], "on": "ax", "label": "w", "label_side": "up", **COMMON_PLOTTED}, [AXES]),
    ("vector", {"tip": [1, 1, 1], "on": "ax3", "show_coordinates": True}, [AXES_3D]),
    ("vector", {"tip": [3], "on": "nl"} | {"tip": [3, 0]}, [LINE]),
    ("line", {"start": [0, 0], "end": [2, 1]}, []),
    ("line", {"start": [0, 0], "end": [2, 1], "dashed": True, "thickness": 6}, []),
    ("line", {"start": [0, 0], "end": [2, 1], "arrow": True, "thickness": 6, "on": "plane"}, [PLANE]),
    ("line", {"start": [1, 0], "end": [1, 80], "dashed": True, "arrow": True, "on": "ax", **COMMON_PLOTTED}, [AXES]),
    ("line", {"start": [0, 0], "end": [0, 0]}, []),
    ("polygon", {"points": [[0, 0], [3, 0], [3, 2]]}, []),
    ("polygon", {"points": [[0, 0], [2, 0], [2, 1], [0, 1]], "on": "plane", "fill": "BLUE", "fill_opacity": 0.8}, [PLANE]),
    ("polygon", {"points": [[0, 0, 0], [1, 0, 1], [0, 1, 1]], "on": "ax3", "fill": "RED", **COMMON_PLOTTED}, [AXES_3D]),
    ("circle", {}, []),
    ("circle", {"radius": 0.5, "fill": "BLUE", "fill_opacity": 1, "thickness": 0}, []),
    ("circle", {"fill": "GREEN", **EVERYTHING_FREE}, []),
    ("rectangle", {}, []),
    ("rectangle", {"width": 3, "height": 1, "corner_radius": 0.3, "fill": "#123456", "thickness": 8}, []),
    ("rectangle", {"width": 1, "height": 0.5, "corner_radius": 5, **EVERYTHING_FREE}, []),
    ("square", {}, []),
    ("square", {"side": 0.5, "fill": "RED", "fill_opacity": 0.2, **EVERYTHING_FREE}, []),
    ("brace", {"target": "words"}, [WORDS]),
    ("brace", {"target": "sq", "side": "left", "label": "n", "buff": 0.3, "color": "YELLOW"}, [SHAPE]),
    ("brace", {"target": "plane", "side": "up", **COMMON_PLOTTED}, [SMALL_PLANE]),
    ("box", {"target": "words"}, [WORDS]),
    ("box", {"target": "sq", "buff": 0.3, "corner_radius": 0.2, "fill_opacity": 0.3, "color": "TEAL", "opacity": 0.5}, [SHAPE]),
    ("box", {"target": "img", "fixed": True, "z": 1}, [IMAGE]),
    ("image", {"path": "pic.png"}, []),
    ("image", {"path": "sub dir/it's.png", "height": 2, **EVERYTHING_FREE}, []),
    ("image", {"path": "sub dir\\it's.png"}, []),
    ("svg", {"path": "star.svg"}, []),
    ("svg", {"path": "star.svg", "height": 1, **EVERYTHING_FREE}, []),
    ("group", {"members": ["words", "sq"]}, [WORDS, SHAPE]),
    ("group", {"members": ["words", "sq", "words"], "arrange": "row", "buff": 0.2, **EVERYTHING_FREE}, [WORDS, SHAPE]),
    ("group", {"members": ["words", "img"], "arrange": "column", "opacity": 0.5}, [WORDS, IMAGE]),
]

EXPECTED_TYPES = {
    "text": Text, "tex": Tex, "title": (Text, VGroup), "quote": VGroup, "bullets": VGroup, "matrix": Matrix,
    "number_plane": NumberPlane, "axes": Axes, "axes_3d": ThreeDAxes, "number_line": NumberLine,
    "graph": VMobject, "dot": Dot, "vector": Arrow, "line": (Line, Arrow, DashedLine), "polygon": Polygon,
    "circle": Circle, "rectangle": (Rectangle, RoundedRectangle), "square": Square, "brace": (Brace, VGroup),
    "box": SurroundingRectangle, "image": ImageMobject, "svg": SVGMobject, "group": (VGroup, Group),
}
KEEP_TYPE_UNDER_BACKDROP = {"number_plane", "axes", "axes_3d", "matrix"}


def test_every_kind_has_cases():
    assert {kind for kind, _, _ in CASES} == set(OBJECT_MODELS)
    assert set(EXPECTED_TYPES) == set(OBJECT_MODELS)
    assert {kind for kind, *_ in COLOR_CASES} == set(OBJECT_MODELS) - {"image"}


@pytest.mark.parametrize("kind, fields, before", latex_marked(CASES))
def test_every_kind_builds(kind, fields, before, media):
    obj = {"id": "it", "type": kind, **fields}
    mob, built = build_one(obj, *before, base_dir=media)
    expr = built.code["it"]
    # One expression, which compiles by itself
    assert isinstance(ast.parse(expr, mode="eval").body, (ast.Call, ast.Attribute, ast.Name))
    compile(expr, "<it>", "eval")
    assert_drawable(mob)
    expected = EXPECTED_TYPES[kind]
    if fields.get("backdrop") and kind not in KEEP_TYPE_UNDER_BACKDROP:
        assert isinstance(mob, (VGroup, Group)) and isinstance(mob[1], expected)
    else:
        assert isinstance(mob, expected)
    for before_obj in before:
        assert_drawable(built[before_obj["id"]])


# Where things end up

def codes(objects: list[dict]) -> dict[str, str]:
    """The code for each object, in build order, without running any of it."""
    doc = document(objects)
    scene = doc.scenes[0]
    ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects})
    return {obj.id: object_expression(obj, ctx) for obj in build_order(scene)}


def test_readable_code():
    """What a person would have written: pinned, since the code is part of the product."""
    code = codes([
        PLANE,
        {"id": "t", "type": "text", "text": "Hello", "place": "top"},
        {"id": "eq", "type": "tex", "tex": R"a^2 + b^2 = c^2", "place": {"next_to": "t"}},
        {"id": "v", "type": "vector", "tip": [1, 2], "on": "plane", "color": "YELLOW"},
        {"id": "d", "type": "dot", "point": [1, 2], "on": "plane", "label": "A"},
        {"id": "c", "type": "circle", "radius": 0.5, "fill": "BLUE"},
        {"id": "g", "type": "group", "members": ["t", "eq"], "arrange": "column"},
    ])
    assert code == {
        "plane": "NumberPlane(x_range=[-8, 8, 1], y_range=[-4, 4, 1])",
        "t": 'place(Text("Hello"), edge="top")',
        "eq": 'place(Tex("a^2 + b^2 = c^2"), next_to=t)',
        "v": "Arrow(plane.c2p(0, 0), plane.c2p(1, 2), buff=0).set_color(YELLOW)",
        "d": 'with_label(Dot(plane.c2p(1, 2)), Tex("A", font_size=36), "up")',
        "c": "Circle(radius=0.5).set_stroke(BLUE).set_fill(BLUE, opacity=0.5)",
        "g": "VGroup(t, eq).arrange(DOWN, buff=0.5)",
    }
    assert list(code) == ["plane", "t", "eq", "v", "d", "c", "g"]
    more = codes([
        {"id": "f", "type": "tex", "tex": R"\frac{a}{b}"},
        {"id": "s", "type": "text", "text": "back\\slash", "backdrop": True, "fixed": True},
        {"id": "n", "type": "number_line", "x_range": [0, 2, 0.5]},
        {"id": "p", "type": "dot", "point": [1, 0.5], "on": "n"},
        {"id": "l", "type": "text", "text": "on the line", "place": {"at": [1, 1], "on": "n"}},
        {"id": "g", "type": "graph", "on": "a", "function": "sin(x)", "x_range": [0, 3]},
        {"id": "a", "type": "axes", "x_range": [0, 3, 1], "y_range": [-1, 1, 0.5], "numbers": True},
    ])
    assert more == {
        "f": R'Tex(R"\frac{a}{b}")',
        "s": "with_backdrop(Text('back\\\\slash')).fix_in_frame()",
        "n": "NumberLine(x_range=[0, 2, 0.5], include_numbers=True, decimal_number_config=dict(num_decimal_places=1))",
        "p": "Dot(n.n2p(1) + 0.5 * UP)",
        "l": 'place(Text("on the line"), at=[1, 1], on=n)',
        "a": "with_numbers(Axes(x_range=[0, 3, 1], y_range=[-1, 1, 0.5]), num_decimal_places=1)",
        "g": 'function_graph(a, "sin(x)", x_range=[0, 3])',
    }


@pytest.mark.parametrize("on, system", [(None, None), ("plane", SMALL_PLANE), ("ax", AXES), ("ax3", AXES_3D), ("nl", LINE)])
def test_plotted_objects_land_on_their_coordinates(on, system):
    def at(coords):
        if on is None:
            return [*coords, 0][:3] if len(coords) == 2 else coords
        mob = built[on]
        if on == "nl":
            return mob.n2p(coords[0]) + coords[1] * np.array([0, 1, 0])
        return mob.c2p(*coords)

    pts = {
        None: ([1, 2], [-2, 1], [0.5, -1], [[0, 0], [2, 0], [1, 1.5]]),
        "plane": ([1, 1.5], [-3, 1], [2, -1], [[0, 0], [2, 0], [1, 1.5]]),
        "ax": ([5, 50], [2, 20], [8, 90], [[1, 10], [9, 10], [5, 80]]),
        "ax3": ([1, 2, 1], [-1, 1, 2], [2, -2, -1], [[0, 0, 0], [2, 0, 1], [1, 1, 2]]),
        "nl": ([1.5, 0.5], [0.5, 0], [3.5, 1], [[0, 0], [2, 0], [1, 1.5]]),
    }[on]
    point, tail, tip, corners = pts
    objects = [] if system is None else [system]
    objects += [
        {"id": "d", "type": "dot", "point": point},
        {"id": "v", "type": "vector", "tip": tip, "tail": tail},
        {"id": "o", "type": "vector", "tip": tip},
        {"id": "l", "type": "line", "start": tail, "end": tip},
        {"id": "a", "type": "line", "start": tail, "end": tip, "arrow": True},
        {"id": "p", "type": "polygon", "points": corners},
    ]
    if on is not None:
        for obj in objects[1:]:
            obj["on"] = on
    built = build(objects)
    assert near(built["d"].get_center(), at(point))
    assert near(built["v"].get_start(), at(tail)) and near(built["v"].get_end(), at(tip))
    origin = [0] * len(tip)
    assert near(built["o"].get_start(), at(origin)) and near(built["o"].get_end(), at(tip))
    assert near(built["l"].get_start(), at(tail)) and near(built["l"].get_end(), at(tip))
    assert near(built["a"].get_start(), at(tail)) and near(built["a"].get_end(), at(tip))
    assert near(built["p"].get_vertices(), [at(c) for c in corners])


def test_graph_follows_its_function_on_its_axes():
    built = build([AXES, {"id": "g", "type": "graph", "on": "ax", "function": "x^2", "x_range": [1, 9]}])
    axes, graph = built["ax"], built["g"]
    coords = np.array([axes.p2c(p) for p in graph.get_anchors()])
    assert np.allclose(coords[:, 1], coords[:, 0] ** 2, atol=0.05)
    assert coords[0, 0] == pytest.approx(1, abs=1e-3) and coords[:, 0].max() == pytest.approx(9, abs=1e-3)


def test_graph_default_range_is_the_axes():
    built = build([AXES, {"id": "g", "type": "graph", "on": "ax", "function": "5 * x"}])
    coords = np.array([built["ax"].p2c(p) for p in built["g"].get_anchors()])
    assert coords[0, 0] == pytest.approx(0, abs=1e-3) and coords[-1, 0] == pytest.approx(10, abs=1e-3)


@pytest.mark.render
@pytest.mark.parametrize("side", ["up", "down", "left", "right"])
def test_vector_label_is_beside_the_tip(side):
    built = build([PLANE, {"id": "v", "type": "vector", "tip": [2, 1], "on": "plane", "label": "v", "label_side": side}])
    arrow = built["v"]
    label = arrow.submobjects[-1]
    x0, y0, x1, y1 = box(label)
    tx, ty, _ = arrow.get_end()
    assert {"right": x0 > tx, "left": x1 < tx, "up": y0 > ty, "down": y1 < ty}[side]
    if side in ("left", "right"):
        assert y0 < ty < y1 and min(abs(x0 - tx), abs(x1 - tx)) < 0.2
    else:
        assert x0 < tx < x1 and min(abs(y0 - ty), abs(y1 - ty)) < 0.2


@pytest.mark.render
def test_vector_coordinates_show_the_tip():
    built = build([PLANE, {"id": "v", "type": "vector", "tip": [-1.5, 2], "tail": [1, 1], "on": "plane",
                            "show_coordinates": True, "label": "u"}])
    arrow = built["v"]
    matrix = next(m for m in arrow.submobjects if isinstance(m, Matrix))
    assert [e.get_tex() for e in matrix.elements] == ["-1.5", "2"]
    # Past the tip, carrying on the way the arrow points
    assert np.dot(matrix.get_center() - arrow.get_end(), arrow.get_end() - arrow.get_start()) > 0
    label = next(m for m in arrow.submobjects if isinstance(m, Tex) and m is not matrix)
    x0, y0, x1, y1 = box(label)
    mx0, my0, mx1, my1 = box(matrix)
    assert x1 <= mx0 or mx1 <= x0 or y1 <= my0 or my1 <= y0


@pytest.mark.render
@pytest.mark.parametrize("side", ["up", "down", "left", "right"])
def test_dot_label_and_number_line_height(side):
    built = build([LINE, {"id": "d", "type": "dot", "point": [2, 0.75], "on": "nl", "label": "p", "label_side": side}])
    dot = built["d"]
    disc = VMobject().set_points(dot.get_points())
    assert near(disc.get_center(), built["nl"].n2p(2) + [0, 0.75, 0])
    lx0, ly0, lx1, ly1 = box(dot.submobjects[-1])
    dx0, dy0, dx1, dy1 = box(disc)
    assert {"up": ly0 > dy1, "down": ly1 < dy0, "left": lx1 < dx0, "right": lx0 > dx1}[side]


@pytest.mark.render
@pytest.mark.parametrize("side", ["up", "down", "left", "right"])
def test_brace_is_on_its_side_with_its_label_beyond(side):
    built = build([SHAPE, {"id": "b", "type": "brace", "target": "sq", "side": side, "label": "n", "buff": 0.2}])
    target, group = built["sq"], built["b"]
    brace, label = group
    tx0, ty0, tx1, ty1 = box(target)
    bx0, by0, bx1, by1 = box(brace)
    lx0, ly0, lx1, ly1 = box(label)
    if side == "down":
        assert by1 == pytest.approx(ty0 - 0.2, abs=0.02) and ly1 < by0
    elif side == "up":
        assert by0 == pytest.approx(ty1 + 0.2, abs=0.02) and ly0 > by1
    elif side == "left":
        assert bx1 == pytest.approx(tx0 - 0.2, abs=0.02) and lx1 < bx0
    else:
        assert bx0 == pytest.approx(tx1 + 0.2, abs=0.02) and lx0 > bx1


def test_box_surrounds_its_target():
    built = build([WORDS, {"id": "b", "type": "box", "target": "words", "buff": 0.3}])
    wx0, wy0, wx1, wy1 = box(built["words"])
    assert box(built["b"]) == pytest.approx((wx0 - 0.3, wy0 - 0.3, wx1 + 0.3, wy1 + 0.3), abs=TOL)


def test_group_arranges_its_members(media):
    built = build([
        {"id": "a", "type": "square", "side": 1},
        {"id": "b", "type": "circle", "radius": 0.3},
        {"id": "c", "type": "text", "text": "c"},
        {"id": "row", "type": "group", "members": ["a", "b", "c"], "arrange": "row", "buff": 0.4},
    ])
    a, b, c = built["a"], built["b"], built["c"]
    assert box(b)[0] == pytest.approx(box(a)[2] + 0.4, abs=TOL)
    assert box(c)[0] == pytest.approx(box(b)[2] + 0.4, abs=TOL)
    assert near(built["row"].get_center(), [0, 0, 0])
    built = build([
        {"id": "a", "type": "square", "side": 1, "place": [3, 3]},
        {"id": "b", "type": "text", "text": "b", "place": [-3, -3]},
        IMAGE,
        {"id": "col", "type": "group", "members": ["a", "b", "img"], "arrange": "column", "buff": 0.2},
        {"id": "loose", "type": "group", "members": ["a", "b"]},
    ], base_dir=media)
    assert isinstance(built["col"], Group) and not isinstance(built["col"], VGroup)
    assert box(built["b"])[3] == pytest.approx(box(built["a"])[1] - 0.2, abs=TOL)
    assert box(built["img"])[3] == pytest.approx(box(built["b"])[1] - 0.2, abs=TOL)
    assert isinstance(built["loose"], VGroup)


def test_group_left_alone_keeps_its_members_where_they_are():
    built = build([
        {"id": "a", "type": "square", "side": 1, "place": [3, 2]},
        {"id": "b", "type": "text", "text": "b", "place": [-3, -2]},
        {"id": "g", "type": "group", "members": ["a", "b"], "color": "RED"},
    ])
    assert near(built["a"].get_center(), [3, 2, 0]) and near(built["b"].get_center(), [-3, -2, 0])


def test_title_goes_to_the_top_by_default():
    title = build([{"id": "t", "type": "title", "text": "Heading"}])["t"]
    x0, y0, x1, y1 = box(title)
    assert y1 == pytest.approx(FRAME_HEIGHT / 2 - 0.25, abs=TOL)
    assert (x0 + x1) / 2 == pytest.approx(0, abs=TOL)


def test_placements_of_free_objects():
    built = build([
        PLANE,
        {"id": "a", "type": "square", "side": 1, "place": [2, -1]},
        {"id": "b", "type": "square", "side": 1, "place": "bottom_right"},
        {"id": "c", "type": "square", "side": 1, "place": {"next_to": "a", "side": "right", "buff": 0.5}},
        {"id": "d", "type": "square", "side": 1, "place": {"at": [2, 1], "on": "plane", "shift": [0, 0.5]}},
        {"id": "e", "type": "square", "side": 1},
        {"id": "f", "type": "text", "text": "x" * 80, "font_size": 60, "place": {"edge": "left", "buff": 0.5}},
    ])
    assert near(built["a"].get_center(), [2, -1, 0])
    assert box(built["b"])[2:] == pytest.approx((FRAME_WIDTH / 2 - 0.25, -FRAME_HEIGHT / 2 + 1.25), abs=TOL)
    assert box(built["c"])[0] == pytest.approx(box(built["a"])[2] + 0.5, abs=TOL)
    assert near(built["d"].get_center(), built["plane"].c2p(2, 1) + [0, 0.5, 0])
    assert near(built["e"].get_center(), [0, 0, 0])
    x0, y0, x1, y1 = box(built["f"])
    assert x0 == pytest.approx(-FRAME_WIDTH / 2 + 0.5, abs=TOL) and x1 <= FRAME_WIDTH / 2 - 0.5 + TOL


def test_scale_and_rotate():
    plain = build([{"id": "r", "type": "rectangle", "width": 2, "height": 1}])["r"]
    scaled = build([{"id": "r", "type": "rectangle", "width": 2, "height": 1, "scale": 1.5}])["r"]
    turned = build([{"id": "r", "type": "rectangle", "width": 2, "height": 1, "rotate": 90}])["r"]
    thirty = build([{"id": "r", "type": "rectangle", "width": 2, "height": 1, "rotate": 30, "scale": 2}])["r"]
    assert scaled.get_width() == pytest.approx(3, abs=TOL) and scaled.get_height() == pytest.approx(1.5, abs=TOL)
    assert turned.get_width() == pytest.approx(1, abs=TOL) and turned.get_height() == pytest.approx(2, abs=TOL)
    expected = plain.copy().scale(2).rotate(math.radians(30))
    assert near(thirty.get_points(), expected.get_points())
    text = build([{"id": "t", "type": "text", "text": "turn", "rotate": -45, "place": [1, 1]}])["t"]
    assert near(text.get_center(), [1, 1, 0])


def test_styles():
    built = build([
        {"id": "t", "type": "text", "text": "blue with red", "color": "BLUE", "colors": {"red": "RED"}},
        {"id": "c", "type": "circle", "fill": "GREEN", "fill_opacity": 0.5, "opacity": 0.5, "thickness": 7},
        {"id": "o", "type": "circle", "color": "YELLOW"},
        {"id": "p", "type": "number_plane", "faded": True, "opacity": 0.5},
        {"id": "s", "type": "square", "z": 4, "fixed": True},
        {"id": "x", "type": "text", "text": "faint", "opacity": 0.25},
        {"id": "g", "type": "group", "members": ["p", "x"], "opacity": 0.5},
    ])
    text = built["t"]
    assert text["blue"][0][0].get_fill_color().upper() == "#58C4DD"
    assert text["red"][0][0].get_fill_color().upper() == "#FC6255"
    circle = built["c"]
    assert circle.get_fill_opacity() == pytest.approx(0.25) and circle.get_stroke_opacity() == pytest.approx(0.5)
    assert circle.get_fill_color().upper() == circle.get_stroke_color().upper() == "#83C167"
    assert circle.get_stroke_width() == pytest.approx(7)
    assert built["o"].get_stroke_color().upper() == color_to_hex(YELLOW).upper()
    assert built["o"].get_fill_opacity() == 0
    # Opacity scales a faded plane's lines, keeping the faint ones fainter; a group's opacity
    # scales its members' in turn
    plane = built["p"]
    assert plane.background_lines.get_stroke_opacity() == pytest.approx(0.35 * 0.5 * 0.5)
    assert plane.faded_lines.get_stroke_opacity() == pytest.approx(0.1 * 0.5 * 0.5)
    square = built["s"]
    assert all(m.z_index == 4 for m in square.get_family())
    assert all(m.is_fixed_in_frame() for m in square.get_family())
    assert all(m.get_fill_opacity() == pytest.approx(0.25 * 0.5) for m in built["x"].family_members_with_points())


SPEC_COLOR = "#2A7B9B"
FILL_COLOR = "#C8553D"


def visible_colors(mob) -> tuple[set[str], set[str]]:
    """The fill colors and stroke colors which show, over every member drawn, leaving out backdrops."""
    panels = {id(m) for m in mob.get_family() if type(m).__name__ == "BackgroundRectangle"}
    fills, strokes = set(), set()
    for member in mob.family_members_with_points():
        if id(member) in panels:
            continue
        if member.has_fill():
            fills.add(member.get_fill_color().upper())
        if member.has_stroke():
            strokes.add(member.get_stroke_color().upper())
    return fills, strokes


COLOR_CASES = [
    ("text", {"text": "words"}, [], "fill"),
    ("text", {"text": "words", "colors": {"or": "RED"}, "backdrop": True}, [], "fill"),
    ("tex", {"tex": R"\frac{a}{b}"}, [], "fill"),
    ("title", {"text": "Title"}, [], "both"),
    ("quote", {"text": "Quote", "author": "Someone"}, [], "fill"),
    ("bullets", {"items": ["one", "two"]}, [], "fill"),
    ("matrix", {"entries": [[1, 2]], "bracket": "round"}, [], "fill"),
    ("number_plane", {"x_range": [-2, 2, 1], "y_range": [-1, 1, 1]}, [], "grid"),
    ("axes", {"numbers": True, "tips": True, "x_label": "x"}, [], "both"),
    ("axes_3d", {"numbers": True}, [], "both"),
    ("number_line", {"tip": True}, [], "both"),
    ("graph", {"on": "ax", "function": "x", "label": "f"}, [AXES], "both"),
    ("dot", {"point": [1, 1], "label": "A"}, [], "fill"),
    ("vector", {"tip": [1, 1], "label": "v", "show_coordinates": True}, [], "fill"),
    ("line", {"start": [0, 0], "end": [1, 1]}, [], "stroke"),
    ("line", {"start": [0, 0], "end": [1, 1], "dashed": True, "arrow": True}, [], "both"),
    ("line", {"start": [0, 0], "end": [1, 1], "arrow": True}, [], "fill"),
    ("polygon", {"points": [[0, 0], [1, 0], [0, 1]]}, [], "stroke"),
    ("polygon", {"points": [[0, 0], [1, 0], [0, 1]], "fill": FILL_COLOR}, [], "outline and fill"),
    ("circle", {}, [], "stroke"),
    ("circle", {"fill": FILL_COLOR}, [], "outline and fill"),
    ("rectangle", {"corner_radius": 0.2}, [], "stroke"),
    ("rectangle", {"fill": FILL_COLOR}, [], "outline and fill"),
    ("square", {}, [], "stroke"),
    ("square", {"fill": FILL_COLOR, "backdrop": True}, [], "outline and fill"),
    ("brace", {"target": "words", "label": "n"}, [WORDS], "fill"),
    ("box", {"target": "words"}, [WORDS], "stroke"),
    ("box", {"target": "words", "fill_opacity": 0.3}, [WORDS], "both"),
    ("svg", {"path": "star.svg"}, [], "fill"),
    ("group", {"members": ["words", "sq"]}, [WORDS, SHAPE], "both"),
]
@pytest.mark.parametrize("kind, fields, before, where", latex_marked(COLOR_CASES))
def test_every_kind_takes_its_color(kind, fields, before, where, media):
    """The color a spec asks for is the one drawn, in fill or outline as suits the kind; a fill has its own color."""
    mob, _ = build_one({"id": "it", "type": kind, "color": SPEC_COLOR, **fields}, *before, base_dir=media)
    fills, strokes = visible_colors(mob)
    if where == "grid":
        assert mob.background_lines.get_stroke_color().upper() == SPEC_COLOR
        assert {m.get_stroke_color().upper() for m in mob.faded_lines} == {SPEC_COLOR}
        return
    if where == "outline and fill":
        assert strokes == {SPEC_COLOR} and fills == {FILL_COLOR}
        return
    colors = fills | strokes
    if kind == "text" and "colors" in fields:
        assert colors == {SPEC_COLOR, "#FC6255"}
        return
    assert colors == {SPEC_COLOR}, (fills, strokes)
    assert {"fill": fills, "stroke": strokes, "both": colors}[where]
    if where == "fill":
        assert not strokes or strokes == {SPEC_COLOR}


def test_shapes_without_a_color_keep_manims_and_take_their_fills():
    built = build([
        {"id": "c", "type": "circle"},
        {"id": "f", "type": "circle", "fill": FILL_COLOR},
        {"id": "s", "type": "square", "fill": FILL_COLOR, "fill_opacity": 1},
    ])
    assert built["c"].get_stroke_color().upper() == "#FC6255"
    assert built["f"].get_stroke_color().upper() == FILL_COLOR == built["f"].get_fill_color().upper()
    assert built["s"].get_fill_opacity() == 1


BACKDROP_CASES = [
    ("text", {"text": "a"}, []), ("tex", {"tex": "x"}, []), ("title", {"text": "t"}, []),
    ("quote", {"text": "q", "author": "a"}, []), ("bullets", {"items": ["i"]}, []), ("circle", {}, []),
    ("rectangle", {}, []), ("square", {}, []), ("number_line", {}, []), ("svg", {"path": "star.svg"}, []),
    ("group", {"members": ["words"]}, [WORDS]), ("image", {"path": "pic.png"}, []),
    ("number_plane", {"x_range": [-2, 2, 1], "y_range": [-1, 1, 1]}, []), ("axes", {}, []), ("axes_3d", {}, []),
    ("matrix", {"entries": [[1]]}, []),
]


@pytest.mark.parametrize("kind, fields, before", latex_marked(BACKDROP_CASES))
def test_backdrop_is_behind_and_moves_with_the_object(kind, fields, before, media):
    mob, _ = build_one({"id": "it", "type": kind, "backdrop": True, "place": [1, -1], **fields}, *before, base_dir=media)
    panel = mob.submobjects[0]
    assert type(panel).__name__ == "BackgroundRectangle"
    # Drawn before anything else of the object, so behind it
    drawn = [m for m in mob.get_family() if m.has_points() or isinstance(m, ImageMobject)]
    assert drawn[0] is panel
    if kind in KEEP_TYPE_UNDER_BACKDROP:
        assert isinstance(mob, EXPECTED_TYPES[kind])
        rest = Group(*mob.submobjects[1:])
    else:
        assert len(mob.submobjects) == 2 and isinstance(mob[1], EXPECTED_TYPES[kind])
        rest = mob[1]
    rx0, ry0, rx1, ry1 = box(rest)
    px0, py0, px1, py1 = box(panel)
    assert px0 < rx0 and py0 < ry0 and px1 > rx1 and py1 > ry1
    assert near(mob.get_center(), [1, -1, 0])


def test_things_placed_on_a_backdropped_number_line_still_find_it():
    built = build([
        {**LINE, "backdrop": True},
        {"id": "d", "type": "dot", "point": [1, 0.5], "on": "nl"},
        {"id": "t", "type": "text", "text": "here", "place": {"at": [3, 1], "on": "nl"}},
    ])
    line = built["nl"][1]
    assert isinstance(line, NumberLine)
    assert near(built["d"].get_center(), line.n2p(1) + [0, 0.5, 0])
    assert near(built["t"].get_center(), line.n2p(3) + [0, 1, 0])


def test_image_and_svg_paths_are_resolved_against_the_scene_folder(media):
    built = build([
        {"id": "a", "type": "image", "path": "pic.png"},
        {"id": "b", "type": "image", "path": "sub dir\\it's.png"},
        {"id": "c", "type": "svg", "path": "star.svg"},
    ], base_dir=media)
    assert f'"{(media / "pic.png").as_posix()}"' in built.code["a"]
    assert Path(built["b"].image_path) == media / "sub dir" / "it's.png"
    assert built["b"].get_height() == pytest.approx(3)
    assert built["c"].get_height() == pytest.approx(2)


# Strings typed by users

HOSTILE = [
    "plain",
    "it's",
    'say "hi"',
    '"""',
    "'''",
    "back\\slash",
    "ends in a backslash\\",
    "\\n is not a newline",
    "two\nlines",
    "windows\r\nline",
    "tab\there",
    "nul\x00byte",
    "\x1b[31mescape",
    "emoji 🙂 ok",
    "ünïcödé",
    "‮right to left",
    "'); import os; os.system('echo pwned'); ('",
    '" + __import__("os").system("echo pwned") + "',
    "\\\" + __import__('os').getcwd() + \\\"",
    "{curly} {{braces}} %s %d",
    "<b>markup</b> &amp; &lt;",
    "lone \ud800 surrogate",
    'R"raw"',
    "\\",
    "",
]


def shape(expr: str) -> str:
    """The expression's syntax tree, with every string in it made the same."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = "S"
    return ast.dump(tree)


def strings_in(expr: str) -> list[str]:
    return [n.value for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def code_for(obj: dict, *before: dict, base_dir: Path | None = None) -> str:
    doc = document([*before, obj])
    scene = doc.scenes[0]
    ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects}, base_dir=base_dir or Path("/scenes"))
    return object_expression(scene.objects[-1], ctx)


STRING_FIELDS = [
    ("text", lambda s: {"text": s}),
    ("text", lambda s: {"text": "colored", "colors": {s: "RED"}}),
    ("text", lambda s: {"text": "font", "font": s}),
    ("tex", lambda s: {"tex": s}),
    ("tex", lambda s: {"tex": "x", "colors": {s: "RED"}}),
    ("title", lambda s: {"text": s}),
    ("quote", lambda s: {"text": s, "author": s}),
    ("bullets", lambda s: {"items": [s, "second"]}),
    ("matrix", lambda s: {"entries": [[s, "1"]]}),
    ("axes", lambda s: {"x_label": s, "y_label": s}),
    ("dot", lambda s: {"point": [0, 0], "label": s}),
    ("vector", lambda s: {"tip": [1, 1], "label": s}),
    ("brace", lambda s: {"target": "words", "label": s}),
    ("graph", lambda s: {"on": "ax", "function": "x", "label": s}),
    # Kept a relative path inside the scene's folder, which is all validation lets through
    ("image", lambda s: {"path": "pictures/" + re.sub(r"\.\.|[/\\:]", "_", s) + ".png"}),
    ("svg", lambda s: {"path": "drawings/" + re.sub(r"\.\.|[/\\:]", "_", s) + ".svg"}),
]


def benign_like(text: str, fields) -> str:
    """
    A harmless string which gives code of the same shape as text is meant to: one with a line
    break if text has one (bullets set left alignment for those), and empty where text comes
    to nothing (an empty author is no author, a font name of only punctuation no font).
    """
    if "font" in fields("x"):
        return "a" if re.sub(r"[^\w .,-]", "", text).strip() else ""
    shown = displayable(text)
    if not shown:
        return ""
    return "a\nb" if "\n" in shown else "a"


@pytest.mark.parametrize("text", HOSTILE, ids=repr)
@pytest.mark.parametrize("kind, fields", STRING_FIELDS, ids=lambda v: v if isinstance(v, str) else "")
def test_typed_text_never_changes_the_code(kind, fields, text):
    before = {"brace": [WORDS], "graph": [AXES]}.get(kind, [])
    obj = {"id": "it", "type": kind, **fields(text)}
    expr = code_for(obj, *before)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(expr, "<it>", "eval")
    assert shape(expr) == shape(code_for({"id": "it", "type": kind, **fields(benign_like(text, fields))}, *before))
    if kind in ("text", "title", "tex", "bullets", "matrix") and "font" not in fields("x") and "colors" not in fields("x"):
        assert displayable(text) in [s.removeprefix("• ") for s in strings_in(expr)]


@pytest.mark.parametrize("text", HOSTILE, ids=repr)
def test_typed_text_is_drawn_exactly(text):
    built = build([
        {"id": "t", "type": "text", "text": text},
        {"id": "h", "type": "title", "text": text},
        {"id": "q", "type": "quote", "text": text, "author": text},
        {"id": "b", "type": "bullets", "items": [text]},
        {"id": "c", "type": "text", "text": "x" + text, "colors": {text or "x": "RED"}, "font": text},
    ])
    wanted = displayable(text)
    assert built["t"].text == wanted
    assert built["h"][0].text == wanted
    assert built["q"][0].text in (wanted, f"“{wanted}”")
    if wanted:
        assert built["q"][1].text == "— " + wanted
    else:
        assert len(built["q"]) == 1
    assert built["b"][0].text == "• " + wanted
    assert built["c"].text == "x" + wanted
    for mob in built.mobs.values():
        assert_drawable(mob)


def test_hostile_part_and_function_strings():
    text = {"id": "t", "type": "text", "text": "it's \"quoted\" \\ here"}
    doc = document([text], [{"do": "highlight", "target": "t", "part": "'s \"quoted\" \\"}])
    scene = doc.scenes[0]
    ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects})
    expr = part_selector(scene.objects[0], scene.steps[0].part, ctx)
    assert shape(expr) == shape('t["x"]')
    assert strings_in(expr) == ["'s \"quoted\" \\"]


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(max_size=30))
def test_property_any_text_keeps_the_code_shape(text):
    for kind, fields in STRING_FIELDS:
        before = {"brace": [WORDS], "graph": [AXES]}.get(kind, [])
        expr = code_for({"id": "it", "type": kind, **fields(text)}, *before)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(expr, "<it>", "eval")
        assert shape(expr) == shape(code_for({"id": "it", "type": kind, **fields(benign_like(text, fields))}, *before))


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(st.characters(blacklist_categories=("Cs", "Co", "Cn")), max_size=25))
def test_property_any_text_is_drawn_exactly(text):
    mob, _ = build_one({"id": "t", "type": "text", "text": text})
    assert mob.text == displayable(text)
    assert_drawable(mob)


# Parts of texts and formulas

def glyph_indices(mob, selection) -> list[int]:
    members = {id(m) for m in selection.get_family() if m.has_points()}
    return [i for i, glyph in enumerate(mob.submobjects) if id(glyph) in members]


def expected_text_glyphs(text: str, part: str) -> list[int]:
    """Glyph indices of every occurrence of part, counting one glyph per non-space character."""
    out = []
    for match in re.finditer(re.escape(part), text):
        start = len(re.sub(r"\s", "", text[:match.start()]))
        out.extend(range(start, start + len(re.sub(r"\s", "", part))))
    return out


def selected(obj: dict, part: str, *before: dict):
    built = build([*before, obj], [{"do": "highlight", "target": obj["id"], "part": part}])
    spec = built.ctx.spec(obj["id"])
    expr = part_selector(spec, part, built.ctx)
    return built[obj["id"]], built.eval(expr), expr


@pytest.mark.parametrize("text, part", [
    ("hello world", "world"),
    ("hello world", "lo wo"),
    ("hello world", "o"),
    ("hello, world!", "world!"),
    ("line one\nline two", "two"),
    ("line one\nline two", "one\nline"),
    ("a+b=c", "b=c"),
    ("café ünïcode", "ünï"),
    ("it's \"quoted\"", "\"quoted\""),
    ("x — y", "y"),
    ("fi fl ffi", "fl"),
])
def test_text_parts_are_the_right_glyphs(text, part):
    mob, selection, _ = selected({"id": "t", "type": "text", "text": text}, part)
    assert glyph_indices(mob, selection) == expected_text_glyphs(text, part)
    assert len(selection) == text.count(part)


def glyph_signature(glyph) -> tuple:
    """What tells one glyph from another in the same formula: its outline's size and number of points."""
    return len(glyph.get_points()), round(glyph.get_width(), 3), round(glyph.get_height(), 3)


def glyph_signatures(mob) -> Counter:
    return Counter(glyph_signature(glyph) for glyph in mob.submobjects)


def phantom_of(tex: str, part: str) -> str:
    """tex with every occurrence of part (not counting letters inside a command's name) made a \\phantom."""
    return re.sub(r"(?<![\\A-Za-z])" + re.escape(part), lambda m: R"\phantom{" + part + "}", tex)


TEX_PARTS = [
    (R"a^2 + b^2 = c^2", "c^2"),
    (R"\frac{a}{b} + c", "c"),
    (R"\frac{a}{b} + c", R"\frac{a}{b}"),
    (R"\sqrt{x} + x^2", "x^2"),
    (R"e^{i\pi} + 1 = 0", R"i\pi"),
    (R"\sum_{n=1}^\infty \frac{1}{n^2}", R"\frac{1}{n^2}"),
    (R"2 \vec{v} + \vec{w}", R"\vec{w}"),
]


@pytest.mark.render
@pytest.mark.parametrize("tex, part", TEX_PARTS)
def test_formula_parts_are_the_right_glyphs(tex, part):
    mob, selection, expr = selected({"id": "eq", "type": "tex", "tex": tex}, part)
    assert "isolate=" in build([{"id": "eq", "type": "tex", "tex": tex}],
                               [{"do": "highlight", "target": "eq", "part": part}]).code["eq"]
    indices = glyph_indices(mob, selection)
    assert len(indices) == len(Tex(part).submobjects)
    # Checked independently of manim's own selecting: the glyphs picked are exactly those
    # which go missing when the part is typeset as a \phantom, which keeps its space but
    # draws nothing
    picked = Counter(glyph_signature(mob.submobjects[i]) for i in indices)
    assert picked == glyph_signatures(Tex(tex)) - glyph_signatures(Tex(phantom_of(tex, part)))


@pytest.mark.render
def test_formula_part_in_every_place_it_occurs():
    mob, selection, _ = selected({"id": "eq", "type": "tex", "tex": R"x + y = x"}, "x")
    assert len(selection) == 2
    assert glyph_indices(mob, selection) == [0, 4]


@pytest.mark.parametrize("obj, part", [
    ({"id": "h", "type": "title", "text": "A title here"}, "title"),
    ({"id": "h", "type": "title", "text": "A title here", "underline": False}, "title"),
    ({"id": "q", "type": "quote", "text": "brevity is the soul", "author": "someone"}, "soul"),
    ({"id": "q", "type": "quote", "text": "brevity is the soul"}, "brevity"),
    ({"id": "t", "type": "text", "text": "over a grid", "backdrop": True}, "grid"),
    ({"id": "h", "type": "title", "text": "with backdrop", "backdrop": True}, "backdrop"),
    ({"id": "q", "type": "quote", "text": "with backdrop", "backdrop": True}, "backdrop"),
])
def test_parts_of_titles_quotes_and_backdropped_text(obj, part):
    mob, selection, expr = selected(obj, part)
    text = [m for m in mob.get_family() if isinstance(m, Text)][0]
    assert glyph_indices(text, selection) == expected_text_glyphs(text.text, part)


@pytest.mark.render
def test_formula_part_through_a_backdrop():
    mob, selection, expr = selected({"id": "eq", "type": "tex", "tex": R"\frac{a}{b} + c", "backdrop": True}, "c")
    assert expr == 'eq[1]["c"]'
    assert glyph_indices(mob[1], selection) == [4]


@pytest.mark.parametrize("kind, fields", [("circle", {}), ("bullets", {"items": ["a"]}), ("matrix", {"entries": [[1]]})])
def test_parts_of_other_kinds_are_refused(kind, fields):
    doc = document([{"id": "it", "type": kind, **fields}])
    scene = doc.scenes[0]
    ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects})
    with pytest.raises(ValueError, match="Only parts of text, formulas, titles and quotes"):
        part_selector(scene.objects[0], "a", ctx)


PART_TEXT = st.text(st.sampled_from("abcxyz019 ,.!?+-=\n"), min_size=1, max_size=30)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(PART_TEXT, st.data())
def test_property_text_parts_are_the_right_glyphs(text, data):
    start = data.draw(st.integers(0, len(text) - 1))
    end = data.draw(st.integers(start + 1, len(text)))
    part = text[start:end]
    if not part.strip():
        return
    mob, selection, _ = selected({"id": "t", "type": "text", "text": text}, part)
    assert glyph_indices(mob, selection) == expected_text_glyphs(text, part)


# Build order

def test_build_order_puts_what_is_referred_to_first():
    doc = document([
        {"id": "grp", "type": "group", "members": ["t2", "v"]},
        {"id": "bx", "type": "box", "target": "t2"},
        {"id": "t2", "type": "text", "text": "b", "place": {"next_to": "t1"}},
        {"id": "loose1", "type": "circle"},
        {"id": "v", "type": "vector", "tip": [1, 1], "on": "plane"},
        {"id": "t1", "type": "text", "text": "a", "place": {"at": [1, 1], "on": "ax"}},
        {"id": "plane", "type": "number_plane"},
        {"id": "loose2", "type": "square"},
        {"id": "ax", "type": "axes"},
        {"id": "br", "type": "brace", "target": "grp"},
    ])
    order = [o.id for o in build_order(doc.scenes[0])]
    assert sorted(order) == sorted(o.id for o in doc.scenes[0].objects)
    for first, then in [("t1", "t2"), ("t2", "bx"), ("t2", "grp"), ("v", "grp"), ("plane", "v"), ("ax", "t1"), ("grp", "br")]:
        assert order.index(first) < order.index(then), (first, then, order)
    assert order.index("loose1") < order.index("loose2")


def test_build_order_keeps_file_order_when_nothing_refers():
    doc = document([{"id": f"o{i}", "type": "circle"} for i in range(10)])
    assert [o.id for o in build_order(doc.scenes[0])] == [f"o{i}" for i in range(10)]


def test_build_order_survives_a_cycle():
    scene = SceneSpec.model_validate({"id": "s", "objects": [
        {"id": "a", "type": "text", "text": "a", "place": {"next_to": "b"}},
        {"id": "b", "type": "text", "text": "b", "place": {"next_to": "a"}},
        {"id": "c", "type": "circle"},
    ]})
    assert [o.id for o in build_order(scene)] == ["c", "a", "b"]


@settings(max_examples=100, deadline=None)
@given(st.integers(2, 12).flatmap(lambda n: st.tuples(
    st.just(n),
    st.lists(st.tuples(st.integers(0, n - 1), st.integers(0, n - 1)), max_size=2 * n),
    st.permutations(list(range(n))),
)))
def test_property_build_order_respects_every_reference(args):
    n, edges, listing = args
    # Only edges from a later node to an earlier one, so there is never a cycle
    refs = {i: sorted({j for a, j in edges if a == i and j < i}) for i in range(n)}
    objects = []
    for i in listing:
        if refs[i]:
            objects.append({"id": f"g{i}", "type": "group", "members": [f"g{j}" for j in refs[i]]})
        else:
            objects.append({"id": f"g{i}", "type": "circle"})
    order = [o.id for o in build_order(document(objects).scenes[0])]
    assert sorted(order) == sorted(o["id"] for o in objects)
    for i, deps in refs.items():
        for j in deps:
            assert order.index(f"g{j}") < order.index(f"g{i}")


# Default styles

def test_default_styles():
    for kind, model in OBJECT_MODELS.items():
        assert default_show_style(model.model_construct(type=kind)) in ("write", "draw", "fade", "grow")
        assert default_hide_style(model.model_construct(type=kind)) in ("fade", "uncreate", "shrink")
    doc = document([
        {"id": "t", "type": "text", "text": "a"}, {"id": "e", "type": "tex", "tex": "a"},
        {"id": "v", "type": "vector", "tip": [1, 1]}, {"id": "a", "type": "line", "start": [0, 0], "end": [1, 1], "arrow": True},
        {"id": "l", "type": "line", "start": [0, 0], "end": [1, 1]}, {"id": "c", "type": "circle"},
        {"id": "i", "type": "image", "path": "p.png"}, {"id": "g", "type": "group", "members": ["t"]},
        {"id": "d", "type": "dot", "point": [0, 0]}, {"id": "p", "type": "number_plane"},
    ])
    styles = {o.id: (default_show_style(o), default_hide_style(o)) for o in doc.scenes[0].objects}
    assert styles == {
        "t": ("write", "fade"), "e": ("write", "fade"), "v": ("grow", "fade"), "a": ("grow", "uncreate"),
        "l": ("draw", "uncreate"), "c": ("draw", "uncreate"), "i": ("fade", "fade"), "g": ("fade", "fade"),
        "d": ("grow", "shrink"), "p": ("draw", "fade"),
    }


# What can't be built

def test_a_graph_whose_function_cant_be_read_is_refused_when_building():
    scene = SceneSpec.model_validate({"id": "s", "objects": [
        {"id": "ax", "type": "axes"}, {"id": "g", "type": "graph", "on": "ax", "function": "import os"},
    ]})
    ctx = CodegenContext(doc=Document(scenes=[scene]), scene=scene, objects={o.id: o for o in scene.objects})
    with pytest.raises(ValueError, match="The function of 'g' can't be drawn"):
        object_expression(scene.objects[1], ctx)


def test_a_reference_to_nothing_is_refused_when_building():
    scene = SceneSpec.model_validate({"id": "s", "objects": [{"id": "v", "type": "vector", "tip": [1, 1], "on": "nope"}]})
    ctx = CodegenContext(doc=Document(scenes=[scene]), scene=scene, objects={o.id: o for o in scene.objects})
    with pytest.raises(ValueError, match="There's no object called 'nope'"):
        object_expression(scene.objects[0], ctx)


@pytest.mark.parametrize("obj, message", [
    ({"id": "p", "type": "number_line", "x_range": [0, 5, 0]}, "The step of a range has to be more than 0"),
    ({"id": "p", "type": "axes", "y_range": [3, -3]}, "A range goes from the smaller number to the larger"),
    ({"id": "p", "type": "number_plane", "x_range": [-1000, 1000, 0.01]}, "more than 500 steps"),
    ({"id": "d", "type": "dot", "point": [float("nan"), 1]}, "finite number"),
    ({"id": "c", "type": "circle", "radius": float("inf")}, "finite number"),
    ({"id": "g", "type": "graph", "on": "ax", "function": "2x"}, "To multiply, write *"),
])
def test_the_format_refuses_what_cant_be_built(obj, message):
    before = [{"id": "ax", "type": "axes"}] if obj["type"] == "graph" else []
    doc, problems = validate_data({"scenes": [{"id": "s", "objects": [*before, obj]}]})
    assert any(message in p.message for p in problems), [str(p) for p in problems]
    if obj["type"] == "graph":
        assert any(p.path == "scenes[0].objects[1].function" for p in problems)


def test_a_graph_function_set_by_a_change_step_is_checked():
    _, problems = validate_data({"scenes": [{"id": "s", "objects": [
        {"id": "ax", "type": "axes"}, {"id": "g", "type": "graph", "on": "ax", "function": "x"},
    ], "steps": [{"do": "change", "target": "g", "set": {"function": "sin x"}}]}]})
    assert [p.path for p in problems if "brackets" in p.message] == ["scenes[0].steps[0].set.function"]


# Random objects of every kind

numbers = st.floats(-4, 4, allow_nan=False).map(lambda v: round(v, 3))
point2 = st.lists(numbers, min_size=2, max_size=2)
point = st.lists(numbers, min_size=2, max_size=3)
colors = st.sampled_from(["RED", "BLUE", "#58C4DD", "YELLOW_E", "#fff", "GREY_B"])
sides = st.sampled_from(["up", "down", "left", "right"])
edges = st.sampled_from(["center", "top", "bottom", "left", "right", "top_left", "top_right", "bottom_left", "bottom_right"])
words = st.text(st.sampled_from("abc xyz 12!?\n'\"\\"), max_size=20)
formulas_tex = st.sampled_from(["x", "x^2", R"\frac{1}{2}", R"\vec{v}", R"\alpha + \beta", "a_n", R"\sqrt{2}", "3"])
ranges = st.tuples(st.floats(-8, -0.5), st.floats(0.5, 8), st.sampled_from([0.5, 1, 2])).map(
    lambda t: [round(t[0], 2), round(t[1], 2), t[2]])


def maybe(**fields):
    """A dict holding any of the fields given, each drawn from its strategy."""
    return st.fixed_dictionaries({}, optional=fields)


placements = st.one_of(
    edges,
    point2,
    st.fixed_dictionaries({"edge": edges}, optional={"buff": st.floats(0, 1), "shift": point2}),
    st.fixed_dictionaries({"next_to": st.just("anchor")}, optional={"side": sides, "buff": st.floats(0, 1)}),
    st.fixed_dictionaries({"at": point2, "on": st.just("plane")}),
)
free = maybe(color=colors, opacity=st.floats(0, 1), z=st.integers(-3, 3), scale=st.floats(0.2, 3),
             rotate=st.floats(-360, 360), place=placements, backdrop=st.booleans(), fixed=st.booleans())
plotted = maybe(color=colors, opacity=st.floats(0, 1), z=st.integers(-3, 3), fixed=st.booleans())
systems = st.sampled_from(["plane", "ax", "ax3", "nl", None])

ANCHORS = [
    {"id": "anchor", "type": "square", "side": 0.5, "place": [3, 2]},
    {"id": "plane", "type": "number_plane", "x_range": [-5, 5, 1], "y_range": [-4, 4, 1]},
    {"id": "ax", "type": "axes", "x_range": [-5, 5, 1], "y_range": [-4, 4, 1], "width": 6, "height": 4},
    {"id": "ax3", "type": "axes_3d", "x_range": [-5, 5, 1], "y_range": [-5, 5, 1], "z_range": [-4, 4, 1]},
    {"id": "nl", "type": "number_line", "x_range": [-5, 5, 1]},
    {"id": "pic", "type": "image", "path": "pic.png"},
]

KIND_FIELDS = {
    "text": maybe(font_size=st.floats(10, 80), bold=st.booleans(), italic=st.booleans(),
                  align=st.sampled_from(["left", "center", "right"]), colors=st.dictionaries(words, colors, max_size=2),
                  font=st.sampled_from(["Serif", "Sans", "Monospace"])).map(lambda d: {"text": "some text", **d}),
    "tex": st.tuples(formulas_tex, maybe(font_size=st.floats(10, 80), colors=st.dictionaries(formulas_tex, colors, max_size=1)))
    .map(lambda t: {"tex": t[0], **t[1]}),
    "title": st.tuples(words, maybe(font_size=st.floats(10, 80), underline=st.booleans())).map(lambda t: {"text": t[0], **t[1]}),
    "quote": st.tuples(words, maybe(author=words, font_size=st.floats(10, 60))).map(lambda t: {"text": t[0], **t[1]}),
    "bullets": st.tuples(st.lists(words, min_size=1, max_size=4), maybe(font_size=st.floats(10, 60), buff=st.floats(0, 1)))
    .map(lambda t: {"items": t[0], **t[1]}),
    "matrix": st.integers(1, 3).flatmap(lambda cols: st.tuples(
        st.lists(st.lists(st.one_of(formulas_tex, numbers), min_size=cols, max_size=cols), min_size=1, max_size=3),
        maybe(bracket=st.sampled_from(["square", "round"]), font_size=st.floats(20, 60),
              row_colors=st.lists(colors, max_size=3), column_colors=st.lists(colors, max_size=3)),
    )).map(lambda t: {"entries": t[0], **t[1]}),
    "number_plane": maybe(x_range=ranges, y_range=ranges, width=st.floats(1, 14), height=st.floats(1, 8),
                          faded=st.booleans(), numbers=st.booleans()),
    "axes": maybe(x_range=ranges, y_range=ranges, width=st.floats(1, 14), height=st.floats(1, 8), numbers=st.booleans(),
                  tips=st.booleans(), x_label=formulas_tex, y_label=formulas_tex),
    "axes_3d": maybe(x_range=ranges, y_range=ranges, z_range=ranges, numbers=st.booleans()),
    "number_line": maybe(x_range=ranges, length=st.floats(1, 14), numbers=st.booleans(), tip=st.booleans()),
    "graph": st.tuples(st.sampled_from(["ax", "plane"]), st.sampled_from(["sin(x)", "1/x", "sqrt(x)", "x^2 - 2", "floor(x)", "log(x)"]),
                       maybe(x_range=st.tuples(numbers, numbers).map(sorted).map(list), label=formulas_tex))
    .map(lambda t: {"on": t[0], "function": t[1], **t[2]}),
    "dot": st.tuples(point, systems, maybe(radius=st.floats(0.01, 1), label=formulas_tex, label_side=sides))
    .map(lambda t: {"point": t[0], **({"on": t[1]} if t[1] else {}), **t[2]}),
    "vector": st.tuples(point, point, systems, maybe(thickness=st.floats(0.5, 10), label=formulas_tex, label_side=sides,
                                                     show_coordinates=st.booleans()))
    .map(lambda t: {"tip": t[0], "tail": t[1], **({"on": t[2]} if t[2] else {}), **t[3]}),
    "line": st.tuples(point, point, systems, maybe(dashed=st.booleans(), arrow=st.booleans(), thickness=st.floats(0.5, 10)))
    .map(lambda t: {"start": t[0], "end": t[1], **({"on": t[2]} if t[2] else {}), **t[3]}),
    "polygon": st.tuples(st.lists(point, min_size=3, max_size=6), systems,
                         maybe(fill=colors, fill_opacity=st.floats(0, 1)))
    .map(lambda t: {"points": t[0], **({"on": t[1]} if t[1] else {}), **t[2]}),
    "circle": maybe(radius=st.floats(0.05, 4), fill=colors, fill_opacity=st.floats(0, 1), thickness=st.floats(0, 10)),
    "rectangle": maybe(width=st.floats(0.05, 8), height=st.floats(0.05, 6), corner_radius=st.floats(0, 3), fill=colors,
                       fill_opacity=st.floats(0, 1), thickness=st.floats(0, 10)),
    "square": maybe(side=st.floats(0.05, 6), fill=colors, fill_opacity=st.floats(0, 1), thickness=st.floats(0, 10)),
    "brace": st.tuples(st.sampled_from(["anchor", "plane", "pic"]), maybe(side=sides, label=formulas_tex, buff=st.floats(0, 1)))
    .map(lambda t: {"target": t[0], **t[1]}),
    "box": st.tuples(st.sampled_from(["anchor", "nl", "pic"]),
                     maybe(buff=st.floats(0, 1), corner_radius=st.floats(0, 0.5), fill_opacity=st.floats(0, 1)))
    .map(lambda t: {"target": t[0], **t[1]}),
    "image": maybe(height=st.floats(0.1, 6)).map(lambda d: {"path": "pic.png", **d}),
    "svg": maybe(height=st.floats(0.1, 6)).map(lambda d: {"path": "star.svg", **d}),
    "group": st.tuples(st.lists(st.sampled_from(["anchor", "plane", "pic", "nl"]), min_size=1, max_size=4),
                       maybe(arrange=st.sampled_from(["none", "row", "column"]), buff=st.floats(0, 1)))
    .map(lambda t: {"members": t[0], **t[1]}),
}

PLOTTED_KINDS = {"graph", "dot", "vector", "line", "polygon"}
ANNOTATION_KINDS = {"brace", "box"}


def test_every_kind_has_a_strategy():
    assert set(KIND_FIELDS) == set(OBJECT_MODELS)


def without_latex(fields: dict) -> dict:
    """fields less whatever would need LaTeX to build, for the runs CI makes without it."""
    fields = {k: v for k, v in fields.items() if k not in LATEX_FIELDS}
    if fields.get("bracket") == "round":
        fields["bracket"] = "square"
    return fields


RANDOM_CASES = [
    *(pytest.param(kind, False, id=kind) for kind in sorted(OBJECT_MODELS) if kind not in LATEX_KINDS),
    *(pytest.param(kind, True, id=f"{kind}-latex", marks=pytest.mark.render)
      for kind in sorted(LATEX_KINDS | {"axes", "graph", "dot", "vector"})),
]


@pytest.mark.parametrize("kind, latex", RANDOM_CASES)
def test_property_random_objects_build(kind, latex, media):
    common = plotted if kind in PLOTTED_KINDS | ANNOTATION_KINDS else free

    @settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @given(KIND_FIELDS[kind], common)
    def check(fields, extra):
        obj = {"id": "it", "type": kind, **(fields if latex else without_latex(fields)), **extra}
        mob, built = build_one(obj, *ANCHORS, base_dir=media)
        assert_drawable(mob)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(built.code["it"], "<it>", "eval")

    check()


# The ten minute example

@pytest.mark.render
def test_every_object_in_the_example_video_builds():
    doc, problems = load_file(EXAMPLE)
    assert doc is not None and not has_errors(problems), [str(p) for p in problems]
    count = 0
    for scene in doc.scenes:
        ctx = CodegenContext(doc=doc, scene=scene, objects={o.id: o for o in scene.objects}, base_dir=EXAMPLE.parent)
        namespace = dict(NAMESPACE)
        for obj in build_order(scene):
            mob = eval(compile(object_expression(obj, ctx), obj.id, "eval"), namespace)
            namespace[ctx.var(obj.id)] = mob
            assert_drawable(mob)
            count += 1
        for step in scene.steps:
            part = getattr(step, "part", None)
            if part:
                selection = eval(part_selector(ctx.spec(step.target), part, ctx), namespace)
                assert len(selection) > 0, (scene.id, step.target, part)
    assert count > 100
