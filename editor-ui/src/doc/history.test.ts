import { describe, expect, it } from 'vitest';
import { HISTORY_LIMIT, breakCoalescing, canRedo, canUndo, commit, createHistory, redo, replacePresent, undo } from './history';

describe('history', () => {
  it('undoes and redoes', () => {
    let h = createHistory('a');
    h = commit(h, 'b', { now: 0 });
    h = commit(h, 'c', { now: 5000 });
    expect(h.present).toBe('c');
    h = undo(h);
    expect(h.present).toBe('b');
    h = undo(h);
    expect(h.present).toBe('a');
    expect(canUndo(h)).toBe(false);
    expect(undo(h)).toBe(h);
    h = redo(h);
    h = redo(h);
    expect(h.present).toBe('c');
    expect(canRedo(h)).toBe(false);
    expect(redo(h)).toBe(h);
  });

  it('drops the redo branch on a new edit', () => {
    let h = createHistory(1);
    h = commit(h, 2);
    h = undo(h);
    h = commit(h, 3);
    expect(canRedo(h)).toBe(false);
    expect(h.past).toEqual([1]);
  });

  it('ignores an edit which changes nothing', () => {
    const h = commit(createHistory('a'), 'b');
    expect(commit(h, h.present)).toBe(h);
  });

  it('merges edits with the same key close together', () => {
    let h = createHistory('');
    h = commit(h, 'h', { key: 'title', now: 0 });
    h = commit(h, 'he', { key: 'title', now: 300 });
    h = commit(h, 'hel', { key: 'title', now: 900 });
    expect(h.past).toEqual(['']);
    // a pause longer than the window starts a new step
    h = commit(h, 'hell', { key: 'title', now: 3000 });
    expect(h.past).toEqual(['', 'hel']);
    // a different key starts a new step
    h = commit(h, 'hello', { key: 'other', now: 3100 });
    expect(h.past).toEqual(['', 'hel', 'hell']);
    // and so does breaking the run (a field losing focus)
    h = breakCoalescing(h);
    h = commit(h, 'hello!', { key: 'other', now: 3200 });
    expect(h.past.length).toBe(4);
    expect(undo(h).present).toBe('hello');
  });

  it('never merges into the first state', () => {
    let h = createHistory('a');
    h = commit(h, 'b', { key: 'k', now: 0 });
    expect(h.past).toEqual(['a']);
  });

  it('keeps a bounded history', () => {
    let h = createHistory(0);
    for (let i = 1; i <= HISTORY_LIMIT + 50; i += 1) h = commit(h, i);
    expect(h.past.length).toBe(HISTORY_LIMIT);
    expect(h.past[0]).toBe(50);
  });

  it('replaces the present without an undo step', () => {
    let h = commit(createHistory('a'), 'b');
    h = replacePresent(h, 'B');
    expect(h.present).toBe('B');
    expect(undo(h).present).toBe('a');
  });
});
