/** Resizing and turning with the handles on the canvas. */
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { MAX_SCALE, MIN_SCALE, angleOf, normalizeDegrees, rotationFromDrag, scaleFromDrag } from './transform';

describe('resizing', () => {
  it('scales by how much further from the centre the pointer ends up', () => {
    expect(scaleFromDrag(1, [0, 0], [10, 0], [20, 0])).toBe(2);
    expect(scaleFromDrag(2, [0, 0], [10, 10], [5, 5])).toBe(1);
    expect(scaleFromDrag(1, [100, 100], [110, 100], [100, 113.3])).toBe(1.33);
  });

  it('rounds to a hundredth, or a quarter with Shift', () => {
    expect(scaleFromDrag(1, [0, 0], [100, 0], [137, 0])).toBe(1.37);
    expect(scaleFromDrag(1, [0, 0], [100, 0], [137, 0], true)).toBe(1.25);
  });

  it('stays within limits, and ignores a drag starting on the centre', () => {
    expect(scaleFromDrag(1, [0, 0], [100, 0], [0.1, 0])).toBe(MIN_SCALE);
    expect(scaleFromDrag(10, [0, 0], [10, 0], [1000, 0])).toBe(MAX_SCALE);
    expect(scaleFromDrag(1.5, [0, 0], [0.2, 0], [50, 0])).toBe(1.5);
  });
});

describe('turning', () => {
  it('measures angles counterclockwise, with pixels y down', () => {
    expect(angleOf([0, 0], [10, 0])).toBe(0);
    expect(angleOf([0, 0], [0, -10])).toBe(90);
    expect(angleOf([0, 0], [-10, 0])).toBe(180);
  });

  it('turns by the angle swept round the centre', () => {
    expect(rotationFromDrag(0, [0, 0], [0, -10], [-10, 0])).toBe(90);
    expect(rotationFromDrag(30, [0, 0], [10, 0], [10, 10])).toBe(-15);
    expect(rotationFromDrag(0, [0, 0], [10, 0], [10, -3], true)).toBe(15);
  });

  it('keeps angles in (-180, 180]', () => {
    fc.assert(
      fc.property(fc.double({ min: -5000, max: 5000, noNaN: true }), (value) => {
        const out = normalizeDegrees(value);
        expect(out).toBeGreaterThan(-180);
        expect(out).toBeLessThanOrEqual(180);
        expect(Math.abs(((out - value) % 360 + 360) % 360) % 360).toBeCloseTo(0, 6);
      }),
    );
    expect(normalizeDegrees(-180)).toBe(180);
    expect(normalizeDegrees(540)).toBe(180);
  });
});
