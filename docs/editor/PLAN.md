# Manim for people who don't write Python: plan

## Goal

Anyone who can use a slide editor should be able to make a manim video: pick objects and
animations, see the result, click on something to change it, export an MP4. Nobody should
have to install LaTeX by hand, learn the manim API, or read a Python traceback.

Final acceptance test: a roughly ten minute recreation of the visuals of a 3Blue1Brown
video, built only with the scene file format and rendered with our tools (see the last
section).

## Architecture

```
  editor-ui/ (TypeScript, browser)          manim_verbose/editor/ (Python server)
  ┌──────────────────────────────┐   HTTP   ┌──────────────────────────────────────┐
  │ step list / timeline         │ ───────▶ │ load/save the scene file             │
  │ canvas: frame + click boxes  │          │ validate → problems in plain words   │
  │ properties panel (from schema)│ ◀─────── │ still frames + object boxes (cached) │
  │ undo/redo, autosave          │          │ preview clips, export jobs           │
  └──────────────────────────────┘          └──────────────┬───────────────────────┘
                                                            │ render worker processes
                                            manim_verbose/scenefile/ (Python)
                                            model.py     the format (pydantic) → schema.json
                                            validate.py  friendly errors, whole document checks
                                            blocks.py    objects → Python expressions
                                            actions.py   steps → Python lines
                                            codegen.py   scene file → a Python module
                                            runtime.py   DocScene: steps, captions, stills
                                            render.py    stills, clips, full videos
                                                            │
                                                         manimlib (unchanged, wgpu renderer)
```

Decisions that everything else rests on:

- **The scene file is the only source of truth.** YAML or JSON, defined once in `model.py`.
  The json schema the editor builds its forms from is generated from those models.
- **Scene files compile to readable Python**, and that code is the only path to a video, so
  "export to Python" gives exactly what the editor showed.
- **Every object and step has a stable id**, so a click on the canvas maps to exactly one
  entry in the file, and errors can be shown beside the field they are about.
- **Scene files are data, not code.** Nothing a user types is ever `eval`ed (function graphs
  go through a whitelisting parser), which is what makes a hosted version possible later.
- **manimlib is imported only through `manim_verbose.manim_import`**, because importing it
  parses `sys.argv` with manim's own parser.

## Milestones

| # | Milestone | Done when |
|---|-----------|-----------|
| 1 | Scene file core | every object and step kind renders; `manimgl-scene render` makes an MP4; test layers 1–3 green |
| 2 | Server | every endpoint in `server-api.md` works against real renders; layer 4 green |
| 3 | Browser editor | a new user can build, preview and export a scene without touching a file; layers 5–6 green |
| 4 | Install and templates | `pip install manimgl[editor]` then `manimgl-editor` works on Linux, macOS, Windows; layer 7 green |
| 5 | Real users | five people new to manim finish the set tasks unaided; every place they got stuck is fixed and has a test |
| ✓ | Final test | the ten minute video renders from a scene file, and holds up next to the original |

Milestones 1–3 are being built in parallel against the contract in `model.py`,
`codegen.py`/`blocks.py`/`render.py` (interfaces in their docstrings) and `server-api.md`.

## Workstreams

| Workstream | Owns | Builds against |
|------------|------|----------------|
| Objects | `scenefile/blocks.py`, `layout.py`, `expressions.py`, their tests | `model.py`, `CodegenContext` |
| Steps and rendering | `scenefile/codegen.py`, `actions.py`, `runtime.py`, `render.py`, render tests, golden images | `model.py`, `blocks.py` interface |
| Server | `manim_verbose/editor/` (except `static/`), its tests | `render.py` interface, `server-api.md` |
| Browser editor | `editor-ui/` (builds into `manim_verbose/editor/static/`) | `schema.json`, `server-api.md` |
| CI and packaging | `.github/workflows/`, packaging checks, install matrix | everything |
| Final video | `examples/eola_vectors/` | the format |

Shared files (`model.py`, `validate.py`, `files.py`, `setup.cfg`) change only through the
integrator, so that parallel work merges cleanly.

## Testing

| Layer | What it proves | Tools | Runs |
|-------|----------------|-------|------|
| 1. Core | validation and its messages; every object and step kind generates code that runs (animations skipped, no pixels); layout rules (inside the frame, no overlaps, `below` is below); save/load round trips | pytest | every push |
| 2. Randomized | thousands of generated valid documents compile and run; random edits keep a document valid; broken files always give a friendly error, never a traceback | Hypothesis | every push |
| 3. Rendering | golden frames for every kind of object and step, compared as `tests/render_compare.py` does; frame counts; each step draws something; speed budgets | software Vulkan (Mesa lavapipe) | every PR |
| 4. Server | every endpoint, good and bad input; stale renders are dropped; exports can be cancelled; errors land on the right field; limits and timeouts | pytest + httpx | every push |
| 5. Editor components | edits and undo/redo; every kind of field; click hit-testing including overlaps; dragging | Vitest | every push |
| 6. End to end | scripted user journeys in real Chromium against the real server and real renders; screenshots of the UI; accessibility; a chaos run of random input | Playwright | every PR |
| 7. Install | a built wheel installs into a clean environment on Linux, macOS and Windows, Python 3.10–3.13, and renders a frame | GitHub Actions matrix | nightly, and before a release |
| 8. People | five people new to manim, set tasks, watched | by hand | each milestone |

Rendering without a GPU was checked in a container with no display: the wgpu renderer picks
up Mesa's CPU Vulkan driver, and a three second clip renders in about four seconds.

## Final test: a ten minute video

Recreate the visuals of *Vectors, what even are they?* (Essence of Linear Algebra, chapter 1,
3Blue1Brown, 9:52) as a scene file, `examples/eola_vectors/vectors.yaml`:

- the three views of a vector (physics, computer science, mathematics);
- vectors on a coordinate plane, and coordinates as instructions for getting to the tip;
- three dimensions;
- adding vectors, tip to tail, and why that is the natural definition;
- scaling vectors, and what a scalar is;
- how the pictures and the lists of numbers correspond.

It uses on-screen captions written for this recreation in place of narration. No audio or
script from the original is copied; the aim is to show the format can carry a real
explanatory video of that length. It passes when:

- `manimgl-scene validate` reports no errors or warnings;
- `manimgl-scene info` totals between 9:30 and 10:30;
- `manimgl-scene render -q hd` produces the video with no manual steps;
- the scene file opens in the editor, and a scene can be changed and re-previewed there.

## Before any hosted version

Running on someone's own machine, a scene file can do no more than its author could. A
server rendering other people's files needs these closed first:

- LaTeX reads files: a formula containing `\input{/etc/passwd}` would typeset it. Formulas
  need filtering in validation (no `\input`, `\include`, `\openin`, `\read`, `\write`,
  `\immediate`, catcode changes), and LaTeX run with `openin_any=p`, `openout_any=p` and
  shell escape off.
- Renders need CPU, memory and time limits per request, and a cap on the total video length.
- Image and svg paths are already confined to the scene file's folder; uploaded files need
  type and size checks.
