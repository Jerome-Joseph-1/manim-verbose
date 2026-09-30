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

Every endpoint that takes a document validates it first. A document the models cannot read
at all gets `422` with `{"problems": [...]}`; one that reads but has errors is still saved
(nobody should lose work to a typo) and rendering endpoints answer `422` with its problems.

## Document

`GET /api/document` → `200`
```json
{ "document": {...}, "path": "/abs/path/lesson.yaml", "revision": 7, "problems": [...] }
```
The document comes back in canonical form: defaults left out, every step with an id.

`PUT /api/document` with `{ "document": {...}, "base_revision": 7 }` → `200`
```json
{ "revision": 8, "problems": [...], "document": {...} }
```
Saves to disk (atomically) in the file's format. `409` with the current
`{document, revision}` if `base_revision` is not the current revision, which happens when
the file was changed on disk or from another tab.

`POST /api/validate` with `{ "document": {...} }` → `200 { "problems": [...] }`

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
  "problems": [...]
}
```
The frame once step `step_index` has finished (`-1`: before the first step). `bbox` is in
pixels of the image, origin top left, `[x0, y0, x1, y1]`; `frame_bbox` in manim units,
`[xmin, ymin, xmax, ymax]`. Objects are listed in drawing order, so the last one containing
a click is the one on top. Results are cached by the content of the scene and the request.
A still request supersedes any still request still waiting from before; the superseded one
answers `409 {"superseded": true}`.

`POST /api/clip` with `{ document, scene_id, start_step, end_step }` → `200 { "video_url": "/files/clips/…mp4" }`

Low quality, for previewing a step or a few. Cached like stills.

`POST /api/code` with `{ document, scene_id? }` → `200 { "code": "from manimlib import *\n…" }`

`GET /api/timeline?scene_id=intro` → `200 { "steps": [ { "step_id", "index", "start", "duration" } ], "duration": 42.5 }`
(for the document as saved).

## Export

`POST /api/export` with `{ "document": {...}, "quality": "hd" }` → `202 { "job_id": "…" }`

`GET /api/jobs/{job_id}` → `200`
```json
{ "job_id": "…", "status": "running", "progress": 0.42, "message": "Rendering scene 3 of 7",
  "output_url": null, "problems": [] }
```
`status` is one of `queued`, `running`, `done`, `failed`, `cancelled`. When done,
`output_url` points at the MP4 under `/files/exports/`.

`DELETE /api/jobs/{job_id}` → `200 { "status": "cancelled" }`

## Files

`GET /files/{kind}/{name}` serves rendered stills, clips and exports. Nothing outside the
server's output folder is reachable.

`GET /api/health` → `200 { "ok": true, "version": "…" }`

## Errors

Anything that goes wrong comes back as problems, never as a stack trace: a LaTeX formula
that fails to compile becomes a problem on that object's `tex` field, a render that runs
past its time limit a problem on the scene. Unexpected failures are `500 {"problems": [...]}`
with the detail in the server log.
