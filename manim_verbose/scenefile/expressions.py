"""
Functions typed by users, such as "sin(x)" or "x**2 / 4", turned into Python callables
without ever handing them to eval: the text is parsed, and only numbers, x, arithmetic and a
fixed list of functions and constants are let through.

OWNER: objects agent. Re-exported by runtime.py.

    safe_function(text, variables=("x",)) -> callable
    check_expression(text, variables=("x",)) -> str | None   # a friendly error message, or None

The parsed formula is turned into a tree of small closures over the math module, so what
runs is only ever arithmetic on floats. That also bounds what a formula can cost: numbers are
floats, so `9**9**9` overflows at once instead of building an enormous integer, and a point
where the formula has no value (log(-1), 1/0, an overflow) gives NaN rather than an error, so
one bad point never stops a render. People who write formulas on paper write `x^2` and `ln x`,
so `^` is read as a power and `ln` as the natural log.

Nothing here imports manimlib, since validate.py checks formulas with check_expression.
"""
from __future__ import annotations

import ast
import difflib
import math
import re
from typing import Any, Callable, Sequence

__all__ = ["safe_function", "check_expression", "SafeFunction", "ExpressionError"]

MAX_LENGTH = 300
MAX_DEPTH = 40
NAN = float("nan")


class ExpressionError(ValueError):
    """A formula which can't be used, with a message meant for the person who typed it."""


def _log(x: float, base: float | None = None) -> float:
    return math.log(x) if base is None else math.log(x, base)


def _sec(x: float) -> float:
    return 1 / math.cos(x)


def _csc(x: float) -> float:
    return 1 / math.sin(x)


def _cot(x: float) -> float:
    return math.cos(x) / math.sin(x)


def _sign(x: float) -> float:
    return float((x > 0) - (x < 0))


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


# name: (function, fewest inputs, most inputs or None for any number)
FUNCTIONS: dict[str, tuple[Callable[..., float], int, int | None]] = {
    "sin": (math.sin, 1, 1),
    "cos": (math.cos, 1, 1),
    "tan": (math.tan, 1, 1),
    "sec": (_sec, 1, 1),
    "csc": (_csc, 1, 1),
    "cot": (_cot, 1, 1),
    "asin": (math.asin, 1, 1),
    "acos": (math.acos, 1, 1),
    "atan": (math.atan, 1, 1),
    "arcsin": (math.asin, 1, 1),
    "arccos": (math.acos, 1, 1),
    "arctan": (math.atan, 1, 1),
    "atan2": (math.atan2, 2, 2),
    "sinh": (math.sinh, 1, 1),
    "cosh": (math.cosh, 1, 1),
    "tanh": (math.tanh, 1, 1),
    "exp": (math.exp, 1, 1),
    "log": (_log, 1, 2),
    "ln": (math.log, 1, 1),
    "log10": (math.log10, 1, 1),
    "log2": (math.log2, 1, 1),
    "sqrt": (math.sqrt, 1, 1),
    "cbrt": (_cbrt, 1, 1),
    "abs": (abs, 1, 1),
    "sign": (_sign, 1, 1),
    "floor": (math.floor, 1, 1),
    "ceil": (math.ceil, 1, 1),
    "min": (min, 2, None),
    "max": (max, 2, None),
}

CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _pow(base: float, exponent: float) -> float:
    # math.pow raises instead of returning a complex number for (-8) ** (1/3)
    return math.pow(base, exponent)


BINARY_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: _pow,
    ast.Mod: lambda a, b: a % b,
}

UNARY_OPS: dict[type, Callable[[float], float]] = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}

OPERATOR_SYMBOLS: dict[type, str] = {
    ast.FloorDiv: "//", ast.MatMult: "@", ast.LShift: "<<", ast.RShift: ">>",
    ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^", ast.Invert: "~",
}

ALLOWED_SUMMARY = "Use numbers, {variables}, + - * / ** ( ) and functions like sin, cos, sqrt, exp, log and abs"

Evaluator = Callable[[Sequence[float]], float]


class SafeFunction:
    """
    A formula of some variables, callable with a number for each. Called with numpy arrays
    it works elementwise. Always gives a float, which is NaN wherever the formula has no value.
    """

    def __init__(self, text: str, variables: Sequence[str], evaluator: Evaluator):
        self.text = text
        self.variables = tuple(variables)
        self._evaluator = evaluator

    def __repr__(self) -> str:
        if self.variables == ("x",):
            return f"safe_function({self.text!r})"
        return f"safe_function({self.text!r}, variables={self.variables!r})"

    def __call__(self, *args: Any) -> Any:
        if len(args) != len(self.variables):
            raise TypeError(f"{self!r} takes {len(self.variables)} input(s), not {len(args)}")
        if any(getattr(a, "ndim", 0) > 0 for a in args):
            import numpy as np
            return np.vectorize(self._scalar, otypes=[float])(*args)
        return self._scalar(*args)

    def _scalar(self, *args: Any) -> float:
        try:
            value = float(self._evaluator([float(a) for a in args]))
        except (ArithmeticError, ValueError, TypeError):
            return NAN
        return value if math.isfinite(value) else NAN


def safe_function(text: str, variables: Sequence[str] = ("x",)) -> SafeFunction:
    """The formula as a callable; raises ExpressionError (a ValueError) saying what is wrong with it."""
    variables = _check_variables(variables)
    tree = _parse(text, variables)
    return SafeFunction(text, variables, _Compiler(variables).compile(tree))


def check_expression(text: str, variables: Sequence[str] = ("x",)) -> str | None:
    """A message saying what is wrong with the formula, in words for its author, or None if it is fine."""
    try:
        safe_function(text, variables)
    except ExpressionError as err:
        return str(err)
    return None


# Parsing

def _check_variables(variables: Sequence[str]) -> tuple[str, ...]:
    if isinstance(variables, str):
        variables = (variables,)
    variables = tuple(variables)
    for name in variables:
        if not isinstance(name, str) or not name.isidentifier() or name in FUNCTIONS or name in CONSTANTS:
            raise ValueError(f"{name!r} can't be a variable of a formula")
    return variables


def _parse(text: Any, variables: tuple[str, ...]) -> ast.expr:
    if not isinstance(text, str):
        raise ExpressionError("A formula has to be written as text, such as sin(x)")
    if not text.strip():
        raise ExpressionError("The formula is empty: write one such as sin(x) or x**2 / 4")
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f"That formula is too long: keep it under {MAX_LENGTH} characters")
    source = text.replace("^", "**").strip()
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as err:
        raise ExpressionError(_syntax_message(source, err, variables)) from None
    except (ValueError, MemoryError, RecursionError):
        # Null bytes, or nesting too deep for the parser itself
        raise ExpressionError("This isn't a formula that can be read: " + ALLOWED_SUMMARY.format(
            variables=_or_list(variables))) from None
    _Checker(variables).visit(tree.body, 0)
    return tree.body


def _syntax_message(source: str, err: SyntaxError, variables: tuple[str, ...]) -> str:
    if re.search(r"(?<![<>=!])=(?!=)", source):
        return "Write only the formula itself, such as sin(x), not y = sin(x)"
    if "|" in source:
        return "Write abs(x) for the size of x, rather than |x|"
    opened, closed = source.count("("), source.count(")")
    if opened != closed:
        return f"The brackets don't match: there are {opened} '(' and {closed} ')'"
    bare_call = re.search(r"\b(" + "|".join(FUNCTIONS) + r")\s+[\w.]", source)
    if bare_call:
        return f"Put a function's input in brackets, as in {bare_call.group(1)}(x)"
    if re.search(r"(\d|\))\s*[A-Za-z_(]", source):
        return "To multiply, write * between the two things, as in 2*x or (x + 1)*(x - 1)"
    where = f" near character {err.offset}" if err.offset else ""
    return f"This isn't a formula that can be read{where}. " + ALLOWED_SUMMARY.format(variables=_or_list(variables))


def _or_list(words: Sequence[str]) -> str:
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


class _Checker:
    """Walks the parsed formula, letting through only what a formula may contain."""

    def __init__(self, variables: tuple[str, ...]):
        self.variables = variables

    def fail(self, message: str):
        raise ExpressionError(message)

    def visit(self, node: ast.AST, depth: int):
        if depth > MAX_DEPTH:
            self.fail("That formula is nested too deeply to be used")
        if isinstance(node, ast.Constant):
            self.check_constant(node.value)
        elif isinstance(node, ast.Name):
            self.check_name(node.id)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in BINARY_OPS:
                self.fail(self.operator_message(node.op))
            self.visit(node.left, depth + 1)
            self.visit(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                self.fail("Comparisons and words like not, and, or can't be used in a formula")
            if type(node.op) not in UNARY_OPS:
                self.fail(self.operator_message(node.op))
            self.visit(node.operand, depth + 1)
        elif isinstance(node, ast.Call):
            self.check_call(node, depth)
        elif isinstance(node, ast.Attribute):
            self.fail("A formula can't use '.' except inside a number, such as 2.5")
        elif isinstance(node, (ast.Subscript, ast.List, ast.Set, ast.Dict)):
            self.fail("Use round brackets ( ) for grouping in a formula, not [ ] or { }")
        elif isinstance(node, ast.Tuple):
            self.fail("A formula has to give one number: commas only go between a function's inputs, as in max(x, 0)")
        elif isinstance(node, (ast.Compare, ast.BoolOp, ast.IfExp)):
            self.fail("Comparisons and words like if, and, or can't be used in a formula")
        elif isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            self.fail("A formula can't contain text in quotes")
        else:
            self.fail("A formula can't contain that. " + self.summary())

    def summary(self) -> str:
        return ALLOWED_SUMMARY.format(variables=_or_list(self.variables))

    def operator_message(self, op: ast.AST) -> str:
        symbol = OPERATOR_SYMBOLS.get(type(op), "that operator")
        if isinstance(op, ast.FloorDiv):
            return "Use floor(a / b) rather than a // b"
        if isinstance(op, ast.BitOr):
            return "Write abs(x) for the size of x, rather than |x|"
        return f"'{symbol}' can't be used in a formula: use + - * / ** and %"

    def check_constant(self, value: Any):
        if isinstance(value, bool) or value is None or value is Ellipsis:
            self.fail(f"'{value}' can't be used in a formula. " + self.summary())
        if isinstance(value, (str, bytes)):
            self.fail("A formula can't contain text in quotes")
        if isinstance(value, complex):
            self.fail("Complex numbers such as 2j can't be used in a formula")
        if not isinstance(value, (int, float)):
            self.fail("A formula can't contain that. " + self.summary())
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            self.fail("That number is too large to be used in a formula")

    def check_name(self, name: str):
        if name in self.variables or name in CONSTANTS:
            return
        if name in FUNCTIONS:
            self.fail(f"'{name}' is a function: give it an input in brackets, as in {name}({self.variables[0] if self.variables else '1'})")
        known = [*self.variables, *CONSTANTS, *FUNCTIONS]
        self.fail(f"'{name}' isn't something a formula can use{_did_you_mean(name, known)}. " + self.summary())

    def check_call(self, node: ast.Call, depth: int):
        if not isinstance(node.func, ast.Name):
            if isinstance(node.func, ast.Attribute):
                self.fail("A formula can't use '.' except inside a number, such as 2.5")
            self.fail("To multiply, write * between the two things, as in 2*(x + 1)")
        name = node.func.id
        if name not in FUNCTIONS:
            if name in self.variables or name in CONSTANTS:
                self.fail(f"'{name}' is a number, not a function: to multiply, write {name}*(...)")
            known = list(FUNCTIONS)
            self.fail(f"'{name}' isn't a function a formula can use{_did_you_mean(name, known)}. " + self.summary())
        if node.keywords:
            self.fail(f"Give {name} its inputs plainly, as in {name}(x), without names or '='")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            self.fail("A formula can't contain '*' in front of a function's input")
        _, fewest, most = FUNCTIONS[name]
        count = len(node.args)
        if count < fewest or (most is not None and count > most):
            self.fail(f"{name} takes {_inputs(fewest, most)}, not {count}")
        for arg in node.args:
            self.visit(arg, depth + 1)


def _inputs(fewest: int, most: int | None) -> str:
    if most is None:
        return f"at least {fewest} inputs"
    if fewest == most:
        return f"{fewest} input" + ("s" if fewest != 1 else "")
    return f"{fewest} or {most} inputs"


def _did_you_mean(word: str, options: Sequence[str]) -> str:
    lowered = {option.lower(): option for option in options}
    if word.lower() in lowered:
        return f" (did you mean '{lowered[word.lower()]}'?)"
    close = difflib.get_close_matches(word, list(options), n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


# Evaluation

class _Compiler:
    """Turns a checked formula into nested closures, evaluated against a list of variable values."""

    def __init__(self, variables: tuple[str, ...]):
        self.index = {name: i for i, name in enumerate(variables)}

    def compile(self, node: ast.expr) -> Evaluator:
        if isinstance(node, ast.Constant):
            value = float(node.value)
            return lambda env: value
        if isinstance(node, ast.Name):
            if node.id in self.index:
                i = self.index[node.id]
                return lambda env: env[i]
            value = CONSTANTS[node.id]
            return lambda env: value
        if isinstance(node, ast.BinOp):
            op = BINARY_OPS[type(node.op)]
            left, right = self.compile(node.left), self.compile(node.right)
            return lambda env: op(left(env), right(env))
        if isinstance(node, ast.UnaryOp):
            uop = UNARY_OPS[type(node.op)]
            operand = self.compile(node.operand)
            return lambda env: uop(operand(env))
        if isinstance(node, ast.Call):
            func = FUNCTIONS[node.func.id][0]
            args = [self.compile(arg) for arg in node.args]
            return lambda env: func(*(arg(env) for arg in args))
        raise ExpressionError("A formula can't contain that")  # the checker has already refused it
