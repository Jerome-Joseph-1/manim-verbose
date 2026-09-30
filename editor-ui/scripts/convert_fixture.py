"""
Turn a scene file (YAML) into the JSON the editor server's API sends: the same data, with
placements written out in full ({"edge": "top"} rather than `top`) and every step given an
id. Used to make the mock server's large performance fixture from the ten minute example:

    PYTHONPATH=.. python scripts/convert_fixture.py ../examples/eola_vectors/vectors.yaml mock/fixtures/eola_vectors.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from manim_verbose.scenefile.files import format_of, parse_text


def full_placement(value):
    if isinstance(value, str):
        return {"edge": value}
    if isinstance(value, list):
        return {"at": value}
    return value


def expand(node, key=None):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("place", "to") and v is not None:
                v = full_placement(v)
            out[k] = expand(v, k)
        return out
    if isinstance(node, list):
        return [expand(item, key) for item in node]
    return node


def iter_steps(steps):
    for step in steps or []:
        yield step
        if step.get("do") == "together":
            yield from iter_steps(step.get("steps"))


def assign_ids(doc):
    taken = {s["id"] for scene in doc["scenes"] for s in iter_steps(scene.get("steps")) if s.get("id")}
    for scene in doc["scenes"]:
        count = 0
        for step in iter_steps(scene.get("steps")):
            if not step.get("id"):
                while True:
                    count += 1
                    candidate = f"{scene['id']}_{count}"
                    if candidate not in taken:
                        break
                step["id"] = candidate
                taken.add(candidate)
    return doc


def main(source: str, target: str) -> None:
    data, problems = parse_text(Path(source).read_text(encoding="utf-8"), format_of(source))
    if problems:
        raise SystemExit("\n".join(str(p) for p in problems))
    doc = assign_ids(expand(data))
    Path(target).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    steps = sum(1 for scene in doc["scenes"] for _ in iter_steps(scene.get("steps")))
    print(f"Wrote {target}: {len(doc['scenes'])} scenes, {steps} steps")


if __name__ == "__main__":
    main(*sys.argv[1:3])
