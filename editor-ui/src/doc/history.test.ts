import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import {
  HISTORY_LIMIT, breakCoalescing, canRedo, canUndo, commit, createHistory, redo, replacePresent, selectionAfterRedo, selectionAfterUndo, undo,
} from './history';

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

describe('what went with each edit', () => {
  it('gives back what was selected before an edit on undo, and after it on redo', () => {
    let h = createHistory<string, string>('doc0');
    h = commit(h, 'doc1', { now: 0, meta: { before: 'circle', after: 'circle' } });
    h = commit(h, 'doc2', { now: 5000, meta: { before: 'text', after: 'new thing' } });
    expect(selectionAfterUndo(h)).toBe('text');
    h = undo(h);
    expect(selectionAfterUndo(h)).toBe('circle');
    expect(selectionAfterRedo(h)).toBe('new thing');
    h = undo(h);
    expect(selectionAfterUndo(h)).toBeUndefined();
    expect(selectionAfterRedo(h)).toBe('circle');
    h = redo(h);
    expect(h.present).toBe('doc1');
    expect(selectionAfterRedo(h)).toBe('new thing');
  });

  it('keeps the first before and the last after of edits merged into one', () => {
    let h = createHistory<number, string>(0);
    h = commit(h, 1, { key: 'typing', now: 0, meta: { before: 'a', after: 'b' } });
    h = commit(h, 2, { key: 'typing', now: 100, meta: { before: 'b', after: 'c' } });
    expect(h.past).toEqual([0]);
    expect(h.pastMeta).toEqual([{ before: 'a', after: 'c' }]);
  });

  it('keeps meta in step with the snapshots, whatever is done', () => {
    type Op = { kind: 'commit'; key: string | null; at: number } | { kind: 'undo' } | { kind: 'redo' };
    const op: fc.Arbitrary<Op> = fc.oneof(
      fc.record({ kind: fc.constant('commit' as const), key: fc.constantFrom(null, 'k'), at: fc.integer({ min: 0, max: 3000 }) }),
      fc.constant({ kind: 'undo' as const }),
      fc.constant({ kind: 'redo' as const }),
    );
    fc.assert(
      fc.property(fc.array(op, { maxLength: 60 }), (ops) => {
        let h = createHistory<number, number>(0);
        let n = 0;
        let now = 0;
        for (const o of ops) {
          if (o.kind === 'commit') {
            n += 1;
            now += o.at;
            h = commit(h, n, { key: o.key, now, meta: { before: -n, after: n } });
          } else if (o.kind === 'undo') {
            const wanted = selectionAfterUndo(h);
            const before = h;
            h = undo(h);
            // The selection given back is the one from before the edit that made what was undone
            if (before.past.length) expect(wanted).toBeLessThan(0);
          } else {
            h = redo(h);
          }
          expect(h.pastMeta).toHaveLength(h.past.length);
          expect(h.futureMeta).toHaveLength(h.future.length);
          // Redoing gives the selection after the edit which made the state redone
          if (h.future.length) expect(selectionAfterRedo(h)).toBe(h.future[0]);
        }
      }),
    );
  });

  it('drops old meta along with old snapshots', () => {
    let h = createHistory<number, number>(0);
    for (let i = 1; i <= HISTORY_LIMIT + 10; i += 1) h = commit(h, i, { meta: { before: i - 1, after: i } });
    expect(h.pastMeta).toHaveLength(HISTORY_LIMIT);
    expect(h.pastMeta[0]).toEqual({ before: 10, after: 11 });
  });
});
