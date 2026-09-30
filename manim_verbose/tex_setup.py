"""
A LaTeX of manim's own, for anyone who has none: TinyTeX (https://yihui.org/tinytex/), with
the packages manim's default template needs, in a folder of the user's. No administrator
rights, and nothing outside that folder is touched.

    manimgl-doctor --install-tex      download and set it up, or finish a setup cut short
    manimgl-doctor --uninstall-tex    delete it again

Once set up, `use_managed_tex()` puts its bin folder first on PATH, which is where manimlib
looks for `latex` and `dvisvgm` (see manimlib/utils/tex_file_writing.py).
manim_verbose.manim_import calls it whenever it imports manim, so manimgl-scene, the editor
and its render workers all find it without anyone editing a PATH.

Where it goes: MANIM_VERBOSE_TEX_DIR if that is set, else a folder of the user's data:
~/.local/share/manim-verbose/TinyTeX on Linux, ~/Library/manim-verbose/TinyTeX on macOS
(not Application Support: TeX and spaces in paths are best kept apart), and
%LOCALAPPDATA%\\manim-verbose\\TinyTeX on Windows (%ProgramData% when the user's folder has
letters TeX can't cope with, as TinyTeX's own installer does).

It counts as set up only once LaTeX has compiled a document using every package of the
template and dvisvgm has turned it into outlines; that writes MARKER. A folder without the
marker is a setup cut short, which --install-tex carries on from.

Nothing here is imported by manim itself, and the import is cheap: the downloading and
unpacking happen only when asked for.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

APP = "manim-verbose"
DIR_VARIABLE = "MANIM_VERBOSE_TEX_DIR"
URL_VARIABLE = "MANIM_VERBOSE_TINYTEX_URL"
MARKER = "manim-verbose-tex.json"
MARKER_FORMAT = 1
# Where the archive came from, noted as soon as it is unpacked, for the marker written at the end
SOURCE_NOTE = "manim-verbose-source.txt"

# TinyTeX's prebuilt bundle, rebuilt every day from the current TeX Live: LaTeX and the few hundred
# packages most documents use, about 200 MB to download. (Its smaller bundles, TinyTeX-0 and
# TinyTeX-1, were last built in v2026.03.)
BUNDLE = "TinyTeX"
# Where tlmgr fetches packages when TinyTeX's own server (tlnet.yihui.org) doesn't answer:
# CTAN's redirector, which picks a mirror near the user
CTAN_REPOSITORY = "https://mirror.ctan.org/systems/texlive/tlnet"
RELEASE_URLS = (
    "https://github.com/rstudio/tinytex-releases/releases/download/daily/{name}",
    # TinyTeX's site, which sends the same names on to the latest release
    "https://yihui.org/tinytex/{name}",
)

# What manim's default template (manimlib/tex_templates.yml) needs from TeX Live, by the name
# tlmgr installs it under, and why. Installing one which is there already does nothing. The
# TinyTeX bundle of 2026-09 has all but doublestroke, relsize, fundus-calligra, calligra,
# calligra-type1, wasysym, wasy, physics, cm-super and dvisvgm; with those, it compiles the
# template (checked by hand against that bundle, the TeX Live packages copied in). Anything a newer TeX Live splits off differently is found by
# file after the first check compile, see fill_gaps().
PACKAGES: dict[str, str] = {
    "standalone": "the document class every formula is compiled in",
    "preview": "standalone's preview option",
    "xkeyval": "standalone reads its options with it",
    "babel": "\\usepackage[english]{babel}",
    "babel-english": "babel's english",
    "amsmath": "amsmath",
    "amsfonts": "amssymb, and the AMS fonts behind \\minus",
    "doublestroke": "dsfont",
    "setspace": "setspace",
    "tipa": "tipa, and its fonts",
    "relsize": "relsize",
    "jknapltx": "mathrsfs",
    "rsfs": "the fonts behind \\mathscr",
    "fundus-calligra": "calligra.sty",
    "calligra": "the calligra font's metrics",
    "calligra-type1": "calligra as outlines rather than a bitmap",
    "wasysym": "wasysym",
    "wasy": "wasysym's fonts",
    "ragged2e": "ragged2e",
    "physics": "physics",
    "l3packages": "xparse, which physics is written with",
    "xcolor": "xcolor",
    "microtype": "microtype",
    "psnfss": "pifont",
    "symbol": "the Symbol font psnfss maps",
    "zapfding": "the Dingbats font behind pifont",
    "ec": "the metrics of T1 encoded text fonts",
    "cm-super": "T1 encoded text fonts as outlines, so text in formulas comes out as paths",
    "dvisvgm": "turns what LaTeX writes into the SVG manim reads",
}

# Where to find a file LaTeX asked for and didn't get: the TeX Live package, for tlmgr, and the
# Ubuntu package (as scripts/ci/check_tex.py knows them, checked there with --provenance)
FILE_HOMES: dict[str, tuple[str, str]] = {
    "standalone.cls": ("standalone", "texlive-latex-extra"),
    "preview.sty": ("preview", "texlive-latex-extra"),
    "xkeyval.sty": ("xkeyval", "texlive-latex-recommended"),
    "babel.sty": ("babel", "texlive-latex-base"),
    "english.ldf": ("babel-english", "texlive-latex-base"),
    "amsmath.sty": ("amsmath", "texlive-latex-base"),
    "amssymb.sty": ("amsfonts", "texlive-base"),
    "dsfont.sty": ("doublestroke", "texlive-fonts-extra"),
    "setspace.sty": ("setspace", "texlive-latex-recommended"),
    "tipa.sty": ("tipa", "tipa"),
    "relsize.sty": ("relsize", "texlive-latex-extra"),
    "mathrsfs.sty": ("jknapltx", "texlive-latex-recommended"),
    "calligra.sty": ("fundus-calligra", "texlive-latex-extra"),
    "wasysym.sty": ("wasysym", "texlive-fonts-recommended"),
    "ragged2e.sty": ("ragged2e", "texlive-latex-recommended"),
    "physics.sty": ("physics", "texlive-science"),
    "xparse.sty": ("l3packages", "texlive-latex-recommended"),
    "xcolor.sty": ("xcolor", "texlive-latex-recommended"),
    "microtype.sty": ("microtype", "texlive-latex-recommended"),
    "pifont.sty": ("psnfss", "texlive-latex-base"),
}
# What every file in FILE_HOMES comes to on Ubuntu 24.04, as scripts/ci/apt/tex.txt installs it
APT_PACKAGES = (
    "texlive-latex-base", "texlive-latex-recommended", "texlive-latex-extra",
    "texlive-fonts-recommended", "texlive-fonts-extra", "texlive-science", "tipa", "cm-super",
    "dvisvgm",
)

# The preamble of manim's default template, as manimlib/tex_templates.yml has it. Kept here
# rather than read from manimlib, so that the check runs without manim importing (and says
# what is wrong with LaTeX even when something else is wrong with manim).
# tests/test_doctor.py checks it is the same.
DEFAULT_PREAMBLE = r"""\usepackage[english]{babel}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{dsfont}
\usepackage{setspace}
\usepackage{tipa}
\usepackage{relsize}
\usepackage{textcomp}
\usepackage{mathrsfs}
\usepackage{calligra}
\usepackage{wasysym}
\usepackage{ragged2e}
\usepackage{physics}
\usepackage{xcolor}
\usepackage{microtype}
\usepackage{pifont}
\DisableLigatures{encoding = *, family = * }
\linespread{1}
%% Borrowed from https://tex.stackexchange.com/questions/6058/making-a-shorter-minus
\DeclareMathSymbol{\minus}{\mathbin}{AMSa}{"39}"""

# Something from every package of the preamble, at more than one size, as
# scripts/ci/check_tex.py does: a font missing for a subscript is still a font missing
CHECK_BODY = r"""
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
# Every glyph above is a path of its own in the SVG; far fewer means glyphs went missing
MIN_PATHS = 50


class TexSetupError(Exception):
    """Setting up TeX failed; `fix` says what to do about it, in words for the person at the keyboard."""

    def __init__(self, message: str, fix: Iterable[str] = ()):
        super().__init__(message)
        self.fix = list(fix)


# Where it lives, and putting it on PATH

def data_dir() -> Path:
    """The per-user folder manim-verbose keeps things in"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / APP
    import appdirs
    path = Path(appdirs.user_data_dir(APP, appauthor=False))
    if sys.platform == "win32" and not str(path).isascii():
        program_data = os.environ.get("ProgramData")
        if program_data:
            return Path(program_data) / APP
    return path


def tex_dir() -> Path:
    """Where the managed TinyTeX is, or would go"""
    configured = os.environ.get(DIR_VARIABLE)
    return Path(configured).expanduser() if configured else data_dir() / "TinyTeX"


def find_bin(root: Path) -> Path | None:
    """TeX Live's folder of programs in an installation: bin/x86_64-linux, bin/universal-darwin, bin/windows..."""
    bins = root / "bin"
    try:
        candidates = sorted(p for p in bins.iterdir() if p.is_dir())
    except OSError:
        return None
    for candidate in candidates:
        if any((candidate / name).exists() for name in ("tlmgr", "tlmgr.bat")):
            return candidate
    return None


def read_marker(root: Path) -> dict | None:
    try:
        data = json.loads((root / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def managed_bin(root: Path | None = None) -> Path | None:
    """The bin folder of a managed TeX which finished setting up, or None"""
    root = tex_dir() if root is None else root
    if read_marker(root) is None:
        return None
    return find_bin(root)


def use_managed_tex(environ: dict | None = None) -> Path | None:
    """
    Puts the managed TeX's bin folder first on PATH, if it has been set up, and says which
    folder that was. Does nothing (and never raises) otherwise. Safe to call any number of
    times: a folder already first is left where it is.
    """
    environ = os.environ if environ is None else environ
    try:
        bin_dir = managed_bin()
    except Exception:  # a broken home folder is no reason for importing manim to fail
        return None
    if bin_dir is None:
        return None
    environ["PATH"] = path_with_first(environ.get("PATH", ""), bin_dir)
    return bin_dir


def path_with_first(path: str, folder: Path) -> str:
    """A PATH with `folder` first, and nowhere else"""
    def same(entry: str) -> bool:
        return os.path.normcase(os.path.normpath(entry)) == os.path.normcase(os.path.normpath(str(folder)))
    entries = [e for e in path.split(os.pathsep) if e]
    if entries and same(entries[0]) and not any(same(e) for e in entries[1:]):
        return path
    return os.pathsep.join([str(folder)] + [e for e in entries if not same(e)])


# Which archive, from where

def archive_name(system: str | None = None, machine: str | None = None, bundle: str = BUNDLE) -> str:
    """The name of TinyTeX's archive for a platform (platform.system() and platform.machine() by default)"""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == "windows":
        # TeX Live's Windows programs are x86_64 only; Windows on ARM runs them emulated
        return f"{bundle}.zip"
    if system == "darwin":
        # universal-darwin: Intel and Apple Silicon both
        return f"{bundle}.tgz"
    if system == "linux" and machine in ("x86_64", "amd64"):
        return f"{bundle}.tar.gz"
    what = f"{platform_label(system)} on {machine}" if machine else platform_label(system)
    raise TexSetupError(
        f"TinyTeX has no ready-made build for {what}, so manimgl-doctor can't install LaTeX here by itself.",
        [
            "Install TeX Live from your system's packages instead. On Debian or Ubuntu:",
            "  sudo apt install " + " ".join(APT_PACKAGES),
            f"Or set {URL_VARIABLE} to the address of a TinyTeX archive built for this computer.",
        ],
    )


def platform_label(system: str) -> str:
    return {"linux": "Linux", "darwin": "macOS", "windows": "Windows"}.get(system.lower(), system)


def candidate_urls(system: str | None = None, machine: str | None = None) -> list[str]:
    """Where to download TinyTeX from, in the order to try them"""
    configured = os.environ.get(URL_VARIABLE)
    if configured:
        return [configured]
    name = archive_name(system, machine)
    return [template.format(name=name) for template in RELEASE_URLS]


# Downloading and unpacking

Progress = Callable[[str], None]


def download(urls: list[str], folder: Path, say: Progress = print) -> tuple[Path, str]:
    """Fetches the first of `urls` which answers into `folder`; the file, and where it came from"""
    import urllib.error
    import urllib.request
    folder.mkdir(parents=True, exist_ok=True)
    failures = []
    for url in urls:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", url.rstrip("/").rsplit("/", 1)[-1]) or "TinyTeX"
        target = folder / name
        partial = target.with_name(target.name + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": f"{APP} (manimgl-doctor)"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                shown = -1
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    step = int(done * 10 / total) if total else done >> 24
                    if step != shown:
                        shown = step
                        size = f"{done / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else "")
                        say(f"  downloaded {size}")
            if total and done != total:
                raise OSError(f"the download stopped at {done} of {total} bytes")
            partial.replace(target)
            return target, url
        except Exception as err:  # every way a download fails is reported the same way, and the next tried
            partial.unlink(missing_ok=True)
            failures.append((url, err))
    raise TexSetupError(
        "Couldn't download TinyTeX:\n" + "\n".join(f"  {url}: {describe_download_error(err)}" for url, err in failures),
        download_fixes([err for _, err in failures]),
    )


def describe_download_error(err: BaseException) -> str:
    import urllib.error
    if isinstance(err, urllib.error.HTTPError):
        return f"the server answered {err.code} {err.reason}"
    if isinstance(err, urllib.error.URLError):
        return f"couldn't connect ({err.reason})"
    return f"{type(err).__name__}: {err}"


def download_fixes(errors: list[BaseException]) -> list[str]:
    import ssl
    fixes = []
    certificate = any(
        isinstance(err, ssl.SSLCertVerificationError)
        or isinstance(getattr(err, "reason", None), ssl.SSLCertVerificationError)
        for err in errors
    )
    if certificate and sys.platform == "darwin":
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        fixes.append(
            f"Python can't check the website's certificate. Python from python.org needs this once: "
            f"open the Applications > Python {version} folder and double-click 'Install Certificates.command'."
        )
    elif certificate:
        fixes.append("Python can't check the website's certificate. Check the computer's date and time are right.")
    fixes += [
        "Check this computer is online, then run  manimgl-doctor --install-tex  again.",
        "Behind a proxy? Set HTTPS_PROXY to it first.",
        "Or download the file yourself, in a browser, from " + (", or ".join(candidate_urls_or_none()) or "TinyTeX's releases")
        + ", and run  manimgl-doctor --install-tex --tex-archive THAT_FILE",
    ]
    return fixes


def candidate_urls_or_none() -> list[str]:
    try:
        return candidate_urls()[:1]
    except TexSetupError:
        return []


def extract(archive: Path, root: Path, say: Progress = print) -> None:
    """Unpacks a TinyTeX archive so that its top folder becomes `root`"""
    staging = root.with_name(f"{root.name}.unpacking-{os.getpid()}")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        name = archive.name.lower()
        if name.endswith(".zip"):
            _extract_zip(archive, staging)
        elif name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar")):
            _extract_tar(archive, staging)
        else:
            raise TexSetupError(f"{archive.name} isn't an archive manimgl-doctor knows how to unpack (.zip, .tgz, .tar.gz)")
        top = _installation_in(staging)
        if top is None:
            raise TexSetupError(f"{archive.name} doesn't hold a TeX installation (no bin folder with tlmgr in it)")
        if root.exists():
            remove_tree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        top.replace(root)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _installation_in(folder: Path) -> Path | None:
    """The folder holding bin/<platform>/tlmgr: the folder itself, or one inside it (TinyTeX, .TinyTeX)"""
    if find_bin(folder):
        return folder
    for child in sorted(folder.iterdir()):
        if child.is_dir() and find_bin(child):
            return child
    return None


def _safe_member(name: str, dest: Path) -> Path:
    target = (dest / name).resolve()
    if dest.resolve() not in target.parents and target != dest.resolve():
        raise TexSetupError(f"The archive tries to write outside its folder ({name}); not unpacking it")
    return target


def _extract_tar(archive: Path, dest: Path) -> None:
    import tarfile
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            _safe_member(member.name, dest)
            if member.islnk() or member.issym():
                link = member.linkname if member.islnk() else str(Path(member.name).parent / member.linkname)
                _safe_member(link, dest)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, members=members, filter="data")
        else:  # Pythons before the extraction filters: checked above instead
            tar.extractall(dest, members=members)


def _extract_zip(archive: Path, dest: Path) -> None:
    import stat
    import zipfile
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            _safe_member(info.filename, dest)
        zf.extractall(dest)
        if os.name != "nt":
            for info in zf.infolist():
                mode = (info.external_attr >> 16) & 0o777
                if mode & stat.S_IXUSR:
                    target = dest / info.filename
                    target.chmod(target.stat().st_mode | mode)


def remove_tree(path: Path) -> None:
    """shutil.rmtree, getting past files Windows keeps read-only"""
    import stat

    def retry(function, name, _info):
        os.chmod(name, stat.S_IWRITE)
        function(name)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


# tlmgr

def tlmgr_command(bin_dir: Path) -> list[str]:
    for name in (("tlmgr.bat", "tlmgr") if os.name == "nt" else ("tlmgr",)):
        path = bin_dir / name
        if path.exists():
            return [str(path)]
    raise TexSetupError(f"There's no tlmgr in {bin_dir}, so this isn't a TeX Live installation")


def tex_environment(bin_dir: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = path_with_first(env.get("PATH", ""), bin_dir)
    return env


def run_tlmgr(bin_dir: Path, args: list[str], say: Progress = print, timeout: float = 3600) -> subprocess.CompletedProcess:
    """Runs tlmgr, passing on the lines saying what it is installing, and keeping all it printed"""
    command = tlmgr_command(bin_dir) + args
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        env=tex_environment(bin_dir),
    )
    lines = []
    deadline = time.monotonic() + timeout
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        shown = line.strip()
        # "[3/28, 00:05/01:10] install: calligra [18k]"
        if re.match(r"\[\d+/\d+", shown) and "install:" in shown:
            say("  " + shown.split("]", 1)[-1].strip())
        if time.monotonic() > deadline:
            process.kill()
            break
    returncode = process.wait()
    return subprocess.CompletedProcess(command, returncode, "".join(lines), "")


def packages_found_for(tlmgr_output: str, file: str) -> list[str]:
    """Package names from `tlmgr search --global --file /FILE`, whose file of that name it holds"""
    found = []
    package = None
    for line in tlmgr_output.splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            package = line.strip().rstrip(":") if line.rstrip().endswith(":") and not line.startswith("tlmgr") else None
        elif package and line.strip().endswith("/" + file) and package not in found:
            found.append(package)
    # A package's -dev version holds the same files, and isn't the one to install
    return sorted(found, key=lambda name: (name.endswith("-dev"), "." in name, name))


# Checking it can do what manim asks of it

@dataclass
class TexCheck:
    """What compiling manim's template with a LaTeX found"""
    latex: str | None
    dvisvgm: str | None
    problems: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    missing_fonts: list[str] = field(default_factory=list)
    paths: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.problems


def full_tex(body: str, preamble: str = DEFAULT_PREAMBLE) -> str:
    """As manimlib.utils.tex_file_writing.get_full_tex"""
    return "\n\n".join((
        "\\documentclass[preview]{standalone}", preamble, "\\begin{document}", body, "\\end{document}",
    )) + "\n"


def compile_check(
    latex: str | None = None, dvisvgm: str | None = None, env: dict | None = None, timeout: float = 180,
    preamble: str | None = None, search: bool = True,
) -> TexCheck:
    """
    Compiles a document using every package of manim's default template, as manim would, and
    turns it into an SVG, as manim would. `latex` and `dvisvgm` are found on PATH when not
    given, unless `search` is false: then a program not given counts as missing.
    """
    preamble = DEFAULT_PREAMBLE if preamble is None else preamble
    started = time.monotonic()
    env = dict(os.environ) if env is None else env
    if search:
        latex = latex or shutil.which("latex", path=env.get("PATH"))
        dvisvgm = dvisvgm or shutil.which("dvisvgm", path=env.get("PATH"))
    check = TexCheck(latex, dvisvgm)
    if latex is None:
        check.problems.append("there's no `latex` program")
    if dvisvgm is None:
        check.problems.append("there's no `dvisvgm` program")
    if check.problems:
        return check
    with tempfile.TemporaryDirectory(prefix="manim-tex-check-") as temp:
        work = Path(temp)
        tex_path = work / "check.tex"
        tex_path.write_text(full_tex(CHECK_BODY, preamble), encoding="utf-8")
        try:
            run = subprocess.run(
                [latex, "-interaction=batchmode", "-halt-on-error", f"-output-directory={work}", tex_path.as_posix()],
                cwd=work, env=env, capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            check.problems.append(f"latex took longer than {timeout:.0f} seconds")
            return _timed(check, started)
        except OSError as err:
            check.problems.append(f"latex couldn't be run: {err}")
            return _timed(check, started)
        dvi = tex_path.with_suffix(".dvi")
        log_path = tex_path.with_suffix(".log")
        log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
        if run.returncode != 0 or not dvi.exists():
            check.missing_files = missing_files_in(log_text)
            for name in check.missing_files:
                check.problems.append(f"LaTeX can't find {name}")
            if not check.missing_files:
                errors = re.findall(r"^! .*(?:\n.*){0,2}", log_text, flags=re.MULTILINE)
                check.problems.append("latex failed: " + ("\n".join(errors[:2]).strip() or run.stdout[-1000:].strip()))
            return _timed(check, started)
        # Metafont kept out of it: without an outline font, dvisvgm would quietly trace a
        # bitmap one, and the glyph would be blurred or missing
        svg_env = dict(env, MKTEXPK="0", MKTEXTFM="0")
        try:
            svg = subprocess.run(
                [dvisvgm, str(dvi), "-n", "-v", "3", "--stdout"],
                env=svg_env, capture_output=True, text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            check.problems.append(f"dvisvgm took longer than {timeout:.0f} seconds")
            return _timed(check, started)
        except OSError as err:
            check.problems.append(f"dvisvgm couldn't be run: {err}")
            return _timed(check, started)
    if svg.returncode != 0:
        check.problems.append(f"dvisvgm failed: {svg.stderr.strip()[-1000:]}")
        return _timed(check, started)
    for line in svg.stderr.splitlines():
        if "WARNING" in line or "not found" in line or "cannot" in line.lower():
            check.problems.append(f"dvisvgm: {line.strip()}")
            check.missing_fonts += [f for f in fonts_named_in(line) if f not in check.missing_fonts]
    check.paths = svg.stdout.count("<path")
    if check.paths < MIN_PATHS:
        check.problems.append(f"the SVG holds only {check.paths} paths, where every glyph should have been one")
    return _timed(check, started)


def _timed(check: TexCheck, started: float) -> TexCheck:
    check.seconds = time.monotonic() - started
    return check


def missing_files_in(log_text: str) -> list[str]:
    """Files a LaTeX log says it couldn't find: packages, classes, and font metrics"""
    names = re.findall(r"File `([^']+)' not found", log_text)
    names += re.findall(r"I can't find file `([^']+)'", log_text)
    names += [f"{font}.tfm" for font in re.findall(r"! Font [^=\n]*=(\S+) (?:at|scaled) [^\n]*not loadable: Metric \(TFM\) file", log_text)]
    unique = []
    for name in names:
        if name not in unique and not name.startswith("check."):
            unique.append(name)
    return unique


def fonts_named_in(line: str) -> list[str]:
    """Font names in a dvisvgm warning, such as "font file 'sfrm1000.pfb' not found" or "font ecrm1000 not found" """
    quoted = re.findall(r"'([A-Za-z0-9_+.-]+)'", line)
    if quoted:
        return quoted
    return re.findall(r"font(?: file)? ([A-Za-z0-9_+.-]+)", line)


# Fonts whose outlines come in another package than the one their name suggests
FONT_PACKAGES = {"ec": "cm-super", "tc": "cm-super", "sf": "cm-super", "rsfs": "rsfs", "callig": "calligra-type1",
                 "dsrom": "doublestroke", "dsss": "doublestroke", "wasy": "wasy", "tipa": "tipa", "xipa": "tipa",
                 "pzd": "zapfding", "uzd": "zapfding", "psy": "symbol", "usy": "symbol"}


def packages_for_fonts(fonts: list[str]) -> list[str]:
    found = []
    for font in fonts:
        stem = font.rsplit(".", 1)[0].lower()
        for prefix, package in FONT_PACKAGES.items():
            if stem.startswith(prefix) and package not in found:
                found.append(package)
    return found


# Setting it up

@dataclass
class InstallResult:
    root: Path
    bin_dir: Path
    already: bool
    seconds: float
    size_bytes: int
    source: str | None
    packages: list[str]


def folder_size(path: Path) -> int:
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total


def install(
    root: Path | None = None,
    *,
    archive: Path | None = None,
    repository: str | None = None,
    force: bool = False,
    say: Progress = print,
) -> InstallResult:
    """
    Sets up the managed TeX, carrying on from wherever an earlier try stopped. With it set up
    and working already, only checks that. Raises TexSetupError, saying what to do, on failure.
    """
    started = time.monotonic()
    root = tex_dir() if root is None else root
    if force and root.exists():
        say(f"Removing the TeX at {root} to start again")
        remove_tree(root)

    bin_dir = find_bin(root)
    if read_marker(root) is not None and bin_dir is not None:
        check = check_installation(bin_dir)
        if check.ok:
            return InstallResult(root, bin_dir, True, time.monotonic() - started, folder_size(root),
                                 read_marker(root).get("source"), sorted(PACKAGES))
        say("The TeX set up before doesn't work any more (" + "; ".join(check.problems[:3]) + "); repairing it")
        (root / MARKER).unlink(missing_ok=True)

    source = None
    steps = 4
    if bin_dir is None:
        if archive is None:
            urls = candidate_urls()
            say(f"[1/{steps}] Downloading TinyTeX (about 200 MB) from {urls[0]}")
            downloads = root.parent / f"{root.name}.download"
            archive_path, source = download(urls, downloads, say)
        else:
            archive_path, source = Path(archive), str(Path(archive).resolve())
            if not archive_path.is_file():
                raise TexSetupError(f"There's no file {archive}")
            say(f"[1/{steps}] Using {archive_path}")
        say(f"[2/{steps}] Unpacking into {root}")
        extract(archive_path, root, say)
        (root / SOURCE_NOTE).write_text(source + "\n", encoding="utf-8")
        if archive is None:
            shutil.rmtree(archive_path.parent, ignore_errors=True)
        bin_dir = find_bin(root)
        assert bin_dir is not None
    else:
        say(f"[1/{steps}] TinyTeX is already unpacked in {root}; carrying on from there")
        say(f"[2/{steps}] (nothing to unpack)")
        try:
            source = (root / SOURCE_NOTE).read_text(encoding="utf-8").strip() or None
        except OSError:
            source = None

    if not have_perl():
        raise TexSetupError(
            "TeX Live's package manager, tlmgr, is written in Perl, and this computer has no `perl`.",
            ["On Debian or Ubuntu:  sudo apt install perl", "On Fedora:  sudo dnf install perl",
             "Then run  manimgl-doctor --install-tex  again."],
        )
    if repository:
        _tlmgr_or_fail(bin_dir, ["option", "repository", repository], say)

    names = sorted(PACKAGES)
    say(f"[3/{steps}] Installing the {len(names)} LaTeX packages manim uses (the slow part: a few minutes)")
    try:
        install_packages(bin_dir, names, say)
    except TexSetupError as err:
        if repository or not unreachable(str(err)):
            raise
        say(f"  TinyTeX's package server didn't answer; trying CTAN's mirrors ({CTAN_REPOSITORY}) instead")
        _tlmgr_or_fail(bin_dir, ["option", "repository", CTAN_REPOSITORY], say)
        install_packages(bin_dir, names, say)

    say(f"[4/{steps}] Checking LaTeX can typeset manim's formulas")
    check = fill_gaps(bin_dir, say)
    if not check.ok:
        raise TexSetupError(
            "TinyTeX is installed, but LaTeX still can't typeset everything manim's template uses:\n"
            + "\n".join(f"  {p}" for p in check.problems[:8]),
            ["Run  manimgl-doctor --install-tex  again (a download may have been cut short).",
             "If it keeps failing, start again from scratch:  manimgl-doctor --install-tex --force"],
        )
    marker = {
        "format": MARKER_FORMAT,
        "bundle": BUNDLE,
        "source": source,
        "packages": names,
        "bin": bin_dir.relative_to(root).as_posix(),
        "installed": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (root / MARKER).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return InstallResult(root, bin_dir, False, time.monotonic() - started, folder_size(root), marker["source"], names)


def have_perl() -> bool:
    """tlmgr is a Perl program; TinyTeX brings its own Perl on Windows only"""
    return os.name == "nt" or shutil.which("perl") is not None


def check_installation(bin_dir: Path) -> TexCheck:
    """compile_check with the installation's own latex and dvisvgm, and nobody else's"""
    return compile_check(
        latex=shutil.which("latex", path=str(bin_dir)), dvisvgm=shutil.which("dvisvgm", path=str(bin_dir)),
        env=tex_environment(bin_dir), search=False,
    )


def _tlmgr_or_fail(bin_dir: Path, args: list[str], say: Progress) -> subprocess.CompletedProcess:
    result = run_tlmgr(bin_dir, args, say)
    if result.returncode != 0:
        raise TexSetupError(f"`tlmgr {' '.join(args)}` failed:\n{result.stdout.strip()[-1500:]}", tlmgr_fixes(result.stdout))
    return result


def tlmgr_fixes(output: str) -> list[str]:
    if re.search(r"older than remote repository|cross release updates are only supported", output):
        return ["This TinyTeX is from an older year of TeX Live than the servers now have. Start again with the "
                "current one:  manimgl-doctor --install-tex --force"]
    if unreachable(output):
        return ["tlmgr couldn't reach a TeX Live server (CTAN). Check this computer is online and run "
                "manimgl-doctor --install-tex  again.",
                "If a particular server is the problem, choose another:  manimgl-doctor --install-tex "
                "--tex-repository https://mirror.example.org/CTAN/systems/texlive/tlnet  (any mirror from "
                "https://ctan.org/mirrors, with /systems/texlive/tlnet on the end)"]
    return ["Run  manimgl-doctor --install-tex  again; if it keeps failing, start from scratch with --force."]


def unreachable(output: str) -> bool:
    """Whether tlmgr said it couldn't reach its package server"""
    return bool(re.search(
        r"(?i)could not get texlive\.tlpdb|unable to download|cannot contact|no connection|timed out|could not connect",
        output,
    ))


def install_packages(bin_dir: Path, names: list[str], say: Progress) -> list[str]:
    """tlmgr install, updating tlmgr itself first if it says it has to be. The names tlmgr didn't know."""
    result = run_tlmgr(bin_dir, ["install", *names], say)
    if result.returncode != 0 and "tlmgr itself needs to be updated" in result.stdout:
        say("  updating tlmgr itself first")
        _tlmgr_or_fail(bin_dir, ["update", "--self"], say)
        result = run_tlmgr(bin_dir, ["install", *names], say)
    unknown = re.findall(r"package (\S+) not present in repository", result.stdout)
    if unknown:
        # Not fatal by itself: the check compile says whether anything is actually missing
        say(f"  (TeX Live has no package called {', '.join(unknown)}; carrying on)")
    elif result.returncode != 0:
        raise TexSetupError(f"`tlmgr install` failed:\n{result.stdout.strip()[-1500:]}", tlmgr_fixes(result.stdout))
    return unknown


def fill_gaps(bin_dir: Path, say: Progress, rounds: int = 8) -> TexCheck:
    """
    Compiles the check document and, for as long as it helps, installs whichever package holds
    each file LaTeX couldn't find (asking tlmgr which that is), and the outline fonts dvisvgm
    couldn't find.
    """
    tried: set[str] = set()
    refreshed_maps = False
    check = check_installation(bin_dir)
    for _ in range(rounds):
        if check.ok:
            break
        wanted: list[str] = [p for p, program in (("latex-bin", check.latex), ("dvisvgm", check.dvisvgm))
                             if program is None and p not in tried]
        for name in check.missing_files:
            known = FILE_HOMES.get(name)
            candidates = [known[0]] if known and known[0] not in tried else []
            if not candidates:
                search = run_tlmgr(bin_dir, ["search", "--global", "--file", "/" + name], say)
                candidates = packages_found_for(search.stdout, name)[:1]
            wanted += [c for c in candidates if c not in tried and c not in wanted]
        wanted += [p for p in packages_for_fonts(check.missing_fonts) if p not in tried and p not in wanted]
        if wanted:
            say(f"  installing what's still missing: {', '.join(wanted)}")
            tried.update(wanted)
            install_packages(bin_dir, wanted, say)
        elif check.missing_fonts and not refreshed_maps:
            # Fonts installed, and not yet in the maps dvisvgm reads
            refreshed_maps = True
            updmap = shutil.which("updmap-sys", path=str(bin_dir))
            if updmap:
                say("  refreshing the font maps")
                subprocess.run([updmap], env=tex_environment(bin_dir), capture_output=True, timeout=600)
        else:
            break
        check = check_installation(bin_dir)
    return check


def uninstall(root: Path | None = None) -> bool:
    """Deletes the managed TeX; whether there was one to delete"""
    root = tex_dir() if root is None else root
    leftovers = [root.with_name(f"{root.name}.download")] + list(root.parent.glob(f"{root.name}.unpacking-*"))
    for leftover in leftovers:
        if leftover.exists():
            remove_tree(leftover)
    if not root.exists():
        return False
    remove_tree(root)
    return True
