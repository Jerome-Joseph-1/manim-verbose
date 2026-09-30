# Vectors, what even are they? (a recreation of the visuals)

This is the final acceptance test in [`docs/editor/PLAN.md`](../../docs/editor/PLAN.md): a
ten minute explanatory video written entirely as a scene file, with no Python. It recreates
the visuals of 3Blue1Brown's
[*Vectors, what even are they?*](https://www.youtube.com/watch?v=fNk_zzaMoSs)
(*Essence of linear algebra*, chapter 1).

The ideas, the order they come in and the visual style all belong to 3Blue1Brown (Grant
Sanderson). Nothing here is copied from the original: no audio, script or 3Blue1Brown assets.
On-screen captions, written for this recreation, stand in for the narration. The shapes are
the format's own: arrows, grids, text, formulas and simple polygons.

| File | What it is |
|------|------------|
| [`vectors.yaml`](vectors.yaml) | The video: 11 scenes, 248 steps and 111 captions, lasting 9:57.5 |
| [`storyboard.md`](storyboard.md) | What happens when, scene by scene, and a timing table |

## Checking and rendering

From the repository root:

```sh
manimgl-scene validate examples/eola_vectors/vectors.yaml       # ok, no errors or warnings
manimgl-scene format --check examples/eola_vectors/vectors.yaml # already in canonical form
manimgl-scene info examples/eola_vectors/vectors.yaml           # per scene timings, once render.timeline exists
manimgl-scene render examples/eola_vectors/vectors.yaml -q hd   # the video
manimgl-scene render examples/eola_vectors/vectors.yaml -s addition -q low   # one scene
```

(Before the package is installed, use `python -m manim_verbose.scenefile …` in place of
`manimgl-scene`.)

The file is in canonical form, so the editor's save round-trips it without changes.
Rendering hasn't been possible yet, because object and step code generation are still being
written. A render-and-review pass will follow once they land.

## How the file is put together

- **Scenes follow the original's sections**: the opening, the three views (one scene each),
  the coordinate system, coordinates, 3D, addition, addition with coordinates, scaling and
  the wrap-up. Every scene has a title.
- **Timing is explicit.** Every animated step has a `run_time` and every wait a `duration`,
  so the length doesn't depend on the renderer's defaults. A `together` step never uses
  `lag`, so it lasts exactly as long as its longest child. Each caption stays on screen for
  3 to 7 s, and many are set on a `wait` so they can be read while nothing moves.
- **Colours**: vectors YELLOW; x things GREEN, y things RED, z BLUE; in addition, `w` PINK
  and the sum ORANGE. The background is black.
- **Layout**: grids and axes fill the frame. Everything else stays above y = −3, leaving
  the caption band at the bottom clear. Text over a grid sits on a dark panel (see gap 4).
  The main plane is always the default full-frame `number_plane`: one unit per frame unit,
  with the origin at the centre. That way labels, which are placed in frame units, line up
  with vectors, which are placed in plane coordinates.
- **Continuity**: `coordinate_plane` ends on the grid, the axes and a vector, and
  `coordinates` declares the same objects with `shown: true`, so there is no cut between
  them. Every other scene starts from an empty frame, and the one before ends with `clear`.

## What the format couldn't say, and what was done instead

This list is feedback on the format, collected while writing the video. Each gap gives the
workaround used here and a suggestion.

1. **Nothing carries over from one scene to the next.** Continuing a picture across a scene
   boundary means declaring the plane, axes, origin dot and vector again in the next scene
   with `shown: true`, and keeping both copies in step by hand.
   *Suggestion:* a scene-level `carry: [ids]` (or `continue_from: <scene>`), which starts a
   scene with those objects as the last scene left them.

2. **A group whose members were shown one at a time isn't "on screen".** The two feature
   lines are written separately, then morphed together into the house vector. Transforming
   their group gave the warning "'features' isn't on screen", and hiding `scal_all` after
   showing its parts did the same.
   *Workaround:* a zero-time `add: features` before the transform, and hiding the parts by
   name. *Suggestion:* treat a group as on screen when all its members are, or let
   `transform` take a list of targets.

3. **Nothing stays facing the camera in 3D.** Free objects turn with the camera once it has
   an `orientation`, so the 3D scene can't show the column `[2; 1; 3]`, axis names, or
   numbers beside the steps.
   *Workaround:* the numbers are given in the captions, and the steps are colour-coded (green
   x, red y, blue z). *Suggestion:* `fixed: true` on free objects (manim's `fix_in_frame`),
   or keep text-like objects fixed in the frame whenever the camera is turned.

4. **No backdrop behind text on a grid.** 3Blue1Brown puts formulas on a dark rectangle so
   the grid doesn't run through them.
   *Workaround:* a `box` around the formula's group with `color: BLACK` and
   `fill_opacity: 0.85`, drawn at `z: 1` under the text at `z: 2`. *Suggestion:*
   `backdrop: true` on text, tex, matrix and group (manim's `add_background_rectangle`).

5. **Part of a matrix can't be picked out.** `highlight … part` and braces work only on
   text, formulas, titles and quotes, or on whole objects, so a row or entry of a `matrix`
   can't be indicated, recoloured or braced.
   *Workaround:* matrices are used where the rows only need colours (`row_colors`). The
   row labels in the house example are separate texts, placed `next_to` the matrix and
   shifted by ±0.42, which is a guess at the row spacing. Where a part has to be
   highlighted, the formula is a `tex` with `bmatrix`. *Suggestion:* matrix parts such as
   `row: 1`, `column: 0` or `entry: [1, 0]` for `highlight` and `brace`.

6. **It isn't specified where a vector's label goes.** `label_side` doesn't say whether the
   side is taken from the tip, the middle, or the arrow's bounding box, and a label can't be
   shown, hidden or moved separately from its arrow.
   *Workaround:* every label side was chosen so that it stays clear under both readings. In
   the numeric addition scene `w` has no label, because every side of its tip is taken by
   the red and green step arrows. *Suggestion:* define it as beside the tip, add
   `label_buff`, and allow `part: label` on show, hide and highlight.

7. **Braces only fit the sides of a bounding box.** The length of a slanted arrow can't be
   braced.
   *Workaround:* the physics arrow is horizontal. *Suggestion:* a brace given `from` and `to`
   points (manim's `BraceBetweenPoints`).

8. **Points on a number line are undefined.** `on:` accepts a `number_line`, but it isn't
   said what a point `[x, y]` means on one.
   *Workaround:* the arrows for 2 + 5 = 7 are in frame units. The number line runs from −1
   to 8 and is centred, so n sits at x = n − 3.5, worked out by hand. *Suggestion:* say that
   on a number line a point is `[n]` or `[n, height above the line]`.

9. **Free objects can't be placed in a coordinate system's coordinates.** Labels and
   coordinate columns are placed in frame units, while vectors use the plane's coordinates.
   This works only because the plane is the default full-frame one.
   *Suggestion:* `place: {at: [x, y], on: plane}`.

10. **Nothing follows anything.** When a vector's tip moves, its coordinate column doesn't
    move with it. The built-in `show_coordinates` would follow, but it can't colour the rows
    green and red.
    *Workaround:* each tip change runs `together` with a `change` of the column's `entries`
    and `place`. *Suggestion:* `row_colors` on `show_coordinates`, or a placement relative to
    a vector's tip (`next_to: v, anchor: tip`) that is kept as the vector changes.

11. **Pushing a moving object to an edge is ambiguous.** manim's `to_edge(UP)` moves only
    vertically, so `move … to: {edge: top}` on a label at x = −4.7 would leave it on the left.
    *Workaround:* `to: [0, 3.3]`. *Suggestion:* say whether `edge` keeps the other
    coordinate or centres it.

12. **Coordinates are plain numbers.** `⅓v` has its tip at `[1, 0.3333]`.
    *Suggestion:* allow fractions or simple expressions in points, such as `1/3`.

13. **No arc or angle marker** to show "direction".
    *Workaround:* the word "direction" beside the tip, while the arrow is indicated.
    *Suggestion:* an `arc` or `angle` object.

14. **Durations can't be known without rendering.** The default `run_time`s live in the
    renderer, which isn't written yet, `manimgl-scene info` doesn't run yet, and how long
    `together` with `lag` lasts isn't documented.
    *Workaround:* explicit times everywhere, no `lag` on `together`, and a small script that
    adds up durations and checks each caption's time on screen against its word count.
    *Suggestion:* document the defaults and the lag rule in `model.py`, and have
    `validate --timing` report caption reading times.

15. **The last caption stays up during the closing `clear`.**
    *Workaround:* `caption: ''` on some closing `clear` steps. *Suggestion:* have `clear`
    clear the caption as well, unless it sets one.

16. **Layout isn't checked.** Validation catches nothing off the frame, in the caption band,
    or overlapping. Layer 1 of the plan lists these checks, but they don't exist yet.
    *Workaround:* a script that measures text, formulas and matrices by building the real
    mobjects without a GPU, repeats the placements (`at`, `edge`, `next_to` chains, arranged
    groups) and the moves and changes, and flags any overlap after each step. It found five
    real problems here, all fixed. *Suggestion:* `validate --layout`, built on the same
    measurements.

17. **The canonical form is long, and its field order reads oddly.** `format` writes every
    object and step as a block mapping, so a 10 minute video is 2,200 lines. It puts
    `caption` and `run_time` before `target`, and `place` before `text`. It expands
    shorthands (`place: [0, 2]` becomes `place: {at: [0, 2]}`), and PyYAML folds long TeX
    strings across two lines. None of this changes the meaning, but it is much harder to
    read than the flow style the file was written in. Because `format --check` has to pass,
    the file can't keep that style.
    *Suggestion:* write short mappings in flow style on one line. Order step fields as
    `id, do, target, into, style, …, run_time, caption`, and object fields as
    `id, type, <content>, place, style`.

18. **3D axes have no axis labels, and a floor grid can't be put on them.** `axes_3d` takes
    no `x_label`/`y_label`/`z_label`, and a `number_plane` can't be put `on` the axes.
    *Workaround:* a faded `number_plane` with the same x and y ranges, which lines up with
    the axes only because both are centred on the origin.

19. **Scaling a copy while dimming the original is verbose.** Each of the three examples
    needs a `together` of a `transform` with `keep: true` and a `change` to `opacity: 0.35`,
    then another `together` to hide the copy and restore the opacity.
    *Suggestion:* `transform … keep: dim`, or a `dim` highlight style that lasts.

These all worked as hoped:

- `transform` with `keep`, and `change` of `tip`, `tail`, `entries` and `place`, as the
  workhorses.
- `together` for simultaneous steps.
- `shown` for continuity from one scene to the next.
- `camera` `orientation` for 3D.
- `row_colors` for coloured coordinates.
- `box` doubling as a backdrop.
- Captions set on `wait` steps.
