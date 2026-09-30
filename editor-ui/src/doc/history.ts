/**
 * Undo and redo over snapshots. Documents are immutable, so a snapshot is just the old
 * value, and structural sharing keeps a long history cheap.
 *
 * Edits carrying the same `key` within `window` ms of each other, such as the keystrokes of
 * one word typed into a field or a run of arrow key nudges, make one step of history.
 */
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  lastKey: string | null;
  lastTime: number;
}

export const HISTORY_LIMIT = 300;
export const COALESCE_WINDOW_MS = 1000;

export function createHistory<T>(present: T): History<T> {
  return { past: [], present, future: [], lastKey: null, lastTime: 0 };
}

export interface CommitOptions {
  /** Edits with the same key close together in time merge into one undo step. */
  key?: string | null;
  now?: number;
  window?: number;
}

export function commit<T>(history: History<T>, next: T, options: CommitOptions = {}): History<T> {
  if (next === history.present) return history;
  const now = options.now ?? Date.now();
  const key = options.key ?? null;
  const window = options.window ?? COALESCE_WINDOW_MS;
  const merge = key !== null && key === history.lastKey && now - history.lastTime <= window && history.past.length > 0;
  if (merge) {
    return { past: history.past, present: next, future: [], lastKey: key, lastTime: now };
  }
  const past = [...history.past, history.present];
  if (past.length > HISTORY_LIMIT) past.splice(0, past.length - HISTORY_LIMIT);
  return { past, present: next, future: [], lastKey: key, lastTime: now };
}

/** Replace the present without making an undo step (e.g. the server's canonical form of it). */
export function replacePresent<T>(history: History<T>, next: T): History<T> {
  return { ...history, present: next };
}

export function canUndo<T>(history: History<T>): boolean {
  return history.past.length > 0;
}

export function canRedo<T>(history: History<T>): boolean {
  return history.future.length > 0;
}

export function undo<T>(history: History<T>): History<T> {
  if (history.past.length === 0) return history;
  const previous = history.past[history.past.length - 1]!;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    lastKey: null,
    lastTime: 0,
  };
}

export function redo<T>(history: History<T>): History<T> {
  if (history.future.length === 0) return history;
  const [next, ...rest] = history.future;
  return {
    past: [...history.past, history.present],
    present: next!,
    future: rest,
    lastKey: null,
    lastTime: 0,
  };
}

/** Stop the next edit from merging into the last one, e.g. when a field loses focus. */
export function breakCoalescing<T>(history: History<T>): History<T> {
  return history.lastKey === null ? history : { ...history, lastKey: null };
}
