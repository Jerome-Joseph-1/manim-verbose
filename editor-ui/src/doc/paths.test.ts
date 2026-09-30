import { describe, expect, it } from 'vitest';
import { formatLoc, getIn, locEquals, locStartsWith, setInMutable } from './paths';

describe('paths', () => {
  it('reads by path', () => {
    const data = { a: [{ b: 1 }, { b: [5, 6] }] };
    expect(getIn(data, ['a', 1, 'b', 0])).toBe(5);
    expect(getIn(data, ['a', 3, 'b'])).toBeUndefined();
    expect(getIn(data, [])).toBe(data);
    expect(getIn(null, ['x'])).toBeUndefined();
  });

  it('writes by path, creating containers', () => {
    const data: Record<string, unknown> = {};
    setInMutable(data, ['place', 'at'], [1, 2]);
    setInMutable(data, ['points', 0], [0, 0]);
    expect(data).toEqual({ place: { at: [1, 2] }, points: [[0, 0]] });
  });

  it('deletes by path, from objects and lists', () => {
    const data: Record<string, unknown> = { a: 1, list: ['x', 'y', 'z'] };
    setInMutable(data, ['a'], undefined);
    setInMutable(data, ['list', 1], undefined);
    setInMutable(data, ['missing', 'deep'], undefined);
    expect(data).toEqual({ list: ['x', 'z'] });
    expect(() => setInMutable(data, [], 1)).toThrow();
  });

  it('formats and compares locs', () => {
    expect(formatLoc(['scenes', 0, 'steps', 3, 'target'])).toBe('scenes[0].steps[3].target');
    expect(formatLoc([])).toBe('');
    expect(locStartsWith(['a', 0, 'b'], ['a', 0])).toBe(true);
    expect(locStartsWith(['a'], ['a', 0])).toBe(false);
    expect(locEquals(['a', 1], ['a', 1])).toBe(true);
    expect(locEquals(['a', 1], ['a', '1'])).toBe(false);
  });
});
