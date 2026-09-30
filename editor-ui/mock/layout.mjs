// Fake stills: where each object would roughly be once a step has run, drawn as labelled
// boxes in an SVG. Sizes are guesses from the object's fields; positions follow the
// placement rules (at, edge, next_to, shift) closely enough for the canvas to be tested.
import { iterSteps } from './validate.mjs';

export const FRAME_HEIGHT = 8;
export const FRAME_WIDTH = (FRAME_HEIGHT * 16) / 9;
const X_RADIUS = FRAME_WIDTH / 2;
const Y_RADIUS = FRAME_HEIGHT / 2;

const PALETTE = {
  BLUE: '#58C4DD', BLUE_E: '#1C758A', BLUE_D: '#29ABCA', BLUE_C: '#58C4DD', BLUE_B: '#9CDCEB', BLUE_A: '#C7E9F1',
  TEAL: '#5CD0B3', GREEN: '#83C167', YELLOW: '#FFFF00', GOLD: '#F0AC5F', RED: '#FC6255', MAROON: '#C55F73',
  PURPLE: '#9A72AC', GREY: '#888888', GRAY: '#888888', WHITE: '#FFFFFF', BLACK: '#000000', PINK: '#D147BD',
  ORANGE: '#FF862F', YELLOW_E: '#E8C11C', RED_E: '#CF5044', GREEN_E: '#699C52', TEAL_E: '#49A88F',
};

export function colorHex(value, fallback) {
  if (typeof value !== 'string') return fallback;
  if (/^#[0-9a-fA-F]{3,8}$/.test(value)) return value.slice(0, 7);
  const upper = value.toUpperCase();
  if (PALETTE[upper]) return PALETTE[upper];
  const base = upper.replace(/_[A-E]$/, '');
  return PALETTE[base] ?? fallback;
}

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const asList = (t) => (Array.isArray(t) ? t : typeof t === 'string' && t ? [t] : []);

function textSize(text, fontSize, lines = null) {
  const rows = lines ?? String(text ?? '').split('\n');
  const longest = Math.max(1, ...rows.map((r) => r.length));
  const scale = fontSize / 48;
  return [Math.max(0.4, longest * 0.27 * scale), Math.max(0.45, rows.length * 0.62 * scale)];
}

function texWidth(tex) {
  const visible = String(tex ?? '').replace(/\\[a-zA-Z]+/g, 'x').replace(/[{}^_\s]/g, '');
  return Math.max(1, visible.length);
}

function rangeSpan(range, fallback) {
  if (Array.isArray(range) && range.length >= 2) return Math.abs(range[1] - range[0]);
  return fallback;
}

/** Width and height, in frame units, of an object on its own. */
function naturalSize(obj, ctx) {
  const scale = typeof obj.scale === 'number' ? obj.scale : 1;
  let size;
  switch (obj.type) {
    case 'text':
      size = textSize(obj.text, obj.font_size ?? 48);
      break;
    case 'title':
      size = textSize(obj.text, obj.font_size ?? 60);
      size[1] += obj.underline === false ? 0 : 0.15;
      break;
    case 'quote': {
      const [w, h] = textSize(obj.text, obj.font_size ?? 40);
      size = [w, h + (obj.author ? 0.5 : 0)];
      break;
    }
    case 'bullets':
      size = textSize('', obj.font_size ?? 36, (obj.items ?? []).map((i) => `•  ${i}`));
      break;
    case 'tex': {
      const f = (obj.font_size ?? 48) / 48;
      size = [texWidth(obj.tex) * 0.3 * f, 0.7 * f];
      break;
    }
    case 'matrix': {
      const rows = Array.isArray(obj.entries) ? obj.entries.length : 1;
      const cols = Array.isArray(obj.entries?.[0]) ? obj.entries[0].length : 1;
      size = [cols * 0.8 + 0.4, rows * 0.65 + 0.2];
      break;
    }
    case 'number_plane':
      size = [obj.width ?? Math.min(rangeSpan(obj.x_range, 16), FRAME_WIDTH), obj.height ?? Math.min(rangeSpan(obj.y_range, 8), FRAME_HEIGHT)];
      break;
    case 'axes':
      size = [obj.width ?? rangeSpan(obj.x_range, 12), obj.height ?? rangeSpan(obj.y_range, 6)];
      break;
    case 'axes_3d':
      size = [rangeSpan(obj.x_range, 10) * 0.8, rangeSpan(obj.z_range, 6) * 0.9];
      break;
    case 'number_line':
      size = [obj.length ?? rangeSpan(obj.x_range, 10), 0.5];
      break;
    case 'circle':
      size = [2 * (obj.radius ?? 1), 2 * (obj.radius ?? 1)];
      break;
    case 'rectangle':
      size = [obj.width ?? 2, obj.height ?? 1];
      break;
    case 'square':
      size = [obj.side ?? 2, obj.side ?? 2];
      break;
    case 'image':
      size = [(obj.height ?? 3) * 1.5, obj.height ?? 3];
      break;
    case 'svg':
      size = [obj.height ?? 2, obj.height ?? 2];
      break;
    default:
      size = [1, 1];
  }
  void ctx;
  return [size[0] * scale, size[1] * scale];
}

function edgeCenter(edge, w, h, buff) {
  const x = { left: -X_RADIUS + buff + w / 2, right: X_RADIUS - buff - w / 2 };
  const y = { top: Y_RADIUS - buff - h / 2, bottom: -Y_RADIUS + buff + h / 2 };
  switch (edge) {
    case 'top': return [0, y.top];
    case 'bottom': return [0, y.bottom];
    case 'left': return [x.left, 0];
    case 'right': return [x.right, 0];
    case 'top_left': return [x.left, y.top];
    case 'top_right': return [x.right, y.top];
    case 'bottom_left': return [x.left, y.bottom];
    case 'bottom_right': return [x.right, y.bottom];
    default: return [0, 0];
  }
}

function besideCenter(box, side, w, h, buff) {
  const [x0, y0, x1, y1] = box;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  switch (side) {
    case 'up': return [cx, y1 + buff + h / 2];
    case 'left': return [x0 - buff - w / 2, cy];
    case 'right': return [x1 + buff + w / 2, cy];
    default: return [cx, y0 - buff - h / 2];
  }
}

function normalizePlace(place) {
  if (typeof place === 'string') return { edge: place };
  if (Array.isArray(place)) return { at: place };
  return isObj(place) ? place : {};
}

/** A coordinate system's mapping from its coordinates to frame units. */
function coordinateMap(system, box) {
  const xr = Array.isArray(system.x_range) ? system.x_range : system.type === 'number_plane' ? [-8, 8] : [-6, 6];
  const yr = Array.isArray(system.y_range) ? system.y_range : system.type === 'number_plane' ? [-4, 4] : [-3, 3];
  const [x0, y0, x1, y1] = box;
  const sx = (x1 - x0) / Math.max(1e-6, xr[1] - xr[0]);
  const sy = system.type === 'number_line' ? sx : (y1 - y0) / Math.max(1e-6, yr[1] - yr[0]);
  return (p) => [x0 + (p[0] - xr[0]) * sx, y0 + ((p[1] ?? 0) - yr[0]) * sy];
}

function pointsBox(points, pad) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

/** Frame boxes of every object in a scene, given the specs in force. */
export function layoutScene(specs) {
  const boxes = new Map();
  const visiting = new Set();
  const byId = new Map(specs.map((o) => [o.id, o]));

  const place = (id) => {
    if (boxes.has(id)) return boxes.get(id);
    const obj = byId.get(id);
    if (!obj || visiting.has(id)) return [-0.5, -0.5, 0.5, 0.5];
    visiting.add(id);
    let box;
    const onBox = typeof obj.on === 'string' && byId.has(obj.on) ? place(obj.on) : null;
    const map = onBox ? coordinateMap(byId.get(obj.on), onBox) : (p) => [p[0], p[1] ?? 0];
    const pt = (p) => (Array.isArray(p) && p.length >= 2 ? map(p) : [0, 0]);
    switch (obj.type) {
      case 'dot': {
        const [x, y] = pt(obj.point);
        const r = Math.max(obj.radius ?? 0.08, 0.08);
        box = [x - r, y - r, x + r, y + r];
        break;
      }
      case 'vector':
        box = pointsBox([pt(obj.tail ?? [0, 0]), pt(obj.tip)], 0.06);
        break;
      case 'line':
        box = pointsBox([pt(obj.start), pt(obj.end)], 0.03);
        break;
      case 'polygon':
        box = pointsBox((obj.points ?? []).filter(Array.isArray).map(pt), 0.02);
        if (!Number.isFinite(box[0])) box = [-0.5, -0.5, 0.5, 0.5];
        break;
      case 'graph':
        box = onBox ? [...onBox] : [-3, -2, 3, 2];
        box = [box[0], box[1] + (box[3] - box[1]) * 0.15, box[2], box[3] - (box[3] - box[1]) * 0.15];
        break;
      case 'brace': {
        const t = typeof obj.target === 'string' && byId.has(obj.target) ? place(obj.target) : [-1, -0.5, 1, 0.5];
        const buff = obj.buff ?? 0.1;
        const side = obj.side ?? 'down';
        const depth = obj.label ? 0.8 : 0.35;
        if (side === 'up') box = [t[0], t[3] + buff, t[2], t[3] + buff + depth];
        else if (side === 'left') box = [t[0] - buff - depth, t[1], t[0] - buff, t[3]];
        else if (side === 'right') box = [t[2] + buff, t[1], t[2] + buff + depth, t[3]];
        else box = [t[0], t[1] - buff - depth, t[2], t[1] - buff];
        break;
      }
      case 'box': {
        const t = typeof obj.target === 'string' && byId.has(obj.target) ? place(obj.target) : [-1, -0.5, 1, 0.5];
        const buff = obj.buff ?? 0.15;
        box = [t[0] - buff, t[1] - buff, t[2] + buff, t[3] + buff];
        break;
      }
      case 'group': {
        const members = (obj.members ?? []).filter((m) => byId.has(m));
        const inner = members.map(place);
        if (inner.length === 0) {
          box = [-0.5, -0.5, 0.5, 0.5];
        } else {
          box = [Math.min(...inner.map((b) => b[0])), Math.min(...inner.map((b) => b[1])), Math.max(...inner.map((b) => b[2])), Math.max(...inner.map((b) => b[3]))];
        }
        box = positioned(obj, box[2] - box[0], box[3] - box[1], place, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, null, byId);
        break;
      }
      default: {
        const [w, h] = naturalSize(obj);
        const defaultEdge = obj.type === 'title' ? 'top' : null;
        box = positioned(obj, w, h, place, 0, 0, defaultEdge, byId);
      }
    }
    visiting.delete(id);
    boxes.set(id, box);
    return box;
  };

  for (const obj of specs) place(obj.id);
  return boxes;
}

function positioned(obj, w, h, place, cx0, cy0, defaultEdge = null, byId = null) {
  const p = normalizePlace(obj.place);
  const buff = typeof p.buff === 'number' ? p.buff : 0.25;
  let cx = cx0;
  let cy = cy0;
  if (Array.isArray(p.at) && p.at.length >= 2 && typeof p.on === 'string' && byId?.has(p.on)) {
    [cx, cy] = coordinateMap(byId.get(p.on), place(p.on))(p.at);
  } else if (Array.isArray(p.at) && p.at.length >= 2) [cx, cy] = p.at;
  else if (typeof p.edge === 'string') [cx, cy] = edgeCenter(p.edge, w, h, buff);
  else if (typeof p.next_to === 'string') [cx, cy] = besideCenter(place(p.next_to), p.side ?? 'down', w, h, buff);
  else if (defaultEdge) [cx, cy] = edgeCenter(defaultEdge, w, h, buff);
  if (Array.isArray(p.shift) && p.shift.length >= 2) {
    cx += p.shift[0];
    cy += p.shift[1];
  }
  return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2];
}

/**
 * Follow a scene's steps up to and including `stepIndex`: what is on screen, what each
 * object looks like by then (after change and move steps), the caption, and the camera.
 */
export function sceneStateAfter(scene, stepIndex) {
  const specs = new Map((scene.objects ?? []).map((o) => [o.id, structuredClone(o)]));
  let onScreen = new Set((scene.objects ?? []).filter((o) => o.shown).map((o) => o.id));
  let caption = null;
  const camera = { zoom: 1, center: [0, 0], focus: null };
  const members = (ref) => {
    const out = new Set([ref]);
    const obj = specs.get(ref);
    if (obj?.type === 'group') for (const m of obj.members ?? []) for (const x of members(m)) out.add(x);
    return out;
  };
  const run = (step) => {
    const targets = asList(step.target);
    switch (step.do) {
      case 'show':
      case 'add':
        for (const t of targets) for (const m of members(t)) onScreen.add(m);
        break;
      case 'hide':
      case 'remove':
        for (const t of targets) for (const m of members(t)) onScreen.delete(m);
        break;
      case 'clear':
        // Clearing takes the caption with it
        onScreen = new Set();
        caption = null;
        break;
      case 'transform':
        if (!step.keep) for (const m of members(step.target)) onScreen.delete(m);
        for (const m of members(step.into)) onScreen.add(m);
        break;
      case 'change':
        if (specs.has(step.target) && isObj(step.set)) Object.assign(specs.get(step.target), structuredClone(step.set));
        break;
      case 'move':
        for (const t of targets) {
          const spec = specs.get(t);
          if (!spec) continue;
          if (Array.isArray(step.by)) {
            const p = normalizePlace(spec.place);
            const shift = Array.isArray(p.shift) ? p.shift : [0, 0];
            spec.place = { ...p, shift: [shift[0] + step.by[0], shift[1] + step.by[1]] };
          } else if (step.to != null) {
            spec.place = normalizePlace(step.to);
          }
        }
        break;
      case 'camera':
        if (step.reset) Object.assign(camera, { zoom: 1, center: [0, 0], focus: null });
        if (typeof step.zoom === 'number') camera.zoom = step.zoom;
        if (Array.isArray(step.center)) Object.assign(camera, { center: step.center.slice(0, 2), focus: null });
        if (typeof step.focus === 'string') camera.focus = step.focus;
        break;
      case 'together':
        for (const inner of step.steps ?? []) run(inner);
        break;
      default:
        break;
    }
    if (step.caption !== undefined && step.caption !== null) caption = step.caption === '' ? null : step.caption;
  };
  (scene.steps ?? []).slice(0, stepIndex + 1).forEach((step) => {
    run(step);
    for (const inner of iterSteps(step.do === 'together' ? step.steps : [])) {
      if (inner.caption) caption = inner.caption;
    }
  });
  return { specs: [...specs.values()], onScreen, caption, camera };
}

function escapeXml(text) {
  return String(text).replace(/[<>&"']/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&#39;' })[c]);
}

function shortLabel(obj) {
  const content = obj.text ?? obj.tex ?? (Array.isArray(obj.items) ? obj.items[0] : null) ?? obj.function ?? obj.path ?? null;
  const text = content ? `${obj.id}: ${String(content).split('\n')[0]}` : `${obj.id} (${obj.type.replace(/_/g, ' ')})`;
  return text.length > 42 ? `${text.slice(0, 40)}…` : text;
}

/**
 * The still for `stepIndex` of a scene, as SVG, with each object's box in pixels and in
 * frame units, in drawing order.
 */
export function renderStill(doc, scene, stepIndex, width) {
  const height = Math.round((width * 9) / 16);
  const state = sceneStateAfter(scene, stepIndex);
  const boxes = layoutScene(state.specs);
  let [cx, cy] = state.camera.center;
  if (state.camera.focus && boxes.has(state.camera.focus)) {
    const b = boxes.get(state.camera.focus);
    [cx, cy] = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
  }
  const zoom = state.camera.zoom || 1;
  const sx = (width / FRAME_WIDTH) * zoom;
  const sy = (height / FRAME_HEIGHT) * zoom;
  const toPx = (x, y) => [(x - cx) * sx + width / 2, height / 2 - (y - cy) * sy];
  const order = state.specs
    .map((o, i) => ({ o, i }))
    .filter(({ o }) => state.onScreen.has(o.id))
    .sort((a, b) => (a.o.z ?? 0) - (b.o.z ?? 0) || a.i - b.i)
    .map(({ o }) => o);
  const background = colorHex(scene.background ?? doc.settings?.background, '#333333');
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<rect width="100%" height="100%" fill="${background}"/>`,
  ];
  const objects = [];
  for (const obj of order) {
    const fb = boxes.get(obj.id);
    const [px0, py0] = toPx(fb[0], fb[3]);
    const [px1, py1] = toPx(fb[2], fb[1]);
    const bbox = [px0, py0, px1, py1].map((v) => Math.round(v * 10) / 10);
    objects.push({ id: obj.id, bbox, frame_bbox: fb.map((v) => Math.round(v * 1000) / 1000) });
    const color = colorHex(obj.color, obj.type === 'number_plane' || obj.type === 'axes' ? '#6B8A99' : '#FFFFFF');
    const w = Math.max(1, px1 - px0);
    const h = Math.max(1, py1 - py0);
    const opacity = typeof obj.opacity === 'number' ? obj.opacity : 1;
    if (obj.type === 'number_plane' || obj.type === 'axes' || obj.type === 'axes_3d') {
      parts.push(`<g opacity="${0.55 * opacity}">`);
      const step = sx;
      for (let x = px0 + ((w / 2) % step); x <= px1; x += step) parts.push(`<line x1="${x}" y1="${py0}" x2="${x}" y2="${py1}" stroke="${color}" stroke-width="${obj.type === 'number_plane' ? 1 : 0}"/>`);
      for (let y = py0 + ((h / 2) % step); y <= py1; y += step) parts.push(`<line x1="${px0}" y1="${y}" x2="${px1}" y2="${y}" stroke="${color}" stroke-width="${obj.type === 'number_plane' ? 1 : 0}"/>`);
      parts.push(`<line x1="${px0}" y1="${(py0 + py1) / 2}" x2="${px1}" y2="${(py0 + py1) / 2}" stroke="#FFFFFF" stroke-width="2"/>`);
      parts.push(`<line x1="${(px0 + px1) / 2}" y1="${py0}" x2="${(px0 + px1) / 2}" y2="${py1}" stroke="#FFFFFF" stroke-width="2"/>`);
      parts.push('</g>');
      continue;
    }
    const fill = obj.fill ? colorHex(obj.fill, color) : color;
    const fillOpacity = typeof obj.fill_opacity === 'number' ? obj.fill_opacity * 0.6 : 0.14;
    if (obj.type === 'circle' || obj.type === 'dot') {
      parts.push(`<ellipse cx="${(px0 + px1) / 2}" cy="${(py0 + py1) / 2}" rx="${w / 2}" ry="${h / 2}" fill="${fill}" fill-opacity="${obj.type === 'dot' ? 1 : fillOpacity}" stroke="${color}" stroke-width="3" opacity="${opacity}"/>`);
    } else if (obj.type === 'polygon' && Array.isArray(obj.points)) {
      const on = typeof obj.on === 'string';
      const pts = on ? [[fb[0], fb[1]], [fb[2], fb[1]], [fb[2], fb[3]]] : obj.points;
      parts.push(`<polygon points="${pts.map((p) => toPx(p[0], p[1]).join(',')).join(' ')}" fill="${fill}" fill-opacity="${fillOpacity}" stroke="${color}" stroke-width="3" opacity="${opacity}"/>`);
    } else if (obj.type === 'vector' || obj.type === 'line') {
      const a = obj.type === 'vector' ? obj.tail ?? [0, 0] : obj.start;
      const b = obj.type === 'vector' ? obj.tip : obj.end;
      if (Array.isArray(a) && Array.isArray(b) && typeof obj.on !== 'string') {
        const [ax, ay] = toPx(a[0], a[1]);
        const [bx, by] = toPx(b[0], b[1]);
        parts.push(`<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="${color}" stroke-width="4" opacity="${opacity}"/>`);
      } else {
        parts.push(`<line x1="${px0}" y1="${py1}" x2="${px1}" y2="${py0}" stroke="${color}" stroke-width="4" opacity="${opacity}"/>`);
      }
    } else if (obj.type === 'graph') {
      const pts = [];
      for (let i = 0; i <= 40; i += 1) {
        const t = i / 40;
        pts.push(`${px0 + t * w},${(py0 + py1) / 2 - Math.sin(t * Math.PI * 2) * (h / 2)}`);
      }
      parts.push(`<polyline points="${pts.join(' ')}" fill="none" stroke="${colorHex(obj.color, '#FFFF00')}" stroke-width="3"/>`);
    } else {
      const rx = obj.type === 'rectangle' || obj.type === 'square' || obj.type === 'box' ? 2 : 8;
      parts.push(`<rect x="${px0}" y="${py0}" width="${w}" height="${h}" rx="${rx}" fill="${fill}" fill-opacity="${obj.type === 'box' ? 0 : fillOpacity}" stroke="${color}" stroke-width="${obj.type === 'text' || obj.type === 'tex' || obj.type === 'title' ? 1.5 : 3}" stroke-dasharray="${obj.type === 'brace' ? '6 4' : ''}" opacity="${opacity}"/>`);
      const fontPx = Math.max(10, Math.min(28, h * 0.45));
      parts.push(`<text x="${(px0 + px1) / 2}" y="${(py0 + py1) / 2}" fill="${color}" font-family="DejaVu Sans, Arial, sans-serif" font-size="${fontPx}" text-anchor="middle" dominant-baseline="central" opacity="${opacity}">${escapeXml(shortLabel(obj))}</text>`);
    }
  }
  if (state.caption) {
    const fontPx = Math.round(height * 0.045);
    parts.push(`<rect x="0" y="${height - fontPx * 2.4}" width="${width}" height="${fontPx * 2.4}" fill="#000000" fill-opacity="0.55"/>`);
    parts.push(`<text x="${width / 2}" y="${height - fontPx * 1.2}" fill="#FFFFFF" font-family="DejaVu Sans, Arial, sans-serif" font-size="${fontPx}" text-anchor="middle" dominant-baseline="central">${escapeXml(state.caption)}</text>`);
  }
  parts.push('</svg>');
  return { svg: parts.join(''), width, height, objects };
}
