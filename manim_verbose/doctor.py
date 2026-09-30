"""
manimgl-doctor: can this computer make manim videos, and if not, what exactly to do about it.

    manimgl-doctor                  check everything, and say how to fix what isn't right
    manimgl-doctor --quick          the same, without the test render (a few seconds quicker)
    manimgl-doctor --json           the same as JSON, for the editor to show
    manimgl-doctor --install-tex    set up a LaTeX of manim's own (TinyTeX), then check it
    manimgl-doctor --uninstall-tex  delete that LaTeX again

What is checked, each with a plain answer and the fix for this operating system:

    python   a supported, 64-bit Python
    manim    manimlib and manim_verbose import (manimpango, which needs Pango on Linux, included)
    editor   the editor's extra is installed, and its UI is built into the package
    gpu      wgpu finds a graphics adapter (a GPU, or Mesa's lavapipe on the CPU)
    latex    latex and dvisvgm, and every package manim's default template uses
    ffmpeg   the ffmpeg program manim writes videos through, with H.264
    fonts    fonts for text; which of manim's usual ones are missing, and what stands in
    render   a tiny scene file rendered to a picture, from start to finish

Exits 0 when nothing failed (warnings don't count), 1 when something did. Nothing here
raises past main(): a check which goes wrong itself is reported as that check failing.

The JSON is {"version": 1, "ok": bool, "system": {...}, "checks": [{"id", "title",
"status" ("ok", "warn", "fail" or "skip"), "summary", "fix": [lines], "notes": [lines],
"details": {...}, "seconds"}]}.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from manim_verbose import tex_setup

JSON_VERSION = 1
SUPPORTED_PYTHONS = ((3, 10), (3, 13))  # oldest and newest, as setup.cfg's classifiers say
INSTALL_DOC = "https://github.com/Jerome-Joseph-1/manim-verbose/blob/master/docs/editor/INSTALL.md"
OPTIONAL_FONT = "CMU Serif"
SUBPROCESS_TIMEOUT = 180


@dataclass
class Result:
    id: str
    title: str
    status: str = "ok"  # ok, warn, fail or skip
    summary: str = ""
    fix: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    seconds: float = 0.0


@dataclass
class System:
    """What the advice depends on. Tests make up their own."""
    os: str                     # "linux", "darwin", "windows" or whatever else platform.system() says
    distro: str | None = None   # on Linux: "debian", "fedora", "arch", "suse", or None when unknown
    distro_name: str = ""
    machine: str = ""
    python: tuple[int, int, int] = (0, 0, 0)
    bits: int = 64
    executable: str = ""

    @classmethod
    def detect(cls) -> "System":
        name = platform.system().lower()
        distro, distro_name = (linux_distro() if name == "linux" else (None, ""))
        return cls(
            os=name, distro=distro, distro_name=distro_name, machine=platform.machine(),
            python=tuple(sys.version_info[:3]), bits=struct.calcsize("P") * 8, executable=sys.executable,
        )


def linux_distro(os_release: str | None = None) -> tuple[str | None, str]:
    """The family of Linux, by its package manager, from /etc/os-release"""
    if os_release is None:
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, ""
    values = dict(re.findall(r'^([A-Z_]+)="?([^"\n]*)"?$', os_release, flags=re.MULTILINE))
    ids = [values.get("ID", "").lower()] + values.get("ID_LIKE", "").lower().split()
    name = values.get("PRETTY_NAME") or values.get("NAME", "")
    for family, members in (
        ("debian", ("debian", "ubuntu", "linuxmint", "pop", "elementary", "raspbian", "kali", "zorin")),
        ("fedora", ("fedora", "rhel", "centos", "rocky", "almalinux", "nobara")),
        ("arch", ("arch", "manjaro", "endeavouros", "garuda")),
        ("suse", ("suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles")),
    ):
        if any(i in members for i in ids):
            return family, name
    return None, name


@dataclass
class Context:
    system: System
    quick: bool = False
    results: dict[str, Result] = field(default_factory=dict)

    def status(self, check_id: str) -> str | None:
        result = self.results.get(check_id)
        return result.status if result else None


# Saying how to install a system package, for whichever Linux this is

def linux_install(system: System, *, apt: str, dnf: str | None = None, pacman: str | None = None,
                  zypper: str | None = None) -> list[str]:
    commands = {
        "debian": f"sudo apt install {apt}",
        "fedora": dnf and f"sudo dnf install {dnf}",
        "arch": pacman and f"sudo pacman -S {pacman}",
        "suse": zypper and f"sudo zypper install {zypper}",
    }
    labels = {"debian": "Debian, Ubuntu, Mint", "fedora": "Fedora", "arch": "Arch, Manjaro", "suse": "openSUSE"}
    if system.distro and commands.get(system.distro):
        return [f"  {commands[system.distro]}"]
    return [f"  {labels[family]}:  {command}" for family, command in commands.items() if command]


# The checks. Each takes the context and returns a Result; anything they call which looks at
# the computer is a module level function, for tests to replace.

def check_python(ctx: Context, result: Result) -> Result:
    system = ctx.system
    version = ".".join(map(str, system.python))
    result.summary = f"Python {version}, {system.bits}-bit ({system.executable})"
    oldest, newest = SUPPORTED_PYTHONS
    if system.python[:2] < oldest:
        result.status = "fail"
        result.summary = f"Python {version} is too old: manim needs Python {oldest[0]}.{oldest[1]} or newer"
        result.fix = [f"Install Python {newest[0]}.{newest[1]} from https://www.python.org/downloads/ and install "
                      "manim again with it (see " + INSTALL_DOC + ")"]
    elif system.bits != 64:
        result.status = "fail"
        result.summary = f"This Python is {system.bits}-bit; manim's graphics need a 64-bit Python"
        result.fix = ["Install the 64-bit Python from https://www.python.org/downloads/ (on Windows: the "
                      "'Windows installer (64-bit)'), and install manim again with it"]
    elif system.python[:2] > newest:
        result.status = "warn"
        result.summary = (f"Python {version} is newer than manim has been tested with "
                          f"({oldest[0]}.{oldest[1]} to {newest[0]}.{newest[1]})")
        result.fix = [f"If something below fails, Python {newest[0]}.{newest[1]} is the safe choice: "
                      "https://www.python.org/downloads/"]
    return result


def import_manim_modules() -> dict[str, str]:
    """Imports what a render needs, as manimgl-editor would; the versions found"""
    from importlib import metadata
    from manim_verbose.manim_import import import_manim
    manimlib = import_manim()
    import manimpango
    from manim_verbose.scenefile import render  # noqa: F401 (imported to see that it imports)
    return {
        "manimgl": metadata.version("manimgl"),
        "manimlib": getattr(manimlib, "__version__", ""),
        "manimpango": getattr(manimpango, "__version__", ""),
        "location": str(Path(manimlib.__file__).resolve().parent.parent),
    }


def check_manim(ctx: Context, result: Result) -> Result:
    try:
        versions = import_manim_modules()
    except Exception as err:
        result.status = "fail"
        message = f"{type(err).__name__}: {err}"
        result.summary = f"manim is installed but doesn't load: {message}"
        result.details = {"error": message}
        if "pango" in message.lower() and ctx.system.os == "linux":
            result.fix = ["manimpango needs the Pango library. Install it:"] + linux_install(
                ctx.system, apt="libpango1.0-dev pkg-config", dnf="pango-devel pkgconf", pacman="pango pkgconf",
                zypper="pango-devel pkg-config",
            ) + ["then reinstall manimpango:  python -m pip install --force-reinstall --no-cache-dir manimpango"]
        else:
            result.fix = ["Install manim again, in the same Python that runs manimgl-doctor, as " + INSTALL_DOC
                          + " says (python -m pip install --force-reinstall ...)"]
        return result
    result.details = versions
    result.summary = f"manimgl {versions['manimgl']} loads (from {versions['location']})"
    return result


def ui_index() -> Path:
    spec = importlib.util.find_spec("manim_verbose.editor")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin).parent / "static" / "index.html"


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_editor(ctx: Context, result: Result) -> Result:
    missing = [name for name in ("fastapi", "uvicorn") if not module_available(name)]
    index = ui_index()
    result.details = {"ui": str(index), "ui_built": index.is_file(), "missing": missing}
    if missing:
        result.status = "fail"
        result.summary = f"manim is installed without the editor ({' and '.join(missing)} missing)"
        result.fix = ['Install manim with the editor: the pip command in ' + INSTALL_DOC + ' ends in "[editor]"; '
                      'or run  python -m pip install "fastapi>=0.110" "uvicorn>=0.27"']
    elif not index.is_file():
        result.status = "fail"
        result.summary = "The editor's page isn't built into this copy of manim, so the browser would show nothing to edit with"
        checkout = index.parents[3] / "editor-ui" / "package.json"
        if checkout.is_file():
            result.fix = ["This is a copy of the source code. Build the editor's page (needs Node.js 20 or newer):",
                          f"  cd {checkout.parent}", "  npm ci", "  npm run build"]
        else:
            result.fix = ["Install manim from a release, whose wheel has the page built in, as " + INSTALL_DOC + " says"]
    else:
        result.summary = "The editor is installed, with its page built in"
    return result


GPU_PROBE = textwrap.dedent("""
    import json, wgpu
    adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    info = adapter.info
    device = adapter.request_device_sync()
    print(json.dumps({key: info.get(key, "") for key in ("vendor", "device", "description", "adapter_type", "backend_type")}))
""")


def probe_gpu() -> dict:
    """The adapter wgpu picks, as manimlib's renderer asks for it; in a process of its own, since a broken driver can crash one"""
    run = subprocess.run([sys.executable, "-c", GPU_PROBE], capture_output=True, text=True, errors="replace",
                         timeout=SUBPROCESS_TIMEOUT)
    if run.returncode != 0:
        lines = [line for line in run.stderr.strip().splitlines() if line.strip()]
        raise RuntimeError(lines[-1] if lines else f"the graphics check exited with status {run.returncode}")
    return json.loads(run.stdout.strip().splitlines()[-1])


def check_gpu(ctx: Context, result: Result) -> Result:
    if ctx.status("manim") == "fail":
        return skip(result, "manim doesn't load")
    try:
        info = probe_gpu()
    except Exception as err:
        result.status = "fail"
        result.summary = "manim can't find a graphics adapter to draw with"
        result.details = {"error": str(err)}
        result.fix = gpu_fixes(ctx.system)
        return result
    result.details = info
    kind = str(info.get("adapter_type", ""))
    name = info.get("device") or info.get("description") or "an adapter"
    backend = info.get("backend_type", "")
    if "cpu" in kind.lower():
        result.summary = f"Drawing on the CPU with {name} ({backend}): it works, just more slowly than a graphics card would"
        result.notes = ["No graphics card was found, or its driver doesn't offer "
                        + ("Vulkan" if ctx.system.os == "linux" else "what manim needs")
                        + ". That's normal in a virtual machine; on a computer with an NVIDIA card, installing "
                        "NVIDIA's own driver makes rendering faster."]
    else:
        result.summary = f"{name} ({kind or 'GPU'}, {backend})"
    return result


def gpu_fixes(system: System) -> list[str]:
    if system.os == "linux":
        return ["manim draws with Vulkan. Install Mesa's Vulkan drivers, which include one that works on any computer, "
                "even without a graphics card:"] + linux_install(
            system, apt="mesa-vulkan-drivers libvulkan1", dnf="mesa-vulkan-drivers vulkan-loader",
            pacman="vulkan-swrast vulkan-icd-loader", zypper="libvulkan_lvp libvulkan1",
        ) + ["then run manimgl-doctor again."]
    if system.os == "darwin":
        return ["manim draws with Metal, which every Mac from 2012 on has with macOS 10.14 or later. Update macOS "
                "(Apple menu > System Settings > General > Software Update). In a virtual machine, Metal may not be available."]
    if system.os == "windows":
        return ["manim draws with DirectX 12 or Vulkan. Update the graphics driver: Settings > Windows Update > "
                "Advanced options > Optional updates, or from the maker of the graphics card (Intel, AMD or NVIDIA).",
                "In a virtual machine or remote desktop without a graphics card, turn on its 3D acceleration if it has any."]
    return ["manim draws through wgpu, which needs Vulkan, Metal or DirectX 12 drivers."]


def check_latex(ctx: Context, result: Result) -> Result:
    root = tex_setup.tex_dir()
    managed = tex_setup.managed_bin(root)
    unfinished = managed is None and tex_setup.find_bin(root) is not None
    check = compile_tex()
    source = "managed" if managed and check.latex and Path(check.latex).parent == managed else "system"
    result.details = {
        "latex": check.latex, "dvisvgm": check.dvisvgm, "source": source if check.latex else None,
        "managed_dir": str(root), "problems": check.problems, "missing_files": check.missing_files,
        "paths": check.paths, "compile_seconds": round(check.seconds, 2),
    }
    where = f"the LaTeX manimgl-doctor installed in {root}" if source == "managed" else f"{check.latex}"
    if check.ok:
        result.summary = f"Formulas work: {where} compiled every package manim uses in {check.seconds:.1f}s"
        return result

    result.status = "fail"
    install_line = "  manimgl-doctor --install-tex"
    if check.latex is None or check.dvisvgm is None:
        missing = " and ".join(name for name, path in (("latex", check.latex), ("dvisvgm", check.dvisvgm)) if path is None)
        if check.latex is None:
            result.summary = "LaTeX isn't installed, so formulas (equations) can't be drawn; everything else works"
        else:
            result.summary = f"LaTeX is here ({check.latex}) but {missing} isn't, so formulas can't be drawn"
        if unfinished:
            result.fix = [f"Setting up LaTeX in {root} was started and didn't finish. Finish it with:", install_line]
            return result
        result.fix = ["Let manimgl-doctor set up a LaTeX just for manim (no administrator rights needed; a few "
                      "minutes, a download of about 200 MB):", install_line]
        if ctx.system.os == "linux":
            result.fix += ["Or install TeX Live from your system's packages" + (":" if ctx.system.distro == "debian" else
                           " (these are the Debian and Ubuntu names):"),
                           "  sudo apt install " + " ".join(tex_setup.APT_PACKAGES)]
        return result

    result.summary = f"LaTeX ({check.latex}) can't typeset everything manim's formulas use: " + "; ".join(check.problems[:4])
    if source == "managed":
        result.fix = ["Repair the LaTeX manimgl-doctor set up:", install_line,
                      "or, if that doesn't help, start it again:  manimgl-doctor --install-tex --force"]
        return result
    tl_names = sorted({tex_setup.FILE_HOMES[f][0] for f in check.missing_files if f in tex_setup.FILE_HOMES})
    apt_names = sorted({tex_setup.FILE_HOMES[f][1] for f in check.missing_files if f in tex_setup.FILE_HOMES})
    result.fix = ["Simplest: let manimgl-doctor set up a LaTeX just for manim, which is then used instead of this one:",
                  install_line]
    if tl_names:
        result.fix.append("Or add what's missing to the LaTeX you have:")
        if ctx.system.os == "linux" and ctx.system.distro == "debian" and check.latex.startswith("/usr/bin"):
            result.fix.append("  sudo apt install " + " ".join(apt_names))
        elif "miktex" in check.latex.lower():
            result.fix.append("  open MiKTeX Console > Packages, and install: " + " ".join(tl_names))
        else:
            result.fix += ["  tlmgr install " + " ".join(tl_names), "(with sudo in front, if it says it can't write there)"]
    elif check.missing_fonts or any("SVG holds only" in p for p in check.problems):
        result.fix.append("Or install the outline fonts LaTeX is missing (cm-super, and the fonts packages "
                          "of your TeX distribution).")
    return result


def compile_tex() -> tex_setup.TexCheck:
    return tex_setup.compile_check()


def ffmpeg_program() -> str:
    """The ffmpeg manim is configured to use: manim_config's file_writer.ffmpeg_bin, usually just "ffmpeg" """
    if "manimlib.config" in sys.modules:
        config = sys.modules["manimlib.config"].manim_config
        return str(getattr(config.file_writer, "ffmpeg_bin", None) or "ffmpeg")
    return "ffmpeg"


def ffmpeg_encoders(program: str) -> str:
    run = subprocess.run([program, "-hide_banner", "-encoders"], capture_output=True, text=True, errors="replace",
                         timeout=60)
    return run.stdout


def check_ffmpeg(ctx: Context, result: Result) -> Result:
    program = ffmpeg_program()
    found = shutil.which(program)
    result.details = {"ffmpeg": found}
    if found is None:
        result.status = "fail"
        result.summary = "ffmpeg isn't installed, so pictures work but previews and videos can't be made"
        result.fix = ffmpeg_fixes(ctx.system)
        return result
    try:
        encoders = ffmpeg_encoders(found)
    except (OSError, subprocess.SubprocessError) as err:
        result.status = "fail"
        result.summary = f"ffmpeg ({found}) doesn't run: {err}"
        result.fix = ffmpeg_fixes(ctx.system)
        return result
    if "libx264" not in encoders:
        result.status = "fail"
        result.summary = f"This ffmpeg ({found}) can't write H.264 video (libx264), which manim's videos are"
        if ctx.system.distro == "fedora":
            result.fix = ["Fedora's own ffmpeg leaves H.264 out. Enable RPM Fusion (https://rpmfusion.org/Configuration), then:",
                          "  sudo dnf swap ffmpeg-free ffmpeg --allowerasing"]
        else:
            result.fix = ["Install a full build of ffmpeg:"] + ffmpeg_fixes(ctx.system)[1:]
        return result
    result.summary = f"{found}, with H.264"
    return result


def ffmpeg_fixes(system: System) -> list[str]:
    if system.os == "windows":
        return ["Install it with winget, then open a new terminal window:",
                "  winget install --id Gyan.FFmpeg -e",
                "(or download a build from https://www.gyan.dev/ffmpeg/builds/ and add its bin folder to PATH)"]
    if system.os == "darwin":
        return ["Install it with Homebrew (https://brew.sh):", "  brew install ffmpeg"]
    if system.os == "linux":
        lines = ["Install it:"] + linux_install(system, apt="ffmpeg", dnf="ffmpeg", pacman="ffmpeg", zypper="ffmpeg")
        if system.distro in (None, "fedora"):
            lines.append("(on Fedora, enable RPM Fusion first for a build with H.264: https://rpmfusion.org/Configuration)")
        return lines
    return ["Install ffmpeg (https://ffmpeg.org/download.html) so that `ffmpeg` runs in a terminal."]


def installed_fonts() -> list[str]:
    import manimpango
    return list(manimpango.list_fonts())


def manim_text_font() -> str:
    if "manimlib.config" in sys.modules:
        return str(sys.modules["manimlib.config"].manim_config.text.font)
    return "Consolas"


def font_substitute(name: str) -> str | None:
    """What fontconfig draws in place of a font which isn't installed (Linux); None where that can't be asked"""
    fc_match = shutil.which("fc-match")
    if fc_match is None:
        return None
    try:
        run = subprocess.run([fc_match, "--format=%{family}", name], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.split(",")[0].strip() or None


def check_fonts(ctx: Context, result: Result) -> Result:
    if ctx.status("manim") == "fail":
        return skip(result, "manim doesn't load")
    fonts = installed_fonts()
    default = manim_text_font()
    present = {font.lower() for font in fonts}
    result.details = {"count": len(fonts), "default_font": default, "default_installed": default.lower() in present,
                      "optional_installed": OPTIONAL_FONT.lower() in present}
    if not fonts:
        result.status = "fail"
        result.summary = "No fonts were found, so no text can be drawn"
        result.fix = ["Install some fonts:"] + (linux_install(ctx.system, apt="fonts-dejavu fontconfig",
                      dnf="dejavu-sans-fonts fontconfig", pacman="ttf-dejavu fontconfig", zypper="dejavu-fonts fontconfig")
                      if ctx.system.os == "linux" else ["  (your system's fonts folder is empty or unreadable)"])
        return result
    result.summary = f"{len(fonts)} fonts"
    for name, why in ((default, "manim's usual font for text"), (OPTIONAL_FONT, "a font scene files often choose")):
        if name.lower() in present:
            result.notes.append(f"{name} ({why}) is installed")
            continue
        substitute = font_substitute(name)
        instead = f"{substitute} is used instead" if substitute else "your system picks a similar font instead"
        result.notes.append(f"{name} ({why}) isn't installed; text asking for it still works, and {instead}")
    if OPTIONAL_FONT.lower() not in present:
        result.notes.append("To install CMU Serif (optional):" + (
            "  sudo apt install fonts-cmu" if ctx.system.distro == "debian" else
            " download cm-unicode from https://sourceforge.net/projects/cm-unicode/files/ , unzip it, and install "
            "the cmunrm, cmunbx, cmunti and cmunbi .otf files (double-click each one)"))
    return result


SMOKE_SCENE = """\
title: manimgl-doctor check
scenes:
  - id: check
    objects:
      - {{id: ring, type: circle, radius: 1.2, color: BLUE}}
      - {{id: words, type: text, text: "manim works", font_size: 40, place: [0, -2]}}{formula}
    steps:
      - {{do: show, target: [{targets}]}}
"""


def render_smoke(folder: Path, with_formula: bool) -> dict:
    """Renders a tiny scene file to a PNG with manimgl-scene, in a process of its own; what came of it"""
    # A formula never typeset before, so that manim's cache of LaTeX output can't answer for LaTeX
    n = random.randint(100, 999999)
    formula = (f'\n      - {{id: formula, type: tex, tex: "\\\\sum_{{k=1}}^{{{n}}} k = \\\\frac{{{n}({n}+1)}}{{2}}", '
               'place: [0, 2.2]}') if with_formula else ""
    targets = "ring, words, formula" if with_formula else "ring, words"
    scene = folder / "doctor-check.yaml"
    scene.write_text(SMOKE_SCENE.format(formula=formula, targets=targets), encoding="utf-8")
    png = folder / "doctor-check.png"
    env = dict(os.environ, MANIM_VERBOSE_CACHE=str(folder / "cache"), PYTHONIOENCODING="utf-8")
    started = time.monotonic()
    run = subprocess.run(
        [sys.executable, "-m", "manim_verbose.scenefile", "still", str(scene), "-s", "check", "--step", "0",
         "-o", str(png), "--width", "320"],
        capture_output=True, text=True, errors="replace", env=env, cwd=folder, timeout=SUBPROCESS_TIMEOUT,
    )
    seconds = time.monotonic() - started
    if run.returncode != 0:
        said = (run.stderr.strip() or run.stdout.strip()).splitlines()
        raise RuntimeError("\n".join(said[-5:]) or f"manimgl-scene still exited with status {run.returncode}")
    from PIL import Image
    with Image.open(png) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1 << 16)
        size = image.size
    if colors is not None and len(colors) < 2:
        raise RuntimeError("the picture came out a single flat color, so nothing was drawn")
    return {"seconds": round(seconds, 2), "width": size[0], "height": size[1], "formula": with_formula}


def check_render(ctx: Context, result: Result) -> Result:
    if ctx.quick:
        return skip(result, "left out (--quick)")
    for needed in ("manim", "gpu"):
        if ctx.status(needed) == "fail":
            return skip(result, f"fix the {ctx.results[needed].title.lower()} problem above first")
    with_formula = ctx.status("latex") == "ok"
    with tempfile.TemporaryDirectory(prefix="manimgl-doctor-") as temp:
        try:
            made = render_smoke(Path(temp), with_formula)
        except subprocess.TimeoutExpired:
            result.status = "fail"
            result.summary = f"Rendering a tiny scene took more than {SUBPROCESS_TIMEOUT} seconds"
            result.fix = ["Something is very slow or stuck; run manimgl-doctor again, and if it happens again, "
                          "report it with what manimgl-doctor --json prints"]
            return result
        except Exception as err:
            result.status = "fail"
            result.summary = "Rendering a tiny scene failed: " + str(err).strip().splitlines()[-1][:300]
            result.details = {"error": str(err)}
            result.fix = ["Fix anything else reported above first. If everything else is ok, report this, with "
                          "what manimgl-doctor --json prints"]
            return result
    result.details = made
    what = "a circle, text and a formula" if with_formula else "a circle and text"
    result.summary = f"Drew {what} to a {made['width']}x{made['height']} picture in {made['seconds']:.1f}s"
    return result


def skip(result: Result, why: str) -> Result:
    result.status = "skip"
    result.summary = f"Not checked: {why}"
    return result


# id, title, check: in the order they run, since some are skipped when an earlier one failed
CHECKS: list[tuple[str, str, Callable[[Context, Result], Result]]] = [
    ("python", "Python", check_python),
    ("manim", "manim itself", check_manim),
    ("editor", "The editor", check_editor),
    ("gpu", "Graphics", check_gpu),
    ("latex", "LaTeX (for formulas)", check_latex),
    ("ffmpeg", "ffmpeg (for videos)", check_ffmpeg),
    ("fonts", "Fonts", check_fonts),
    ("render", "Test render", check_render),
]


def run_check(ctx: Context, check_id: str) -> Result:
    """One check, by id, noted in the context for the checks after it"""
    title, check = next((title, check) for id_, title, check in CHECKS if id_ == check_id)
    started = time.monotonic()
    try:
        result = check(ctx, Result(check_id, title))
    except Exception as err:  # a check which breaks is that check failing, not the doctor
        result = Result(check_id, title, "fail", f"The check itself went wrong: {type(err).__name__}: {err}",
                        fix=["Report this, with what manimgl-doctor --json prints"])
    result.seconds = round(time.monotonic() - started, 2)
    ctx.results[check_id] = result
    return result


def run_checks(ctx: Context, on_result: Callable[[Result], None] | None = None) -> list[Result]:
    tex_setup.use_managed_tex()
    results = []
    for check_id, _title, _check in CHECKS:
        result = run_check(ctx, check_id)
        results.append(result)
        if on_result is not None:
            on_result(result)
    return results


def report_json(ctx: Context, results: list[Result]) -> dict:
    system = asdict(ctx.system)
    system["python"] = ".".join(map(str, ctx.system.python))
    return {
        "version": JSON_VERSION,
        "ok": not any(r.status == "fail" for r in results),
        "system": system,
        "checks": [asdict(r) for r in results],
    }


LABELS = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL", "skip": "skip"}


def print_result(result: Result, out=None) -> None:
    out = out or sys.stdout
    indent = " " * 8
    width = max(60, min(shutil.get_terminal_size((100, 20)).columns, 110))
    print(f"  {LABELS.get(result.status, result.status)}  {result.title}: {result.summary}", file=out, flush=True)
    for note in result.notes:
        print(textwrap.fill(note, width, initial_indent=indent, subsequent_indent=indent + "  "), file=out)
    if result.fix and result.status in ("fail", "warn"):
        print(f"{indent}To fix:", file=out)
        for line in result.fix:
            if line.startswith("  "):  # a command, printed as it is to be typed
                print(f"{indent}    {line.strip()}", file=out)
            else:
                print(textwrap.fill(line, width, initial_indent=indent + "  ", subsequent_indent=indent + "  "), file=out)
    out.flush()


def summary_line(results: list[Result]) -> str:
    failed = [r for r in results if r.status == "fail"]
    warned = [r for r in results if r.status == "warn"]
    if failed:
        things = "1 thing" if len(failed) == 1 else f"{len(failed)} things"
        return (f"{things} to fix: {', '.join(r.title for r in failed)}. "
                "Do what 'To fix' says above, then run manimgl-doctor again.")
    if warned:
        return "manim is ready to use (see the warnings above). Start the editor with:  manimgl-editor"
    return "Everything works. Start the editor with:  manimgl-editor"


# Setting up TeX from the command line

def cmd_install_tex(args, out=None) -> int:
    out = out or sys.stdout
    root = tex_setup.tex_dir()
    say = lambda line: print(line, file=out, flush=True)  # noqa: E731
    say(f"Setting up LaTeX for manim in {root}")
    say("Nothing outside that folder is changed, and no administrator rights are needed.")
    try:
        done = tex_setup.install(root, archive=args.tex_archive, repository=args.tex_repository,
                                 force=args.force, say=say)
    except tex_setup.TexSetupError as err:
        say(f"\nCouldn't set up LaTeX: {err}")
        for line in err.fix:
            say(f"  {line}")
        return 1
    except KeyboardInterrupt:
        say("\nStopped. Run  manimgl-doctor --install-tex  again to carry on from where it got to.")
        return 130
    size = done.size_bytes / 1e6
    if done.already:
        say(f"\nLaTeX was already set up in {done.root} ({size:.0f} MB), and works.")
    else:
        minutes, seconds = divmod(int(done.seconds), 60)
        say(f"\nDone in {minutes} min {seconds} s: LaTeX is ready ({size:.0f} MB in {done.root}).")
    tex_setup.use_managed_tex()
    result = run_check(Context(System.detect()), "latex")
    print_result(result, out)
    if result.status == "ok":
        say("manimgl-editor and manimgl-scene use it from now on. (For other programs, it is in "
            f"{done.bin_dir}; `manimgl-doctor --uninstall-tex` removes it.)")
    return 0 if result.status == "ok" else 1


def cmd_uninstall_tex(out=None) -> int:
    out = out or sys.stdout
    root = tex_setup.tex_dir()
    try:
        removed = tex_setup.uninstall(root)
    except OSError as err:
        print(f"Couldn't delete everything in {root}: {err}. Close any program using it (the editor, a terminal "
              "in that folder) and try again.", file=out)
        return 1
    print(f"Deleted the LaTeX in {root}." if removed else f"There's no LaTeX set up by manimgl-doctor (looked in {root}).",
          file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manimgl-doctor",
        description="Check this computer can make manim videos, and say how to fix anything that stops it.",
    )
    parser.add_argument("--json", action="store_true", help="Print the results as JSON")
    parser.add_argument("--quick", action="store_true", help="Leave out the test render")
    tex = parser.add_argument_group("LaTeX of manim's own (TinyTeX)")
    what = tex.add_mutually_exclusive_group()
    what.add_argument("--install-tex", action="store_true",
                      help=f"Download TinyTeX and the LaTeX packages manim uses into {tex_setup.tex_dir()}")
    what.add_argument("--uninstall-tex", action="store_true", help="Delete the LaTeX --install-tex set up")
    tex.add_argument("--force", action="store_true", help="With --install-tex: delete what is there and start again")
    tex.add_argument("--tex-archive", type=Path, metavar="FILE",
                     help="With --install-tex: a TinyTeX archive already downloaded, rather than downloading one")
    tex.add_argument("--tex-repository", metavar="URL",
                     help="With --install-tex: the TeX Live package server (CTAN mirror) to install packages from")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # A Windows console may not be able to show every character a path or font name has
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.install_tex and (args.force or args.tex_archive or args.tex_repository):
        parser.error("--force, --tex-archive and --tex-repository go with --install-tex")
    try:
        if args.install_tex:
            return cmd_install_tex(args)
        if args.uninstall_tex:
            return cmd_uninstall_tex()
        ctx = Context(System.detect(), quick=args.quick)
        if args.json:
            results = run_checks(ctx)
            print(json.dumps(report_json(ctx, results), indent=2))
        else:
            print("manimgl-doctor: checking this computer can make manim videos\n", flush=True)
            results = run_checks(ctx, print_result)
            print("\n" + summary_line(results))
        return 1 if any(r.status == "fail" for r in results) else 0
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
