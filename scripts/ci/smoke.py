"""
That an installed manimgl works as someone who has just installed it would use it. Run it with
the Python manimgl is installed into:

    python scripts/ci/smoke.py --scene scripts/ci/smoke/hello.yaml [--installed] [--render still|video --out DIR] [--no-checks]

--installed   fail unless manimlib and manim_verbose come from site-packages. The install
              workflow runs this from an empty directory with a wheel installed into a fresh
              venv, and a checkout on sys.path would mean it tested the checkout instead.
--render      also draw something: a still, or a video (which needs ffmpeg). Through
              `manimgl-scene still`/`render` once manim_verbose.scenefile.render has them, and
              until then through `manimgl` on a small Python scene, saying which it used.
--no-checks   only render (after the first check, of where manim is imported from)

Each check is printed as it runs; the exit status is 1 if any failed.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import time
from pathlib import Path

FAILURES: list[str] = []
TIMEOUT = 600

SCENE = textwrap.dedent('''
    from manimlib import *


    class Smoke(Scene):
        def construct(self):
            ring = Circle(radius=1.5).set_color(BLUE)
            label = Text("manimgl smoke test").next_to(ring, DOWN)
            self.play(ShowCreation(ring), run_time=0.5)
            self.add(label)
''')


def check(name: str):
    """Runs the decorated function as a check named `name`, noting whether it raised"""
    def run(function):
        start = time.monotonic()
        try:
            detail = function()
        except Exception as error:  # a check failing is reported, and the rest still run
            FAILURES.append(name)
            print(f"FAIL  {name}: {type(error).__name__}: {error}", flush=True)
        else:
            print(f"ok    {name} ({time.monotonic() - start:.1f}s){': ' + detail if detail else ''}", flush=True)
        return function
    return run


def script(name: str) -> str:
    """A console script installed beside this Python"""
    found = shutil.which(name, path=sysconfig.get_path("scripts"))
    if found is None:
        raise FileNotFoundError(f"no {name} in {sysconfig.get_path('scripts')}")
    return found


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    # What is printed goes to a pipe here, which Windows would otherwise encode as cp1252
    kwargs.setdefault("env", dict(os.environ, PYTHONIOENCODING="utf-8"))
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=TIMEOUT, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"`{' '.join(map(str, command))}` exited {result.returncode}\n"
            f"--- stdout\n{result.stdout[-4000:]}\n--- stderr\n{result.stderr[-4000:]}"
        )
    return result


def image_has_something_drawn(path: Path) -> str:
    from PIL import Image
    image = Image.open(path).convert("RGB")
    colors = image.getcolors(maxcolors=1 << 16)
    if colors is not None and len(colors) < 2:
        raise AssertionError(f"{path} is a single flat color, so nothing was drawn")
    return f"{path.name} {image.width}x{image.height}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scene", type=Path, required=True, help="a scene file which validates cleanly")
    parser.add_argument("--installed", action="store_true", help="require manim to come from site-packages")
    parser.add_argument("--render", choices=["still", "video"], help="also render")
    parser.add_argument("--out", type=Path, help="where rendered files go")
    parser.add_argument("--no-checks", action="store_true", help="only render")
    args = parser.parse_args()
    scene_file = args.scene.resolve()
    out = (args.out or Path.cwd() / "smoke-out").resolve()
    print(f"Python {sys.version.split()[0]} at {sys.executable}, in {Path.cwd()}")

    @check("manimlib and manim_verbose come from where manimgl is installed")
    def _():
        places = {}
        for name in ("manimlib", "manim_verbose"):
            spec = importlib.util.find_spec(name)
            if spec is None or spec.origin is None:
                raise ModuleNotFoundError(name)
            places[name] = Path(spec.origin).resolve()
        if args.installed:
            site = {Path(sysconfig.get_path(key)).resolve() for key in ("purelib", "platlib")}
            for name, origin in places.items():
                if not any(root in origin.parents for root in site):
                    raise AssertionError(f"{name} comes from {origin}, not from {', '.join(map(str, site))}")
        return ", ".join(f"{name} from {origin.parent}" for name, origin in places.items())

    if not args.no_checks:
        cli_checks(scene_file)
    if args.render:
        out.mkdir(parents=True, exist_ok=True)
        render(args.render, scene_file, out)

    print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}" if FAILURES else "\nAll checks passed")
    return 1 if FAILURES else 0


def cli_checks(scene_file: Path) -> None:
    @check("import manimlib through manim_import, and the scene file model")
    def _():
        from manim_verbose.manim_import import import_manim
        manimlib = import_manim()
        importlib.import_module("manim_verbose.scenefile.model")
        importlib.import_module("manim_verbose.scenefile.validate")
        version = importlib.metadata.version("manimgl")
        if manimlib.__version__ != version:
            raise AssertionError(f"manimlib.__version__ is {manimlib.__version__}, the installed manimgl {version}")
        return f"manimgl {version}"

    @check("manimgl --version")
    def _():
        printed = run([script("manimgl"), "--version"]).stdout
        return re.sub(r"\x1b\[[0-9;]*m", "", printed).strip().splitlines()[-1]

    @check(f"manimgl-scene validate {scene_file.name}")
    def _():
        return run([script("manimgl-scene"), "validate", str(scene_file)]).stdout.strip()

    @check(f"python -m manim_verbose.scenefile validate {scene_file.name}")
    def _():
        run([sys.executable, "-m", "manim_verbose.scenefile", "validate", str(scene_file)])

    @check("manimgl-scene schema prints the schema the package ships")
    def _():
        printed = json.loads(run([script("manimgl-scene"), "schema"]).stdout)
        from importlib.resources import files
        shipped = json.loads(files("manim_verbose.scenefile").joinpath("schema.json").read_text(encoding="utf-8"))
        if printed != shipped:
            raise AssertionError("the schema generated from the models differs from schema.json in the package")
        return f"{len(json.dumps(printed))} bytes, {len(printed.get('$defs', {}))} definitions"

    if importlib.util.find_spec("manim_verbose.editor") is not None:
        @check("manimgl-editor --help")
        def _():
            run([script("manimgl-editor"), "--help"])
    else:
        print("note  manim_verbose.editor is not in this install yet, so manimgl-editor is not tried")


def render(kind: str, scene_file: Path, out: Path) -> None:
    from manim_verbose.scenefile import render as scenefile_render
    via_scenefile = hasattr(scenefile_render, "render_still" if kind == "still" else "render_video")
    if not via_scenefile:
        print(
            f"note  manim_verbose.scenefile.render has no render_{kind} yet, so this renders a small "
            f"Python scene with manimgl instead of {scene_file.name}"
        )

    if kind == "still" and via_scenefile:
        @check(f"manimgl-scene still {scene_file.name}")
        def _():
            png = out / "hello.png"
            run([script("manimgl-scene"), "still", str(scene_file), "-s", "hello", "--step", "1", "-o", str(png)])
            return image_has_something_drawn(png)
    elif kind == "video" and via_scenefile:
        @check(f"manimgl-scene render {scene_file.name}")
        def _():
            mp4 = out / "hello.mp4"
            run([script("manimgl-scene"), "render", str(scene_file), "-q", "low", "-o", str(mp4)])
            return video_frames(mp4)
    else:
        scene_py = out / "smoke_scene.py"
        scene_py.write_text(SCENE, encoding="utf-8")
        flags = ["-s"] if kind == "still" else []

        @check(f"manimgl renders a {kind} of a small scene")
        def _():
            run([script("manimgl"), str(scene_py), "Smoke", "-w", "-l", *flags, "--video_dir", str(out)], cwd=out)
            if kind == "still":
                return image_has_something_drawn(out / "Smoke.png")
            return video_frames(out / "Smoke.mp4")


def video_frames(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    probe = run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(path),
    ])
    stream = json.loads(probe.stdout)["streams"][0]
    frames = int(stream["nb_read_frames"])
    if frames < 2:
        raise AssertionError(f"{path} holds {frames} frame(s)")
    return f"{path.name} {stream['width']}x{stream['height']}, {frames} frames"


if __name__ == "__main__":
    sys.exit(main())
