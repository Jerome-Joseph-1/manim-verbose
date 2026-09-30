"""
That a LaTeX formula can't reach the machine it is compiled on: neither reading files, nor
writing them, nor running programs. This matters the moment a scene file might come from
someone other than the person running the render (a shared file, the hosted editor).

Two layers, tested independently:

1. Validation (scenefile/validate.py) rejects the dangerous commands, in every field that
   carries LaTeX, before a formula ever reaches the compiler. These tests are fast and need
   no LaTeX.
2. Even with validation bypassed, the compiler itself (manimlib/utils/tex_file_writing.py,
   run with openin_any=p, openout_any=p and shell escape off) fails to read a secret, fails
   to write outside its own directory, and never runs a program. These call the compile
   directly, past manim's disk cache (``full_tex_to_svg.__wrapped__``), and need LaTeX, so
   they are marked ``render``.
"""
from __future__ import annotations

import os

import pytest

from manim_verbose.scenefile.validate import tex_safety_message, validate_data


# A corpus of known ways a LaTeX formula tries to read or write files or run a program. Each
# should be refused by validation, and, if it somehow reached LaTeX, fail there safely.
ATTACKS: dict[str, str] = {
    "input_abs": r"\input{/etc/passwd}",
    "input_plain": r"\input /etc/passwd",
    "include": r"\include{secret}",
    "includeonly": r"\includeonly{secret}",
    "includegraphics": r"\includegraphics{/etc/passwd}",
    "InputIfFileExists": r"\InputIfFileExists{/etc/passwd}{}{}",
    "lstinputlisting": r"\lstinputlisting{/etc/passwd}",
    "verbatiminput": r"\verbatiminput{/etc/passwd}",
    "openin_read": r"\newread\myread \openin\myread=/etc/passwd \read\myread to\line \line",
    "pdffiledump": r"\pdffiledump offset 0 length 100 {/etc/passwd}",
    "pdffilesize": r"\pdffilesize{/etc/passwd}",
    "openout_write": r"\immediate\openout15=/tmp/pwned.txt \immediate\write15{x}\immediate\closeout15",
    "write18": r"\immediate\write18{touch /tmp/pwned}",
    "usepackage": r"\usepackage{tikz}",
    "documentclass": r"\documentclass{article}",
    "requirepackage": r"\RequirePackage{tikz}",
    "catcode": r"\catcode`\@=11 \@input{/etc/passwd}",
    "makeatletter": r"\makeatletter \@input{/etc/passwd}",
    "csname": r"\csname input\endcsname{/etc/passwd}",
    "expandafter": r"\expandafter\input\expandafter{/etc/passwd}",
    "def_redefine": r"\def\safe{\input{/etc/passwd}}\safe",
    "let_alias": r"\let\grab\input \grab{/etc/passwd}",
    "newcommand": r"\newcommand{\grab}{\input{/etc/passwd}}\grab",
    "filecontents": r"\begin{filecontents}{pwned.tex}\end{filecontents}",
    "special": r"\special{ps: (/etc/passwd) run}",
    "scantokens": r"\scantokens{\input{/etc/passwd}}",
    "caret_escape": r"\csname ^^69nput\endcsname{/etc/passwd}",
    "explsyntax": r"\ExplSyntaxOn \file_input:n {/etc/passwd}",
    "directlua": r"\directlua{os.execute('id')}",
}

# Formulas that must keep working: the sandbox is worthless if it rejects real mathematics.
SAFE_FORMULAS: list[str] = [
    r"e^{i\pi} + 1 = 0",
    r"\int_0^1 x^2 \, dx = \frac{1}{3}",
    r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}",
    r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
    r"\mathbb{R}^3 \to \mathbb{R}^2",
    r"\vec{v} = \langle 1, 2, 3 \rangle",
    r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
    r"\det(A) \neq 0",
    r"\nabla \cdot \vec{F}",
    r"f \colon \mathbb{R} \longrightarrow \mathbb{R}",
    r"\ker T \subseteq \dim V",
    r"\Re z + \Im z",
    r"\left\{ x \mid x > 0 \right\}",
]


@pytest.mark.parametrize("name", list(ATTACKS))
def test_validation_rejects_attack(name: str):
    assert tex_safety_message(ATTACKS[name]) is not None, f"{name} slipped past tex_safety_message"


@pytest.mark.parametrize("formula", SAFE_FORMULAS)
def test_validation_allows_real_mathematics(formula: str):
    assert tex_safety_message(formula) is None, f"real formula wrongly rejected: {formula}"


@pytest.mark.parametrize("name", list(ATTACKS))
def test_attack_is_rejected_in_every_tex_field(name: str):
    """The check has to fire wherever LaTeX is used, not only in a `tex` object."""
    payload = ATTACKS[name]
    documents = {
        "tex": {"id": "eq", "type": "tex", "tex": payload},
        "tex-colors": {"id": "eq", "type": "tex", "tex": "x", "colors": {payload: "RED"}},
        "matrix": {"id": "m", "type": "matrix", "entries": [[payload, "1"]]},
        "vector-label": {"id": "v", "type": "vector", "tip": [1, 1], "label": payload},
        "axes-label": {"id": "ax", "type": "axes", "x_label": payload},
        "brace-label": {"id": "b", "type": "brace", "target": "eq2", "label": payload},
    }
    for where, obj in documents.items():
        extra = [{"id": "eq2", "type": "tex", "tex": "y"}] if where == "brace-label" else []
        doc = {"version": 1, "scenes": [{"id": "s", "objects": [obj, *extra], "steps": []}]}
        _, problems = validate_data(doc)
        messages = [p.message for p in problems if p.severity == "error"]
        assert any("isn't allowed" in m for m in messages), f"{name} not caught in {where}: {messages}"


def test_attack_is_rejected_when_introduced_by_a_change_step():
    doc = {
        "version": 1,
        "scenes": [{
            "id": "s",
            "objects": [{"id": "eq", "type": "tex", "tex": "x"}],
            "steps": [{"do": "change", "target": "eq", "set": {"tex": r"\input{/etc/passwd}"}}],
        }],
    }
    _, problems = validate_data(doc)
    assert any("isn't allowed" in p.message and p.path.startswith("scenes[0].steps[0].set")
               for p in problems), [p.to_json() for p in problems]


def test_message_names_the_offending_command_and_reads_plainly():
    message = tex_safety_message(r"\input{/etc/passwd}")
    assert message is not None
    assert "read files" in message
    assert r"\input" in message
    assert "extra_forbidden" not in message  # never a raw model error


# --- Compile-level: even if validation were bypassed, LaTeX itself must fail safely -------

SECRET = "TOP_SECRET_CANARY_9d1f7"


@pytest.fixture
def sandboxed_latex(tmp_path, monkeypatch):
    """A LaTeX cache in a temporary folder, a secret file to try to steal, and the raw
    (un-cached) compile. Returns (compile_fn, compiler, preamble, secret_path)."""
    from manimlib.config import manim_config
    from manimlib.utils.tex_file_writing import full_tex_to_svg, get_tex_config

    monkeypatch.setitem(manim_config.directories, "latex_cache", str(tmp_path / "latexcache"))
    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET + "\n")
    compiler, preamble = get_tex_config("default")
    return full_tex_to_svg.__wrapped__, compiler, preamble, secret


def _attacks_reading(secret) -> dict[str, str]:
    s = secret.as_posix()
    return {
        "input": r"\input{%s}" % s,
        "openin": r"\newread\r\openin\r=%s \read\r to\x \x" % s,
        "InputIfFileExists": r"\InputIfFileExists{%s}{}{}" % s,
        "pdffiledump": r"\pdffiledump offset 0 length 24 {%s}" % s,
        "catcode_atinput": r"\catcode`\@=11 \@input{%s}" % s,
    }


@pytest.mark.render
@pytest.mark.parametrize("name", ["input", "openin", "InputIfFileExists", "pdffiledump", "catcode_atinput"])
def test_compile_never_leaks_a_file(sandboxed_latex, name):
    from manimlib.utils.tex_file_writing import get_full_tex, LatexError
    compile_fn, compiler, preamble, secret = sandboxed_latex
    body = _attacks_reading(secret)[name]
    tex = get_full_tex(body, preamble)
    try:
        svg = compile_fn(tex, compiler)
    except LatexError:
        return  # refused outright: safe
    assert SECRET not in svg, f"{name} leaked the file's contents into the SVG"


@pytest.mark.render
def test_compile_cannot_write_outside_its_directory(sandboxed_latex, tmp_path):
    from manimlib.utils.tex_file_writing import get_full_tex, LatexError
    compile_fn, compiler, preamble, _ = sandboxed_latex
    target = tmp_path / "written_by_latex.txt"
    body = (r"\immediate\openout15=%s \immediate\write15{PWNED}\immediate\closeout15 ok"
            % target.as_posix())
    tex = get_full_tex(body, preamble)
    try:
        compile_fn(tex, compiler)
    except LatexError:
        pass
    assert not target.exists(), "LaTeX wrote a file outside its working directory"


@pytest.mark.render
def test_compile_cannot_run_a_program(sandboxed_latex, tmp_path):
    from manimlib.utils.tex_file_writing import get_full_tex, LatexError
    compile_fn, compiler, preamble, _ = sandboxed_latex
    marker = tmp_path / "program_ran"
    body = r"\immediate\write18{touch %s} ok" % marker.as_posix()
    tex = get_full_tex(body, preamble)
    try:
        compile_fn(tex, compiler)
    except LatexError:
        pass
    assert not marker.exists(), "shell escape ran a program"


@pytest.mark.render
def test_a_real_formula_still_compiles(sandboxed_latex):
    from manimlib.utils.tex_file_writing import get_full_tex
    compile_fn, compiler, preamble, _ = sandboxed_latex
    tex = get_full_tex(r"$e^{i\pi} + 1 = 0$", preamble)
    svg = compile_fn(tex, compiler)
    assert "<svg" in svg
