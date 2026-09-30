# Installing the manim editor

This guide is for people who don't program. It takes about fifteen minutes, most of it
waiting for downloads, and ends with the editor open in your web browser. You type a few
commands into a terminal; each one is given in full, to copy and paste.

You will:

1. install Python, if you don't have it;
2. install manim with one command;
3. run `manimgl-doctor`, which checks everything and tells you exactly what to do about
   anything missing;
4. start the editor with `manimgl-editor`.

You don't need to install LaTeX (for equations) yourself: `manimgl-doctor --install-tex` sets
up a copy just for manim. You never need Node.js.

## 1. Python

manim needs **Python 3.10, 3.11, 3.12 or 3.13**, 64-bit.

### Windows

1. Go to <https://www.python.org/downloads/> and click **Download Python 3.13**.
2. Run the installer. On its first screen, **tick "Add python.exe to PATH"**, then click
   **Install Now**.
3. Open **Terminal** (or **PowerShell**) from the Start menu. Everything below is typed there.

### macOS

1. Go to <https://www.python.org/downloads/> and click **Download Python 3.13**.
2. Open the downloaded file and follow the installer.
3. In Finder, open **Applications > Python 3.13** and double-click
   **Install Certificates.command**. (Without this, Python can't download anything securely.)
4. Open **Terminal** (Applications > Utilities > Terminal). Everything below is typed there.

### Linux

Python is already installed. manim also needs a few system packages: Pango and a compiler
(pip builds one part of manim, `manimpango`, on Linux), a Vulkan driver (Mesa's works on any
computer, even without a graphics card) and ffmpeg (for videos).

Debian, Ubuntu, Linux Mint:

    sudo apt install python3-venv python3-dev build-essential libpango1.0-dev pkg-config mesa-vulkan-drivers ffmpeg

Fedora (enable [RPM Fusion](https://rpmfusion.org/Configuration) first, for an ffmpeg which
can write H.264 video):

    sudo dnf install python3-devel gcc pango-devel pkgconf mesa-vulkan-drivers vulkan-loader ffmpeg

Arch, Manjaro:

    sudo pacman -S python base-devel pango pkgconf vulkan-swrast vulkan-icd-loader ffmpeg

## 2. Install manim

Find the newest release on <https://github.com/Jerome-Joseph-1/manim-verbose/releases>. Its
notes start with the exact command to copy. It looks like this, with the release's version
in place of `X.Y.Z` (twice):

**Windows:**

    py -m pip install "manimgl[editor] @ https://github.com/Jerome-Joseph-1/manim-verbose/releases/download/vX.Y.Z/manimgl-X.Y.Z-py3-none-any.whl"

**macOS:**

    python3 -m pip install "manimgl[editor] @ https://github.com/Jerome-Joseph-1/manim-verbose/releases/download/vX.Y.Z/manimgl-X.Y.Z-py3-none-any.whl"

**Linux:** first make a folder of its own for manim (a "virtual environment"), then install
into it:

    python3 -m venv ~/manim
    ~/manim/bin/python -m pip install "manimgl[editor] @ https://github.com/Jerome-Joseph-1/manim-verbose/releases/download/vX.Y.Z/manimgl-X.Y.Z-py3-none-any.whl"
    source ~/manim/bin/activate

The last line makes the `manimgl-...` commands available in this terminal. In every new
terminal, run `source ~/manim/bin/activate` again before using them (or type them as
`~/manim/bin/manimgl-editor` and so on).

The install downloads about 150 MB and takes a few minutes. Lots of text scrolls past; what
matters is that it ends with `Successfully installed ... manimgl-X.Y.Z ...`.

## 3. Check everything with manimgl-doctor

    manimgl-doctor

It checks your Python, manim, the editor, your graphics, LaTeX, ffmpeg and fonts, then draws
a small test picture. Each line starts with `ok`, `WARN` or `FAIL`, and every `FAIL` says what
to type to fix it:

```
manimgl-doctor: checking this computer can make manim videos

  ok    Python: Python 3.13.1, 64-bit (C:\Users\ann\AppData\Local\Programs\Python\Python313\python.exe)
  ok    manim itself: manimgl X.Y.Z loads (...)
  ok    The editor: The editor is installed, with its page built in
  ok    Graphics: Intel(R) UHD Graphics (IntegratedGPU, D3D12)
  FAIL  LaTeX (for formulas): LaTeX isn't installed, so formulas (equations) can't be drawn; everything else works
        To fix:
          Let manimgl-doctor set up a LaTeX just for manim (no administrator rights needed; a few
          minutes, a download of about 200 MB):
            manimgl-doctor --install-tex
  ok    ffmpeg (for videos): C:\...\ffmpeg.exe, with H.264
  ok    Fonts: 312 fonts
  ok    Test render: Drew a circle and text to a 320x180 picture in 2.1s

1 thing to fix: LaTeX (for formulas). Do what 'To fix' says above, then run manimgl-doctor again.
```

Do what it says, run `manimgl-doctor` again, and repeat until it says **Everything works**.
The [troubleshooting](#troubleshooting) section below goes through every problem it can
report. A `WARN` doesn't stop anything working.

## 4. LaTeX, for equations (only if manimgl-doctor says it's missing)

    manimgl-doctor --install-tex

This downloads [TinyTeX](https://yihui.org/tinytex/), a small LaTeX, and the LaTeX packages
manim uses, and checks it can typeset manim's equations. It needs no administrator password
and changes nothing outside its own folder:

| System  | Where it goes |
|---------|---------------|
| Windows | `%LOCALAPPDATA%\manim-verbose\TinyTeX` |
| macOS   | `~/Library/manim-verbose/TinyTeX` |
| Linux   | `~/.local/share/manim-verbose/TinyTeX` |

It downloads about 200 MB, then some packages, and takes a few minutes; it needs about 500 MB
of disk space. If it's interrupted, run it again: it carries on from where it stopped. Once
it's done, the editor uses it automatically (restart the editor if it was already running).
To remove it again: `manimgl-doctor --uninstall-tex`.

(If you already have a LaTeX, such as MiKTeX, MacTeX or TeX Live, and manimgl-doctor says it
works, you don't need this.)

## 5. Start the editor

    manimgl-editor my-video.yaml

The editor opens in your web browser. `my-video.yaml` is the file your video is saved in
(any name ending in `.yaml` will do); if it doesn't exist yet, it's created with a short
example to start from. To stop the editor, go back to the terminal and press **Ctrl+C**.

Next time, open a terminal (on Linux, `source ~/manim/bin/activate` first) and run the same
command to carry on where you left off.

## Updating and removing

**Update:** run the install command from step 2 again, with the new release's version.

**Remove:** first `manimgl-doctor --uninstall-tex` (if you used `--install-tex`), then
`py -m pip uninstall manimgl` (Windows), `python3 -m pip uninstall manimgl` (macOS), or just
delete the `~/manim` folder (Linux). Your `.yaml` files are left where they are.

## Troubleshooting

### Before manimgl-doctor runs

**"py", "python3" or "pip" is not recognized / command not found.** Python isn't installed,
or (Windows) "Add python.exe to PATH" wasn't ticked. Run the Python installer again, choose
**Modify**, and tick **Add Python to environment variables**. Then open a new terminal.

**"manimgl-doctor" / "manimgl-editor" is not recognized / command not found**, although the
install worked. The folder pip put them in isn't on your PATH (pip says which folder, in a
yellow warning). Either fix that as just above, or run them through Python instead, which
always works:

    py -m manim_verbose.doctor        (macOS/Linux: python3 -m manim_verbose.doctor)
    py -m manim_verbose.editor my-video.yaml

On Linux, run `source ~/manim/bin/activate` first.

**error: externally-managed-environment.** Your Python belongs to the system (Linux, or
Homebrew's Python on macOS) and won't let pip install into it. On Linux, use the virtual
environment in step 2. On macOS, install Python from python.org as in step 1 and use its
`python3`.

**The install fails while "Building wheel for manimpango"** (Linux). The system packages
from step 1 are missing: Pango's development files, `pkg-config` or a C compiler. Install
them as step 1 says for your Linux, then run the install command again.

**The install fails with "No matching distribution found for wgpu"**, or similar. Your Python
is 32-bit, or older than 3.10. Install the 64-bit Python 3.13 from python.org.

**The install is very slow or fails downloading.** Check you're online; behind a proxy, set
`HTTPS_PROXY` first. Re-running the same command carries on.

### What manimgl-doctor reports

**Python: too old.** Install Python 3.13 (step 1), then install manim again with it.

**Python: 32-bit.** manim's graphics need a 64-bit Python. On Windows, choose the "Windows
installer (64-bit)" on python.org.

**Python: newer than manim has been tested with** (a `WARN`). Usually fine. If something else
then fails, install Python 3.13 and use that.

**manim itself: installed but doesn't load.** Something went wrong installing it. Run the
install command from step 2 again, adding `--force-reinstall` after `install`. On Linux, if the
message mentions Pango, install the packages from step 1, then
`python -m pip install --force-reinstall --no-cache-dir manimpango`.

**The editor: installed without the editor.** The install command left out `[editor]`; run
the one from step 2, which has it.

**The editor: its page isn't built into this copy.** You installed manim from the source code
rather than from a release. Install from a release (step 2). (Working on the source code
itself? Build the page with Node.js: `cd editor-ui`, `npm ci`, `npm run build`.)

**Graphics: can't find a graphics adapter.** manim draws with your graphics card through
Vulkan (Linux), Metal (macOS) or DirectX 12 (Windows).
- Linux: install Mesa's Vulkan drivers, which include one that runs on the processor, so it
  works on any computer: `sudo apt install mesa-vulkan-drivers libvulkan1` (Fedora:
  `sudo dnf install mesa-vulkan-drivers vulkan-loader`; Arch:
  `sudo pacman -S vulkan-swrast vulkan-icd-loader`; openSUSE:
  `sudo zypper install libvulkan_lvp libvulkan1`).
- Windows: update the graphics driver: Settings > Windows Update > Advanced options >
  Optional updates, or from Intel, AMD or NVIDIA. In a virtual machine or over remote
  desktop, turn on 3D acceleration if it has any.
- macOS: every Mac from 2012 on has Metal with macOS 10.14 or later; update macOS. In a
  virtual machine, Metal may not be available.

**Graphics: drawing on the CPU.** Not a problem: it works, a few times more slowly than a
graphics card. Normal in virtual machines, and on Linux without a graphics card's Vulkan
driver (NVIDIA cards need NVIDIA's own driver).

**LaTeX: isn't installed.** Run `manimgl-doctor --install-tex` (step 4). On Linux you can use
your system's TeX Live instead:
`sudo apt install texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended texlive-fonts-extra texlive-science tipa cm-super dvisvgm`.

**LaTeX: can't typeset everything manim's formulas use** (it names the missing files). Your
LaTeX lacks some packages manim's equations use. Either run `manimgl-doctor --install-tex`,
which sets up a complete one that is then used instead of yours, or add the packages it names
to yours, with the command it gives (`sudo apt install ...`, `tlmgr install ...`, or MiKTeX
Console > Packages).

**LaTeX: setting up was started and didn't finish.** Run `manimgl-doctor --install-tex` again.

**`--install-tex`: couldn't download TinyTeX.**
- Check you're online and run it again. Behind a proxy, set `HTTPS_PROXY` first.
- macOS, with a message about certificates: do step 1.3 (Install Certificates.command).
- Or download the file it names yourself, in a browser, and give it to the installer:
  `manimgl-doctor --install-tex --tex-archive path/to/TinyTeX.tar.gz` (`.tgz` on macOS,
  `.zip` on Windows).

**`--install-tex`: tlmgr couldn't reach a TeX Live server.** The packages come from CTAN's
mirrors, one picked for you. Run it again later, or pick a mirror from
<https://ctan.org/mirrors>:
`manimgl-doctor --install-tex --tex-repository https://mirror.example.org/CTAN/systems/texlive/tlnet`.

**`--install-tex`: an older year of TeX Live than the servers.** TeX Live moves to a new year
each spring, and an old copy can't install from the new servers. Start again:
`manimgl-doctor --install-tex --force`.

**`--install-tex`: this computer has no perl** (Linux). `sudo apt install perl` (Fedora:
`sudo dnf install perl`), then run it again.

**`--install-tex`: no ready-made build for this computer** (Linux on ARM, such as a Raspberry
Pi). Install your system's TeX Live instead, as under "LaTeX: isn't installed" above.

**`--install-tex`: still can't typeset everything.** Run it again; if it fails the same way,
start from scratch with `manimgl-doctor --install-tex --force`.

**ffmpeg: isn't installed.** Pictures work without it, but previews and videos need it.
- Windows: `winget install --id Gyan.FFmpeg -e`, then open a new terminal.
- macOS: install [Homebrew](https://brew.sh), then `brew install ffmpeg`.
- Linux: `sudo apt install ffmpeg` (Fedora: `sudo dnf install ffmpeg` after enabling RPM
  Fusion; Arch: `sudo pacman -S ffmpeg`).

**ffmpeg: can't write H.264 video.** Your ffmpeg was built without H.264 (Fedora's own is).
On Fedora, enable RPM Fusion, then `sudo dnf swap ffmpeg-free ffmpeg --allowerasing`.
Elsewhere, install ffmpeg as above.

**Fonts: no fonts were found.** Very unusual; on Linux, `sudo apt install fonts-dejavu fontconfig`.

**Fonts: CMU Serif isn't installed** (a note, not a problem). Some scene files, like the
examples, ask for CMU Serif, the font of LaTeX documents. Without it, a similar font is used.
To install it: `sudo apt install fonts-cmu` on Debian and Ubuntu; elsewhere download
cm-unicode from <https://sourceforge.net/projects/cm-unicode/files/>, unzip it, and install
the `cmunrm`, `cmunbx`, `cmunti` and `cmunbi` `.otf` files (double-click each one).

**Test render failed.** Fix anything else manimgl-doctor reported first. If everything else is
`ok`, please report it, with what `manimgl-doctor --json` prints.

### Using the editor

**The browser doesn't open.** Open the address `manimgl-editor` prints yourself, usually
<http://127.0.0.1:8765/>. If that port is taken (by another editor, say), it uses the next
free one and prints that instead.

**Equations show an error in the editor, although manimgl-doctor says LaTeX works.** Stop
the editor (Ctrl+C) and start it again, so it picks up the LaTeX set up since it started.

## For reporting problems

`manimgl-doctor --json` prints everything it found, including your operating system and
versions, as text you can paste into a bug report. It doesn't include any of your files.
