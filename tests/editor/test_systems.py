"""
Where coordinate systems are in a still, so the editor can turn a drag into coordinates: the
still response carries `coordinate_systems`, from the renderer (measured on the scene it drew)
or from the cache, and never fails a still for want of them.
"""
from __future__ import annotations

import copy

import pytest

from manim_verbose.editor.systems import systems_data

PLANE_DOC = {
    "version": 1,
    "title": "Plane",
    "scenes": [{
        "id": "s",
        "objects": [
            {"id": "plane", "type": "number_plane"},
            {"id": "v", "type": "vector", "tip": [2, 1], "on": "plane"},
            {"id": "t", "type": "text", "text": "Hi"},
        ],
        "steps": [{"id": "s_1", "do": "show", "target": ["plane", "v", "t"]}],
    }],
}


def test_a_still_says_where_its_coordinate_systems_are(client):
    body = client.post("/api/still", json={"document": PLANE_DOC, "scene_id": "s", "step_index": 0}).json()
    assert body["coordinate_systems"] == [
        {"id": "plane", "type": "number_plane", "origin": [480.0, 270.0], "x_unit": [67.5, 0.0], "y_unit": [0.0, -67.5], "z_unit": None},
    ]


def test_a_still_with_no_system_on_screen_has_none(client):
    body = client.post("/api/still", json={"document": PLANE_DOC, "scene_id": "s", "step_index": -1}).json()
    assert body["coordinate_systems"] == []


def test_the_cache_keeps_them(client, backend):
    first = client.post("/api/still", json={"document": PLANE_DOC, "scene_id": "s", "step_index": 0}).json()
    again = client.post("/api/still", json={"document": copy.deepcopy(PLANE_DOC), "scene_id": "s", "step_index": 0}).json()
    assert len(backend.calls("still")) == 1, "the second came from the cache"
    assert again["coordinate_systems"] == first["coordinate_systems"]


def test_the_cache_outlives_the_server(make_client, scene_file, backend):
    one = make_client(scene_file)
    first = one.post("/api/still", json={"document": PLANE_DOC, "scene_id": "s", "step_index": 0}).json()
    two = make_client(scene_file)
    again = two.post("/api/still", json={"document": PLANE_DOC, "scene_id": "s", "step_index": 0}).json()
    assert len(backend.calls("still")) == 1
    assert again["coordinate_systems"] == first["coordinate_systems"] != []


def test_systems_data_keeps_what_it_can_read():
    good = {"id": "p", "type": "axes", "origin": [1, 2], "x_unit": [3, 0], "y_unit": [0, -3], "z_unit": None}
    three_d = {"id": "a", "type": "axes_3d", "origin": [1, 2, 0], "x_unit": [3, 1], "y_unit": [0, -3], "z_unit": [1, 1]}
    bad = [{"id": "x"}, {"id": "y", "type": "axes", "origin": "here", "x_unit": [1, 0], "y_unit": [0, 1]}, None]
    assert systems_data({"coordinate_systems": [good, *bad, three_d]}) == [
        {"id": "p", "type": "axes", "origin": [1.0, 2.0], "x_unit": [3.0, 0.0], "y_unit": [0.0, -3.0], "z_unit": None},
        {"id": "a", "type": "axes_3d", "origin": [1.0, 2.0], "x_unit": [3.0, 1.0], "y_unit": [0.0, -3.0], "z_unit": [1.0, 1.0]},
    ]
    assert systems_data(object()) == []
    assert systems_data({}) == []


# With the real renderer

@pytest.mark.render
def test_measured_on_a_real_still(tmp_path):
    from manim_verbose.editor.systems import render_still_with_systems
    from manim_verbose.scenefile.validate import validate_data
    data = {"scenes": [{
        "id": "s",
        "objects": [
            {"id": "plane", "type": "number_plane"},
            {"id": "ax", "type": "axes", "x_range": [-2, 2, 1], "y_range": [-1, 1, 1], "width": 4, "height": 2,
             "place": {"at": [3, 2]}},
            {"id": "nl", "type": "number_line", "place": {"edge": "bottom"}},
            {"id": "t", "type": "text", "text": "not a system"},
        ],
        "steps": [{"do": "show", "target": ["plane", "ax", "nl", "t"]}],
    }]}
    doc, problems = validate_data(data)
    assert doc is not None, problems
    result = render_still_with_systems(doc, "s", 0, tmp_path / "still.png", 960, tmp_path)
    assert (tmp_path / "still.png").is_file()
    systems = {s["id"]: s for s in result.coordinate_systems}
    assert set(systems) == {"plane", "ax", "nl"}
    unit = 540 / 8  # manim's frame is 8 units high
    plane = systems["plane"]
    assert plane["type"] == "number_plane"
    assert plane["origin"] == pytest.approx([480, 270], abs=0.5)
    assert plane["x_unit"] == pytest.approx([unit, 0], abs=0.5)
    assert plane["y_unit"] == pytest.approx([0, -unit], abs=0.5)
    # The axes are 4 units wide for a range of 4, placed around (3, 2)
    ax = systems["ax"]
    box = next(o for o in result.objects if o.id == "ax").bbox
    assert box[0] < ax["origin"][0] < box[2] and box[1] < ax["origin"][1] < box[3]
    assert ax["x_unit"] == pytest.approx([unit, 0], abs=0.5)
    nl = systems["nl"]
    assert nl["type"] == "number_line" and nl["y_unit"] == pytest.approx([0, -unit], abs=0.5), "a number line's height is in frame units"
    assert nl["origin"][1] > 400, "at the bottom"
