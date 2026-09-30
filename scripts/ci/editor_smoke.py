"""
The editor, started the way docs/editor/INSTALL.md tells people to start it, answering as the
browser would ask it: run with the Python manimgl is installed into.

    python scripts/ci/editor_smoke.py WORKDIR [--port 8765] [--formula] [--clip]

Starts `manimgl-editor WORKDIR/video.yaml --no-browser` (a new file, so the starter document),
then checks /api/health, that / serves the built editor rather than the page saying it isn't
built, and that /api/still draws the starter's first step into a PNG it can fetch. --formula
also asks for a still of a document with a LaTeX formula in it, which is what finds a LaTeX
set up by `manimgl-doctor --install-tex` not being found; --clip a preview clip, which needs
ffmpeg. release.yml runs it on Linux; it is also how to try an install by hand.

Exits 0 when everything answered as it should, 1 otherwise, printing what it saw either way.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import sysconfig
import time
import urllib.error
import urllib.request
from pathlib import Path

# A formula never typeset before, so that manim's cache of LaTeX output can't stand in for LaTeX
N = random.randint(100, 999999)
FORMULA_DOCUMENT = {
    "version": 1,
    "title": "Formula check",
    "scenes": [{
        "id": "formula",
        "objects": [{"id": "sum", "type": "tex", "tex": f"\\sum_{{k=1}}^{{{N}}} k = \\frac{{{N}({N}+1)}}{{2}}"}],
        "steps": [{"do": "show", "target": "sum"}],
    }],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--formula", action="store_true", help="also render a LaTeX formula")
    parser.add_argument("--clip", action="store_true", help="also render a preview clip (needs ffmpeg)")
    args = parser.parse_args()
    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    scene_file = workdir / "video.yaml"
    scene_file.unlink(missing_ok=True)

    editor = shutil.which("manimgl-editor", path=sysconfig.get_path("scripts")) or shutil.which("manimgl-editor")
    command = [editor] if editor else [sys.executable, "-m", "manim_verbose.editor"]
    command += [str(scene_file), "--no-browser", "--port", str(args.port), "--output-dir", str(workdir / "out")]
    print("Starting:", " ".join(command), flush=True)
    log = open(workdir / "editor.log", "w", encoding="utf-8")
    server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=workdir)
    base = f"http://127.0.0.1:{args.port}"
    failures = []

    def call(path: str, body: dict | None = None, timeout: float = 600) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}: {detail}", flush=True)
        if not ok:
            failures.append(name)

    try:
        started = time.monotonic()
        health = None
        while time.monotonic() - started < 120 and server.poll() is None:
            try:
                status, body = call("/api/health", timeout=5)
                if status == 200:
                    health = json.loads(body)
                    break
            except OSError:
                pass
            time.sleep(0.5)
        check("the editor starts and answers /api/health", health is not None and health.get("ok") is True,
              f"{health} after {time.monotonic() - started:.1f}s" if health else f"no answer (exit status {server.poll()})")
        if health is None:
            return 1
        check("a new scene file is created from the starter", scene_file.is_file(), str(scene_file))

        status, page = call("/")
        text = page.decode("utf-8", errors="replace")
        check("/ serves the built editor", status == 200 and "npm run build" not in text and "<script" in text,
              f"{status}, {len(page)} bytes")

        status, body = call("/api/document")
        document = json.loads(body).get("document") if status == 200 else None
        check("/api/document", document is not None, f"{status}, {len(document['scenes']) if document else 0} scene(s)")
        if document:
            still(call, check, document, document["scenes"][0]["id"], workdir / "starter.png", "the starter's first step")
        if args.formula:
            still(call, check, FORMULA_DOCUMENT, "formula", workdir / "formula.png", "a LaTeX formula")
        if args.clip and document:
            scene_id = document["scenes"][0]["id"]
            status, body = call("/api/clip", {"document": document, "scene_id": scene_id, "start_step": 0, "end_step": 0})
            answer = json.loads(body)
            video_ok = status == 200 and answer.get("video_url")
            detail = f"{status} {answer.get('problems') or ''}"
            if video_ok:
                status, video = call(answer["video_url"])
                video_ok = status == 200 and len(video) > 1000
                detail = f"{answer['video_url']}, {len(video)} bytes"
            check("/api/clip makes a preview clip", bool(video_ok), detail)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    if failures:
        print(f"\n{len(failures)} check(s) failed; the editor's log:\n" + (workdir / "editor.log").read_text(errors="replace")[-4000:])
        return 1
    print("\nThe editor works")
    return 0


def still(call, check, document: dict, scene_id: str, out: Path, what: str) -> None:
    started = time.monotonic()
    status, body = call("/api/still", {"document": document, "scene_id": scene_id, "step_index": 0, "width": 480})
    answer = json.loads(body)
    errors = [p for p in answer.get("problems", []) if p.get("severity") == "error"]
    if status != 200 or not answer.get("image_url") or errors:
        check(f"/api/still draws {what}", False, f"{status} {answer}")
        return
    status, png = call(answer["image_url"])
    out.write_bytes(png)
    ok = status == 200 and png.startswith(b"\x89PNG") and bool(answer.get("objects"))
    check(f"/api/still draws {what}", ok,
          f"{answer['width']}x{answer['height']}, {len(answer.get('objects', []))} object(s), "
          f"{len(png)} bytes in {time.monotonic() - started:.1f}s -> {out}")


if __name__ == "__main__":
    sys.exit(main())
