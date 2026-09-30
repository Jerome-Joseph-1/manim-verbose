"""
That the TeX installed here can do what manim asks of it: compile a document put together the
way manimlib.utils.tex_file_writing puts one together, with the preamble of the default
template in manimlib/tex_templates.yml, and turn it into an SVG with dvisvgm, every glyph an
outline.

    python scripts/ci/check_tex.py                 compile and convert; exit 1 saying what failed
    python scripts/ci/check_tex.py --provenance    also say which Debian package every file read
                                                   came from, and check each is one that
                                                   scripts/ci/apt/tex.txt installs

CI runs it straight after installing TeX, so that a missing package is reported as that rather
than as a render test failing somewhere further on. --provenance is for changing the package
list on a machine with more of TeX Live installed than CI has: it shows the list is enough
without needing a clean machine to try it on.

The document uses something from every package the preamble loads, at more than one size,
since a font missing for a subscript is still a font missing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "manimlib" / "tex_templates.yml"
TEX_PACKAGES = Path(__file__).resolve().parent / "apt" / "tex.txt"

# Something from every package of the default preamble. What manim writes is mostly an align*
# of mathematics, see Tex.tex_environment, with text inside it now and then.
BODY = r"""
\begin{align*}
e^{i\pi} + 1 &= 0 \\
\mathds{R}^2 \ni \vec{v} &= \mqty(x \\ y), \quad \mathbb{Z} \subset \mathds{1} \\
\mathscr{L}\{f\}(s) &= \int_0^\infty f(t)\, e^{-st} \dd{t} \\
\dv{x} \qty(\frac{a}{b}) &\minus \sum_{n=1}^{\infty} \frac{1}{n^2}
    \quad \text{text in math}_{\text{and smaller}^{\text{and smaller}}}
\end{align*}
{\color{red} T1 text: caf\'e, na\"ive, \textdegree, --- ``quotes''}
\textipa{[D@ "kwIk]} {\calligra Calligraphy} \smiley\ \ding{52}
\textlarger{larger} {\Large Large text} {\tiny tiny text}
"""

# Where to find a LaTeX file on Ubuntu, for saying what to install when one is missing
KNOWN_HOMES = {
    "standalone.cls": "texlive-latex-extra",
    "preview.sty": "preview-latex-style (a dependency of texlive-latex-extra)",
    "babel.sty": "texlive-latex-base",
    "english.ldf": "texlive-latex-base",
    "amsmath.sty": "texlive-latex-base",
    "amssymb.sty": "texlive-base",
    "dsfont.sty": "texlive-fonts-extra",
    "setspace.sty": "texlive-latex-recommended",
    "tipa.sty": "tipa",
    "relsize.sty": "texlive-latex-extra",
    "mathrsfs.sty": "texlive-latex-recommended",
    "calligra.sty": "texlive-latex-extra",
    "wasysym.sty": "texlive-fonts-recommended",
    "ragged2e.sty": "texlive-latex-recommended",
    "physics.sty": "texlive-science",
    "xcolor.sty": "texlive-latex-recommended",
    "microtype.sty": "texlive-latex-recommended",
    "pifont.sty": "texlive-latex-base",
}


def default_preamble() -> str:
    import yaml
    with open(TEMPLATES, encoding="utf-8") as file:
        return yaml.safe_load(file)["default"]["preamble"]


def full_tex(body: str, preamble: str) -> str:
    """As manimlib.utils.tex_file_writing.get_full_tex, kept apart so as not to import manimlib"""
    return "\n\n".join((
        "\\documentclass[preview]{standalone}",
        preamble,
        "\\begin{document}",
        body,
        "\\end{document}",
    )) + "\n"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, errors="replace", **kwargs)


def compile_document(work: Path, provenance: bool) -> tuple[list[str], set[Path]]:
    """Problems found, and every file TeX and dvisvgm read"""
    problems: list[str] = []
    read: set[Path] = set()
    for tool in ("latex", "dvisvgm"):
        if shutil.which(tool) is None:
            problems.append(f"`{tool}` is not on PATH")
    if problems:
        return problems, read

    env = dict(os.environ)
    if provenance:
        # kpathsea reads texfonts.map, for other names a font might go by, whenever looking
        # for a file by its own name fails, as dvisvgm does asking for an .ofm before the
        # .tfm. It comes with texlive-plain-generic, which CI leaves out along with every
        # other Recommends, so hide it here too: what is checked is then what CI will do.
        # The same path finds the font maps dvisvgm reads, so keep the directories of those.
        maps = run(["kpsewhich", "ps2pk.map", "pdftex.map", "dvipdfm.map", "psfonts.map"]).stdout.split()
        env["TEXFONTMAPS"] = os.pathsep.join(sorted({str(Path(m).parent) for m in maps}))

    tex_path = work / "check.tex"
    tex_path.write_text(full_tex(BODY, default_preamble()), encoding="utf-8")
    # The command manim runs, see full_tex_to_svg, with -recorder to list what was read
    latex = run(
        ["latex", "-interaction=batchmode", "-halt-on-error", "-recorder",
         f"-output-directory={work}", tex_path.name],
        cwd=work, env=env,
    )
    dvi = tex_path.with_suffix(".dvi")
    log = tex_path.with_suffix(".log")
    log_text = log.read_text(errors="replace") if log.exists() else ""
    if latex.returncode != 0 or not dvi.exists():
        for name in re.findall(r"File `([^']+)' not found", log_text):
            home = KNOWN_HOMES.get(name)
            problems.append(f"LaTeX can't find {name}" + (f"; on Ubuntu it is in {home}" if home else ""))
        if not problems:
            errors = re.findall(r"^! .*(?:\n.*){0,2}", log_text, flags=re.MULTILINE)
            problems.append("latex failed: " + ("\n".join(errors[:3]) or latex.stdout[-2000:]))
        return problems, read
    fls = tex_path.with_suffix(".fls")
    for line in fls.read_text(errors="replace").splitlines():
        if line.startswith("INPUT "):
            path = Path(line[len("INPUT "):])
            read.add(path if path.is_absolute() else work / path)

    # As manim runs it, but with warnings shown, and with Metafont kept out of it: without a
    # Type 1 font, dvisvgm would quietly have mktexpk make a bitmap one, and a glyph would go
    # missing from the outlines
    env.update(MKTEXPK="0", MKTEXTFM="0")
    if provenance:
        env["KPATHSEA_DEBUG"] = "32"  # every search, and what it found
    svg = run(["dvisvgm", str(dvi), "-n", "-v", "3", "--stdout"], env=env)
    if svg.returncode != 0:
        problems.append(f"dvisvgm failed: {svg.stderr.strip()[-2000:]}")
        return problems, read
    tex_path.with_suffix(".svg").write_text(svg.stdout, encoding="utf-8")
    for line in svg.stderr.splitlines():
        if line.startswith("kdebug:"):
            found = re.match(r"kdebug:returning from (?:generic )?search\(.*?\) =>(.*)", line)
            if found:
                read.update(Path(p) for p in found.group(1).split())
        elif "WARNING" in line or "not found" in line or "cannot" in line.lower():
            problems.append(f"dvisvgm: {line.strip()}")
    paths = svg.stdout.count("<path")
    if paths < 50:
        problems.append(f"the SVG holds only {paths} paths; every glyph should have been one")
    if "<text" in svg.stdout:
        problems.append("the SVG holds <text> elements, where -n should have made every glyph a path")
    if not problems:
        print(f"Compiled the default template's preamble and converted it: {paths} paths")
    return problems, read


def packages_listed() -> list[str]:
    names = []
    for line in TEX_PACKAGES.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def dependency_closure(packages: list[str]) -> set[str]:
    """What installing these with --no-install-recommends brings in"""
    result = run([
        "apt-cache", "depends", "--recurse", "--no-recommends", "--no-suggests", "--no-conflicts",
        "--no-breaks", "--no-replaces", "--no-enhances", "--no-pre-depends", *packages,
    ])
    closure = set(packages)
    for line in result.stdout.splitlines():
        if not line.startswith(" "):
            closure.add(line.strip().split(":")[0])
    return closure


def owners(paths: set[Path]) -> tuple[dict[str, list[Path]], list[Path]]:
    """Which Debian package installed each file, and the files no package did (generated ones)"""
    by_package: dict[str, list[Path]] = {}
    generated: list[Path] = []
    for path in sorted(paths):
        real = path.resolve()
        found = None
        for candidate in (real, path):
            result = run(["dpkg", "-S", str(candidate)])
            if result.returncode == 0:
                found = result.stdout.split(":", 1)[0].split(",")[0].strip()
                break
        if found:
            by_package.setdefault(found, []).append(real)
        else:
            generated.append(real)
    return by_package, generated


def check_provenance(read: set[Path], work: Path) -> list[str]:
    if shutil.which("dpkg") is None:
        return ["--provenance needs dpkg, so a Debian or Ubuntu machine"]
    listed = packages_listed()
    closure = dependency_closure(listed)
    by_package, generated = owners({p for p in read if work not in p.parents})
    print(f"\nFiles read, by the package that installed them ({TEX_PACKAGES.name}: {' '.join(listed)}):")
    problems = []
    for package, files in sorted(by_package.items()):
        inside = package in closure
        mark = "ok " if inside else "OUT"
        print(f"  {mark} {package:28s} {len(files):4d} files, e.g. {files[0].name}")
        if not inside:
            problems.append(
                f"{package} provided {', '.join(f.name for f in files[:5])}, and is not installed "
                f"by {TEX_PACKAGES.relative_to(REPO)} or anything it depends on"
            )
    print(f"  --- generated by the install rather than shipped: {', '.join(sorted({p.name for p in generated}))}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provenance", action="store_true",
                        help="list the Debian package behind every file read, and check them against apt/tex.txt")
    parser.add_argument("--keep", type=Path, help="write the document and its outputs here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="check-tex-") as temp:
        work = args.keep or Path(temp)
        work.mkdir(parents=True, exist_ok=True)
        problems, read = compile_document(work, args.provenance)
        if args.provenance and not problems:
            problems += check_provenance(read, work)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
