/**
 * Putting each problem beside the field it is about.
 *
 * A problem says where it is twice: `loc`, a path into the document as it was checked, and
 * `scene_id` with `item_id`, which survive steps being added or moved since. So the item is
 * found by id, and only the part of `loc` after the item (the field) is taken from the path.
 */
import type { Document, Loc, Problem } from '../doc/types';
import type { ItemKind } from '../doc/ops';
import { formatLoc, locStartsWith } from '../doc/paths';

export interface ProblemTarget {
  kind: ItemKind;
  sceneId: string | null;
  /** The object or step (possibly one nested in `together`) the problem is about. */
  itemId: string | null;
  /** Path of the field inside the item; empty for the item as a whole. */
  field: Loc;
}

export interface ItemAddress {
  kind: ItemKind;
  sceneId?: string | null;
  itemId?: string | null;
}

function idAt(doc: Document | null | undefined, loc: Loc): string | null {
  let node: unknown = doc;
  for (const part of loc) {
    if (typeof node !== 'object' || node === null) return null;
    node = (node as Record<string | number, unknown>)[part];
  }
  if (typeof node === 'object' && node !== null && typeof (node as { id?: unknown }).id === 'string') {
    return (node as { id: string }).id;
  }
  return null;
}

/** Which item and field a problem is about. `doc` fills in ids a problem lacks. */
export function locateProblem(problem: Problem, doc?: Document | null): ProblemTarget {
  const loc = problem.loc ?? [];
  if (loc[0] !== 'scenes' || typeof loc[1] !== 'number') {
    return { kind: 'document', sceneId: null, itemId: null, field: loc };
  }
  const sceneId = problem.scene_id ?? idAt(doc, loc.slice(0, 2));
  const rest = loc.slice(2);
  if (rest[0] === 'objects' && typeof rest[1] === 'number') {
    return {
      kind: 'object',
      sceneId,
      itemId: problem.item_id ?? idAt(doc, loc.slice(0, 4)),
      field: rest.slice(2),
    };
  }
  if (rest[0] === 'steps' && typeof rest[1] === 'number') {
    // Go as deep as ('steps', n) pairs go: a problem inside `together` is about the inner step
    let depth = 2;
    while (rest[depth] === 'steps' && typeof rest[depth + 1] === 'number') depth += 2;
    return {
      kind: 'step',
      sceneId,
      itemId: problem.item_id ?? idAt(doc, loc.slice(0, 2 + depth)),
      field: rest.slice(depth),
    };
  }
  return { kind: 'scene', sceneId, itemId: null, field: rest };
}

export function sameItem(target: ProblemTarget, item: ItemAddress): boolean {
  if (target.kind !== item.kind) return false;
  if (item.kind === 'document') return true;
  if ((item.sceneId ?? null) !== target.sceneId) return false;
  if (item.kind === 'scene') return true;
  return (item.itemId ?? null) === target.itemId;
}

/** Problems about an item, anywhere in it. */
export function problemsForItem(problems: Problem[], item: ItemAddress, doc?: Document | null): Problem[] {
  return problems.filter((p) => sameItem(locateProblem(p, doc), item));
}

/**
 * Problems about a field of an item, or anything inside that field (`exact` for the field
 * itself only).
 */
export function problemsForField(
  problems: Problem[],
  item: ItemAddress,
  field: Loc,
  options: { exact?: boolean; doc?: Document | null } = {},
): Problem[] {
  return problems.filter((p) => {
    const target = locateProblem(p, options.doc);
    if (!sameItem(target, item)) return false;
    return options.exact ? formatLoc(target.field) === formatLoc(field) : locStartsWith(target.field, field);
  });
}

export function worstSeverity(problems: Problem[]): 'error' | 'warning' | null {
  if (problems.some((p) => p.severity === 'error')) return 'error';
  if (problems.length > 0) return 'warning';
  return null;
}

/** The same problem reported twice (by a save and by a render, say) shown once. */
export function dedupeProblems(problems: Problem[]): Problem[] {
  const seen = new Set<string>();
  const out: Problem[] = [];
  for (const p of problems) {
    const key = `${p.severity}|${formatLoc(p.loc ?? [])}|${p.message}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(p);
    }
  }
  return out;
}

/** Errors first, then in document order. */
export function sortProblems(problems: Problem[]): Problem[] {
  const rank = (p: Problem) => (p.severity === 'error' ? 0 : 1);
  return [...problems].sort((a, b) => rank(a) - rank(b) || compareLoc(a.loc ?? [], b.loc ?? []));
}

function compareLoc(a: Loc, b: Loc): number {
  for (let i = 0; i < Math.min(a.length, b.length); i += 1) {
    const x = a[i]!;
    const y = b[i]!;
    if (x === y) continue;
    if (typeof x === 'number' && typeof y === 'number') return x - y;
    return String(x) < String(y) ? -1 : 1;
  }
  return a.length - b.length;
}

/** The data-field attribute value an input for this field carries, for focusing it. */
export function fieldKey(field: Loc): string {
  return formatLoc(field);
}
