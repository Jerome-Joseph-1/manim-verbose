"""
How much the editor's server takes on at once, and how long it lets a render run.

The server only ever listens on the user's own machine by default, so these are not there to
fend off attackers so much as to keep one runaway request (a pasted ten megabyte document, a
render stuck in a loop) from making the editor stop answering. docs/editor/server-api.md lists
the same values; keep the two in step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from manim_verbose.scenefile.validate import Problem


@dataclass(frozen=True)
class Limits:
    max_body_bytes: int = 5 * 1024 * 1024
    max_asset_bytes: int = 10 * 1024 * 1024  # an uploaded picture
    max_scenes: int = 100
    max_objects: int = 500              # per scene
    max_steps: int = 1000               # per scene, counting the steps inside `together`
    min_still_width: int = 64
    max_still_width: int = 3840
    still_timeout: float = 60.0         # seconds
    clip_timeout: float = 300.0
    export_timeout: float = 4 * 3600.0
    worker_start_timeout: float = 120.0
    cancel_grace: float = 5.0           # after this long a cancelled export's process is killed
    job_workers: int = 2                # processes for clips and exports, apart from the one for stills
    max_pending_exports: int = 10       # queued or running
    finished_jobs_kept: int = 100
    cached_stills: int = 2000           # files kept in the output folder
    cached_clips: int = 200


def size_problems(data: Any, limits: Limits) -> list[Problem]:
    """
    Problems for a document, as plain data, which is bigger than the server will handle.
    This runs before the models see the document, so it only counts, and trusts nothing
    about the shape of what it is given.
    """
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        return []
    scenes = data["scenes"]
    problems = []
    if len(scenes) > limits.max_scenes:
        problems.append(Problem(
            f"This video has {len(scenes)} scenes, and the editor handles at most {limits.max_scenes}. "
            "Split it into more than one file",
            ["scenes"],
        ))
        return problems
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        scene_id = scene.get("id") if isinstance(scene.get("id"), str) else None
        objects = scene.get("objects")
        if isinstance(objects, list) and len(objects) > limits.max_objects:
            problems.append(Problem(
                f"This scene has {len(objects)} objects, and the editor handles at most {limits.max_objects} "
                "in one scene. Split it into more than one scene",
                ["scenes", index, "objects"], scene_id=scene_id,
            ))
        steps = _count_steps(scene.get("steps"))
        if steps > limits.max_steps:
            problems.append(Problem(
                f"This scene has {steps} steps, and the editor handles at most {limits.max_steps} "
                "in one scene. Split it into more than one scene",
                ["scenes", index, "steps"], scene_id=scene_id,
            ))
    return problems


def _count_steps(steps: Any, depth: int = 0) -> int:
    if not isinstance(steps, list) or depth > 20:
        return 0
    count = len(steps)
    for step in steps:
        if isinstance(step, dict):
            count += _count_steps(step.get("steps"), depth + 1)
    return count
