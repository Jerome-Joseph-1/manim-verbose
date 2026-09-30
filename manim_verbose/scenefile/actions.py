"""
Steps to code: for each kind of step, the lines of Python which play it, inside the scene's
construct method.

OWNER: steps/render agent.

    step_lines(step, ctx) -> list[str]
        The body of the step's `with self.step(...)` block. May update ctx.objects (a change
        step records the object's new values there).
    default_run_time(step, ctx) -> float
        How long a step takes when it doesn't say. timeline() in render.py uses the same
        numbers, so durations can be known without rendering anything.
"""
from __future__ import annotations
