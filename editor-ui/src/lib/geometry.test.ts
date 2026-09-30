import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  boxContains, cycleHit, defaultMapping, fitMapping, frameToPixel, hitTest, hitTestAll, pixelDeltaToFrame, pixelToFrame, roundFrame,
  scaleBox, type Box, type FrameMapping, type StillObject,
} from './geometry';

/** Make a still object from a frame box under a mapping, as a server would. */
function objectAt(id: string, frame: Box, m: FrameMapping): StillObject {
  const [x0, y0] = frameToPixel(m, frame[0], frame[3]);
  const [x1, y1] = frameToPixel(m, frame[2], frame[1]);
  return { id, bbox: [x0, y0, x1, y1], frame_bbox: frame };
}

const close = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) < eps;

describe('the default frame', () => {
  it('is 8 units high, centred, y up', () => {
    const m = defaultMapping(960, 540);
    expect(frameToPixel(m, 0, 0)).toEqual([480, 270]);
    const [, top] = frameToPixel(m, 0, 4);
    expect(top).toBeCloseTo(0);
    const [right] = frameToPixel(m, (8 * 16) / 9 / 2, 0);
    expect(right).toBeCloseTo(960);
  });

  it('maps back and forth', () => {
    const m = defaultMapping(1280, 720);
    const [px, py] = frameToPixel(m, 1.5, -2.25);
    const [x, y] = pixelToFrame(m, px, py);
    expect(x).toBeCloseTo(1.5);
    expect(y).toBeCloseTo(-2.25);
  });
});

describe('fitting the mapping from a still', () => {
  it('recovers the mapping from the objects exactly', () => {
    const truth = defaultMapping(960, 540);
    const objects = [objectAt('a', [-1, 2, 2, 3], truth), objectAt('b', [3, -3, 4.5, -1], truth)];
    const m = fitMapping(objects, 960, 540);
    expect(m.ax).toBeCloseTo(truth.ax);
    expect(m.bx).toBeCloseTo(truth.bx);
    expect(m.ay).toBeCloseTo(truth.ay);
    expect(m.by).toBeCloseTo(truth.by);
  });

  it('follows a zoomed and panned camera', () => {
    const zoomed: FrameMapping = { ax: 135, bx: 480 - 135 * 2, ay: -135, by: 270 - 135 * 1 };
    const objects = [objectAt('a', [1, 0, 3, 2], zoomed), objectAt('b', [2, 0.5, 2.5, 1.5], zoomed)];
    const m = fitMapping(objects, 960, 540);
    expect(m.ax).toBeCloseTo(135);
    expect(m.bx).toBeCloseTo(210);
    expect(m.ay).toBeCloseTo(-135);
    expect(m.by).toBeCloseTo(135);
  });

  it('takes the vertical scale from the horizontal one when nothing has height', () => {
    const truth = defaultMapping(960, 540);
    const line = objectAt('line', [-2, 1, 2, 1], truth);
    const m = fitMapping([line], 960, 540);
    expect(m.ax).toBeCloseTo(truth.ax);
    expect(m.ay).toBeCloseTo(-truth.ax);
    expect(frameToPixel(m, 0, 1)[1]).toBeCloseTo(frameToPixel(truth, 0, 1)[1]);
  });

  it('takes the horizontal scale from the vertical one when nothing has width', () => {
    const truth = defaultMapping(960, 540);
    const m = fitMapping([objectAt('v', [1, -2, 1, 2], truth)], 960, 540);
    expect(m.ay).toBeCloseTo(truth.ay);
    expect(m.ax).toBeCloseTo(-truth.ay);
    expect(frameToPixel(m, 1, 0)[0]).toBeCloseTo(frameToPixel(truth, 1, 0)[0]);
  });

  it('falls back to the default frame with nothing to go on', () => {
    expect(fitMapping([], 960, 540)).toEqual(defaultMapping(960, 540));
    const dot: StillObject = { id: 'p', bbox: [480, 270, 480, 270], frame_bbox: [0, 0, 0, 0] };
    expect(fitMapping([dot], 960, 540)).toEqual(defaultMapping(960, 540));
    const broken = { id: 'x', bbox: [Number.NaN, 0, 1, 1], frame_bbox: [0, 0, 1, 1] } as StillObject;
    expect(fitMapping([broken], 960, 540)).toEqual(defaultMapping(960, 540));
  });

  it('round trips any point for any camera (property)', () => {
    fc.assert(
      fc.property(
        fc.double({ min: 20, max: 400, noNaN: true }),
        fc.double({ min: -500, max: 1500, noNaN: true }),
        fc.double({ min: -500, max: 1000, noNaN: true }),
        fc.array(fc.tuple(fc.double({ min: -7, max: 7, noNaN: true }), fc.double({ min: -4, max: 4, noNaN: true }), fc.double({ min: 0.1, max: 3, noNaN: true }), fc.double({ min: 0.1, max: 3, noNaN: true })), { minLength: 1, maxLength: 6 }),
        fc.double({ min: -7, max: 7, noNaN: true }),
        fc.double({ min: -4, max: 4, noNaN: true }),
        (scale, bx, by, boxes, x, y) => {
          const truth: FrameMapping = { ax: scale, bx, ay: -scale, by };
          const objects = boxes.map(([cx, cy, w, h], i) => objectAt(`o${i}`, [cx, cy, cx + w, cy + h], truth));
          const m = fitMapping(objects, 960, 540);
          const [px, py] = frameToPixel(m, x, y);
          const [tx, ty] = frameToPixel(truth, x, y);
          expect(close(px, tx, 1e-3)).toBe(true);
          expect(close(py, ty, 1e-3)).toBe(true);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('turns a drag in pixels into a move in frame units', () => {
    const m = defaultMapping(960, 540);
    const [dx, dy] = pixelDeltaToFrame(m, m.ax, -2 * m.ax);
    expect(dx).toBeCloseTo(1);
    expect(dy).toBeCloseTo(2);
  });
});

describe('hit testing', () => {
  const plane: StillObject = { id: 'plane', bbox: [0, 0, 960, 540], frame_bbox: [-7.1, -4, 7.1, 4] };
  const square: StillObject = { id: 'square', bbox: [300, 200, 500, 400], frame_bbox: [0, 0, 1, 1] };
  const label: StillObject = { id: 'label', bbox: [350, 250, 450, 300], frame_bbox: [0, 0, 1, 1] };
  const line: StillObject = { id: 'line', bbox: [100, 100, 300, 100], frame_bbox: [0, 0, 1, 0] };
  const objects = [plane, square, label, line];

  it('picks the topmost object containing the point (the last drawn)', () => {
    expect(hitTest(objects, 400, 275)?.id).toBe('label');
    expect(hitTest(objects, 320, 380)?.id).toBe('square');
    expect(hitTest(objects, 10, 10)?.id).toBe('plane');
    expect(hitTest([square], 10, 10)).toBeNull();
  });

  it('lists every object at a point, topmost first', () => {
    expect(hitTestAll(objects, 400, 275).map((o) => o.id)).toEqual(['label', 'square', 'plane']);
  });

  it('can hit a line with no height, with a little slop', () => {
    expect(hitTest(objects, 200, 102)?.id).toBe('line');
    expect(hitTest(objects, 200, 110)?.id).toBe('plane');
  });

  it('cycles through overlapping objects on repeated clicks', () => {
    expect(cycleHit(objects, 400, 275, null)?.id).toBe('label');
    expect(cycleHit(objects, 400, 275, 'label')?.id).toBe('square');
    expect(cycleHit(objects, 400, 275, 'square')?.id).toBe('plane');
    expect(cycleHit(objects, 400, 275, 'plane')?.id).toBe('label');
    expect(cycleHit(objects, 400, 275, 'line')?.id).toBe('label');
    expect(cycleHit([square], 0, 0, 'square')).toBeNull();
  });

  it('treats boxes given the wrong way round like any other', () => {
    expect(boxContains([500, 400, 300, 200], 400, 300)).toBe(true);
  });

  it('agrees with a brute force check (property)', () => {
    const box = fc.tuple(fc.integer({ min: 0, max: 900 }), fc.integer({ min: 0, max: 500 }), fc.integer({ min: 10, max: 300 }), fc.integer({ min: 10, max: 300 }));
    fc.assert(
      fc.property(fc.array(box, { minLength: 1, maxLength: 8 }), fc.integer({ min: 0, max: 960 }), fc.integer({ min: 0, max: 540 }), (boxes, x, y) => {
        const objs: StillObject[] = boxes.map(([bx, by, w, h], i) => ({ id: `o${i}`, bbox: [bx, by, bx + w, by + h], frame_bbox: [0, 0, 1, 1] }));
        const expected = [...objs].reverse().find((o) => x >= o.bbox[0] && x <= o.bbox[2] && y >= o.bbox[1] && y <= o.bbox[3]);
        expect(hitTest(objs, x, y)?.id).toBe(expected?.id);
      }),
      { numRuns: 300 },
    );
  });
});

describe('small helpers', () => {
  it('rounds to hundredths without negative zero', () => {
    expect(roundFrame(1.23456)).toBe(1.23);
    expect(Object.is(roundFrame(-0.001), 0)).toBe(true);
  });

  it('scales boxes', () => {
    expect(scaleBox([10, 20, 30, 40], 0.5, 2)).toEqual([5, 40, 15, 80]);
  });
});
