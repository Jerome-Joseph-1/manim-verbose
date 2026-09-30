/**
 * The units a point of an object is written in, and how they sit in a still: frame units for
 * most things, the coordinates of a number plane, axes or a number line for an object `on`
 * one. A Space turns a point into still pixels and a move in pixels back into the object's
 * own units, so that a drag on the canvas writes coordinates the file can use as they are.
 */
import type { CoordinateSystem } from './api';
import { frameToPixel, pixelDeltaToFrame, type FrameMapping } from './geometry';

export type Vec2 = [number, number];

export interface Space {
  kind: 'frame' | 'system';
  /** The coordinate system's id, for a system. */
  id?: string;
  /** A point (the object's own units; z ignored) as still pixels. */
  toPixel(point: readonly number[]): Vec2;
  /** A move in still pixels as a move in the object's own units. */
  fromPixelDelta(dx: number, dy: number): Vec2;
  /** The grid points are rounded to when dragged, and to with Shift held. */
  step: number;
  bigStep: number;
}

export function frameSpace(mapping: FrameMapping): Space {
  return {
    kind: 'frame',
    toPixel: (p) => frameToPixel(mapping, p[0] ?? 0, p[1] ?? 0),
    fromPixelDelta: (dx, dy) => pixelDeltaToFrame(mapping, dx, dy),
    step: 0.01,
    bigStep: 0.5,
  };
}

/**
 * The space of a coordinate system as a still measured it: (x, y) lands at
 * origin + x * x_unit + y * y_unit. A number line's y is height above it in frame units, which
 * its y_unit already says; a system whose y_unit is missing or parallel to x moves along x only.
 */
export function systemSpace(system: CoordinateSystem): Space {
  const [ox, oy] = system.origin;
  const [ax, ay] = system.x_unit;
  const [bx, by] = system.y_unit ?? [0, 0];
  const det = ax * by - bx * ay;
  const flat = Math.abs(det) < 1e-9;
  return {
    kind: 'system',
    id: system.id,
    toPixel: (p) => [ox + (p[0] ?? 0) * ax + (p[1] ?? 0) * bx, oy + (p[0] ?? 0) * ay + (p[1] ?? 0) * by],
    fromPixelDelta: (dx, dy) => {
      if (flat) {
        // Along x only: the move projected onto the x direction
        const length = ax * ax + ay * ay;
        return [length > 0 ? (dx * ax + dy * ay) / length : 0, 0];
      }
      return [(dx * by - dy * bx) / det, (ax * dy - ay * dx) / det];
    },
    step: 0.1,
    bigStep: 1,
  };
}

/** Round to a multiple of `step`, without the float noise (0.30000000000000004) that leaves. */
export function snap(value: number, step: number): number {
  const decimals = Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) + 1e-9)));
  const rounded = Number((Math.round(value / step) * step).toFixed(decimals));
  return Object.is(rounded, -0) ? 0 : rounded;
}

/** Clean up float noise in a value without rounding it to a grid. */
export function tidy(value: number): number {
  const out = Number(value.toFixed(6));
  return Object.is(out, -0) ? 0 : out;
}

/**
 * The space an object's points are in: its coordinate system's if it is `on` one (null when
 * that system isn't in the still, so the object can't be dragged), else the frame's.
 */
export function spaceFor(on: unknown, mapping: FrameMapping, systems: readonly CoordinateSystem[]): Space | null {
  if (typeof on !== 'string' || on === '') return frameSpace(mapping);
  const system = systems.find((s) => s.id === on);
  return system ? systemSpace(system) : null;
}
