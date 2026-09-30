/** Moving the points of plotted objects: as a whole, or one point at a time. */
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import type { SceneObject } from '../doc/types';
import { allPoints, isPlotted, movePoint, offset, pointHandles, pointOf, translatePoints } from './handles';

const vector: SceneObject = { id: 'v', type: 'vector', tip: [2, 1], on: 'plane' };
const line: SceneObject = { id: 'l', type: 'line', start: [-1, 0], end: [1, 0.5, 2] };
const polygon: SceneObject = { id: 'p', type: 'polygon', points: [[0, 0], [2, 0], [1, 1.5]] };
const angle: SceneObject = { id: 'a', type: 'angle', points: [[2, 0], [0, 0], [1, 1]] };
const arc: SceneObject = { id: 'r', type: 'arc', radius: 1 };
const dot: SceneObject = { id: 'd', type: 'dot', point: [1, 1] };
const braceOnPoints: SceneObject = { id: 'b', type: 'brace', start: [0, 0], end: [3, 0] };
const braceOnObject: SceneObject = { id: 'b', type: 'brace', target: 'eq' };

describe('which objects are plotted', () => {
  it('knows them by their points', () => {
    expect([vector, line, polygon, angle, arc, dot, braceOnPoints].every(isPlotted)).toBe(true);
    expect(isPlotted(braceOnObject)).toBe(false);
    expect(isPlotted({ id: 't', type: 'text', text: 'hi' })).toBe(false);
  });

  it('fills in the default tail of a vector and centre of an arc', () => {
    expect(pointOf(vector, { field: 'tail' })).toEqual([0, 0]);
    expect(pointOf(arc, { field: 'center' })).toEqual([0, 0]);
    expect(allPoints(vector)).toEqual([[0, 0], [2, 1]]);
    expect(allPoints(angle)).toHaveLength(3);
  });
});

describe('handles', () => {
  it('are on a vector tip and tail, a line ends, a polygon corners, a brace ends', () => {
    expect(pointHandles(vector).map((h) => h.field)).toEqual(['tip', 'tail']);
    expect(pointHandles(line).map((h) => h.label)).toEqual(['start', 'end']);
    expect(pointHandles(polygon).map((h) => h.index)).toEqual([0, 1, 2]);
    expect(pointHandles(braceOnPoints).map((h) => h.field)).toEqual(['start', 'end']);
    expect(pointHandles(braceOnObject)).toEqual([]);
    // Angles and arcs move as a whole
    expect(pointHandles(angle)).toEqual([]);
    expect(pointHandles(arc)).toEqual([]);
  });

  it('move one point, rounded, keeping any z', () => {
    expect(movePoint(vector, { field: 'tip' }, [3.04, -1.26], 0.1)).toEqual({ tip: [3, -1.3] });
    expect(movePoint(line, { field: 'end' }, [0.123, 4.5], 0.01)).toEqual({ end: [0.12, 4.5, 2] });
    expect(movePoint(polygon, { field: 'points', index: 1 }, [5, 5], 1)).toEqual({ points: [[0, 0], [5, 5], [1, 1.5]] });
    expect(movePoint(vector, { field: 'tail' }, [1, 1], 0.1)).toEqual({ tail: [1, 1] });
    expect(movePoint(braceOnObject, { field: 'start' }, [1, 1], 0.1)).toBeNull();
  });
});

describe('moving as a whole', () => {
  it('moves every point, and a default tail with the tip', () => {
    expect(translatePoints(vector, 1, -1, 0.1)).toEqual({ tail: [1, -1], tip: [3, 0] });
    expect(translatePoints(line, 0.5, 0.5, 0.01)).toEqual({ start: [-0.5, 0.5], end: [1.5, 1, 2] });
    expect(translatePoints(arc, 2, 0, 0.1)).toEqual({ center: [2, 0] });
    expect(translatePoints(angle, 0, 1, 0.1)).toEqual({ points: [[2, 1], [0, 1], [1, 2]] });
    expect(translatePoints(braceOnPoints, 1, 1, 0.1)).toEqual({ start: [1, 1], end: [4, 1] });
    expect(translatePoints(braceOnObject, 1, 1, 0.1)).toBeNull();
  });

  it('rounds the move, not the points, so the shape stays exactly the same', () => {
    const point = fc.tuple(fc.integer({ min: -500, max: 500 }), fc.integer({ min: -500, max: 500 })).map(([x, y]) => [x / 100, y / 100]);
    fc.assert(
      fc.property(fc.array(point, { minLength: 3, maxLength: 6 }), fc.double({ min: -5, max: 5, noNaN: true }), fc.double({ min: -5, max: 5, noNaN: true }), (points, dx, dy) => {
        const shape: SceneObject = { id: 'p', type: 'polygon', points };
        const moved = translatePoints(shape, dx, dy, 0.1)!.points as number[][];
        const shiftX = moved[0]![0]! - points[0]![0]!;
        const shiftY = moved[0]![1]! - points[0]![1]!;
        expect(Math.abs(shiftX - dx)).toBeLessThanOrEqual(0.05 + 1e-9);
        moved.forEach((p, i) => {
          expect(p[0]! - points[i]![0]!).toBeCloseTo(shiftX, 6);
          expect(p[1]! - points[i]![1]!).toBeCloseTo(shiftY, 6);
        });
      }),
    );
  });

  it('offsets pixel points', () => {
    expect(offset([1, 2], [3, 4])).toEqual([4, 6]);
    expect(offset([1, 2], null)).toEqual([1, 2]);
  });
});
