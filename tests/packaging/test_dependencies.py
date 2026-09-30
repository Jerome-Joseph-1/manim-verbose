"""
That everything manimlib and manim_verbose import is something installing them installs.

An import nobody declared works on every machine it was written on, the developer having the
package already, and fails for everyone who installs from PyPI. av went into requirements.txt
but not setup.cfg that way, and `pip install manimgl` gave a manimlib which could not be
imported. So every import is read from the source (nothing is run), mapped to the distribution
which provides it, and looked for in setup.cfg:

- code under manim_verbose/editor may use what the `editor` extra adds, everything else only
  what install_requires does;
- imports made only for type checkers, under `if TYPE_CHECKING:`, don't count;
- imports inside a try whose except catches ImportError are optional, and have to be listed in
  OPTIONAL below with the reason, so that nothing is optional by accident;
- imports under `if sys.version_info ...` or `if sys.platform ...` are needed only there, and
  the requirement's environment marker has to cover at least that much.

requirements.txt, for `pip install -r`, has to say the same as install_requires.
"""
from __future__ import annotations

import ast
import collections
import configparser
import importlib.metadata
import itertools
import sys
import textwrap
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[2]
SOURCE_PACKAGES = ("manimlib", "manim_verbose")
# Code under these directories may also use what the named extra installs
EXTRA_DIRS = {"manim_verbose/editor": "editor"}

# Import names under which a distribution goes by another name. packages_distributions() knows
# this for whatever is installed; this table answers the same way whatever is installed.
DISTRIBUTION_OF = {
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "dateutil": "python-dateutil",
    "fontTools": "fonttools",
    "importlib_metadata": "importlib-metadata",
    "IPython": "ipython",
    "manimpango": "manimpango",
    "mapbox_earcut": "mapbox-earcut",
    "moderngl_window": "moderngl-window",
    "multipart": "python-multipart",
    "OpenGL": "pyopengl",
    "pathops": "skia-pathops",
    "PIL": "pillow",
    "pkg_resources": "setuptools",
    "pydantic_core": "pydantic-core",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "typing_extensions": "typing-extensions",
    "yaml": "pyyaml",
}

# Modules which were in the standard library, and are not on every Python supported: the
# first Python without them, and what to install in their place from then on
REMOVED_FROM_STDLIB = {
    "asynchat": ((3, 12), "pyasynchat"),
    "asyncore": ((3, 12), "pyasyncore"),
    "distutils": ((3, 12), "setuptools"),
    "imp": ((3, 12), "zombie-imp"),
    "smtpd": ((3, 12), "aiosmtpd"),
    "aifc": ((3, 13), "standard-aifc"),
    "audioop": ((3, 13), "audioop-lts"),
    "cgi": ((3, 13), "legacy-cgi"),
    "cgitb": ((3, 13), "legacy-cgi"),
    "chunk": ((3, 13), "standard-chunk"),
    "crypt": ((3, 13), "crypt-r"),
    "imghdr": ((3, 13), "standard-imghdr"),
    "lib2to3": ((3, 13), "fissix"),
    "mailcap": ((3, 13), "standard-mailcap"),
    "nntplib": ((3, 13), "standard-nntplib"),
    "pipes": ((3, 13), "standard-pipes"),
    "sndhdr": ((3, 13), "standard-sndhdr"),
    "sunau": ((3, 13), "standard-sunau"),
    "telnetlib": ((3, 13), "standard-telnetlib"),
    "uu": ((3, 13), "standard-uu"),
    "xdrlib": ((3, 13), "standard-xdrlib"),
}

# Imports which are only made if the package is there, and what happens without it
OPTIONAL = {
    "importlib_metadata": "manimlib/__init__.py falls back to it before Python 3.8, which is no longer supported",
}

# Distributions which may be imported without being declared themselves, because one which is
# declared (in the same place) always brings them, as part of what it is
PROVIDED_BY = {
    "starlette": "fastapi",  # fastapi is built on it, and pins the versions it works with
    "pydantic-core": "pydantic",
}

PLATFORMS = {"linux": ("Linux", "posix"), "darwin": ("Darwin", "posix"), "win32": ("Windows", "nt")}


@dataclass(frozen=True)
class Import:
    module: str        # top level name, as imported
    file: str          # relative to the repository
    line: int
    kind: str          # "required", "optional" or "typing"
    # (python version, sys.platform) pairs on which the import is made, None for everywhere
    where: frozenset[tuple[tuple[int, int], str]] | None = None

    @property
    def place(self) -> str:
        return f"{self.file}:{self.line}"


# Reading imports


def imports_in_source(source: str, file: str, pythons: list[tuple[int, int]]) -> list[Import]:
    """Every import of a top level module in some source, with how it is guarded"""
    tree = ast.parse(source, filename=file)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module] if node.level == 0 and node.module else []
        elif _is_dynamic_import(node):
            modules = [node.args[0].value]
        else:
            continue
        for module in modules:
            kind, where = _guards(node, parents, pythons)
            found.append(Import(module.split(".")[0], file, node.lineno, kind, where))
    return found


def _is_dynamic_import(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not node.args:
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return (
        name in ("import_module", "__import__")
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )


def _guards(node, parents, pythons):
    kind = "required"
    conditions = []  # (test, holds when true)
    child, parent = node, parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.If):
            in_body = child in parent.body
            if _is_type_checking(parent.test):
                if in_body:
                    return "typing", None
            elif _is_environment_test(parent.test) and (in_body or child in parent.orelse):
                conditions.append((parent.test, in_body))
        elif isinstance(parent, ast.Try) and _catches_import_error(parent):
            if child in parent.body or any(child is handler for handler in parent.handlers):
                kind = "optional"
        child, parent = parent, parents.get(parent)
    if not conditions:
        return kind, None
    where = frozenset(
        (python, platform)
        for python, platform in itertools.product(pythons, PLATFORMS)
        if all(_evaluate(test, python, platform) == holds for test, holds in conditions)
    )
    return kind, where


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _is_environment_test(test: ast.expr) -> bool:
    """A test of nothing but sys.version_info, sys.platform and constants"""
    for node in ast.walk(test):
        if isinstance(node, ast.Name) and node.id != "sys":
            return False
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr not in (
            "version_info", "platform"
        ):
            return False
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "startswith"):
                return False
    return any(isinstance(node, ast.Name) for node in ast.walk(test))


VersionInfo = collections.namedtuple("VersionInfo", "major minor micro releaselevel serial")


def _evaluate(test: ast.expr, python: tuple[int, int], platform: str) -> bool:
    fake_sys = type("sys", (), {"version_info": VersionInfo(*python, 0, "final", 0), "platform": platform})
    code = compile(ast.Expression(test), "<guard>", "eval")
    return bool(eval(code, {"__builtins__": {}}, {"sys": fake_sys}))


def _catches_import_error(node: ast.Try) -> bool:
    caught = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
    for handler in node.handlers:
        if handler.type is None:
            return True
        types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        if any(getattr(t, "id", getattr(t, "attr", None)) in caught for t in types):
            return True
    return False


def source_files(repo: Path = REPO) -> list[Path]:
    return sorted(
        path for package in SOURCE_PACKAGES for path in (repo / package).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def third_party_imports(repo: Path = REPO, pythons: list[tuple[int, int]] | None = None) -> list[Import]:
    pythons = pythons or read_setup_cfg((repo / "setup.cfg").read_text(encoding="utf-8")).pythons
    local = set(SOURCE_PACKAGES)
    found = []
    for path in source_files(repo):
        rel = path.relative_to(repo).as_posix()
        for imp in imports_in_source(path.read_text(encoding="utf-8"), rel, pythons):
            if imp.module in local:
                continue
            if imp.module in REMOVED_FROM_STDLIB:
                removed_in, _ = REMOVED_FROM_STDLIB[imp.module]
                where = imp.where if imp.where is not None else frozenset(itertools.product(pythons, PLATFORMS))
                where = frozenset((py, plat) for py, plat in where if py >= removed_in)
                if where:
                    found.append(Import(imp.module, imp.file, imp.line, imp.kind, where))
            elif imp.module not in sys.stdlib_module_names:
                found.append(imp)
    return found


# Reading what is declared


@dataclass
class Declared:
    install_requires: list[Requirement]
    extras: dict[str, list[Requirement]]
    pythons: list[tuple[int, int]]


def read_setup_cfg(text: str) -> Declared:
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    install_requires = _requirements(config.get("options", "install_requires", fallback=""))
    extras = {}
    if config.has_section("options.extras_require"):
        for extra, value in config.items("options.extras_require"):
            extras[extra] = _requirements(value)
    return Declared(install_requires, extras, supported_pythons_from(config))


def _requirements(text: str) -> list[Requirement]:
    lines = (line.split(" #", 1)[0].strip() for line in text.splitlines())
    return [Requirement(line) for line in lines if line and not line.startswith(("#", "-"))]


def supported_pythons_from(config: configparser.ConfigParser) -> list[tuple[int, int]]:
    versions = []
    for line in config.get("metadata", "classifiers", fallback="").splitlines():
        parts = line.strip().split(" :: ")
        if parts[:2] == ["Programming Language", "Python"] and len(parts) == 3 and parts[2].count(".") == 1:
            major, minor = parts[2].split(".")
            versions.append((int(major), int(minor)))
    return sorted(versions) or [(3, 10), (3, 11), (3, 12), (3, 13)]


def read_requirements_txt(text: str) -> list[Requirement]:
    return _requirements(text)


# Import names to distributions


@cache
def _installed_distributions() -> dict[str, list[str]]:
    return importlib.metadata.packages_distributions()


def distributions_for(module: str) -> set[str]:
    if module in REMOVED_FROM_STDLIB:
        return {canonicalize_name(REMOVED_FROM_STDLIB[module][1])}
    if module in DISTRIBUTION_OF:
        return {canonicalize_name(DISTRIBUTION_OF[module])}
    installed = _installed_distributions().get(module)
    if installed:
        return {canonicalize_name(name) for name in installed}
    return {canonicalize_name(module)}


# The checks


def _environment(python: tuple[int, int], platform: str, extra: str) -> dict[str, str]:
    system, os_name = PLATFORMS[platform]
    version = f"{python[0]}.{python[1]}"
    return {
        "python_version": version, "python_full_version": f"{version}.0", "sys_platform": platform,
        "platform_system": system, "os_name": os_name, "implementation_name": "cpython",
        "platform_python_implementation": "CPython", "extra": extra,
    }


def undeclared_problems(imports: list[Import], declared: Declared) -> list[str]:
    """What is imported but not declared where it has to be, each saying what to add where"""
    everywhere = frozenset(itertools.product(declared.pythons, PLATFORMS))
    problems = []
    by_need = collections.defaultdict(list)
    for imp in imports:
        if imp.kind != "required":
            continue
        extra = next((e for d, e in EXTRA_DIRS.items() if imp.file.startswith(d + "/")), None)
        by_need[(imp.module, extra)].append(imp)

    for (module, extra), sites in sorted(by_need.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        dists = distributions_for(module)
        scopes = [("install_requires", declared.install_requires, "")]
        if extra:
            scopes.append((f"the {extra} extra", declared.extras.get(extra, []), extra))
        where = frozenset().union(*(s.where if s.where is not None else everywhere for s in sites))
        places = ", ".join(s.place for s in sites[:3]) + (f" and {len(sites) - 3} more" if len(sites) > 3 else "")
        dist_names = " or ".join(sorted(dists))

        matching = [
            (req, env_extra) for _, reqs, env_extra in scopes for req in reqs
            if canonicalize_name(req.name) in dists
            or canonicalize_name(req.name) in {canonicalize_name(PROVIDED_BY[d]) for d in dists if d in PROVIDED_BY}
        ]
        if not matching:
            elsewhere = [
                name for name, reqs in declared.extras.items() if name != extra
                and any(canonicalize_name(r.name) in dists for r in reqs)
            ]
            target = (
                f"under [options.extras_require] {extra} in setup.cfg (or install_requires, if code "
                f"outside {next(d for d, e in EXTRA_DIRS.items() if e == extra)}/ needs it too)"
                if extra else "to install_requires in setup.cfg (requirements.txt has to say the same)"
            )
            also = (
                f" setup.cfg only installs it with the {', '.join(elsewhere)} extra, which code "
                f"here can't count on." if elsewhere else ""
            )
            problems.append(
                f"{places} import{'s' if len(sites) == 1 else ''} {module}, from the distribution "
                f"{dist_names}, which installing manimgl doesn't install.{also} Add "
                f"`{sorted(dists)[0]}` {target}."
            )
            continue

        uncovered = sorted(
            (python, platform) for python, platform in where
            if not any(
                req.marker is None or req.marker.evaluate(_environment(python, platform, env_extra))
                for req, env_extra in matching
            )
        )
        if uncovered:
            shown = sorted({f"{p[0]}.{p[1]}" for p, _ in uncovered})
            platforms = sorted({plat for _, plat in uncovered})
            markers = "; ".join(f"`{req}`" for req, _ in matching)
            problems.append(
                f"{places} import{'s' if len(sites) == 1 else ''} {module} on Python "
                f"{', '.join(shown)} ({', '.join(platforms)}), but setup.cfg declares only {markers}, "
                f"whose marker leaves those out. Widen the marker, or guard the import with the "
                f"same condition (`if sys.version_info ...:`)."
            )
    return problems


def unknown_optional_problems(imports: list[Import]) -> list[str]:
    optional = collections.defaultdict(list)
    for imp in imports:
        if imp.kind == "optional":
            optional[imp.module].append(imp.place)
    problems = [
        f"{', '.join(places)} import{'s' if len(places) == 1 else ''} {module} inside a try which "
        f"catches ImportError, so manim runs without it. If that is meant, add {module!r} to "
        f"OPTIONAL in {Path(__file__).relative_to(REPO).as_posix()}, saying what happens without "
        f"it; if it isn't, declare it in setup.cfg and drop the try."
        for module, places in sorted(optional.items()) if module not in OPTIONAL
    ]
    problems += [
        f"OPTIONAL in {Path(__file__).relative_to(REPO).as_posix()} lists {module!r}, which "
        f"nothing imports optionally any more: take it out."
        for module in sorted(set(OPTIONAL) - set(optional))
    ]
    return problems


def requirements_mismatch_problems(setup_cfg: list[Requirement], requirements_txt: list[Requirement]) -> list[str]:
    def key(req):
        return canonicalize_name(req.name)

    def normal(req):
        return (key(req), tuple(sorted(req.extras)), str(req.specifier), str(req.marker or ""))

    cfg = collections.defaultdict(set)
    txt = collections.defaultdict(set)
    for req in setup_cfg:
        cfg[key(req)].add(normal(req))
    for req in requirements_txt:
        txt[key(req)].add(normal(req))
    shown = {normal(r): str(r) for r in [*setup_cfg, *requirements_txt]}

    problems = []
    for name in sorted(set(cfg) | set(txt)):
        if name not in txt:
            problems.append(
                f"setup.cfg installs {' and '.join(f'`{shown[n]}`' for n in sorted(cfg[name]))} and "
                f"requirements.txt doesn't: add the same line to requirements.txt."
            )
        elif name not in cfg:
            problems.append(
                f"requirements.txt has {' and '.join(f'`{shown[n]}`' for n in sorted(txt[name]))} and "
                f"setup.cfg install_requires doesn't, so `pip install manimgl` leaves it out: add it "
                f"to install_requires in setup.cfg."
            )
        elif cfg[name] != txt[name]:
            problems.append(
                f"setup.cfg says {' and '.join(f'`{shown[n]}`' for n in sorted(cfg[name]))} where "
                f"requirements.txt says {' and '.join(f'`{shown[n]}`' for n in sorted(txt[name]))}: "
                f"make them the same."
            )
    return problems


def _fail(problems: list[str]) -> None:
    if problems:
        pytest.fail("\n\n".join(problems), pytrace=False)


@cache
def _declared() -> Declared:
    return read_setup_cfg((REPO / "setup.cfg").read_text(encoding="utf-8"))


@cache
def _imports() -> tuple[Import, ...]:
    return tuple(third_party_imports(REPO, _declared().pythons))


def test_every_import_is_declared():
    _fail(undeclared_problems(list(_imports()), _declared()))


def test_optional_imports_are_known():
    _fail(unknown_optional_problems(list(_imports())))


def test_requirements_txt_says_what_setup_cfg_does():
    requirements = read_requirements_txt((REPO / "requirements.txt").read_text(encoding="utf-8"))
    _fail(requirements_mismatch_problems(_declared().install_requires, requirements))


def test_what_is_found():
    """The scan finds what it has to for the checks above to mean anything"""
    modules = {imp.module for imp in _imports() if imp.kind == "required"}
    assert {"numpy", "av", "PIL", "pydantic", "yaml", "wgpu"} <= modules, modules
    assert len(source_files()) > 100


# The checks, on what they are meant to catch


def _without(text: str, name: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip().split(";")[0].strip() != name)


def test_a_dependency_missing_from_setup_cfg_is_caught():
    """
    What happened with av: requirements.txt had it, setup.cfg didn't, and the code imports it.
    Both checks catch it, and say what to add where.
    """
    setup_cfg = _without((REPO / "setup.cfg").read_text(encoding="utf-8"), "av")
    requirements = read_requirements_txt((REPO / "requirements.txt").read_text(encoding="utf-8"))
    declared = read_setup_cfg(setup_cfg)

    undeclared = undeclared_problems(list(_imports()), declared)
    assert len(undeclared) == 1, undeclared
    assert undeclared[0].startswith("manimlib/mobject/types/video_mobject.py:")
    assert "Add `av` to install_requires in setup.cfg" in undeclared[0]

    mismatched = requirements_mismatch_problems(declared.install_requires, requirements)
    assert mismatched == [
        "requirements.txt has `av` and setup.cfg install_requires doesn't, so `pip install "
        "manimgl` leaves it out: add it to install_requires in setup.cfg."
    ]


PYTHONS = [(3, 10), (3, 11), (3, 12), (3, 13)]


def scan(source: str, file: str = "manimlib/example.py") -> list[Import]:
    return [
        imp for imp in imports_in_source(textwrap.dedent(source), file, PYTHONS)
        if imp.module not in sys.stdlib_module_names and imp.module not in SOURCE_PACKAGES
    ]


def test_guards_are_read():
    found = {imp.module: imp for imp in scan("""
        from __future__ import annotations
        import os, numpy.linalg
        from typing import TYPE_CHECKING
        from . import sibling
        from manimlib.utils import thing
        if TYPE_CHECKING:
            import only_for_types
        else:
            import at_runtime
        try:
            import maybe
        except ImportError:
            import fallback
        try:
            import required_anyway
        except ValueError:
            pass
        if sys.version_info < (3, 11):
            import old_pythons
        else:
            import new_pythons
        if sys.platform == "win32":
            import windows_only
        def later():
            import lazily
            importlib.import_module("dynamic")
    """)}
    kinds = {name: imp.kind for name, imp in found.items()}
    assert kinds == {
        "numpy": "required", "only_for_types": "typing", "at_runtime": "required",
        "maybe": "optional", "fallback": "optional", "required_anyway": "required",
        "old_pythons": "required", "new_pythons": "required", "windows_only": "required",
        "lazily": "required", "dynamic": "required",
    }
    assert {py for py, _ in found["old_pythons"].where} == {(3, 10)}
    assert {py for py, _ in found["new_pythons"].where} == {(3, 11), (3, 12), (3, 13)}
    assert {plat for _, plat in found["windows_only"].where} == {"win32"}
    assert found["numpy"].where is None


def _declared_from(install_requires: str, editor: str = "") -> Declared:
    def block(text: str) -> str:
        return "".join(f"\n    {line}" for line in text.splitlines())

    classifiers = block("\n".join(f"Programming Language :: Python :: {p[0]}.{p[1]}" for p in PYTHONS))
    return read_setup_cfg(
        f"[metadata]\nclassifiers ={classifiers}\n"
        f"[options]\ninstall_requires ={block(install_requires)}\n"
        f"[options.extras_require]\neditor ={block(editor)}\n"
    )


def test_names_markers_and_extras():
    imports = scan("""
        import PIL.Image
        import yaml
        if sys.version_info < (3, 11):
            import tomli
        import typing_extensions
    """) + scan("import fastapi\nimport starlette.responses\n", "manim_verbose/editor/server.py") \
        + scan("import fastapi\n", "manim_verbose/scenefile/cli.py")
    declared = _declared_from(
        'Pillow\nPyYAML\ntomli; python_version < "3.11"\ntyping-extensions; python_version < "3.11"',
        "fastapi>=0.110",
    )
    problems = undeclared_problems(imports, declared)
    assert len(problems) == 2, problems
    typing_problem, fastapi_problem = sorted(problems, key=lambda p: "fastapi" in p)
    assert "typing_extensions on Python 3.11, 3.12, 3.13" in typing_problem
    assert fastapi_problem.startswith("manim_verbose/scenefile/cli.py:1 imports fastapi")
    assert "only installs it with the editor extra" in fastapi_problem


def test_a_removed_standard_module_needs_its_stand_in():
    imports = [
        Import("audioop", "manimlib/sound.py", 1, "required",
               frozenset(itertools.product([(3, 13)], PLATFORMS))),
    ]
    assert undeclared_problems(imports, _declared_from('audioop-lts; python_version >= "3.13"')) == []
    assert "Add `audioop-lts`" in undeclared_problems(imports, _declared_from("numpy"))[0]


def test_requirement_files_are_compared_as_requirements():
    same = requirements_mismatch_problems(
        [Requirement('audioop-lts; python_version >= "3.13"'), Requirement("Pillow")],
        [Requirement("audioop_lts; python_version>='3.13'"), Requirement("pillow")],
    )
    assert same == []
    assert requirements_mismatch_problems([Requirement("numpy>=2")], [Requirement("numpy")]) == [
        "setup.cfg says `numpy>=2` where requirements.txt says `numpy`: make them the same."
    ]
