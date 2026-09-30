/**
 * Undo and redo over snapshots. Documents are immutable, so a snapshot is just the old
 * value, and structural sharing keeps a long history cheap.
 *
 * Edits carrying the same `key` within `window` ms of each other, such as the keystrokes of
 * one word typed into a field or a run of arrow key nudges, make one step of history.
 *
 * Each edit can also carry `meta`: what was selected just before it (`before`) and just after
 * (`after`). Undoing an edit gives back its `before`, redoing it its `after`, so the selection
 * goes back and forth with the document and the user sees what changed.
 */
export interface EditMeta<S> {
  before: S;
  after: S;
}

export interface History<T, S = unknown> {
  past: T[];
  present: T;
  future: T[];
  /** For each entry of `past`, the edit which led from it to the next state (same index). */
  pastMeta: (EditMeta<S> | undefined)[];
  /** For each entry of `future`, the edit which leads to it (same index). */
  futureMeta: (EditMeta<S> | undefined)[];
  lastKey: string | null;
  lastTime: number;
}

export const HISTORY_LIMIT = 300;
export const COALESCE_WINDOW_MS = 1000;

export function createHistory<T, S = unknown>(present: T): History<T, S> {
  return { past: [], present, future: [], pastMeta: [], futureMeta: [], lastKey: null, lastTime: 0 };
}

export interface CommitOptions<S = unknown> {
  /** Edits with the same key close together in time merge into one undo step. */
  key?: string | null;
  now?: number;
  window?: number;
  /** What was selected before and after this edit. */
  meta?: EditMeta<S>;
}

export function commit<T, S>(history: History<T, S>, next: T, options: CommitOptions<S> = {}): History<T, S> {
  if (next === history.present) return history;
  const now = options.now ?? Date.now();
  const key = options.key ?? null;
  const window = options.window ?? COALESCE_WINDOW_MS;
  const merge = key !== null && key === history.lastKey && now - history.lastTime <= window && history.past.length > 0;
  if (merge) {
    // One step of history: from before the first of the merged edits to after the last
    const pastMeta = [...history.pastMeta];
    const last = pastMeta[pastMeta.length - 1];
    pastMeta[pastMeta.length - 1] = options.meta ? { before: last?.before ?? options.meta.before, after: options.meta.after } : last;
    return { ...history, present: next, future: [], futureMeta: [], pastMeta, lastKey: key, lastTime: now };
  }
  const past = [...history.past, history.present];
  const pastMeta = [...history.pastMeta, options.meta];
  if (past.length > HISTORY_LIMIT) {
    past.splice(0, past.length - HISTORY_LIMIT);
    pastMeta.splice(0, pastMeta.length - HISTORY_LIMIT);
  }
  return { past, present: next, future: [], pastMeta, futureMeta: [], lastKey: key, lastTime: now };
}

/** Replace the present without making an undo step (e.g. the server's canonical form of it). */
export function replacePresent<T, S>(history: History<T, S>, next: T): History<T, S> {
  return { ...history, present: next };
}

export function canUndo<T, S>(history: History<T, S>): boolean {
  return history.past.length > 0;
}

export function canRedo<T, S>(history: History<T, S>): boolean {
  return history.future.length > 0;
}

export function undo<T, S>(history: History<T, S>): History<T, S> {
  if (history.past.length === 0) return history;
  const previous = history.past[history.past.length - 1]!;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    pastMeta: history.pastMeta.slice(0, -1),
    futureMeta: [history.pastMeta[history.pastMeta.length - 1], ...history.futureMeta],
    lastKey: null,
    lastTime: 0,
  };
}

export function redo<T, S>(history: History<T, S>): History<T, S> {
  if (history.future.length === 0) return history;
  const [next, ...rest] = history.future;
  const [meta, ...restMeta] = history.futureMeta;
  return {
    past: [...history.past, history.present],
    present: next!,
    future: rest,
    pastMeta: [...history.pastMeta, meta],
    futureMeta: restMeta,
    lastKey: null,
    lastTime: 0,
  };
}

/** What to select once the last edit is undone: what was selected before it, if it was recorded. */
export function selectionAfterUndo<T, S>(history: History<T, S>): S | undefined {
  return history.pastMeta[history.pastMeta.length - 1]?.before;
}

/** What to select once the next edit is redone: what was selected after it, if it was recorded. */
export function selectionAfterRedo<T, S>(history: History<T, S>): S | undefined {
  return history.futureMeta[0]?.after;
}

/** Stop the next edit from merging into the last one, e.g. when a field loses focus. */
export function breakCoalescing<T, S>(history: History<T, S>): History<T, S> {
  return history.lastKey === null ? history : { ...history, lastKey: null };
}
