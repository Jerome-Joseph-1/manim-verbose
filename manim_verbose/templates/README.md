# Templates

Ready-made scene files to start a video from. Each one is a short, finished video: it
renders as it is, and it shows one way of making a kind of video people actually make.

| Template | Title | Length | What it shows |
|----------|-------|--------|---------------|
| `blank` | Blank video | 0:04.5 | One scene with a title placeholder and a caption, nothing else |
| `welcome` | My first video | 0:49.5 | A tour: text, an equation, a highlight, a transform, shapes that change and move, steps run together, captions. New files in the editor start as this one |
| `equation_steps` | Solving an equation step by step | 0:38.5 | 3x + 5 = 20 solved one line at a time, each line grown from the one before, with notes and a boxed answer; then a check, transformed in place |
| `function_graph` | Graphing a function | 0:27 | Axes, f(x) = x², a point read off the curve with guide lines, the line g(x) = x + 2, and the point sliding to their second crossing |
| `geometry_proof` | A proof by rearranging shapes | 0:37.5 | Pythagoras by rearrangement: four triangles in a square, three of them slid, the space left over before and after |
| `vectors_and_matrices` | Vectors and a linear transformation | 0:32.5 | A grid, i-hat, j-hat and v, a matrix applied to all of them, and where each lands |
| `number_line` | Adding on a number line | 0:30 | 3/4 + 1/2 worked out by jumping along a line cut into quarters |
| `lesson_intro` | Lesson opener | 0:31.5 | A title card, a boxed list of what the lesson covers, a closing card |

Each template's `description` says what it is for and what to change first. `blank`,
`welcome` and `lesson_intro` need no LaTeX; the others use formulas, and so need LaTeX
installed to render.

## Using them

In the editor, pick one from the gallery when making a new file. From the command line:

```sh
manimgl-scene templates                               # name, title and description of each
manimgl-scene new lesson.yaml                         # a copy of `blank`
manimgl-scene new lesson.yaml --template number_line  # a copy of another one
manimgl-scene new lesson.json -t welcome              # the same, as JSON
```

`new` won't replace a file which already exists unless given `--force`.

## How they are made

All of them follow the same rules, which `tests/scenefile/test_templates.py` checks:

- `manimgl-scene validate` finds no errors and no warnings, and the file is in canonical
  form (`manimgl-scene format --check`), so the editor saves it back unchanged.
- `title` and `description` are set; every scene has a title too.
- A black background, and text in CMU Serif (`settings.font`), the Computer Modern of LaTeX,
  so words and formulas match. On Debian and Ubuntu it is `apt install fonts-cmu`; without
  it, text falls back to another font and still renders.
- Captions are plain words on one line (at most 90 characters), each on screen long enough to
  read: at least 3 seconds, and 0.3 seconds a word. Everything else stays above y = −3, clear
  of the caption band at the bottom.
- Every step says how long it takes (`run_time`, or `duration` for a wait), so the timing is
  there to read and change. Each template lasts 20 to 90 seconds, except `blank`.
- Objects have names a beginner can read (`question`, `answer`, `first_triangle`), not `t1`.
- Only kinds of object and step which render today: no scene `carry`, no `anchor` or
  `follow` placements, no `angle` or `arc` objects, no matrix parts, no braces between
  points and no `keep: dim` yet (see below).
- Each has a thumbnail `NAME.png` beside it: 480x270, at most 60 KB, a still of a
  representative step.

To add one: write `NAME.yaml` here, run `manimgl-scene format NAME.yaml`, check it with
`manimgl-scene validate`, render it (`manimgl-scene render NAME.yaml -q low`) and look at the
frame after every step, then make its thumbnail with
`manimgl-scene still NAME.yaml -s SCENE --step N -o NAME.png --width 480`. The editor's gallery
lists every `*.yaml` here, with the `.png` of the same name.

## What the newer parts of the format will improve

The format has gained features which are still being built (scene carry-over, anchored and
following placements, angles and arcs, matrix parts, braces between points, `keep: dim`).
Once they render, these templates can use them:

- `welcome`: `keep: dim` on the circle-to-square transform, so the original shows as the
  original; an `arc` with `arrow: true` for a curved arrow between the shapes.
- `equation_steps`: `keep: dim` to fade each line of working as the next is derived; notes
  placed `next_to` their line (`side: right`) rather than in a column at a fixed x; `carry`
  to take the equation into the check scene instead of declaring it again.
- `function_graph`: the reading placed `next_to: point, follow: true`, so it rides along with
  the point; a brace from `start: [2, 0]` to `end: [2, 4]` on the axes to show the height.
  (The point can only move in a straight line, which is why it slides along g rather than
  along the curve; moving along a graph is not among the new features.)
- `geometry_proof`: an `angle` with `right_angle: true` on the first triangle; braces between
  points for the sides a, b and a + b in place of plain letters; `carry` to split the proof
  into a "before" and an "after" scene.
- `vectors_and_matrices`: labels `next_to` a vector with `anchor: tip, follow: true`, so they
  ride through `apply_matrix` rather than being hidden and shown again at worked-out places;
  highlighting `part: column 1` and `column 2` of the matrix as i-hat and j-hat land.
- `number_line`: `arc` objects with `arrow: true` for the jumps, the usual curved hops, in
  place of straight arrows above the line; a label following the marker.
- `lesson_intro`: `carry` to keep the heading over several scenes. (Picking out one item of
  a bullet list, to reveal or highlight it alone, is still not possible.)
