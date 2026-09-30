# Editor server API

`manimgl-editor lesson.yaml` starts a server on `127.0.0.1:8765` (by default), serves the
editor at `/`, and the API below under `/api`. The server edits one scene file, the one it
was started with. All bodies are JSON.

A **document** below is a scene file as JSON data (see `manim_verbose/scenefile/schema.json`).
A **problem** is:

```json
{
  "message": "There's no object called 'eqq' in scene 'intro' (did you mean 'eq'?)",
  "severity": "error",                      // or "warning"
  "loc": ["scenes", 0, "steps", 3, "target"],
  "path": "scenes[0].steps[3].target",
  "scene_id": "intro",                      // null when not inside a scene
  "item_id": "intro_4"                      // id of the object or step it is about, or null
}
```

A problem with the request itself rather than the document in it (an unknown `scene_id`,
a `step_index` out of range, a field of the wrong type) has a `loc` naming the request's
field, such as `["step_index"]`, rather than a path into the document; its `scene_id` and
`item_id` are null unless it concerns a scene. Its message is meant for a developer as much
as a user. Numbers in requests have to be JSON numbers (`"3"` is refused) and are `422`
otherwise.

Every endpoint that takes a document validates it first. A document the models cannot read
at all gets `422` with `{"problems": [...]}`; one that reads but has errors is still saved
(nobody should lose work to a typo) and rendering endpoints answer `422` with its problems.
Rendering endpoints which render one scene (still, clip, and code with a `scene_id`) only
refuse for errors in that scene or in no scene; errors in other scenes come back in their
`problems` with a `200`, so a typo in one scene never stops the others being previewed.
Export, and code for the whole document, refuse for an error anywhere.

## Document

`GET /api/document` → `200`
```json
{ "document": {...}, "path": "/abs/path/lesson.yaml", "revision": 7, "problems": [...] }
```
The document comes back in canonical form: defaults left out, every step with an id.
`document` is `null` when the file can't be read as a scene file at all (broken YAML, say,
from an edit outside the editor), with `problems` saying why; saving a document replaces it.
Revisions start at 1, and every GET first checks the file on disk: an edit made outside the
editor gives the next revision.

`PUT /api/document` with `{ "document": {...}, "base_revision": 7 }` → `200`
```json
{ "revision": 8, "problems": [...], "document": {...} }
```
Saves to disk (atomically) in the file's format, in canonical form (a hand-written file's
comments don't survive its first save). `409` with the current
`{document, revision, problems}` if `base_revision` is not the current revision, which
happens when the file was changed on disk or from another tab. Saving a document identical
to the saved one writes nothing and keeps the revision. `422` for a document the models
can't read (nothing is saved), `413` for a body over the size limit, and
`500 {"problems": [...]}` if the disk refuses the write, in which case the file is untouched.

`POST /api/validate` with `{ "document": {...} }` → `200 { "problems": [...] }`, whether or
not the models can read the document (`422` only for a malformed request).

## Format

`GET /api/schema` → the json schema of a document.

`GET /api/catalog` → what the editor offers to add, with defaults to start from:
```json
{
  "objects": [
    { "type": "tex", "label": "Equation", "category": "Text & math",
      "description": "A LaTeX formula, in math mode.",
      "template": { "type": "tex", "tex": "e^{i\\pi} + 1 = 0" } }
  ],
  "steps": [
    { "do": "show", "label": "Show", "description": "Bring objects onto the screen.",
      "template": { "do": "show", "target": "" } }
  ]
}
```
Every kind of object and step is listed, in the order of the schema. Steps have no
`category`. A template has no `id`, for the editor to give it, and leaves each reference to
another object (`target`, `into`, `on`, `members`, …) as `""`, for the editor to fill in
from the selection or leave for the user to pick. With those filled in, every template is a
valid object or step.

## Rendering

`POST /api/still` with
```json
{ "document": {...}, "scene_id": "intro", "step_index": 3, "width": 960 }
```
→ `200`
```json
{
  "image_url": "/files/stills/5f2c…png",
  "width": 960, "height": 540,
  "objects": [ { "id": "eq", "bbox": [412.5, 40.0, 690.1, 96.3], "frame_bbox": [-1.2, 2.9, 2.1, 3.6] } ],
  "coordinate_systems": [
    { "id": "plane", "type": "number_plane", "origin": [480.0, 270.0],
      "x_unit": [67.5, 0.0], "y_unit": [0.0, -67.5], "z_unit": null }
  ],
  "problems": [...]
}
```
The frame once step `step_index` has finished (`-1`: before the first step; the default).
`width` defaults to 960 and may be 64 to 3840; the height follows from the document's
resolution. `bbox` is in pixels of the image, origin top left, `[x0, y0, x1, y1]`;
`frame_bbox` in manim units, `[xmin, ymin, xmax, ymax]`. Objects are listed in drawing
order, so the last one containing a click is the one on top. Results are cached by the
content of the scene and the request (steps after `step_index` don't count, nor do other
scenes), including across restarts of the server.

`coordinate_systems` has an entry for each number plane, set of axes, 3D axes and number
line on screen, saying where its coordinates land in the image, so that a drag on the picture
can be turned into coordinates on it: the point `(x, y)` of the system is at pixel
`origin + x * x_unit + y * y_unit` (and `+ z * z_unit` for 3D axes, whose `z_unit` is
otherwise `null`). All are in pixels of the image, measured on the scene as the still left it
(after any camera move or change). For a number line, `x_unit` runs along the line and
`y_unit` is one frame unit up, matching how a point `[n, height]` on a number line is read.
A system which can't be measured is left out; the list is never a reason for a still to fail.

Stills are drawn one at a time. A still request supersedes any still request still waiting
from before; the superseded one answers `409 {"superseded": true}`. This holds for every
still request, including one answered at once from the cache, and one which reaches the
server after a newer one did. The still being drawn is never superseded, and a request for
exactly that still waits for it and shares its result.

`POST /api/clip` with `{ document, scene_id, start_step, end_step }` →
`200 { "video_url": "/files/clips/…mp4", "problems": [...] }`

Low quality, for previewing a step or a few: steps `start_step` (default 0) to `end_step`
(default: the last step) inclusive, from the state the earlier steps left. Cached like
stills. Clips go ahead of exports waiting to start, and never wait for stills.

`POST /api/code` with `{ document, scene_id? }` → `200 { "code": "from manimlib import *\n…" }`

`GET /api/timeline?scene_id=intro` →
`200 { "steps": [ { "step_id", "index", "start", "duration" } ], "duration": 42.5, "revision": 7 }`
for the document as saved; `revision` says which saved revision it describes. `scene_id` is
required.

## Export

`POST /api/export` with `{ "document": {...}, "quality": "hd" }` → `202 { "job_id": "…" }`

`quality` is one of `low`, `medium`, `hd` (the default) and `uhd`. `429` when too many
exports are already waiting or running.

`GET /api/jobs/{job_id}` → `200`
```json
{ "job_id": "…", "status": "running", "progress": 0.42, "message": "Rendering scene 3 of 7",
  "output_url": null, "problems": [] }
```
`status` is one of `queued`, `running`, `done`, `failed`, `cancelled`. `progress` runs from
0 to 1 and never goes back; it reaches 1 only when done. When done, `output_url` points at
the MP4 under `/files/exports/`, named after the scene file (`lesson-hd-3f2a9c1b.mp4`). When
failed, `problems` says why. Unknown ids are `404`; the server forgets finished jobs beyond
the newest hundred.

`DELETE /api/jobs/{job_id}` → `200 { "status": "cancelled", ... }`, the job as `GET` gives
it. A job which has already finished is left as it is, and its status says so (`done`,
say). A running export is asked to stop, and killed if it hasn't within a few seconds.

## Pictures

`POST /api/assets`, a `multipart/form-data` body with the file in a part called `file` →
`200 { "path": "assets/cat.png", "kind": "png" }`

Saves a picture for an image or svg object in the folder `assets/` beside the scene file (made
if need be), and gives its path relative to the scene file, ready for the object's `path`.
What is accepted is decided by the file's content, never its name or claimed type: PNG, JPEG,
GIF and WebP pictures, and SVG drawings (XML with an `<svg>` root and no DTD). Its name is the
name it was sent with made safe (only the last part of it, in letters, digits, `-` and `_`,
at most 48 of them), with the extension its content calls for: `../My Cat.JPG` holding a PNG
is saved as `assets/My-Cat.png`. The same picture sent again gets the same path back; a
different one of the same name is saved beside it as `cat-2.png`, `cat-3.png`, and so on.
Nothing is ever written outside `assets/`, and an `assets` which is a link elsewhere is
refused.

| Answer | When |
|--------|------|
| `413` | the file is over 10 MB (the only request allowed a body over 5 MB) |
| `415` | the content isn't one of those pictures, or the body isn't multipart |
| `422` | the file is empty, or the upload has no file in it |
| `500` | the folder can't be written to |

each with `{"problems": [...]}` whose `loc` is `["file"]`.

## Templates

Videos to start from. Every `*.yaml` scene file in `manim_verbose/templates/` is one, named
by its file name; its title and description are the document's own, and a picture of it is
`<name>.png` beside it, if there is one. The folder is read on each request, so templates
added while the editor runs are offered at once; one that can't be read as a scene file is
left out (and logged).

`GET /api/templates` → `200`
```json
{ "templates": [
  { "name": "vectors", "title": "Vectors on a plane", "description": "…",
    "thumbnail_url": "/api/templates/vectors/thumbnail.png" }
] }
```
in order of name; `thumbnail_url` is `null` for a template with no picture.

`GET /api/templates/{name}` → `200`, the same fields and `"document": {...}` (in canonical
form, with step ids) and `"problems": [...]`; `404` for a name that isn't a template.

`GET /api/templates/{name}/thumbnail.png` → the picture, or `404`.

`POST /api/templates/{name}/apply` with `{ "base_revision": 7 }` → saves the template in place
of the document, exactly as `PUT /api/document` would with the template's document: the same
answer, a new revision, and `409` with the current version when `base_revision` isn't the
latest. (The editor applies templates itself, as an edit it can undo, from
`GET /api/templates/{name}`; this is for tools.)

## Files

`GET /files/{kind}/{name}` serves rendered stills (`/files/stills/*.png`), clips
(`/files/clips/*.mp4`) and exports (`/files/exports/*.mp4`). Nothing outside the server's
output folder is reachable. Stills and clips are named by their content and sent as
immutable; exports are not cached. The output folder is `--output-dir`, or by default a
folder for the scene file in the user's cache (`~/.cache/manim-verbose/editor/` on Linux).

`GET /api/health` → `200 { "ok": true, "version": "…" }`

## The editor itself

Every other `GET` serves the built editor from `manim_verbose/editor/static/`: a file if it
exists, `index.html` for any other path without a file extension (so the editor can use
client-side routes), and `404` for a missing file with one. Unknown paths under `/api/` and
`/files/` are always `404 {"problems": [...]}`. Before the editor is built, every page is
one explaining how to build it (`cd editor-ui && npm install && npm run build`).

The API is same-origin only: there are no CORS headers. While developing the editor, proxy
`/api` and `/files` through the dev server. When listening on this computer only (the
default), the server answers only requests addressed to `localhost`, `127.0.0.1` or `[::1]`
(on any port), and `400` otherwise, so web pages elsewhere can't reach it by DNS rebinding.

## Errors

Anything that goes wrong comes back as problems, never as a stack trace: a LaTeX formula
that fails to compile becomes a problem on that object's `tex` field (`422`), a render that
runs past its time limit a problem on the scene (`422`, `loc: ["scenes", i]`). A renderer
which crashes is restarted, and that request answers `500`. Unexpected failures are
`500 {"problems": [...]}` with the detail in the server log. Unknown routes are `404` and
wrong methods `405`, both with problems.

## Limits

| Limit | Value | Answer |
|-------|-------|--------|
| Request body | 5 MB | `413` |
| An uploaded picture (`/api/assets`) | 10 MB | `413` |
| Scenes in a document | 100 | `422`, `loc: ["scenes"]` |
| Objects in a scene | 500 | `422`, `loc: ["scenes", i, "objects"]` |
| Steps in a scene, counting those inside `together` | 1000 | `422`, `loc: ["scenes", i, "steps"]` |
| Still width | 64 to 3840 pixels | `422`, `loc: ["width"]` |
| Time to draw a still | 60 s | `422`, a problem on the scene |
| Time to render a clip | 5 min | `422`, a problem on the scene |
| Time to render an export | 4 h | the job fails |
| Exports waiting or running | 10 | `429` |

The size limits apply to every endpoint taking a document (`/api/validate` reports them as
problems with a `200`).
