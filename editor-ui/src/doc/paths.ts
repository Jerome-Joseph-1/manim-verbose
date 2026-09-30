/** Reading and writing a value by its path (a problem's `loc`) in plain JSON data. */
import type { Loc } from './types';

type Container = Record<string | number, unknown>;

function isContainer(value: unknown): value is Container {
  return typeof value === 'object' && value !== null;
}

export function getIn(root: unknown, loc: Loc): unknown {
  let node: unknown = root;
  for (const key of loc) {
    if (!isContainer(node)) return undefined;
    node = (node as Container)[key];
  }
  return node;
}

/**
 * Write `value` at `loc` in a mutable value (such as an immer draft), creating objects on
 * the way as needed. `undefined` deletes: a key from an object, an item from a list.
 */
export function setInMutable(root: unknown, loc: Loc, value: unknown): void {
  if (loc.length === 0) throw new Error('Cannot replace the root');
  let node = root as Container;
  for (let i = 0; i < loc.length - 1; i += 1) {
    const key = loc[i]!;
    let next = node[key];
    if (!isContainer(next)) {
      if (value === undefined) return; // nothing there to delete
      next = typeof loc[i + 1] === 'number' ? [] : {};
      node[key] = next;
    }
    node = next as Container;
  }
  const last = loc[loc.length - 1]!;
  if (value === undefined) {
    if (Array.isArray(node) && typeof last === 'number') {
      if (last < node.length) node.splice(last, 1);
    } else {
      delete node[last];
    }
  } else {
    node[last] = value;
  }
}

export function locEquals(a: Loc, b: Loc): boolean {
  return a.length === b.length && a.every((part, i) => part === b[i]);
}

export function locStartsWith(loc: Loc, prefix: Loc): boolean {
  return prefix.length <= loc.length && prefix.every((part, i) => part === loc[i]);
}

/** "scenes[0].steps[3].target", as validate.py writes a loc. */
export function formatLoc(loc: Loc): string {
  let out = '';
  for (const part of loc) {
    if (typeof part === 'number') out += `[${part}]`;
    else out += out ? `.${part}` : part;
  }
  return out;
}
