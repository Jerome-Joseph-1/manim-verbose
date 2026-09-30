"""
That a formula which fails to compile is reported, rather than rendered as whatever compiled
before it. LaTeX used to work in one shared working.tex, and a DVI left from the last good
formula was read in place of the one which failed to build.
"""
from __future__ import annotations

import pytest

from manimlib.utils.tex_file_writing import LatexError, full_tex_to_svg

GOOD = r"\documentclass{article}\begin{document}$x^2$\end{document}"
BAD = r"\documentclass{article}\begin{document}$\frac{a}{$\end{document}"


@pytest.mark.render
def test_failed_compile_after_a_good_one_raises():
    assert "<svg" in full_tex_to_svg(GOOD)
    with pytest.raises(LatexError):
        full_tex_to_svg(BAD)


@pytest.mark.render
def test_compiles_leave_nothing_behind(tmp_path, monkeypatch):
    from manimlib.config import manim_config
    monkeypatch.setitem(manim_config.directories, "latex_cache", str(tmp_path))
    full_tex_to_svg(GOOD)
    with pytest.raises(LatexError):
        full_tex_to_svg(BAD)
    assert list(tmp_path.iterdir()) == []
