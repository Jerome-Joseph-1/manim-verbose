/**
 * The points of plotted objects, for dragging them on the canvas: which fields hold points,
 * which of those get a handle of their own, and the new field values after a move. Everything
 * here is in the object's own units (see coords.ts), and pure.
 *
 *   dot      point                       dragged as a whole
 *   vector   tail (default [0, 0]), tip  as a whole (tail and tip), or its tip or tail alone
 *   line     start, end                  as a whole, or either end
 *   polygon  points                      as a whole, or any corner
 *   angle    points [a, vertex, b]       as a whole
 *   arc      center (default [0, 0])     as a whole
 *   brace    start, end (between points) as a whole, or either end
 */
import type { Json, SceneObject } from '../doc/types';
import { snap, tidy, type Vec2 } from './coords';

export interface HandleRef {
  field: string;
  /** For a list of points (a polygon's corners), which one. */
  index?: number;
  /** What it is, for people: "tip", "corner 2". */
  label: string;
}

const DEFAULTS: Record<string, Record<string, number[]>> = {
  vector: { tail: [0, 0] },
  arc: { center: [0, 0] },
};

function isPoint(value: Json | undefined): value is number[] {
  return Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number';
}

/** The fields of an object holding single points, with their defaults filled in. */
function pointFields(obj: SceneObject): string[] {
  switch (obj.type) {
    case 'dot':
      return ['point'];
    case 'vector':
      return ['tail', 'tip'];
    case 'line':
      return ['start', 'end'];
    case 'arc':
      return ['center'];
    case 'brace':
      return isPoint(obj.start) && isPoint(obj.end) ? ['start', 'end'] : [];
    default:
      return [];
  }
}

/** Fields holding a list of points. */
function listFields(obj: SceneObject): string[] {
  return obj.type === 'polygon' || obj.type === 'angle' ? ['points'] : [];
}

/** Whether an object is placed by points (and so dragged by moving them). */
export function isPlotted(obj: SceneObject): boolean {
  return pointFields(obj).length > 0 || listFields(obj).length > 0;
}

export function pointOf(obj: SceneObject, handle: Pick<HandleRef, 'field' | 'index'>): number[] | null {
  const value = obj[handle.field] ?? DEFAULTS[obj.type]?.[handle.field];
  if (handle.index !== undefined) {
    const item = Array.isArray(value) ? value[handle.index] : undefined;
    return isPoint(item) ? item : null;
  }
  return isPoint(value as Json) ? (value as number[]) : null;
}

/** The handles an object has for moving one of its points alone. */
export function pointHandles(obj: SceneObject): HandleRef[] {
  switch (obj.type) {
    case 'vector':
      return [{ field: 'tip', label: 'tip' }, { field: 'tail', label: 'tail' }];
    case 'line':
      return [{ field: 'start', label: 'start' }, { field: 'end', label: 'end' }];
    case 'brace':
      return isPoint(obj.start) && isPoint(obj.end) ? [{ field: 'start', label: 'start' }, { field: 'end', label: 'end' }] : [];
    case 'polygon': {
      const out: HandleRef[] = [];
      if (Array.isArray(obj.points)) obj.points.forEach((p, index) => isPoint(p) && out.push({ field: 'points', index, label: `corner ${index + 1}` }));
      return out;
    }
    default:
      return [];
  }
}

/** Every point of an object, in order, for drawing its outline while it is dragged. */
export function allPoints(obj: SceneObject): number[][] {
  const out: number[][] = [];
  for (const field of pointFields(obj)) {
    const p = pointOf(obj, { field });
    if (p) out.push(p);
  }
  for (const field of listFields(obj)) {
    const list = obj[field];
    if (Array.isArray(list)) for (const p of list) if (isPoint(p)) out.push(p);
  }
  return out;
}

function moved(p: number[], dx: number, dy: number): number[] {
  return [tidy(p[0]! + dx), tidy(p[1]! + dy), ...p.slice(2)];
}

/**
 * The fields of an object moved by (dx, dy) as a whole, rounded to `step`: the move is
 * rounded rather than each point, so the shape stays exactly as it was. Null for an object
 * with no points to move.
 */
export function translatePoints(obj: SceneObject, dx: number, dy: number, step: number): Record<string, Json> | null {
  const sx = snap(dx, step);
  const sy = snap(dy, step);
  const patch: Record<string, Json> = {};
  for (const field of pointFields(obj)) {
    const p = pointOf(obj, { field });
    if (p) patch[field] = moved(p, sx, sy);
  }
  for (const field of listFields(obj)) {
    const list = obj[field];
    if (Array.isArray(list)) patch[field] = list.map((p) => (isPoint(p) ? moved(p, sx, sy) : p));
  }
  return Object.keys(patch).length ? patch : null;
}

/** The fields of an object with one of its points put at `to` (rounded to `step`), keeping any z. */
export function movePoint(obj: SceneObject, handle: Pick<HandleRef, 'field' | 'index'>, to: Vec2, step: number): Record<string, Json> | null {
  const old = pointOf(obj, handle);
  if (!old) return null;
  const point = [snap(to[0], step), snap(to[1], step), ...old.slice(2)];
  if (handle.index !== undefined) {
    const list = Array.isArray(obj[handle.field]) ? [...(obj[handle.field] as Json[])] : [];
    list[handle.index] = point;
    return { [handle.field]: list };
  }
  return { [handle.field]: point };
}

/** A pixel point moved by a pixel offset. */
export function offset(p: Vec2, by: Vec2 | null): Vec2 {
  return by ? [p[0] + by[0], p[1] + by[1]] : p;
}
