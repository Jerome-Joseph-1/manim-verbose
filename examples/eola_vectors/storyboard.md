# Storyboard: *Vectors, what even are they?*, recreated as a scene file

This is the plan behind [`vectors.yaml`](vectors.yaml): what is on screen, and when. Times are
from the start of the video. Each numbered section is one scene in the file (its `id` is in
the heading). The captions quoted are the ones in the file. They were written for this
recreation and stand in for the narration.

Visual conventions, following the original: black background, vectors YELLOW, anything to do
with x GREEN, y RED, z BLUE. In the addition scenes the second vector `w` is PINK and the sum
ORANGE. Captions sit at the bottom of the frame, so everything else stays above y = −3
(frame units: the frame is about 14.2 × 8, with the origin at the centre).

## Timing

Every animated step has an explicit `run_time` and every wait a `duration`. `add` and `remove`
take no time, and a `together` step lasts as long as its longest child (none of them uses
`lag`).

| # | Scene | Title | Steps | Captions | Starts | Duration |
|---|-------|-------|------:|---------:|-------:|---------:|
| 1 | `opening` | Title card and opening quote | 8 | 0 | 0:00.0 | 0:30.0 |
| 2 | `physics_view` | Three views of a vector; the physics student | 27 | 13 | 0:30.0 | 1:04.5 |
| 3 | `cs_view` | The computer science student | 23 | 10 | 1:34.5 | 0:51.5 |
| 4 | `math_view` | The mathematician | 12 | 6 | 2:26.0 | 0:32.5 |
| 5 | `coordinate_plane` | A coordinate system | 20 | 9 | 2:58.5 | 0:45.5 |
| 6 | `coordinates` | Coordinates as instructions | 25 | 12 | 3:44.0 | 0:57.0 |
| 7 | `three_d` | Three dimensions | 22 | 11 | 4:41.0 | 0:57.5 |
| 8 | `addition` | Adding vectors, and why tip to tail | 37 | 17 | 5:38.5 | 1:17.5 |
| 9 | `addition_numbers` | Adding vectors with coordinates | 25 | 11 | 6:56.0 | 0:58.0 |
| 10 | `scaling` | Scaling, and what a scalar is | 28 | 13 | 7:54.0 | 1:10.0 |
| 11 | `wrap_up` | Moving between the views, and what's next | 21 | 9 | 9:04.0 | 0:53.5 |
| | **Total** | | 248 | 111 | | **9:57.5** |

The original runs 9:52. Every caption has at most 12 words and stays on screen for 3 to 7
seconds, allowing at least 0.3 s per word.

## 1. `opening`: title card and opening quote (0:00–0:30)

- **0:00** The title card: "Vectors, what even are they?" and "Essence of linear algebra,
  chapter 1". Beneath them, a note that this recreates the visuals of the 3Blue1Brown video
  using a manim scene file, the credit to 3Blue1Brown (Grant Sanderson), and a line saying
  that the captions stand in for the narration. Held for 8 s.
- **0:14.5** The card fades out. Hermann Weyl's line, "The introduction of numbers as
  coordinates is an act of violence.", is written out as a quote and held for 10 s.

## 2. `physics_view`: three views, then the physics student (0:30–1:34.5)

- **0:30** "What is a vector?" at the top. Three headings fade in across the frame: *Physics
  student*, *Computer science student* and *Mathematician*.
- **0:40.5–0:56** One icon appears under each heading in turn, with a caption: an arrow, a
  column of numbers `[2,600; 300,000]`, and `v + w   2v`.
- **0:56** Everything fades except *Physics student*, which moves to the top centre.
- **1:00.5** A horizontal yellow arrow grows. A brace labelled "length" appears under it, then
  the word "direction" beside its tip while the arrow is indicated.
- **1:15** The brace and label fade. The arrow slides to the top left, then down to the right,
  then back, without turning ("…as far as physics cares, nothing has changed").
- **1:22.5** Four identical copies grow around the frame: "Equal length, equal direction:
  every one of these is the same vector." Then a caption on 2D against 3D vectors.

## 3. `cs_view`: the computer science student (1:34.5–2:26)

- **1:34.5** Heading *Computer science student*: "a vector is a list of numbers".
- **1:40** A simple house (teal square, red roof, door) is drawn on the left.
- **1:45.5** "Floor area: 2,600 sq ft" is written on the right, then "Price: $300,000".
- **1:52.5** The two lines morph into the column vector `[2,600 ft²; $300,000]`, with grey
  labels "floor area" and "price" beside its rows.
- **1:58.5** The vector is indicated: in this view the list *is* the vector. A brace on its
  left reads "2 entries", which makes it two-dimensional.
- **2:13.5** The entries swap places ("a very strange house"), then swap back: the order
  matters.

## 4. `math_view`: the mathematician (2:26–2:58.5)

- **2:26** Heading *Mathematician*. `v + w` ("adding") and `2 · v` ("multiplying by a
  number") are written in two columns.
- **2:41.5** Below them, examples: an arrow and a list of numbers, then small axes with a
  sine wave ("stranger things, which turn up later in the series").
- **2:52.5** "That abstract view can wait. First, connect the other two."

## 5. `coordinate_plane`: a coordinate system (2:58.5–3:44)

- **2:58.5** A horizontal number line with ticks is drawn, labelled "x-axis" in green.
- **3:07.5** A vertical one is drawn, labelled "y-axis" in red.
- **3:11.5** A dot pops in at the origin, labelled "origin", with a flash.
- **3:17** A yellow unit segment from 0 to 1, with a brace labelled 1: ticks are one unit
  apart, and you choose how long a unit is.
- **3:27** The full grid is drawn behind the axes.
- **3:33** The vector `[-2, 3]` grows from the origin. Unlike the physicist's arrows, its tail
  stays at the origin. The axis names fade, and the next scene carries on from this frame.

## 6. `coordinates`: coordinates as instructions (3:44–4:41)

This scene starts from the frame where the last one left off (the grid, axes, origin dot and
vector are declared `shown`).

- **3:44** The column `[-2; 3]` appears near the tip, -2 in green and 3 in red. It is
  indicated as "a recipe for getting from the tail to the tip". The column form keeps
  vectors apart from points.
- **3:58.5** A green arrow runs along the x-axis from 0 to −2, labelled −2: "head left: two
  units".
- **4:07** A red arrow runs up from (−2, 0) to (−2, 3), labelled 3: "head up: three units".
  The vector is indicated: the trip ends at its tip.
- **4:20.5** The steps fade. The vector's tip moves to `[3, 1]`, `[4, −1]` and `[−4, −2]`,
  and back to `[-2, 3]`, with its coordinates following it: every pair gives one vector and
  every vector one pair.

## 7. `three_d`: three dimensions (4:41–5:38.5)

- **4:41** 3D axes and a faint floor grid, seen from straight above, so they look flat.
- **4:46.5** The camera swings to a 3D view (θ −30°, φ 70°) and the z axis appears.
- **4:57.5** The instructions for `[2, 1, 3]` are drawn as arrows, one at a time: green along
  x, red parallel to y, blue up parallel to z. The numbers are given in the captions (see
  README, gap 3).
- **5:08** The yellow vector `[2, 1, 3]` grows to where the steps end.
- **5:13** The camera orbits to θ 20° while the captions say that triples of numbers and
  vectors in space match one to one.
- **5:24.5** The steps fade. The vector changes to `[−3, 2, 1]`, then `[1, −3, 2]`, and the
  camera moves again.

## 8. `addition`: tip to tail, and why (5:38.5–6:56)

- **5:38.5** The grid is drawn and "Vector addition" appears top left on a dark panel.
- **5:46** `v = [1, 2]` (yellow) and `w = [3, −1]` (pink) grow from the origin.
- **5:51** `w` slides so that its tail sits on `v`'s tip.
- **5:56** The sum (orange, labelled `v + w`) grows from the origin to `w`'s tip, and is
  indicated.
- **6:04.5** The same construction is shown for another pair (`v = [−2, 1]`, `w = [3, 2]`),
  then goes back.
- **6:11.5** "But why should addition work like this?" A white dot at the origin walks along
  `v`, then along `w`, and the sum flashes: the two trips together equal the single trip
  `v + w`.
- **6:33.5** The screen clears. A number line from −1 to 8 is drawn. Arrows of 2 and then 5
  are laid end to end above it, and a 7 arrow above those. `2 + 5 = 7` is written.
- **6:50** "Vector addition carries that idea off the line, into the plane."

## 9. `addition_numbers`: adding with coordinates (6:56–7:54)

- **6:56** The grid, `v = [1, 2]`, and `w` already placed tip to tail. On a dark panel at the
  top left: `[1; 2] + [3; −1]`, x entries green and y entries red.
- **7:07** `v` as steps: green one right, red two up. Then `w`: green three right, red one
  down.
- **7:17** The steps are regrouped: `w`'s green step drops onto the x-axis to follow `v`'s,
  and `v`'s red step moves over to x = 4. The result is 1 + 3 along x, and 2 then −1 up and
  down.
- **7:22.5** The panel continues: `= [1 + 3; 2 + (−1)] = [4; 1]`. The sum grows, and `[4; 1]`
  is indicated.
- **7:38.5** On a second panel at the lower left, the general rule
  `[x₁; y₁] + [x₂; y₂] = [x₁ + x₂; y₁ + y₂]`. The x part is indicated in green, then the y
  part in red.

## 10. `scaling`: scaling and scalars (7:54–9:04)

- **7:54** The grid, and `v = [3, 1]` labelled `v`.
- **7:59.5** A copy of `v` grows into `2v` while `v` dims. It then fades, and `v` returns to
  full strength.
- **8:06.5** The same for `⅓v`.
- **8:13.5** The same for `−1.8v`, which flips round, then stretches. `2v` and `⅓v` return,
  so that all three are on screen: this is scaling.
- **8:27** On a dark panel at the top left, `2   ⅓   −1.8` appear, then the word "Scalars"
  above them, which is indicated. Scaling vectors is most of what numbers do here, so
  "scalar" is used almost to mean "number".
- **8:46.5** The panel is replaced with `2 · [3; 1] = [6; 2]`, and `2v` stays on screen. Then
  every coordinate is multiplied by the same scalar, and the entries morph into
  `2 · [x; y] = [2x; 2y]`.

## 11. `wrap_up`: moving between the views, and what's next (9:04–9:57.5)

- **9:04** On the left, the column `[2; 1]`. On the right, a small grid with the arrow
  `[2, 1]`. Neither view is the whole story: the payoff is in switching between them.
- **9:14** An arrow points from the list to the picture, labelled "data analysis". Five thin
  white vectors appear on the small grid, their tips roughly in a line: many lists at once
  can show a pattern.
- **9:24.5** An arrow points back from the picture to the list, labelled "physics,
  graphics". The list is indicated, since computers crunch the numbers. Then the arrow is
  indicated: this video itself was made by turning arrows into numbers, and then into pixels.
- **9:41** "Coming up next", with bullets: *Linear combinations*, *Span*, *Basis vectors*.
- **9:49.5** The caption clears. A credit line for 3Blue1Brown's *Essence of linear algebra*
  fades in, holds for 4.5 s, and everything fades out at 9:57.5.
