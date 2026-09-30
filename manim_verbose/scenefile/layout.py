"""
Placement helpers which generated code calls at runtime: putting a mobject against an edge,
beside another, at a point, arranging a group. Kept as plain functions returning the mobject,
so that generated code reads as one expression per object.

OWNER: objects agent. Re-exported by runtime.py, so generated code can call these unqualified.

    place(mob, at=None, edge=None, next_to=None, side="down", buff=0.25, shift=None) -> mob
"""
from __future__ import annotations
