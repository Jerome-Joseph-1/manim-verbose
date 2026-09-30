/**
 * Resizing and turning an object with handles on the canvas: a corner handle scales it
 * about its centre by how much further from (or nearer to) the centre the pointer is than
 * where the drag started; a handle above it turns it by the angle the pointer sweeps round
 * the centre. Pixels in, the `scale` and `rotate` fields out. Pure.
 */
import type { Vec2 } from './coords';

export const MIN_SCALE = 0.05;
export const MAX_SCALE = 50;

function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/**
 * The scale after dragging a corner from `from` to `to`, starting at `start`: to a hundredth,
 * or with `coarse` (Shift) to a quarter.
 */
export function scaleFromDrag(start: number, center: Vec2, from: Vec2, to: Vec2, coarse = false): number {
  const before = distance(center, from);
  if (before < 1) return start;
  const raw = start * (distance(center, to) / before);
  const step = coarse ? 0.25 : 0.01;
  const rounded = Math.round(raw / step) * step;
  return Number(Math.max(MIN_SCALE, Math.min(MAX_SCALE, rounded)).toFixed(2));
}

/** Degrees counterclockwise of a pixel point round a centre (pixels have y down). */
export function angleOf(center: Vec2, p: Vec2): number {
  return (Math.atan2(center[1] - p[1], p[0] - center[0]) * 180) / Math.PI || 0;
}

/** An angle in (-180, 180]. */
export function normalizeDegrees(value: number): number {
  let out = value % 360;
  if (out <= -180) out += 360;
  if (out > 180) out -= 360;
  return Object.is(out, -0) ? 0 : out;
}

/**
 * The rotation after dragging the turn handle from `from` to `to`, starting at `start`
 * degrees: to a whole degree, or with `coarse` (Shift) to 15.
 */
export function rotationFromDrag(start: number, center: Vec2, from: Vec2, to: Vec2, coarse = false): number {
  if (distance(center, to) < 1 || distance(center, from) < 1) return start;
  const raw = start + angleOf(center, to) - angleOf(center, from);
  const step = coarse ? 15 : 1;
  return normalizeDegrees(Math.round(raw / step) * step);
}
