"""
That a wheel built from this tree holds what manim needs at runtime (shaders, tex templates,
the scene file schema) and nothing it shouldn't (tests, caches), see wheel_contents.py.

The wheel is built with pip, in isolation, from a copy of the tree, so that neither a build/
directory left from an earlier build nor anything installed here can make it look better than
it is. That takes a few seconds and needs the package index, hence slow.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

_spec = importlib.util.spec_from_file_location("wheel_contents", Path(__file__).with_name("wheel_contents.py"))
wheel_contents = importlib.util.module_from_spec(_spec)
sys.modules["wheel_contents"] = wheel_contents
_spec.loader.exec_module(wheel_contents)

REPO = wheel_contents.REPO
# Nothing of these goes into a wheel, or is needed to build one
NOT_COPIED = shutil.ignore_patterns(
    ".git", "node_modules", "build", "dist", "*.egg-info", "__pycache__", ".pytest_cache",
    ".hypothesis", "videos", "latex_cache", "test-results", "playwright-report",
)


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    source = tmp_path_factory.mktemp("source")
    shutil.copytree(REPO, source, dirs_exist_ok=True, ignore=NOT_COPIED)
    out = tmp_path_factory.mktemp("wheel")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(out), str(source)],
        capture_output=True, text=True, env=dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1"),
    )
    assert result.returncode == 0, f"building the wheel failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
    wheels = list(out.glob("manimgl-*.whl"))
    assert len(wheels) == 1, [p.name for p in out.iterdir()]
    return wheels[0]


def test_wheel_holds_what_manim_needs(wheel):
    problems, notes = wheel_contents.check(wheel, REPO)
    assert not problems, "\n".join(problems)


def test_wheel_is_pure_python(wheel):
    """One wheel does for every platform and Python, which publish.yml relies on"""
    assert wheel.name.endswith("-py3-none-any.whl"), wheel.name


def test_the_check_catches_a_broken_wheel(wheel, tmp_path):
    """wheel_contents.check fails a wheel missing runtime data, or carrying tests along"""
    broken = tmp_path / wheel.name
    with zipfile.ZipFile(wheel) as original, zipfile.ZipFile(broken, "w") as copy:
        for item in original.infolist():
            if item.filename.startswith("manimlib/shaders/") or item.filename.endswith("schema.json"):
                continue
            copy.writestr(item, original.read(item))
        copy.writestr("tests/__init__.py", "")
        copy.writestr("manimlib/__pycache__/x.cpython-311.pyc", b"")
    problems, _ = wheel_contents.check(broken, REPO)
    text = "\n".join(problems)
    assert "manimlib/shaders/fill.wgsl is missing" in text
    assert "manim_verbose/scenefile/schema.json is missing" in text
    assert "would put tests into site-packages" in text
    assert "no business in it: manimlib/__pycache__/x.cpython-311.pyc" in text
