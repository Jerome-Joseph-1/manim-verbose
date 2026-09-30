// A stand-in for the layout checker (POST /api/layout): for each step of a scene, whether
// something on screen goes off the edge of the picture, or text sits on top of other text,
// from the mock's own guesses at where things are (layout.mjs). Each problem is reported once,
// at the first step it happens, as a warning about the object, naming the step.
import { FRAME_HEIGHT, FRAME_WIDTH, carriedSpecs, layoutScene, sceneStateAfter } from './layout.mjs';

const TEXT_LIKE = new Set(['text', 'tex', 'title', 'quote', 'bullets', 'matrix']);
const NOT_CHECKED = new Set(['number_plane', 'axes', 'axes_3d', 'group']);
const SLACK = 0.05;

function when(index, scene) {
  if (index < 0) return 'at the start of the scene';
  const step = (scene.steps ?? [])[index];
  return `after step ${index + 1}${step?.do ? ` (${step.do})` : ''}`;
}

function overlap(a, b) {
  const w = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
  const h = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  if (w <= 0 || h <= 0) return 0;
  const area = (box) => Math.max(1e-6, (box[2] - box[0]) * (box[3] - box[1]));
  return (w * h) / Math.min(area(a), area(b));
}

export function layoutProblems(doc, sceneIndex) {
  const scene = doc.scenes[sceneIndex];
  const carried = carriedSpecs(doc, scene);
  const objectIndex = new Map((scene.objects ?? []).map((o, i) => [o.id, i]));
  const seen = new Set();
  const out = [];
  const warn = (id, kind, message) => {
    const key = `${id}|${kind}`;
    if (seen.has(key) || !objectIndex.has(id)) return;
    seen.add(key);
    out.push({
      message,
      severity: 'warning',
      loc: ['scenes', sceneIndex, 'objects', objectIndex.get(id)],
      path: `scenes[${sceneIndex}].objects[${objectIndex.get(id)}]`,
      scene_id: scene.id,
      item_id: id,
    });
  };
  const xr = FRAME_WIDTH / 2 + SLACK;
  const yr = FRAME_HEIGHT / 2 + SLACK;
  for (let i = -1; i < (scene.steps ?? []).length; i += 1) {
    const state = sceneStateAfter(scene, i, carried);
    const boxes = layoutScene(state.specs);
    const shown = state.specs.filter((o) => state.onScreen.has(o.id) && !NOT_CHECKED.has(o.type));
    for (const obj of shown) {
      const [x0, y0, x1, y1] = boxes.get(obj.id);
      if (x0 < -xr || x1 > xr || y0 < -yr || y1 > yr) {
        warn(obj.id, 'edge', `'${obj.id}' goes off the edge of the picture ${when(i, scene)}`);
      }
    }
    const texts = shown.filter((o) => TEXT_LIKE.has(o.type));
    for (let a = 0; a < texts.length; a += 1) {
      for (let b = a + 1; b < texts.length; b += 1) {
        if (overlap(boxes.get(texts[a].id), boxes.get(texts[b].id)) > 0.25) {
          warn(texts[b].id, `over:${texts[a].id}`, `'${texts[b].id}' is on top of '${texts[a].id}' ${when(i, scene)}`);
        }
      }
    }
  }
  return out;
}
