"""
What a wheel of manimgl has to hold, and what it mustn't.

    python tests/packaging/wheel_contents.py dist/manimgl-*.whl [--require-ui]

test_wheel.py checks a wheel it builds from the working tree with this. The install workflow
checks the wheel it builds for release, from the sdist, with the editor's UI built into it,
which is what --require-ui is for.

Not a test module itself (pytest collects test_*.py only), so it runs without manimlib or
anything else of manim's installed.
"""
from __future__ import annotations

import argparse
import configparser
import email.parser
import fnmatch
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGES = ("manimlib", "manim_verbose")

# What the packages read from their own directories at runtime, rather than import. A wheel
# without one of these installs, imports, and then fails when first asked to draw or load.
RUNTIME_DATA = {
    "manimlib/default_config.yml": "config.py starts every setting from it",
    "manimlib/tex_templates.yml": "utils/tex_file_writing.py reads the LaTeX preambles from it",
    "manimlib/shaders/*.wgsl": "the renderer compiles them, see renderer/shader_source.py",
    "manimlib/shaders/inserts/*.wgsl": "shaders pull them in with #INSERT lines",
    "manim_verbose/scenefile/schema.json": "scenefile/schema.py, and the editor's forms, are built from it",
}
# Every file in the packages with one of these suffixes is code or data, and has to be shipped
SHIPPED_SUFFIXES = {".py", ".yml", ".yaml", ".json", ".wgsl"}
# The editor's UI, built from editor-ui/ into the package, and not kept in git
UI_DIR = "manim_verbose/editor/static"
UI_INDEX = f"{UI_DIR}/index.html"

# Console scripts whose module is still being written: its absence is noted rather than failed,
# and once it is in the wheel, the entry has to come out of here
PENDING_ENTRY_POINTS = {
    "manimgl-editor": "manim_verbose/editor/cli.py is still being written",
}

FORBIDDEN_PARTS = {"tests", "__pycache__", "node_modules", "latex_cache", ".DS_Store", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def source_files(repo: Path = REPO) -> list[str]:
    """Code and data files in the packages, as the wheel would name them"""
    found = []
    for package in PACKAGES:
        for path in (repo / package).rglob("*"):
            rel = path.relative_to(repo).as_posix()
            if (
                path.is_file() and path.suffix in SHIPPED_SUFFIXES
                and "__pycache__" not in path.parts and not rel.startswith(UI_DIR + "/")
            ):
                found.append(rel)
    return sorted(found)


def _setup_cfg(repo: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    config.read(repo / "setup.cfg", encoding="utf-8")
    return config


def _canonical(name: str) -> str:
    import re
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(line: str) -> str:
    import re
    return _canonical(re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line).group(1))


def check(wheel: Path, repo: Path = REPO, require_ui: bool = False) -> tuple[list[str], list[str]]:
    """Problems with the wheel, and notes about it which are not problems"""
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        dist_info = sorted({n.split("/")[0] for n in names if n.split("/")[0].endswith(".dist-info")})
        metadata = entry_points = ""
        if len(dist_info) == 1:
            metadata = archive.read(f"{dist_info[0]}/METADATA").decode("utf-8")
            if f"{dist_info[0]}/entry_points.txt" in names:
                entry_points = archive.read(f"{dist_info[0]}/entry_points.txt").decode("utf-8")
    problems: list[str] = []
    notes: list[str] = []

    if len(dist_info) != 1:
        return [f"{wheel.name} holds {len(dist_info)} .dist-info directories, where a wheel has one"], notes

    for pattern, why in RUNTIME_DATA.items():
        in_source = fnmatch.filter(source_files(repo), pattern)
        if not in_source:
            problems.append(f"nothing in the source matches {pattern}; RUNTIME_DATA in {Path(__file__).name} is out of date")
        for rel in in_source:
            if rel not in names:
                problems.append(f"{rel} is missing, and {why}. Check MANIFEST.in and [options.package_data] in setup.cfg.")

    missing = [rel for rel in source_files(repo) if rel not in names]
    if missing:
        problems.append(
            f"{len(missing)} file(s) of the packages are not in the wheel: {', '.join(missing[:10])}"
            + (" ..." if len(missing) > 10 else "")
            + ". A directory of .py files needs an __init__.py for `packages = find:` to see it; "
            "data files need to be covered by MANIFEST.in."
        )

    tops = sorted({n.split("/")[0] for n in names} - set(PACKAGES) - set(dist_info))
    if tops:
        problems.append(
            f"the wheel would put {', '.join(tops)} into site-packages beside manimlib and manim_verbose. "
            f"Exclude them under [options.packages.find] in setup.cfg."
        )
    stray = sorted(
        n for n in names
        if FORBIDDEN_PARTS & set(n.split("/")) or Path(n).suffix in FORBIDDEN_SUFFIXES
    )
    if stray:
        problems.append(f"the wheel holds files which have no business in it: {', '.join(stray[:10])}")

    config = _setup_cfg(repo)
    scripts = {}
    for line in config.get("options.entry_points", "console_scripts", fallback="").splitlines():
        if "=" in line:
            name, target = (part.strip() for part in line.split("=", 1))
            scripts[name] = target
    for name, target in scripts.items():
        if f"{name} = {target}" not in entry_points and f"{name}={target}" not in entry_points:
            problems.append(f"the console script {name} = {target} from setup.cfg is not in the wheel's entry_points.txt")
        module = target.split(":")[0].replace(".", "/")
        present = f"{module}.py" in names or f"{module}/__init__.py" in names
        if name in PENDING_ENTRY_POINTS:
            if present:
                problems.append(
                    f"{name}'s module is in the wheel now: take it out of PENDING_ENTRY_POINTS in {Path(__file__).name}"
                )
            else:
                notes.append(f"{name} = {target} has no module yet ({PENDING_ENTRY_POINTS[name]})")
        elif not present:
            problems.append(
                f"the console script {name} runs {target}, and {module}.py is not in the wheel, so "
                f"`{name}` would fail on every run"
            )

    parsed = email.parser.Parser().parsestr(metadata)
    requires = parsed.get_all("Requires-Dist") or []
    unconditional = {_requirement_name(r) for r in requires if "extra ==" not in r}
    declared = [
        line.strip() for line in config.get("options", "install_requires", fallback="").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for line in declared:
        if _requirement_name(line) not in unconditional:
            problems.append(f"setup.cfg installs {line!r}, and the wheel's METADATA doesn't require it")
    extras = set(parsed.get_all("Provides-Extra") or [])
    if config.has_section("options.extras_require"):
        for extra, _ in config.items("options.extras_require"):
            if extra not in extras:
                problems.append(f"the wheel doesn't provide the extra {extra!r} which setup.cfg declares")
    python_requires = config.get("options", "python_requires", fallback="")
    if python_requires and parsed.get("Requires-Python", "").replace(" ", "") != python_requires.replace(" ", ""):
        problems.append(f"the wheel says Requires-Python {parsed.get('Requires-Python')!r}, setup.cfg {python_requires!r}")

    ui_files = [n for n in names if n.startswith(UI_DIR + "/")]
    if require_ui and UI_INDEX not in names:
        problems.append(f"{UI_INDEX} is missing: build editor-ui (npm run build) before building the wheel")
    elif (repo / UI_INDEX).exists() and UI_INDEX not in names:
        problems.append(f"{UI_INDEX} is built in the source but not in the wheel; check [options.package_data] in setup.cfg")
    elif not ui_files:
        notes.append("no editor UI in this wheel (editor-ui/ not built into manim_verbose/editor/static)")
    else:
        notes.append(f"the editor UI is in the wheel: {len(ui_files)} files")
    return problems, notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Check what a built wheel of manimgl holds")
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--require-ui", action="store_true", help="fail unless the editor's built UI is in it")
    args = parser.parse_args()
    problems, notes = check(args.wheel, REPO, args.require_ui)
    for note in notes:
        print(f"note: {note}")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if not problems:
        print(f"{args.wheel.name}: holds everything it should, and nothing it shouldn't")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
