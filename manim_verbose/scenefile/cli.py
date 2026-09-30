"""
manimgl-scene: scene files from the command line.

    manimgl-scene validate lesson.yaml          check it, and say what is wrong in plain words
    manimgl-scene format lesson.yaml            rewrite it in canonical form (ids filled in, defaults dropped)
    manimgl-scene schema [--write]              print the json schema, or refresh schema.json
    manimgl-scene info lesson.yaml              scenes, steps and how long each runs
    manimgl-scene code lesson.yaml [-s ID]      the Python the file turns into
    manimgl-scene still lesson.yaml -s ID --step N -o frame.png
    manimgl-scene render lesson.yaml [-o out.mp4] [-q low|medium|hd|uhd] [-s ID ...] [-j JOBS]

Exits 0 when all is well, 1 when the file has errors, 2 when the command line was wrong.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manim_verbose.scenefile.files import dump_text, format_of, load_file
from manim_verbose.scenefile.validate import Problem, has_errors


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.run(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manimgl-scene", description="Work with manim scene files")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Check a scene file")
    p.add_argument("file", type=Path)
    p.add_argument("--json", action="store_true", help="Print problems as json")
    p.set_defaults(run=cmd_validate)

    p = sub.add_parser("format", help="Rewrite a scene file in canonical form")
    p.add_argument("file", type=Path)
    p.add_argument("--check", action="store_true", help="Only report whether it would change")
    p.set_defaults(run=cmd_format)

    p = sub.add_parser("schema", help="Print the json schema of the format")
    p.add_argument("--write", action="store_true", help="Refresh the schema.json kept in the package")
    p.set_defaults(run=cmd_schema)

    p = sub.add_parser("info", help="List scenes and steps, with timings")
    p.add_argument("file", type=Path)
    p.set_defaults(run=cmd_info)

    p = sub.add_parser("code", help="Print the Python a scene file turns into")
    p.add_argument("file", type=Path)
    p.add_argument("-s", "--scene", action="append", help="Only this scene (repeatable)")
    p.add_argument("-o", "--output", type=Path, help="Write to this file rather than printing")
    p.set_defaults(run=cmd_code)

    p = sub.add_parser("still", help="Render the frame after a step")
    p.add_argument("file", type=Path)
    p.add_argument("-s", "--scene", required=True)
    p.add_argument("--step", type=int, default=-1, help="Index of the step; -1 for before the first")
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--width", type=int, default=960)
    p.set_defaults(run=cmd_still)

    p = sub.add_parser("render", help="Render the video")
    p.add_argument("file", type=Path)
    p.add_argument("-o", "--output", type=Path, help="Defaults to the scene file's name, as .mp4")
    p.add_argument("-q", "--quality", choices=["low", "medium", "hd", "uhd"], default="hd")
    p.add_argument("-s", "--scene", action="append", help="Only this scene (repeatable)")
    p.add_argument("-j", "--jobs", type=int, help="Scenes to render at once")
    p.set_defaults(run=cmd_render)
    return parser


def report(problems: list[Problem], file: Path) -> None:
    for problem in problems:
        print(f"{file}: {problem}", file=sys.stderr)


def load_or_report(file: Path):
    doc, problems = load_file(file)
    report(problems, file)
    if doc is None or has_errors(problems):
        return None
    return doc


def cmd_validate(args) -> int:
    doc, problems = load_file(args.file)
    if args.json:
        import json
        print(json.dumps([p.to_json() for p in problems], indent=2))
    else:
        report(problems, args.file)
        if not has_errors(problems):
            warnings = sum(p.severity == "warning" for p in problems)
            print(f"{args.file}: ok" + (f", {warnings} warning(s)" if warnings else ""))
    return 1 if doc is None or has_errors(problems) else 0


def cmd_format(args) -> int:
    doc = load_or_report(args.file)
    if doc is None:
        return 1
    new_text = dump_text(doc, format_of(args.file))
    old_text = args.file.read_text(encoding="utf-8")
    if args.check:
        changed = new_text != old_text
        print(f"{args.file}: {'would change' if changed else 'already formatted'}")
        return 1 if changed else 0
    args.file.write_text(new_text, encoding="utf-8")
    return 0


def cmd_schema(args) -> int:
    from manim_verbose.scenefile.schema import SCHEMA_PATH, schema_text, write_schema
    if args.write:
        write_schema()
        print(f"Wrote {SCHEMA_PATH}")
    else:
        sys.stdout.write(schema_text())
    return 0


def cmd_info(args) -> int:
    doc = load_or_report(args.file)
    if doc is None:
        return 1
    from manim_verbose.scenefile import render
    total = 0.0
    for scene in doc.scenes:
        timings = render.timeline(doc, scene.id)
        duration = render.scene_duration(doc, scene.id)
        total += duration
        print(f"{scene.id}  {_clock(duration)}  {len(scene.objects)} objects, {len(scene.steps)} steps"
              + (f"  ({scene.title})" if scene.title else ""))
        for timing, step in zip(timings, scene.steps):
            print(f"    {_clock(timing.start)}  {timing.duration:5.1f}s  {step.do:<12} {step.id}")
    print(f"total  {_clock(total)}")
    return 0


def cmd_code(args) -> int:
    doc = load_or_report(args.file)
    if doc is None:
        return 1
    from manim_verbose.scenefile.codegen import document_to_python
    code = document_to_python(doc, base_dir=args.file.parent.resolve(), scene_ids=args.scene)
    if args.output:
        args.output.write_text(code, encoding="utf-8")
    else:
        sys.stdout.write(code)
    return 0


def cmd_still(args) -> int:
    doc = load_or_report(args.file)
    if doc is None:
        return 1
    from manim_verbose.scenefile.render import RenderError, render_still
    try:
        result = render_still(doc, args.scene, args.step, args.output, width=args.width,
                              base_dir=args.file.parent.resolve())
    except RenderError as err:
        report(err.problems, args.file)
        return 1
    print(f"Wrote {result.path} ({result.width}x{result.height}, {len(result.objects)} objects on screen)")
    return 0


def cmd_render(args) -> int:
    doc = load_or_report(args.file)
    if doc is None:
        return 1
    from manim_verbose.scenefile.render import RenderError, render_video
    output = args.output or args.file.with_suffix(".mp4")

    def progress(fraction: float, message: str) -> None:
        print(f"\r{fraction * 100:5.1f}%  {message:<60}", end="", file=sys.stderr, flush=True)

    try:
        path = render_video(doc, output, quality=args.quality, scene_ids=args.scene, jobs=args.jobs,
                            base_dir=args.file.parent.resolve(), progress=progress)
    except RenderError as err:
        print(file=sys.stderr)
        report(err.problems, args.file)
        return 1
    print(f"\nWrote {path}", file=sys.stderr)
    return 0


def _clock(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes):2d}:{secs:04.1f}"


if __name__ == "__main__":
    sys.exit(main())
