/**
 * Between the pixels of a still and manim's frame units, and finding what was clicked.
 *
 * A still comes with each object's box twice over, in pixels (origin top left, y down) and
 * in frame units (origin centre, y up). The mapping between them is fitted from those
 * pairs rather than assumed, so it stays right when a camera step has zoomed or panned.
 */

export type Box = [number, number, number, number];

export interface StillObject {
  id: string;
  /** Pixels: x0, y0, x1, y1, origin top left. */
  bbox: Box;
  /** Frame units: xmin, ymin, xmax, ymax. */
  frame_bbox: Box;
}

/** px = ax * x + bx, py = ay * y + by. */
export interface FrameMapping {
  ax: number;
  bx: number;
  ay: number;
  by: number;
}

export const FRAME_HEIGHT = 8;

/** manim's default frame: 8 units high, as wide as the image's aspect ratio makes it. */
export function defaultMapping(width: number, height: number): FrameMapping {
  const frameWidth = (FRAME_HEIGHT * width) / height;
  const ax = width / frameWidth;
  const ay = -height / FRAME_HEIGHT;
  return { ax, bx: width / 2, ay, by: height / 2 };
}

interface Fit {
  slope: number;
  intercept: number;
}

/** Least squares line through (frame, pixel) pairs, or null when the frame values don't vary. */
function fitLine(pairs: [number, number][]): Fit | null {
  if (pairs.length < 2) return null;
  const n = pairs.length;
  const meanF = pairs.reduce((s, [f]) => s + f, 0) / n;
  const meanP = pairs.reduce((s, [, p]) => s + p, 0) / n;
  let sff = 0;
  let sfp = 0;
  for (const [f, p] of pairs) {
    sff += (f - meanF) ** 2;
    sfp += (f - meanF) * (p - meanP);
  }
  if (sff < 1e-9) return null;
  const slope = sfp / sff;
  if (!Number.isFinite(slope) || Math.abs(slope) < 1e-9) return null;
  return { slope, intercept: meanP - slope * meanF };
}

function isFiniteBox(box: unknown): box is Box {
  return Array.isArray(box) && box.length === 4 && box.every((v) => typeof v === 'number' && Number.isFinite(v));
}

/**
 * The mapping implied by the objects of a still. An axis whose frame values don't vary
 * (only a horizontal line on screen, say) takes its scale from the other axis, since
 * pixels are square; with nothing to go on, manim's default frame is assumed.
 */
export function fitMapping(objects: StillObject[], width: number, height: number): FrameMapping {
  const xs: [number, number][] = [];
  const ys: [number, number][] = [];
  for (const obj of objects) {
    if (!isFiniteBox(obj.bbox) || !isFiniteBox(obj.frame_bbox)) continue;
    const [x0, y0, x1, y1] = obj.bbox;
    const [fx0, fy0, fx1, fy1] = obj.frame_bbox;
    xs.push([fx0, x0], [fx1, x1]);
    // Pixel y grows downwards: the frame's top (ymax) is the box's y0
    ys.push([fy1, y0], [fy0, y1]);
  }
  const fallback = defaultMapping(width, height);
  const fx = fitLine(xs);
  const fy = fitLine(ys);
  if (fx && fy && fx.slope > 0 && fy.slope < 0) {
    return { ax: fx.slope, bx: fx.intercept, ay: fy.slope, by: fy.intercept };
  }
  if (fx && fx.slope > 0) {
    const ay = -fx.slope;
    const by = ys.length ? ys.reduce((s, [f, p]) => s + (p - ay * f), 0) / ys.length : fallback.by;
    return { ax: fx.slope, bx: fx.intercept, ay, by };
  }
  if (fy && fy.slope < 0) {
    const ax = -fy.slope;
    const bx = xs.length ? xs.reduce((s, [f, p]) => s + (p - ax * f), 0) / xs.length : fallback.bx;
    return { ax, bx, ay: fy.slope, by: fy.intercept };
  }
  return fallback;
}

export function frameToPixel(m: FrameMapping, x: number, y: number): [number, number] {
  return [m.ax * x + m.bx, m.ay * y + m.by];
}

export function pixelToFrame(m: FrameMapping, px: number, py: number): [number, number] {
  return [(px - m.bx) / m.ax, (py - m.by) / m.ay];
}

/** A distance in pixels as a distance in frame units (y flipped). */
export function pixelDeltaToFrame(m: FrameMapping, dx: number, dy: number): [number, number] {
  return [dx / m.ax, dy / m.ay];
}

export function boxContains(box: Box, x: number, y: number, slop = 0): boolean {
  const [x0, y0, x1, y1] = box;
  return x >= Math.min(x0, x1) - slop && x <= Math.max(x0, x1) + slop && y >= Math.min(y0, y1) - slop && y <= Math.max(y0, y1) + slop;
}

/**
 * Every object whose box contains the point, topmost first. The still lists objects in
 * drawing order, so later ones are on top. Very thin boxes (a horizontal line) get a few
 * pixels of slop so they can be hit at all.
 */
export function hitTestAll(objects: StillObject[], x: number, y: number, slop = 3): StillObject[] {
  const hits: StillObject[] = [];
  for (let i = objects.length - 1; i >= 0; i -= 1) {
    const obj = objects[i]!;
    if (!isFiniteBox(obj.bbox)) continue;
    const [x0, y0, x1, y1] = obj.bbox;
    const thin = Math.abs(x1 - x0) < 2 * slop || Math.abs(y1 - y0) < 2 * slop;
    if (boxContains(obj.bbox, x, y, thin ? slop : 0)) hits.push(obj);
  }
  return hits;
}

/** The topmost object at a point, or null. */
export function hitTest(objects: StillObject[], x: number, y: number): StillObject | null {
  return hitTestAll(objects, x, y)[0] ?? null;
}

/**
 * Clicking again at the same spot picks the next object down, so that one under another
 * can still be reached. Returns what to select given what is selected now.
 */
export function cycleHit(objects: StillObject[], x: number, y: number, currentId: string | null): StillObject | null {
  const hits = hitTestAll(objects, x, y);
  if (hits.length === 0) return null;
  const at = currentId === null ? -1 : hits.findIndex((h) => h.id === currentId);
  if (at < 0) return hits[0]!;
  return hits[(at + 1) % hits.length]!;
}

export function boxCenter(box: Box): [number, number] {
  return [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
}

/** Round to a hundredth, the precision positions are written to the file with. */
export function roundFrame(value: number): number {
  const rounded = Math.round(value * 100) / 100;
  return Object.is(rounded, -0) ? 0 : rounded;
}

/** Scale a box from one image size to another (the still vs the displayed image). */
export function scaleBox(box: Box, sx: number, sy: number): Box {
  return [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy];
}
