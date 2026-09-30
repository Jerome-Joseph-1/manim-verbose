/**
 * Names for new objects, steps and scenes. Ids have to be valid Python identifiers (the
 * generated code uses object ids as variable names), at most 64 characters. Object ids are
 * unique within their scene, step ids across the whole document, scene ids across scenes.
 */
import { ID_MAX_LENGTH, ID_PATTERN, type Document, type Json, type Scene, type Step } from './types';

export function isValidId(value: string): boolean {
  return value.length <= ID_MAX_LENGTH && ID_PATTERN.test(value);
}

/**
 * The nearest valid id to what someone typed: "My circle!" -> "My_circle". A valid id comes
 * back unchanged.
 */
export function sanitizeId(value: string): string {
  if (isValidId(value)) return value;
  let out = value.trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
  if (out === '') out = 'item';
  if (/^[0-9]/.test(out)) out = `_${out}`;
  return out.slice(0, ID_MAX_LENGTH);
}

function withSuffix(stem: string, n: number): string {
  const suffix = `_${n}`;
  return stem.slice(0, ID_MAX_LENGTH - suffix.length) + suffix;
}

/**
 * An id based on `base` which isn't in `taken`: `base` itself when free (and `bare` is
 * allowed), else base_2, base_3 and so on (from `start`). A base already ending in _N
 * continues from N + 1.
 */
export function uniqueId(
  base: string,
  taken: Set<string>,
  options: { bare?: boolean; start?: number } = {},
): string {
  const clean = sanitizeId(base);
  const bare = options.bare ?? true;
  if (bare && !taken.has(clean)) return clean;
  const match = /^(.*?)_(\d+)$/.exec(clean);
  const numbered = match !== null && match[1] !== undefined && match[1] !== '' && (match[2]?.length ?? 0) < 9;
  const stem = numbered ? match[1]! : clean;
  let n = numbered ? Number(match[2]) + 1 : (options.start ?? 2);
  for (;;) {
    const candidate = withSuffix(stem, n);
    if (!taken.has(candidate)) return candidate;
    n += 1;
  }
}

function isStepLike(value: Json | undefined): value is Json & Step {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && typeof value.do === 'string';
}

/** Every step in a list, including those nested in `together`, depth first. */
export function* iterSteps(steps: Step[] | undefined): Generator<Step> {
  for (const step of steps ?? []) {
    yield step;
    const inner = step.steps;
    if (step.do === 'together' && Array.isArray(inner)) {
      yield* iterSteps(inner.filter(isStepLike) as Step[]);
    }
  }
}

export function stepIds(doc: Document): Set<string> {
  const ids = new Set<string>();
  for (const scene of doc.scenes) {
    for (const step of iterSteps(scene.steps)) if (step.id) ids.add(step.id);
  }
  return ids;
}

export function objectIds(scene: Scene): Set<string> {
  return new Set((scene.objects ?? []).map((o) => o.id));
}

export function sceneIds(doc: Document): Set<string> {
  return new Set(doc.scenes.map((s) => s.id));
}

/**
 * A step id the way the server makes them (`<scene>_<n>`, see assign_step_ids in
 * validate.py): the smallest n not yet taken anywhere in the document.
 */
export function newStepId(sceneId: string, taken: Set<string>): string {
  for (let n = 1; ; n += 1) {
    const candidate = withSuffix(sceneId, n);
    if (!taken.has(candidate)) return candidate;
  }
}

/** Friendlier starting names than the raw type for a few kinds of object. */
const OBJECT_BASE_NAMES: Record<string, string> = {
  tex: 'equation',
  number_plane: 'plane',
  axes_3d: 'axes3d',
  bullets: 'list',
  svg: 'drawing',
  box: 'box',
};

export function objectBaseName(type: string): string {
  return OBJECT_BASE_NAMES[type] ?? type;
}

export function newObjectId(scene: Scene, type: string): string {
  return uniqueId(objectBaseName(type), objectIds(scene));
}

export function newSceneId(doc: Document, base = 'scene'): string {
  return uniqueId(base, sceneIds(doc), { bare: false, start: 1 });
}
