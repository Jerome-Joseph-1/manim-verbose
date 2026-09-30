/**
 * The units points are written in: frame units, or a coordinate system's, and the way a drag
 * in pixels becomes a move in those units.
 */
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import type { CoordinateSystem } from './api';
import { frameSpace, snap, spaceFor, systemSpace, tidy } from './coords';
import { defaultMapping } from './geometry';

const mapping = defaultMapping(960, 540);
const plane: CoordinateSystem = { id: 'plane', type: 'number_plane', origin: [480, 270], x_unit: [67.5, 0], y_unit: [0, -67.5], z_unit: null };

describe('frame units', () => {
  it('put the origin in the middle, with y up', () => {
    const space = frameSpace(mapping);
    expect(space.toPixel([0, 0])).toEqual([480, 270]);
    expect(space.toPixel([1, 1])).toEqual([547.5, 202.5]);
    expect(space.fromPixelDelta(67.5, -135)).toEqual([1, 2]);
    expect(space.kind).toBe('frame');
    expect(space.step).toBe(0.01);
  });
});

describe('a coordinate system', () => {
  it('reads a point as origin + x * x_unit + y * y_unit', () => {
    const skewed: CoordinateSystem = { ...plane, origin: [100, 400], x_unit: [30, -10], y_unit: [5, -40] };
    const space = systemSpace(skewed);
    expect(space.toPixel([2, 3])).toEqual([100 + 60 + 15, 400 - 20 - 120]);
    expect(space.kind).toBe('system');
    expect(space.id).toBe('plane');
  });

  it('turns a move in pixels back into coordinates, for any system that has two directions', () => {
    const unit = fc.tuple(fc.double({ min: -80, max: 80, noNaN: true }), fc.double({ min: -80, max: 80, noNaN: true }));
    fc.assert(
      fc.property(unit, unit, fc.tuple(fc.double({ min: -5, max: 5, noNaN: true }), fc.double({ min: -5, max: 5, noNaN: true })), (xu, yu, [dx, dy]) => {
        fc.pre(Math.abs(xu[0] * yu[1] - yu[0] * xu[1]) > 50);
        const space = systemSpace({ ...plane, x_unit: xu, y_unit: yu });
        const [a, b] = space.toPixel([0, 0]);
        const [c, d] = space.toPixel([dx, dy]);
        const [u, v] = space.fromPixelDelta(c - a, d - b);
        expect(u).toBeCloseTo(dx, 6);
        expect(v).toBeCloseTo(dy, 6);
      }),
    );
  });

  it('moves along a line only when its directions are the same', () => {
    const line: CoordinateSystem = { id: 'nl', type: 'number_line', origin: [100, 100], x_unit: [50, 0], y_unit: null, z_unit: null };
    const space = systemSpace(line);
    expect(space.fromPixelDelta(100, 37)).toEqual([2, 0]);
  });

  it('steps by a tenth of a unit, or a whole one', () => {
    const space = systemSpace(plane);
    expect([space.step, space.bigStep]).toEqual([0.1, 1]);
  });
});

describe('which space an object is in', () => {
  it('is its coordinate system, when it is on one that is on screen', () => {
    expect(spaceFor(undefined, mapping, [plane])?.kind).toBe('frame');
    expect(spaceFor('plane', mapping, [plane])?.kind).toBe('system');
    expect(spaceFor('elsewhere', mapping, [plane])).toBeNull();
    expect(spaceFor('', mapping, [plane])?.kind).toBe('frame');
  });
});

describe('rounding', () => {
  it('snaps to a grid without float noise', () => {
    expect(snap(0.1 + 0.2, 0.1)).toBe(0.3);
    expect(snap(2.345, 0.01)).toBe(2.35);
    expect(snap(-0.04, 0.1)).toBe(0);
    expect(Object.is(snap(-0.04, 0.1), -0)).toBe(false);
    expect(snap(7.6, 0.5)).toBe(7.5);
    expect(snap(1.26, 1)).toBe(1);
  });

  it('always lands on a multiple of the step', () => {
    fc.assert(
      fc.property(fc.double({ min: -1000, max: 1000, noNaN: true }), fc.constantFrom(0.01, 0.1, 0.5, 1), (value, step) => {
        const out = snap(value, step);
        expect(Math.abs(out - value)).toBeLessThanOrEqual(step / 2 + 1e-9);
        expect(Math.abs(out / step - Math.round(out / step))).toBeLessThan(1e-6);
      }),
    );
  });

  it('tidies float noise away', () => {
    expect(tidy(0.1 + 0.2)).toBe(0.3);
    expect(Object.is(tidy(-0), 0)).toBe(true);
    expect(tidy(1.2345678)).toBe(1.234568);
  });
});
