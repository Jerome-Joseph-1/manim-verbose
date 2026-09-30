"""
manimgl-doctor and the TeX it sets up (manim_verbose/doctor.py, manim_verbose/tex_setup.py).

Every check is run with what it looks at faked: no graphics adapter, no LaTeX, a package
missing, no UI, the wrong Python, and so on, for each operating system its advice differs on.
The TinyTeX installer runs against archives made here and served from a local HTTP server,
with tlmgr faked, so nothing is downloaded from the internet, except by the one test of a real
download, which only runs when MANIM_TEST_TINYTEX=1 (it fetches a few hundred MB).
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import zipfile
from pathlib import Path

import pytest
import yaml

from manim_verbose import doctor, tex_setup
from manim_verbose.doctor import Context, Result, System
from manim_verbose.tex_setup import TexCheck, TexSetupError

REPO = Path(__file__).resolve().parents[1]
HAVE_LATEX = bool(tex_setup.shutil.which("latex") and tex_setup.shutil.which("dvisvgm"))
needs_latex = pytest.mark.skipif(not HAVE_LATEX, reason="needs latex and dvisvgm on PATH")
posix_only = pytest.mark.skipif(os.name == "nt", reason="fakes tlmgr with a shell script")


def make_system(os_name="linux", distro="debian", python=(3, 11, 4), bits=64) -> System:
    return System(os=os_name, distro=distro, distro_name="", machine="x86_64", python=python, bits=bits,
                  executable="/usr/bin/python3")


def run(check_id: str, ctx: Context | None = None, **system) -> Result:
    return doctor.run_check(ctx or Context(make_system(**system)), check_id)


def fix_text(result: Result) -> str:
    return "\n".join(result.fix)


@pytest.fixture(autouse=True)
def managed_tex_dir(tmp_path, monkeypatch):
    """Every test gets a managed TeX folder of its own, empty, and a PATH put back afterwards"""
    root = tmp_path / "data" / "TinyTeX"
    monkeypatch.setenv(tex_setup.DIR_VARIABLE, str(root))
    monkeypatch.delenv(tex_setup.URL_VARIABLE, raising=False)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    return root


# Python

def test_a_supported_python_passes():
    result = run("python", python=(3, 12, 1))
    assert result.status == "ok"
    assert "3.12.1, 64-bit" in result.summary


def test_an_old_python_fails_saying_which_to_install():
    result = run("python", python=(3, 9, 18))
    assert result.status == "fail"
    assert "too old" in result.summary and "3.10" in result.summary
    assert "python.org/downloads" in fix_text(result)


def test_a_32_bit_python_fails():
    result = run("python", bits=32)
    assert result.status == "fail"
    assert "64-bit" in result.summary and "64-bit" in fix_text(result)


def test_a_python_newer_than_tested_warns_but_does_not_fail():
    result = run("python", python=(3, 14, 0))
    assert result.status == "warn"
    assert "3.13" in fix_text(result)


@pytest.mark.parametrize("os_release, family", [
    ('NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\n', "debian"),
    ('NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\n', "debian"),
    ('NAME="Fedora Linux"\nID=fedora\n', "fedora"),
    ('ID="rocky"\nID_LIKE="rhel centos fedora"\n', "fedora"),
    ('NAME="Arch Linux"\nID=arch\n', "arch"),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "suse"),
    ('ID=nixos\n', None),
])
def test_linux_is_told_apart_by_package_manager(os_release, family):
    assert doctor.linux_distro(os_release)[0] == family


# manim itself

def test_manim_failing_to_load_for_want_of_pango_says_to_install_it(monkeypatch):
    def broken():
        raise ImportError("libpango-1.0.so.0: cannot open shared object file")
    monkeypatch.setattr(doctor, "import_manim_modules", broken)
    result = run("manim", distro="fedora")
    assert result.status == "fail"
    assert "sudo dnf install pango-devel" in fix_text(result)
    assert "manimpango" in fix_text(result)


def test_manim_failing_to_load_otherwise_says_to_reinstall(monkeypatch):
    def broken():
        raise ModuleNotFoundError("No module named 'scipy'")
    monkeypatch.setattr(doctor, "import_manim_modules", broken)
    result = run("manim")
    assert result.status == "fail"
    assert "scipy" in result.summary
    assert "--force-reinstall" in fix_text(result)


def test_manim_loads_here():
    result = run("manim")
    assert result.status == "ok", result.summary
    assert result.details["manimgl"]


# The editor

def test_editor_without_its_ui_fails_and_points_at_a_release(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "ui_index", lambda: tmp_path / "site-packages" / "manim_verbose" / "editor" / "static" / "index.html")
    result = run("editor")
    assert result.status == "fail"
    assert "isn't built" in result.summary
    assert "INSTALL.md" in fix_text(result) and "npm" not in fix_text(result)


def test_editor_without_its_ui_in_a_checkout_says_how_to_build_it(tmp_path, monkeypatch):
    (tmp_path / "editor-ui").mkdir()
    (tmp_path / "editor-ui" / "package.json").write_text("{}")
    monkeypatch.setattr(doctor, "ui_index", lambda: tmp_path / "manim_verbose" / "editor" / "static" / "index.html")
    result = run("editor")
    assert result.status == "fail"
    commands = [line.strip() for line in result.fix if line.startswith("  ")]
    assert commands == [f"cd {tmp_path / 'editor-ui'}", "npm ci", "npm run build"]


def test_editor_without_its_extra_says_to_install_it(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html>")
    monkeypatch.setattr(doctor, "ui_index", lambda: index)
    monkeypatch.setattr(doctor, "module_available", lambda name: name != "uvicorn")
    result = run("editor")
    assert result.status == "fail"
    assert "uvicorn missing" in result.summary
    assert "[editor]" in fix_text(result)


def test_editor_with_ui_and_extra_passes(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<html>")
    monkeypatch.setattr(doctor, "ui_index", lambda: index)
    monkeypatch.setattr(doctor, "module_available", lambda name: True)
    assert run("editor").status == "ok"


# Graphics

def no_adapter():
    raise RuntimeError("Request adapter failed: no suitable adapter found")


@pytest.mark.parametrize("distro, command", [
    ("debian", "sudo apt install mesa-vulkan-drivers libvulkan1"),
    ("fedora", "sudo dnf install mesa-vulkan-drivers vulkan-loader"),
    ("arch", "sudo pacman -S vulkan-swrast vulkan-icd-loader"),
    ("suse", "sudo zypper install libvulkan_lvp libvulkan1"),
])
def test_no_adapter_on_linux_says_which_drivers_to_install(monkeypatch, distro, command):
    monkeypatch.setattr(doctor, "probe_gpu", no_adapter)
    result = run("gpu", distro=distro)
    assert result.status == "fail"
    assert "can't find a graphics adapter" in result.summary
    commands = [line.strip() for line in result.fix if line.startswith("  ")]
    assert commands == [command]
    assert result.details["error"].startswith("Request adapter failed")


def test_no_adapter_on_an_unknown_linux_lists_every_package_manager(monkeypatch):
    monkeypatch.setattr(doctor, "probe_gpu", no_adapter)
    text = fix_text(run("gpu", distro=None))
    for manager in ("apt", "dnf", "pacman", "zypper"):
        assert f"sudo {manager} " in text


@pytest.mark.parametrize("os_name, words", [("darwin", "Metal"), ("windows", "graphics driver")])
def test_no_adapter_on_macos_and_windows(monkeypatch, os_name, words):
    monkeypatch.setattr(doctor, "probe_gpu", no_adapter)
    result = run("gpu", os_name=os_name, distro=None)
    assert result.status == "fail"
    assert words in fix_text(result)
    assert "sudo" not in fix_text(result)


def test_a_cpu_adapter_passes_saying_it_is_slower(monkeypatch):
    monkeypatch.setattr(doctor, "probe_gpu", lambda: {
        "vendor": "llvmpipe", "device": "llvmpipe (LLVM 20.1.2, 256 bits)", "description": "Mesa 25.2.8",
        "adapter_type": "CPU", "backend_type": "Vulkan"})
    result = run("gpu")
    assert result.status == "ok"
    assert "CPU" in result.summary and "llvmpipe" in result.summary and "slowly" in result.summary
    assert result.notes


def test_a_gpu_passes_naming_it(monkeypatch):
    monkeypatch.setattr(doctor, "probe_gpu", lambda: {
        "vendor": "Apple", "device": "Apple M2", "description": "", "adapter_type": "IntegratedGPU",
        "backend_type": "Metal"})
    result = run("gpu", os_name="darwin", distro=None)
    assert result.status == "ok"
    assert result.summary == "Apple M2 (IntegratedGPU, Metal)"
    assert not result.notes


def test_graphics_is_not_checked_when_manim_does_not_load(monkeypatch):
    ctx = Context(make_system())
    ctx.results["manim"] = Result("manim", "manim itself", "fail")
    monkeypatch.setattr(doctor, "probe_gpu", lambda: pytest.fail("should not be probed"))
    assert run("gpu", ctx).status == "skip"


def test_the_real_gpu_probe_answers_or_raises():
    try:
        info = doctor.probe_gpu()
    except RuntimeError as err:
        assert str(err)
    else:
        assert set(info) == {"vendor", "device", "description", "adapter_type", "backend_type"}


# LaTeX

def fake_tex(monkeypatch, **fields):
    check = TexCheck(fields.pop("latex", "/usr/bin/latex"), fields.pop("dvisvgm", "/usr/bin/dvisvgm"), **fields)
    monkeypatch.setattr(doctor, "compile_tex", lambda: check)
    return check


def test_no_latex_fails_and_offers_to_install_one(monkeypatch):
    fake_tex(monkeypatch, latex=None, dvisvgm=None, problems=["there's no `latex` program"])
    result = run("latex")
    assert result.status == "fail"
    assert "LaTeX isn't installed" in result.summary and "everything else works" in result.summary
    commands = [line.strip() for line in result.fix if line.startswith("  ")]
    assert commands[0] == "manimgl-doctor --install-tex"
    assert commands[1] == "sudo apt install " + " ".join(tex_setup.APT_PACKAGES)


def test_no_latex_on_macos_and_windows_offers_only_the_managed_one(monkeypatch):
    fake_tex(monkeypatch, latex=None, dvisvgm=None, problems=["there's no `latex` program"])
    for os_name in ("darwin", "windows"):
        result = run("latex", os_name=os_name, distro=None)
        assert [line.strip() for line in result.fix if line.startswith("  ")] == ["manimgl-doctor --install-tex"]


def test_latex_without_dvisvgm(monkeypatch):
    fake_tex(monkeypatch, dvisvgm=None, problems=["there's no `dvisvgm` program"])
    result = run("latex", os_name="darwin", distro=None)
    assert result.status == "fail"
    assert "dvisvgm isn't" in result.summary


@pytest.mark.parametrize("latex, distro, command", [
    ("/usr/bin/latex", "debian", "sudo apt install texlive-fonts-extra texlive-science"),
    ("/usr/local/texlive/2025/bin/x86_64-linux/latex", "debian", "tlmgr install doublestroke physics"),
    ("/Library/TeX/texbin/latex", None, "tlmgr install doublestroke physics"),
    ("C:\\Program Files\\MiKTeX\\miktex\\bin\\x64\\latex.exe", None, "open MiKTeX Console > Packages, and install: doublestroke physics"),
])
def test_a_missing_package_is_named_with_how_to_add_it(monkeypatch, latex, distro, command):
    fake_tex(monkeypatch, latex=latex, problems=["LaTeX can't find dsfont.sty", "LaTeX can't find physics.sty"],
             missing_files=["dsfont.sty", "physics.sty"])
    result = run("latex", distro=distro)
    assert result.status == "fail"
    assert "dsfont.sty" in result.summary
    commands = [line.strip() for line in result.fix if line.startswith("  ")]
    assert commands == ["manimgl-doctor --install-tex", command]


def test_a_broken_managed_tex_is_repaired_by_installing_again(monkeypatch, managed_tex_dir):
    bin_dir = fake_installation(managed_tex_dir, marker=True)
    fake_tex(monkeypatch, latex=str(bin_dir / "latex"), problems=["LaTeX can't find dsfont.sty"],
             missing_files=["dsfont.sty"])
    result = run("latex")
    assert result.details["source"] == "managed"
    assert "manimgl-doctor --install-tex" in [line.strip() for line in result.fix]
    assert "--force" in fix_text(result)


def test_an_unfinished_managed_tex_is_finished(monkeypatch, managed_tex_dir):
    fake_installation(managed_tex_dir, marker=False)
    fake_tex(monkeypatch, latex=None, dvisvgm=None, problems=["there's no `latex` program"])
    result = run("latex")
    assert "didn't finish" in fix_text(result)


def test_working_latex_passes_saying_where_it_is(monkeypatch):
    fake_tex(monkeypatch, paths=120, seconds=0.8)
    result = run("latex")
    assert result.status == "ok"
    assert "/usr/bin/latex" in result.summary and result.details["source"] == "system"


@needs_latex
def test_the_real_compile_check_passes_with_the_tex_installed_here():
    check = tex_setup.compile_check()
    assert check.ok, check.problems
    assert check.paths >= tex_setup.MIN_PATHS


@needs_latex
def test_the_real_compile_check_names_a_missing_package():
    preamble = tex_setup.DEFAULT_PREAMBLE + "\n\\usepackage{nosuchpackage-for-manimgl-doctor}"
    check = tex_setup.compile_check(preamble=preamble)
    assert not check.ok
    assert check.missing_files == ["nosuchpackage-for-manimgl-doctor.sty"]


def test_latex_logs_and_dvisvgm_warnings_are_read():
    log = (
        "! LaTeX Error: File `dsfont.sty' not found.\n\nType X to quit\n"
        "! Font T1/cmr/m/n/10=ecrm1000 at 10.0pt not loadable: Metric (TFM) file not found.\n"
        "! LaTeX Error: File `dsfont.sty' not found.\n"
    )
    assert tex_setup.missing_files_in(log) == ["dsfont.sty", "ecrm1000.tfm"]
    assert tex_setup.fonts_named_in("WARNING: font file 'sfrm1000.pfb' not found") == ["sfrm1000.pfb"]
    assert tex_setup.fonts_named_in("PK font ecrm1000 not found") == ["ecrm1000"]
    assert tex_setup.packages_for_fonts(["ecrm1000", "tcrm1000", "rsfs10.pfb"]) == ["cm-super", "rsfs"]


def test_the_check_uses_manims_own_default_preamble():
    templates = yaml.safe_load((REPO / "manimlib" / "tex_templates.yml").read_text(encoding="utf-8"))
    assert tex_setup.DEFAULT_PREAMBLE == templates["default"]["preamble"]


def test_every_package_of_the_preamble_has_a_home():
    used = []
    for options_and_names in __import__("re").findall(r"\\usepackage(?:\[[^]]*\])?\{([^}]*)\}", tex_setup.DEFAULT_PREAMBLE):
        used += [name.strip() for name in options_and_names.split(",")]
    in_latex_itself = {"inputenc", "fontenc", "textcomp"}
    for name in used:
        if name not in in_latex_itself:
            assert f"{name}.sty" in tex_setup.FILE_HOMES, name
    for tl_name, _apt in tex_setup.FILE_HOMES.values():
        assert tl_name in tex_setup.PACKAGES


def test_apt_advice_is_what_ci_installs():
    listed = []
    for line in (REPO / "scripts" / "ci" / "apt" / "tex.txt").read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            listed.append(name)
    assert list(tex_setup.APT_PACKAGES) == listed


# ffmpeg

@pytest.mark.parametrize("os_name, distro, command", [
    ("windows", None, "winget install --id Gyan.FFmpeg -e"),
    ("darwin", None, "brew install ffmpeg"),
    ("linux", "debian", "sudo apt install ffmpeg"),
    ("linux", "arch", "sudo pacman -S ffmpeg"),
])
def test_no_ffmpeg_says_how_to_install_it(monkeypatch, os_name, distro, command):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, *a, **k: None if name == "ffmpeg" else "/bin/" + name)
    result = run("ffmpeg", os_name=os_name, distro=distro)
    assert result.status == "fail"
    assert "previews and videos" in result.summary
    assert command in [line.strip() for line in result.fix]


def test_ffmpeg_without_h264_on_fedora_says_to_swap_it(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, *a, **k: "/usr/bin/ffmpeg")
    monkeypatch.setattr(doctor, "ffmpeg_encoders", lambda program: " V....D libopenh264  OpenH264\n V....D libvpx")
    result = run("ffmpeg", distro="fedora")
    assert result.status == "fail"
    assert "libx264" in result.summary
    assert "sudo dnf swap ffmpeg-free ffmpeg --allowerasing" in [line.strip() for line in result.fix]


def test_ffmpeg_with_h264_passes(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name, *a, **k: "/usr/bin/ffmpeg")
    monkeypatch.setattr(doctor, "ffmpeg_encoders", lambda program: " V....D libx264  libx264 H.264")
    assert run("ffmpeg").status == "ok"


# Fonts

def test_no_fonts_at_all_fails(monkeypatch):
    monkeypatch.setattr(doctor, "installed_fonts", lambda: [])
    result = run("fonts")
    assert result.status == "fail"
    assert "sudo apt install fonts-dejavu fontconfig" in [line.strip() for line in result.fix]


def test_missing_optional_fonts_pass_saying_what_stands_in(monkeypatch):
    monkeypatch.setattr(doctor, "installed_fonts", lambda: ["DejaVu Sans", "DejaVu Serif"])
    monkeypatch.setattr(doctor, "manim_text_font", lambda: "Consolas")
    monkeypatch.setattr(doctor, "font_substitute", lambda name: "DejaVu Serif" if name == "CMU Serif" else None)
    result = run("fonts", distro="debian")
    assert result.status == "ok"
    notes = "\n".join(result.notes)
    assert "CMU Serif (a font scene files often choose) isn't installed" in notes
    assert "DejaVu Serif is used instead" in notes
    assert "Consolas" in notes and "your system picks a similar font" in notes
    assert "sudo apt install fonts-cmu" in notes
    assert result.details["optional_installed"] is False


def test_installed_fonts_are_noted_as_installed(monkeypatch):
    monkeypatch.setattr(doctor, "installed_fonts", lambda: ["CMU Serif", "Consolas"])
    monkeypatch.setattr(doctor, "manim_text_font", lambda: "Consolas")
    result = run("fonts", os_name="windows", distro=None)
    assert result.status == "ok"
    assert all("is installed" in note for note in result.notes)


# The test render

def test_the_render_is_skipped_when_there_is_nothing_to_draw_with(monkeypatch):
    ctx = Context(make_system())
    ctx.results["gpu"] = Result("gpu", "Graphics", "fail")
    monkeypatch.setattr(doctor, "render_smoke", lambda *a: pytest.fail("should not render"))
    result = run("render", ctx)
    assert result.status == "skip" and "graphics" in result.summary


def test_the_render_is_skipped_when_quick(monkeypatch):
    monkeypatch.setattr(doctor, "render_smoke", lambda *a: pytest.fail("should not render"))
    assert run("render", Context(make_system(), quick=True)).status == "skip"


@pytest.mark.parametrize("latex_status, formula", [("ok", True), ("fail", False)])
def test_the_render_includes_a_formula_only_when_latex_works(monkeypatch, latex_status, formula):
    asked = []

    def render(folder, with_formula):
        asked.append(with_formula)
        return {"seconds": 1.5, "width": 320, "height": 180, "formula": with_formula}
    monkeypatch.setattr(doctor, "render_smoke", render)
    ctx = Context(make_system())
    ctx.results["latex"] = Result("latex", "LaTeX", latex_status)
    result = run("render", ctx)
    assert result.status == "ok" and asked == [formula]
    assert "320x180" in result.summary


def test_a_failed_render_says_what_went_wrong(monkeypatch):
    def render(folder, with_formula):
        raise RuntimeError("doctor-check.yaml: scenes[0]: something broke\nRender failed: the adapter was lost")
    monkeypatch.setattr(doctor, "render_smoke", render)
    result = run("render")
    assert result.status == "fail"
    assert result.summary.endswith("the adapter was lost")


# The whole run

def fake_everything_ok(monkeypatch, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<html>")
    monkeypatch.setattr(doctor.System, "detect", classmethod(lambda cls: make_system()))
    monkeypatch.setattr(doctor, "import_manim_modules", lambda: {"manimgl": "1.7.2", "location": "/site"})
    monkeypatch.setattr(doctor, "ui_index", lambda: index)
    monkeypatch.setattr(doctor, "module_available", lambda name: True)
    monkeypatch.setattr(doctor, "probe_gpu", lambda: {"device": "GPU", "adapter_type": "DiscreteGPU", "backend_type": "Vulkan"})
    fake_tex(monkeypatch, paths=120)
    monkeypatch.setattr(doctor, "ffmpeg_program", lambda: "ffmpeg")
    monkeypatch.setattr(doctor.shutil, "which", lambda name, *a, **k: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "ffmpeg_encoders", lambda program: "libx264")
    monkeypatch.setattr(doctor, "installed_fonts", lambda: ["CMU Serif", "Consolas"])
    monkeypatch.setattr(doctor, "render_smoke", lambda folder, formula: {"seconds": 1.0, "width": 320, "height": 180})


def test_json_output_lists_every_check_in_order(monkeypatch, tmp_path, capsys):
    fake_everything_ok(monkeypatch, tmp_path)
    assert doctor.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == 1 and report["ok"] is True
    assert [c["id"] for c in report["checks"]] == ["python", "manim", "editor", "gpu", "latex", "ffmpeg", "fonts", "render"]
    for check in report["checks"]:
        assert set(check) == {"id", "title", "status", "summary", "fix", "notes", "details", "seconds"}
        assert check["status"] == "ok", check
    assert report["system"]["os"] == "linux" and report["system"]["python"] == "3.11.4"


def test_a_failure_makes_the_exit_status_1_and_shows_in_the_json(monkeypatch, tmp_path, capsys):
    fake_everything_ok(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "probe_gpu", no_adapter)
    assert doctor.main(["--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    statuses = {c["id"]: c["status"] for c in report["checks"]}
    assert report["ok"] is False
    assert statuses["gpu"] == "fail" and statuses["render"] == "skip"


def test_a_warning_does_not_fail(monkeypatch, tmp_path, capsys):
    fake_everything_ok(monkeypatch, tmp_path)
    monkeypatch.setattr(doctor.System, "detect", classmethod(lambda cls: make_system(python=(3, 14, 0))))
    assert doctor.main([]) == 0
    out = capsys.readouterr().out
    assert "WARN  Python" in out and "ready to use" in out


def test_human_output_says_what_to_type(monkeypatch, tmp_path, capsys):
    fake_everything_ok(monkeypatch, tmp_path)
    fake_tex(monkeypatch, latex=None, dvisvgm=None, problems=["there's no `latex` program"])
    assert doctor.main(["--quick"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  LaTeX (for formulas)" in out
    assert "\n            manimgl-doctor --install-tex\n" in out
    assert "skip  Test render: Not checked: left out (--quick)" in out
    assert out.rstrip().endswith("then run manimgl-doctor again.")
    assert out.isascii()


def test_a_check_which_breaks_is_reported_rather_than_raised(monkeypatch, tmp_path, capsys):
    fake_everything_ok(monkeypatch, tmp_path)

    def broken():
        raise ValueError("unexpected")
    monkeypatch.setattr(doctor, "installed_fonts", broken)
    assert doctor.main(["--json"]) == 1
    fonts = next(c for c in json.loads(capsys.readouterr().out)["checks"] if c["id"] == "fonts")
    assert fonts["status"] == "fail" and "ValueError: unexpected" in fonts["summary"]


def test_tex_options_need_install_tex(capsys):
    with pytest.raises(SystemExit) as exited:
        doctor.main(["--force"])
    assert exited.value.code == 2


def test_the_real_doctor_runs_here(capsys):
    """Nothing faked, no render: whatever this machine has, the answer is well formed"""
    status = doctor.main(["--json", "--quick"])
    report = json.loads(capsys.readouterr().out)
    assert status == (0 if report["ok"] else 1)
    statuses = {c["id"]: c["status"] for c in report["checks"]}
    assert statuses["python"] in ("ok", "warn") and statuses["manim"] == "ok"
    assert statuses["render"] == "skip"


def test_the_console_script_is_declared():
    import configparser
    config = configparser.ConfigParser(interpolation=None)
    config.read(REPO / "setup.cfg", encoding="utf-8")
    scripts = config.get("options.entry_points", "console_scripts")
    assert "manimgl-doctor = manim_verbose.doctor:main" in scripts


# The managed TeX: where it goes, and PATH

def fake_installation(root: Path, marker: bool, bin_name: str = "x86_64-linux") -> Path:
    bin_dir = root / "bin" / bin_name
    bin_dir.mkdir(parents=True)
    for name in ("tlmgr", "latex", "dvisvgm"):
        (bin_dir / name).write_text("#!/bin/sh\n")
        (bin_dir / name).chmod(0o755)
    if marker:
        (root / tex_setup.MARKER).write_text(json.dumps({"format": 1}))
    return bin_dir


def test_the_folder_follows_the_environment_variable(managed_tex_dir):
    assert tex_setup.tex_dir() == managed_tex_dir


def test_the_default_folder_is_per_user(monkeypatch, tmp_path):
    monkeypatch.delenv(tex_setup.DIR_VARIABLE)
    if sys.platform.startswith("linux"):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert tex_setup.tex_dir() == tmp_path / "xdg" / "manim-verbose" / "TinyTeX"
    monkeypatch.setattr(tex_setup.sys, "platform", "darwin")
    assert tex_setup.tex_dir() == Path.home() / "Library" / "manim-verbose" / "TinyTeX"
    assert " " not in str(tex_setup.tex_dir().relative_to(Path.home()))


def test_on_windows_a_user_folder_tex_cant_use_moves_to_programdata(monkeypatch):
    import appdirs
    monkeypatch.setattr(tex_setup.sys, "platform", "win32")
    monkeypatch.setattr(appdirs, "user_data_dir", lambda *a, **k: "C:\\Users\\Jos\u00e9\\AppData\\Local\\manim-verbose")
    monkeypatch.setenv("ProgramData", "C:\\ProgramData")
    assert str(tex_setup.data_dir()).replace("/", "\\").endswith("C:\\ProgramData\\manim-verbose")
    monkeypatch.setattr(appdirs, "user_data_dir", lambda *a, **k: "C:\\Users\\Ann\\AppData\\Local\\manim-verbose")
    assert "Ann" in str(tex_setup.data_dir())


def test_nothing_goes_on_path_without_a_finished_install(managed_tex_dir):
    fake_installation(managed_tex_dir, marker=False)
    env = {"PATH": "/usr/bin"}
    assert tex_setup.use_managed_tex(env) is None
    assert env == {"PATH": "/usr/bin"}


def test_a_finished_install_goes_first_on_path_once(managed_tex_dir):
    bin_dir = fake_installation(managed_tex_dir, marker=True)
    env = {"PATH": os.pathsep.join(["/usr/bin", str(bin_dir), "/bin"])}
    assert tex_setup.use_managed_tex(env) == bin_dir
    assert env["PATH"] == os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])
    tex_setup.use_managed_tex(env)
    assert env["PATH"] == os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])


def test_importing_manim_puts_the_managed_tex_on_path(managed_tex_dir, monkeypatch):
    from manim_verbose.manim_import import import_manim
    bin_dir = fake_installation(managed_tex_dir, marker=True)
    import_manim()
    assert os.environ["PATH"].split(os.pathsep)[0] == str(bin_dir)


def test_a_broken_data_folder_never_stops_manim_importing(monkeypatch):
    monkeypatch.setattr(tex_setup, "managed_bin", lambda: (_ for _ in ()).throw(PermissionError("no")))
    assert tex_setup.use_managed_tex({"PATH": ""}) is None


# The managed TeX: which archive

@pytest.mark.parametrize("system, machine, name", [
    ("Linux", "x86_64", "TinyTeX.tar.gz"),
    ("Darwin", "x86_64", "TinyTeX.tgz"),
    ("Darwin", "arm64", "TinyTeX.tgz"),
    ("Windows", "AMD64", "TinyTeX.zip"),
    ("Windows", "ARM64", "TinyTeX.zip"),
])
def test_the_archive_for_each_platform(system, machine, name):
    assert tex_setup.archive_name(system, machine) == name
    urls = tex_setup.candidate_urls(system, machine)
    assert urls[0] == f"https://github.com/rstudio/tinytex-releases/releases/download/daily/{name}"
    assert all(url.endswith("/" + name) for url in urls)


@pytest.mark.parametrize("system, machine", [("Linux", "aarch64"), ("FreeBSD", "amd64")])
def test_platforms_without_a_build_are_told_what_to_do_instead(system, machine):
    with pytest.raises(TexSetupError) as raised:
        tex_setup.archive_name(system, machine)
    assert "no ready-made build" in str(raised.value)
    assert any("sudo apt install" in line for line in raised.value.fix)


def test_the_download_address_can_be_given(monkeypatch):
    monkeypatch.setenv(tex_setup.URL_VARIABLE, "https://mirror.example/TinyTeX.tar.gz")
    assert tex_setup.candidate_urls("Linux", "aarch64") == ["https://mirror.example/TinyTeX.tar.gz"]


# The managed TeX: downloading, unpacking, installing

def tar_archive(path: Path, top: str = ".TinyTeX", scripts: dict[str, str] | None = None, extra: dict[str, str] | None = None) -> Path:
    scripts = scripts or {"tlmgr": "#!/bin/sh\n", "latex": "#!/bin/sh\n", "dvisvgm": "#!/bin/sh\n"}
    with tarfile.open(path, "w:gz") as tar:
        def add(name, text, mode):
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))
        for name, text in scripts.items():
            add(f"{top}/bin/x86_64-linux/{name}", text, 0o755)
        add(f"{top}/texmf-dist/ls-R", "% ls-R\n", 0o644)
        for name, text in (extra or {}).items():
            add(name, text, 0o644)
    return path


class Server:
    """Serves a folder over HTTP on localhost, counting requests"""

    def __init__(self, folder: Path):
        self.requests: list[str] = []
        outer = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                super().do_GET()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(folder)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(tmp_path, monkeypatch):
    folder = tmp_path / "served"
    folder.mkdir()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    serving = Server(folder)
    serving.folder = folder
    yield serving
    serving.close()


class FakeTlmgr:
    """Stands in for run_tlmgr, recording what it was asked"""

    def __init__(self, answers=None):
        self.calls: list[list[str]] = []
        self.answers = answers or {}

    def __call__(self, bin_dir, args, say=print, timeout=3600):
        self.calls.append(list(args))
        answer = self.answers.get(args[0], (0, ""))
        if callable(answer):
            answer = answer(args)
        return subprocess.CompletedProcess(["tlmgr", *args], answer[0], answer[1], "")


@pytest.fixture
def quiet_install(monkeypatch):
    """tlmgr and the check compile faked, Perl taken as there"""
    tlmgr = FakeTlmgr()
    monkeypatch.setattr(tex_setup, "run_tlmgr", tlmgr)
    monkeypatch.setattr(tex_setup, "have_perl", lambda: True)
    monkeypatch.setattr(tex_setup, "compile_check", lambda **kw: TexCheck("latex", "dvisvgm", paths=100))
    return tlmgr


def test_install_downloads_unpacks_installs_and_marks_it_done(managed_tex_dir, server, quiet_install, monkeypatch):
    tar_archive(server.folder / "TinyTeX.tar.gz")
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    said = []
    done = tex_setup.install(say=said.append)
    assert not done.already
    assert done.bin_dir == managed_tex_dir / "bin" / "x86_64-linux"
    assert server.requests == ["/TinyTeX.tar.gz"]
    assert quiet_install.calls == [["install", *sorted(tex_setup.PACKAGES)]]
    marker = json.loads((managed_tex_dir / tex_setup.MARKER).read_text())
    assert marker["source"] == f"{server.url}/TinyTeX.tar.gz" and marker["bin"] == "bin/x86_64-linux"
    assert os.access(done.bin_dir / "tlmgr", os.X_OK)
    assert not (managed_tex_dir.parent / "TinyTeX.download").exists()
    assert any("[1/4] Downloading" in line for line in said) and any("[4/4]" in line for line in said)
    # and from now on it is used
    env = {"PATH": "/usr/bin"}
    assert tex_setup.use_managed_tex(env) == done.bin_dir


def test_installing_again_only_checks_it_still_works(managed_tex_dir, server, quiet_install, monkeypatch):
    tar_archive(server.folder / "TinyTeX.tar.gz")
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    tex_setup.install(say=lambda line: None)
    server.requests.clear()
    quiet_install.calls.clear()
    again = tex_setup.install(say=lambda line: None)
    assert again.already
    assert server.requests == [] and quiet_install.calls == []


def test_an_install_cut_short_carries_on_without_downloading_again(managed_tex_dir, server, quiet_install, monkeypatch):
    fake_installation(managed_tex_dir, marker=False)
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    done = tex_setup.install(say=lambda line: None)
    assert server.requests == []
    assert quiet_install.calls[0][0] == "install"
    assert (managed_tex_dir / tex_setup.MARKER).exists() and not done.already


def test_an_install_which_stopped_working_is_repaired(managed_tex_dir, quiet_install, monkeypatch):
    fake_installation(managed_tex_dir, marker=True)
    checks = iter([TexCheck("latex", "dvisvgm", problems=["LaTeX can't find dsfont.sty"], missing_files=["dsfont.sty"]),
                   TexCheck("latex", "dvisvgm", paths=100)])
    monkeypatch.setattr(tex_setup, "compile_check", lambda **kw: next(checks))
    said = []
    done = tex_setup.install(say=said.append)
    assert not done.already and any("repairing" in line for line in said)
    assert quiet_install.calls[0][0] == "install"


def test_force_starts_again(managed_tex_dir, server, quiet_install, monkeypatch):
    tar_archive(server.folder / "TinyTeX.tar.gz")
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    bin_dir = fake_installation(managed_tex_dir, marker=True)
    (bin_dir / "stale").write_text("old")
    tex_setup.install(force=True, say=lambda line: None)
    assert server.requests == ["/TinyTeX.tar.gz"]
    assert not (bin_dir / "stale").exists()


def test_install_from_an_archive_already_downloaded(managed_tex_dir, tmp_path, quiet_install):
    archive = tar_archive(tmp_path / "TinyTeX.tgz", top="TinyTeX")
    done = tex_setup.install(archive=archive, say=lambda line: None)
    assert done.source == str(archive.resolve())
    assert archive.exists()  # someone else's file is left alone


def test_the_next_address_is_tried_when_one_fails(tmp_path, server):
    tar_archive(server.folder / "TinyTeX.tar.gz")
    said = []
    path, url = tex_setup.download([f"{server.url}/missing.tar.gz", f"{server.url}/TinyTeX.tar.gz"], tmp_path / "dl", said.append)
    assert url.endswith("/TinyTeX.tar.gz") and path.read_bytes() == (server.folder / "TinyTeX.tar.gz").read_bytes()
    assert not list((tmp_path / "dl").glob("*.part"))
    assert said and said[-1].startswith("  downloaded")


def test_a_failed_download_says_what_to_do(tmp_path, server):
    with pytest.raises(TexSetupError) as raised:
        tex_setup.download([f"{server.url}/missing.tar.gz"], tmp_path / "dl", lambda line: None)
    assert "404" in str(raised.value)
    assert any("--tex-archive" in line for line in raised.value.fix)
    assert not list((tmp_path / "dl").glob("*.part"))


def test_certificate_trouble_on_macos_points_at_install_certificates(monkeypatch):
    import ssl
    import urllib.error
    monkeypatch.setattr(tex_setup.sys, "platform", "darwin")
    fixes = tex_setup.download_fixes([urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer"))])
    assert "Install Certificates.command" in fixes[0]


def test_a_zip_as_windows_gets_it_unpacks(tmp_path):
    archive = tmp_path / "TinyTeX.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("TinyTeX/bin/windows/tlmgr.bat", "@echo off\n")
        zf.writestr("TinyTeX/bin/windows/latex.exe", "")
        zf.writestr("TinyTeX/texmf-dist/ls-R", "")
    root = tmp_path / "out" / "TinyTeX"
    tex_setup.extract(archive, root, lambda line: None)
    assert tex_setup.find_bin(root) == root / "bin" / "windows"
    assert not list((tmp_path / "out").glob("*.unpacking-*"))


def test_an_archive_writing_outside_its_folder_is_refused(tmp_path):
    archive = tar_archive(tmp_path / "evil.tar.gz", extra={"../../escaped.txt": "gotcha"})
    with pytest.raises(TexSetupError, match="outside its folder"):
        tex_setup.extract(archive, tmp_path / "out" / "TinyTeX", lambda line: None)
    assert not (tmp_path / "escaped.txt").exists()


def test_an_archive_without_tex_in_it_is_refused(tmp_path):
    archive = tmp_path / "not-tex.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("README")
        tar.addfile(info, io.BytesIO(b""))
    with pytest.raises(TexSetupError, match="doesn't hold a TeX installation"):
        tex_setup.extract(archive, tmp_path / "out" / "TinyTeX", lambda line: None)


def test_no_perl_is_explained(managed_tex_dir, quiet_install, monkeypatch):
    fake_installation(managed_tex_dir, marker=False)
    monkeypatch.setattr(tex_setup, "have_perl", lambda: False)
    with pytest.raises(TexSetupError, match="Perl") as raised:
        tex_setup.install(say=lambda line: None)
    assert "sudo apt install perl" in raised.value.fix[0]


def test_tlmgr_is_updated_when_it_says_it_has_to_be(managed_tex_dir, quiet_install):
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    attempts = []

    def install(args):
        attempts.append(args)
        return (1, "tlmgr itself needs to be updated.\n") if len(attempts) == 1 else (0, "")
    quiet_install.answers = {"install": install}
    tex_setup.install_packages(bin_dir, ["physics"], lambda line: None)
    assert [call[0:2] for call in quiet_install.calls] == [["install", "physics"], ["update", "--self"], ["install", "physics"]]


def test_a_package_tex_live_does_not_have_is_not_fatal_by_itself(managed_tex_dir, quiet_install):
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    quiet_install.answers = {"install": (1, "tlmgr install: package wasy-type1 not present in repository.\n")}
    said = []
    assert tex_setup.install_packages(bin_dir, ["wasy-type1"], said.append) == ["wasy-type1"]
    assert any("carrying on" in line for line in said)


def test_an_old_tex_live_year_says_to_start_again(managed_tex_dir, quiet_install):
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    quiet_install.answers = {"install": (1, "tlmgr: Local TeX Live (2025) is older than remote repository (2026).\n")}
    with pytest.raises(TexSetupError) as raised:
        tex_setup.install_packages(bin_dir, ["physics"], lambda line: None)
    assert "--force" in raised.value.fix[0]


UNREACHABLE = ("tlmgr: TLPDB::from_file could not get texlive.tlpdb from: https://tlnet.yihui.org/tlpkg/texlive.tlpdb\n"
               "Maybe the repository setting should be changed.\n")


def test_when_tinytexs_server_does_not_answer_ctan_is_tried(managed_tex_dir, quiet_install):
    fake_installation(managed_tex_dir, marker=False)
    attempts = []

    def install(args):
        attempts.append(args)
        return (1, UNREACHABLE) if len(attempts) == 1 else (0, "")
    quiet_install.answers = {"install": install}
    said = []
    tex_setup.install(say=said.append)
    assert [call[:3] for call in quiet_install.calls] == [
        ["install", *sorted(tex_setup.PACKAGES)[:2]],
        ["option", "repository", tex_setup.CTAN_REPOSITORY],
        ["install", *sorted(tex_setup.PACKAGES)[:2]],
    ]
    assert any("trying CTAN's mirrors" in line for line in said)


def test_a_repository_given_is_not_second_guessed(managed_tex_dir, quiet_install):
    fake_installation(managed_tex_dir, marker=False)
    quiet_install.answers = {"install": (1, UNREACHABLE)}
    with pytest.raises(TexSetupError) as raised:
        tex_setup.install(repository="https://mirror.example/tlnet", say=lambda line: None)
    assert quiet_install.calls[0] == ["option", "repository", "https://mirror.example/tlnet"]
    assert not any(call[:2] == ["option", "repository"] and call[2] == tex_setup.CTAN_REPOSITORY for call in quiet_install.calls)
    assert "couldn't reach a TeX Live server" in raised.value.fix[0]


@posix_only
def test_the_installations_own_dvisvgm_is_required(managed_tex_dir, tmp_path, monkeypatch):
    """TinyTeX's bundle has no dvisvgm; one elsewhere on PATH mustn't make it look complete"""
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    (bin_dir / "dvisvgm").unlink()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "dvisvgm").write_text("#!/bin/sh\n")
    (elsewhere / "dvisvgm").chmod(0o755)
    monkeypatch.setenv("PATH", str(elsewhere))
    check = tex_setup.check_installation(bin_dir)
    assert check.dvisvgm is None and "there's no `dvisvgm` program" in check.problems


def test_missing_programs_are_installed_as_packages(managed_tex_dir, quiet_install, monkeypatch):
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    checks = iter([TexCheck("latex", None, problems=["there's no `dvisvgm` program"]), TexCheck("latex", "dvisvgm", paths=100)])
    monkeypatch.setattr(tex_setup, "compile_check", lambda **kw: next(checks))
    assert tex_setup.fill_gaps(bin_dir, lambda line: None).ok
    assert quiet_install.calls == [["install", "dvisvgm"]]


SEARCH_OUTPUT = """\
tlmgr: package repository https://mirror.example/systems/texlive/tlnet (verified)
foo-dev:
\ttexmf-dist/tex/latex/foo/foo.sty
foo:
\ttexmf-dist/tex/latex/foo/foo.sty
notfoo:
\ttexmf-dist/tex/latex/notfoo/xfoo.sty
"""


def test_files_are_found_in_packages_through_tlmgr_search():
    assert tex_setup.packages_found_for(SEARCH_OUTPUT, "foo.sty") == ["foo", "foo-dev"]


def test_whatever_is_still_missing_is_found_and_installed(managed_tex_dir, quiet_install, monkeypatch):
    bin_dir = fake_installation(managed_tex_dir, marker=False)
    quiet_install.answers = {"search": (0, SEARCH_OUTPUT)}
    checks = iter([TexCheck("latex", "dvisvgm", problems=["LaTeX can't find foo.sty"], missing_files=["foo.sty"]),
                   TexCheck("latex", "dvisvgm", problems=["dvisvgm: font file 'sfrm1000.pfb' not found"],
                            missing_fonts=["sfrm1000.pfb"]),
                   TexCheck("latex", "dvisvgm", paths=100)])
    monkeypatch.setattr(tex_setup, "compile_check", lambda **kw: next(checks))
    check = tex_setup.fill_gaps(bin_dir, lambda line: None)
    assert check.ok
    assert quiet_install.calls == [["search", "--global", "--file", "/foo.sty"], ["install", "foo"], ["install", "cm-super"]]


def test_an_install_which_still_cannot_typeset_fails_saying_so(managed_tex_dir, quiet_install, monkeypatch):
    fake_installation(managed_tex_dir, marker=False)
    monkeypatch.setattr(tex_setup, "compile_check", lambda **kw: TexCheck("latex", "dvisvgm", problems=["latex failed: ! Emergency stop."]))
    with pytest.raises(TexSetupError, match="still can't typeset") as raised:
        tex_setup.install(say=lambda line: None)
    assert not (managed_tex_dir / tex_setup.MARKER).exists()
    assert any("--force" in line for line in raised.value.fix)


def test_uninstall_deletes_it_and_can_be_run_again(managed_tex_dir):
    fake_installation(managed_tex_dir, marker=True)
    (managed_tex_dir.parent / "TinyTeX.download").mkdir()
    (managed_tex_dir.parent / "TinyTeX.unpacking-99").mkdir()
    assert tex_setup.uninstall() is True
    assert list(managed_tex_dir.parent.iterdir()) == []
    assert tex_setup.uninstall() is False


def test_install_and_uninstall_from_the_command_line(managed_tex_dir, tmp_path, quiet_install, monkeypatch, capsys):
    archive = tar_archive(tmp_path / "TinyTeX.tar.gz")
    monkeypatch.setattr(doctor, "compile_tex", lambda: TexCheck(
        str(managed_tex_dir / "bin" / "x86_64-linux" / "latex"), "dvisvgm", paths=100, seconds=1.0))
    assert doctor.main(["--install-tex", "--tex-archive", str(archive)]) == 0
    out = capsys.readouterr().out
    assert f"Setting up LaTeX for manim in {managed_tex_dir}" in out
    assert "LaTeX is ready" in out and "ok    LaTeX (for formulas): Formulas work: the LaTeX manimgl-doctor installed" in out
    assert doctor.main(["--install-tex"]) == 0
    assert "already set up" in capsys.readouterr().out
    assert doctor.main(["--uninstall-tex"]) == 0
    assert "Deleted the LaTeX" in capsys.readouterr().out
    assert doctor.main(["--uninstall-tex"]) == 0
    assert "There's no LaTeX set up by manimgl-doctor" in capsys.readouterr().out


def test_a_failed_install_from_the_command_line_says_what_to_do(managed_tex_dir, server, monkeypatch, capsys):
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    assert doctor.main(["--install-tex"]) == 1
    out = capsys.readouterr().out
    assert "Couldn't set up LaTeX: Couldn't download TinyTeX" in out and "404" in out
    assert "--tex-archive" in out
    assert "Traceback" not in out


@posix_only
@needs_latex
def test_a_whole_install_with_real_tex_behind_a_fake_tinytex(managed_tex_dir, tmp_path, server, monkeypatch):
    """
    The installer end to end, as on Linux: downloaded over HTTP, unpacked, tlmgr run as a program,
    and LaTeX really compiling the check document, through a bin folder whose latex and dvisvgm
    hand over to the ones installed here. Then the doctor finds it through PATH, with the
    system's LaTeX nowhere on it.
    """
    log = tmp_path / "tlmgr.log"
    latex, dvisvgm, kpsewhich = (tex_setup.shutil.which(name) for name in ("latex", "dvisvgm", "kpsewhich"))
    tar_archive(server.folder / "TinyTeX.tar.gz", scripts={
        "tlmgr": f'#!/bin/sh\necho "$@" >> "{log}"\necho "[1/1, 00:00/00:00] install: physics [3k]"\n',
        "latex": f'#!/bin/sh\nexec "{latex}" "$@"\n',
        "dvisvgm": f'#!/bin/sh\nexec "{dvisvgm}" "$@"\n',
        "kpsewhich": f'#!/bin/sh\nexec "{kpsewhich}" "$@"\n',
    })
    monkeypatch.setenv(tex_setup.URL_VARIABLE, f"{server.url}/TinyTeX.tar.gz")
    monkeypatch.setattr(tex_setup, "have_perl", lambda: True)
    said = []
    done = tex_setup.install(say=said.append)
    assert log.read_text().split() == ["install", *sorted(tex_setup.PACKAGES)]
    assert "  install: physics [3k]" in said
    assert (managed_tex_dir / tex_setup.MARKER).exists()

    no_tex = tmp_path / "no-tex"
    no_tex.mkdir()
    monkeypatch.setenv("PATH", str(no_tex))
    assert tex_setup.shutil.which("latex") is None
    tex_setup.use_managed_tex()
    result = run("latex")
    assert result.status == "ok", result.summary
    assert result.details["source"] == "managed" and result.details["latex"] == str(done.bin_dir / "latex")


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("MANIM_TEST_TINYTEX") != "1",
                    reason="downloads TinyTeX and packages from CTAN; set MANIM_TEST_TINYTEX=1 to run it")
def test_a_real_tinytex_install(tmp_path, monkeypatch):
    root = tmp_path / "TinyTeX"
    done = tex_setup.install(root, say=print)
    assert (root / tex_setup.MARKER).exists()
    check = tex_setup.check_installation(done.bin_dir)
    assert check.ok, check.problems
    print(f"TinyTeX: {done.size_bytes / 1e6:.0f} MB in {done.seconds:.0f} s, from {done.source}")
    assert tex_setup.install(root, say=print).already
    assert tex_setup.uninstall(root)
