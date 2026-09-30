"""
That formulas typed by users are read without ever being run as Python: what is allowed
gives the right numbers, what isn't is refused with a message its author can act on, a point
where the formula has no value gives NaN, and nothing typed, however hostile, gets anything
executed. The last is checked with an audit hook, which sees every exec and eval, every
process started and every file opened in the process, whoever asks for them.
"""
from __future__ import annotations

import math
import sys
import time

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from manim_verbose.scenefile.expressions import (
    CONSTANTS, FUNCTIONS, MAX_LENGTH, ExpressionError, SafeFunction, check_expression, safe_function,
)


# What is allowed

@pytest.mark.parametrize("text, x, expected", [
    ("x", 3, 3),
    ("2", 7, 2),
    ("-x", 3, -3),
    ("+x", 3, 3),
    ("x + 1", 2, 3),
    ("x - 1", 2, 1),
    ("3 * x", 2, 6),
    ("x / 4", 2, 0.5),
    ("x ** 2", 3, 9),
    ("x^2", 3, 9),
    ("x^2 + 1", 3, 10),
    ("2^-x", 1, 0.5),
    ("-x^2", 3, -9),
    ("x % 3", 7, 1),
    ("(x + 1) * (x - 1)", 3, 8),
    ("((((x))))", 5, 5),
    ("1e3 * x", 2, 2000),
    ("1_000 + x", 1, 1001),
    (".5 * x", 4, 2),
    ("sin(x)", math.pi / 2, 1),
    ("cos(x)", 0, 1),
    ("tan(x)", math.pi / 4, 1),
    ("sec(x)", 0, 1),
    ("csc(x)", math.pi / 2, 1),
    ("cot(x)", math.pi / 4, 1),
    ("asin(x)", 1, math.pi / 2),
    ("acos(x)", 1, 0),
    ("atan(x)", 1, math.pi / 4),
    ("arcsin(x)", 1, math.pi / 2),
    ("arccos(x)", 0, math.pi / 2),
    ("arctan(x)", 0, 0),
    ("atan2(x, 1)", 1, math.pi / 4),
    ("sinh(x)", 0, 0),
    ("cosh(x)", 0, 1),
    ("tanh(x)", 0, 0),
    ("exp(x)", 1, math.e),
    ("log(x)", math.e, 1),
    ("log(x, 2)", 8, 3),
    ("ln(x)", math.e, 1),
    ("log10(x)", 1000, 3),
    ("log2(x)", 8, 3),
    ("sqrt(x)", 9, 3),
    ("cbrt(x)", -8, -2),
    ("abs(x)", -2, 2),
    ("sign(x)", -2, -1),
    ("floor(x)", 2.7, 2),
    ("ceil(x)", 2.2, 3),
    ("min(x, 1)", 3, 1),
    ("max(x, 1, 5)", 3, 5),
    ("pi * x", 2, 2 * math.pi),
    ("e^x", 1, math.e),
    ("tau", 0, math.tau),
    ("x**2 / 4", 2, 1),
    ("sin(x)^2 + cos(x)^2", 0.7, 1),
    ("  x  ", 1, 1),
])
def test_accepted(text, x, expected):
    assert check_expression(text) is None
    f = safe_function(text)
    assert isinstance(f, SafeFunction)
    assert f(x) == pytest.approx(expected)


def test_several_variables():
    f = safe_function("x * y + t", variables=("x", "y", "t"))
    assert f(2, 3, 1) == 7
    assert check_expression("x + z", variables=("x", "y")) is not None
    assert "'z' isn't something" in check_expression("x + z", variables=("x", "y"))


@pytest.mark.parametrize("variables", [("sin",), ("pi",), ("1x",), ("",), ("a b",)])
def test_bad_variable_names_are_a_programming_error(variables):
    with pytest.raises(ValueError):
        safe_function("1", variables=variables)


def test_calling_with_the_wrong_number_of_inputs_is_a_programming_error():
    with pytest.raises(TypeError):
        safe_function("x")(1, 2)


def test_arrays_work_elementwise():
    f = safe_function("sqrt(x)")
    out = f(np.array([4.0, -1.0, 0.0]))
    assert out.shape == (3,)
    assert out[0] == 2 and math.isnan(out[1]) and out[2] == 0
    assert f(np.float64(9)) == 3


def test_repr_says_what_it_is():
    assert repr(safe_function("sin(x)")) == "safe_function('sin(x)')"
    assert "variables" in repr(safe_function("x+y", variables=("x", "y")))


# Where a formula has no value

@pytest.mark.parametrize("text, x", [
    ("log(x)", -1),
    ("log(x)", 0),
    ("1 / x", 0),
    ("x % 0", 1),
    ("sqrt(x)", -1),
    ("asin(x)", 2),
    ("(-8) ^ (1/3)", 0),
    ("x ^ -1", 0),
    ("exp(x)", 1000),
    ("10 ** x", 400),
    ("1e308 * x", 10),
    ("9**9**9", 0),
    ("floor(x)", float("inf")),
    ("tan(x) * 0", float("nan")),
    ("cot(x)", 0),
    ("log(x, 1)", 5),
])
def test_no_value_gives_nan(text, x):
    assert check_expression(text) is None
    assert math.isnan(safe_function(text)(x))


@pytest.mark.parametrize("text", ["9**9**9**9", "(9**9)**(9**9)", "2**2**2**2**2**2**2**2", "10^10^10^10"])
def test_exponent_bombs_are_cheap(text):
    f = safe_function(text)
    start = time.perf_counter()
    for x in range(100):
        f(x)
    assert time.perf_counter() - start < 0.5


# What isn't

@pytest.mark.parametrize("text, message", [
    ("", "The formula is empty"),
    ("   ", "The formula is empty"),
    ("x" * (MAX_LENGTH + 1), f"under {MAX_LENGTH} characters"),
    ("2x", "To multiply, write *"),
    ("2(x + 1)", "To multiply, write *"),
    ("(x + 1)(x - 1)", "To multiply, write *"),
    ("x(2)", "'x' is a number, not a function"),
    ("pi(2)", "'pi' is a number, not a function"),
    ("sin x", "Put a function's input in brackets, as in sin(x)"),
    ("y = x^2", "not y = sin(x)"),
    ("|x|", "abs(x)"),
    ("x // 2", "floor(a / b)"),
    ("sin(x", "The brackets don't match"),
    ("x)", "The brackets don't match"),
    ("sin", "'sin' is a function"),
    ("foo(x)", "'foo' isn't a function a formula can use"),
    ("Sin(x)", "did you mean 'sin'"),
    ("sine(x)", "did you mean 'sin'"),
    ("sqr(x)", "did you mean 'sqrt'"),
    ("PI * x", "did you mean 'pi'"),
    ("y", "'y' isn't something a formula can use"),
    ("X + 1", "did you mean 'x'"),
    ("sin(x, 2)", "sin takes 1 input, not 2"),
    ("atan2(x)", "atan2 takes 2 inputs, not 1"),
    ("log(x, 2, 3)", "log takes 1 or 2 inputs, not 3"),
    ("max(x)", "max takes at least 2 inputs, not 1"),
    ("sin(x=1)", "without names or '='"),
    ("max(*x)", "'*' in front of a function's input"),
    ("x.real", "can't use '.'"),
    ("(1).real", "can't use '.'"),
    ("x.__class__", "can't use '.'"),
    ("math.sin(x)", "can't use '.'"),
    ("[x]", "round brackets"),
    ("[x][0]", "round brackets"),
    ("x[0]", "round brackets"),
    ("{x}", "round brackets"),
    ("{'a': x}", "round brackets"),
    ("(x, 1)", "has to give one number"),
    ("'x'", "text in quotes"),
    ('"x"', "text in quotes"),
    ("f'{x}'", "text in quotes"),
    ("b'x'", "text in quotes"),
    ("True", "'True' can't be used"),
    ("None", "'None' can't be used"),
    ("...", "'Ellipsis' can't be used"),
    ("2j", "Complex numbers"),
    ("1e400", "too large"),
    ("9" * 290 + "e20", "too large"),
    ("x < 1", "Comparisons"),
    ("x == 1", "Comparisons"),
    ("x and 1", "Comparisons"),
    ("not x", "Comparisons"),
    ("x if x else 1", "Comparisons"),
    ("x @ x", "'@' can't be used"),
    ("x << 1", "'<<' can't be used"),
    ("x & 1", "'&' can't be used"),
    ("~x", "'~' can't be used"),
    ("lambda: 1", "can't contain that"),
    ("[i for i in x]", "can't contain that"),
    ("(i for i in x)", "can't contain that"),
    ("(y := 1)", "can't contain that"),
    ("await x", "can't contain that"),
    ("yield x", "isn't a formula that can be read"),
    ("__import__('os').system('ls')", "can't use '.'"),
    ("__import__('os')", "'__import__' isn't a function"),
    ("eval('1')", "'eval' isn't a function"),
    ("exec('1')", "'exec' isn't a function"),
    ("open('/etc/passwd')", "'open' isn't a function"),
    ("globals()", "'globals' isn't a function"),
    ("().__class__.__bases__[0].__subclasses__()", "can't use '.'"),
    ("x; import os", "isn't a formula that can be read"),
    ("import os", "isn't a formula that can be read"),
    ("x\nimport os", "isn't a formula that can be read"),
    ("x\x00", "isn't a formula that can be read"),
    ("-" * 60 + "x", "nested too deeply"),
    ("sin(" * 45 + "x" + ")" * 45, "nested too deeply"),
    ("#x", "isn't a formula that can be read"),
])
def test_rejected(text, message):
    problem = check_expression(text)
    assert problem is not None, text
    assert message in problem, problem
    with pytest.raises(ExpressionError) as err:
        safe_function(text)
    assert str(err.value) == problem
    assert isinstance(err.value, ValueError)


@pytest.mark.parametrize("value", [None, 3, 2.5, ["x"], b"x"])
def test_text_that_isnt_text_is_refused(value):
    assert check_expression(value) == "A formula has to be written as text, such as sin(x)"


def test_every_listed_function_and_constant_works():
    for name, (_, fewest, _) in FUNCTIONS.items():
        text = f"{name}({', '.join(['0.5'] * fewest)})"
        assert check_expression(text) is None, text
        assert isinstance(safe_function(text)(0), float)
    for name, value in CONSTANTS.items():
        assert safe_function(name)(0) == value


def test_messages_name_the_variables():
    assert "Use numbers, x, + - * /" in check_expression("y")
    assert "Use numbers, x and t" in check_expression("y", variables=("x", "t"))


# Nothing typed is ever run

class Watch:
    """
    Records the audit events which would mean code or a program was run, while switched
    on. Audit hooks can't be removed, so one hook is added for the whole test session and
    switched on only around the calls under test.
    """
    EVENTS = ("exec", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "subprocess.Popen", "open", "import")
    on = False
    seen: list[tuple[str, str]] = []

    @classmethod
    def hook(cls, event, args):
        if cls.on and event.startswith(cls.EVENTS):
            cls.seen.append((event, repr(args)[:80]))


sys.addaudithook(Watch.hook)


def watching(action):
    Watch.seen.clear()
    Watch.on = True
    try:
        return action()
    finally:
        Watch.on = False


def evaluate_everywhere(text):
    """Check, build and call a formula at a few points, as a render would, never raising."""
    problem = check_expression(text)
    try:
        f = safe_function(text)
    except ExpressionError as err:
        assert problem == str(err)
        return None
    assert problem is None
    values = [f(x) for x in (-2.5, -1, 0, 0.5, 1, 3, 1e6)]
    assert all(isinstance(v, float) for v in values)
    assert all(math.isnan(v) or math.isfinite(v) for v in values)
    return values


def test_the_watch_sees_what_it_should():
    assert watching(lambda: eval("1 + 1")) == 2
    assert any(event == "exec" for event, _ in Watch.seen)


HOSTILE = [
    "__import__('os').system('touch /tmp/pwned')",
    "exec('import os')",
    "eval('1+1')",
    "open('/etc/passwd').read()",
    "(lambda: 1)()",
    "[c for c in ().__class__.__base__.__subclasses__()]",
    "x.__globals__",
    "breakpoint()",
    "compile('1', '', 'eval')",
    "sin.__self__",
    "sin(x).__class__",
]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_formulas_run_nothing(text):
    assert watching(lambda: evaluate_everywhere(text)) is None
    assert Watch.seen == []


FORMULA_ALPHABET = "x0123456789.+-*/%^() ,e" + "sincotaqrlgbfmp"
FORMULA_PIECES = st.sampled_from([
    "x", "2", "0.5", "pi", "e", "+", "-", "*", "/", "**", "^", "%", "(", ")", ",",
    *(f"{name}(" for name in FUNCTIONS), "1e5", " ", "9", "0",
])


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text(max_size=80))
def test_fuzz_any_text(text):
    watching(lambda: evaluate_everywhere(text))
    assert Watch.seen == []


@settings(max_examples=400, deadline=None)
@given(st.text(alphabet=FORMULA_ALPHABET, max_size=40))
def test_fuzz_formula_like_text(text):
    watching(lambda: evaluate_everywhere(text))
    assert Watch.seen == []


@settings(max_examples=400, deadline=None)
@given(st.lists(FORMULA_PIECES, max_size=25).map("".join))
def test_fuzz_formula_pieces(text):
    watching(lambda: evaluate_everywhere(text))
    assert Watch.seen == []


def formulas(depth: int = 3):
    """Formulas which are valid by construction, from a small grammar."""
    leaf = st.sampled_from(["x", "1", "2.5", "pi", "e", "0", "-3", "1e3"])
    if depth == 0:
        return leaf
    inner = formulas(depth - 1)
    return st.one_of(
        leaf,
        st.tuples(inner, st.sampled_from(["+", "-", "*", "/", "**", "^", "%"]), inner).map(lambda t: f"({t[0]} {t[1]} {t[2]})"),
        st.tuples(st.sampled_from([n for n, (_, lo, _) in FUNCTIONS.items() if lo == 1]), inner).map(lambda t: f"{t[0]}({t[1]})"),
        st.tuples(st.sampled_from(["min", "max", "atan2", "log"]), inner, inner).map(lambda t: f"{t[0]}({t[1]}, {t[2]})"),
        inner.map(lambda s: f"-{s}"),
    )


@settings(max_examples=400, deadline=None)
@given(formulas(), st.floats(allow_nan=True, allow_infinity=True))
def test_valid_formulas_always_give_a_float(text, x):
    assert check_expression(text) is None, text
    f = safe_function(text)
    value = watching(lambda: f(x))
    assert Watch.seen == []
    assert isinstance(value, float)
    assert math.isnan(value) or math.isfinite(value)
