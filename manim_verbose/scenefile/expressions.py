"""
Functions typed by users, such as "sin(x)" or "x**2 / 4", turned into Python callables
without ever handing them to eval: the text is parsed, and only numbers, x, arithmetic and a
fixed list of functions and constants are let through.

OWNER: objects agent. Re-exported by runtime.py.

    safe_function(text, variables=("x",)) -> callable
    check_expression(text, variables=("x",)) -> str | None   # a friendly error message, or None
"""
from __future__ import annotations
