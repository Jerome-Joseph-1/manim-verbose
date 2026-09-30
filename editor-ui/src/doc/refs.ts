/**
 * Every place an object or step refers to another object by id, mirroring `object_refs`
 * and `step_refs` in manim_verbose/scenefile/validate.py (next_to, on, targets, into,
 * focus, members, and a placement's `on`), plus the fields a change step can set which are
 * themselves references.
 *
 * References are scene local: an object in one scene can never refer to one in another.
 */
import type { Json, JsonObject, Loc, Scene, SceneObject, Step } from './types';

export interface RefSite {
  /** Where the reference is, relative to the object or top level step. */
  path: Loc;
  /** The id referred to. */
  id: string;
}

/** Called for each reference; `replace` writes a new id in its place (on a mutable value). */
export type RefVisitor = (id: string, path: Loc, replace: (next: string) => void) => void;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Types of object whose `target` field names another object. */
const TARGETING_OBJECTS = new Set(['brace', 'box']);

function visitScalar(container: Record<string, unknown>, key: string, path: Loc, visit: RefVisitor) {
  const value = container[key];
  if (typeof value === 'string') {
    visit(value, [...path, key], (next) => {
      container[key] = next;
    });
  }
}

function visitList(container: Record<string, unknown>, key: string, path: Loc, visit: RefVisitor) {
  const value = container[key];
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      if (typeof item === 'string') {
        visit(item, [...path, key, index], (next) => {
          value[index] = next;
        });
      }
    });
  }
}

function visitScalarOrList(container: Record<string, unknown>, key: string, path: Loc, visit: RefVisitor) {
  if (Array.isArray(container[key])) visitList(container, key, path, visit);
  else visitScalar(container, key, path, visit);
}

/** A placement names objects in `next_to`, and a coordinate system in `on` (for `at`). */
function visitPlacement(container: Record<string, unknown>, key: string, path: Loc, visit: RefVisitor) {
  const place = container[key];
  if (isObject(place)) {
    visitScalar(place, 'next_to', [...path, key], visit);
    visitScalar(place, 'on', [...path, key], visit);
  }
}

/**
 * The reference fields an object of kind `type` has. Used both for objects themselves and
 * for the `set` of a change step, whose keys are fields of its target.
 */
function visitObjectFields(fields: Record<string, unknown>, type: string | undefined, path: Loc, visit: RefVisitor) {
  visitPlacement(fields, 'place', path, visit);
  visitScalar(fields, 'on', path, visit);
  if (type === undefined || TARGETING_OBJECTS.has(type)) visitScalar(fields, 'target', path, visit);
  visitList(fields, 'members', path, visit);
}

export function forEachObjectRef(obj: SceneObject, visit: RefVisitor): void {
  visitObjectFields(obj as Record<string, unknown>, obj.type, [], visit);
}

export function forEachStepRef(step: Step, visit: RefVisitor, prefix: Loc = []): void {
  const fields = step as Record<string, unknown>;
  if ('target' in fields) visitScalarOrList(fields, 'target', prefix, visit);
  if (step.do === 'transform') visitScalar(fields, 'into', prefix, visit);
  if (step.do === 'camera') visitScalar(fields, 'focus', prefix, visit);
  if (step.do === 'move') visitPlacement(fields, 'to', prefix, visit);
  if (step.do === 'change' && isObject(fields.set)) {
    // A change can set fields which are themselves references, such as a new `next_to`.
    // The target's kind isn't known here, so `target` inside `set` counts as a reference.
    visitObjectFields(fields.set as Record<string, unknown>, undefined, [...prefix, 'set'], visit);
  }
  if (step.do === 'together' && Array.isArray(fields.steps)) {
    (fields.steps as Json[]).forEach((inner, index) => {
      if (isObject(inner) && typeof inner.do === 'string') {
        forEachStepRef(inner as unknown as Step, visit, [...prefix, 'steps', index]);
      }
    });
  }
}

export function objectRefs(obj: SceneObject): RefSite[] {
  const out: RefSite[] = [];
  forEachObjectRef(obj, (id, path) => out.push({ id, path }));
  return out;
}

export function stepRefs(step: Step): RefSite[] {
  const out: RefSite[] = [];
  forEachStepRef(step, (id, path) => out.push({ id, path }));
  return out;
}

export interface RefUse {
  kind: 'object' | 'step';
  /** Id of the object or top level step holding the reference. */
  itemId: string;
  /** Index of that object or step in its scene. */
  index: number;
  path: Loc;
}

/** Everything in a scene which refers to `objectId`. */
export function findReferences(scene: Scene, objectId: string): RefUse[] {
  const uses: RefUse[] = [];
  (scene.objects ?? []).forEach((obj, index) => {
    for (const ref of objectRefs(obj)) {
      if (ref.id === objectId) uses.push({ kind: 'object', itemId: obj.id, index, path: ref.path });
    }
  });
  (scene.steps ?? []).forEach((step, index) => {
    for (const ref of stepRefs(step)) {
      if (ref.id === objectId) uses.push({ kind: 'step', itemId: step.id ?? `#${index}`, index, path: ref.path });
    }
  });
  return uses;
}

/** References in a scene which name no object in it. Empty strings count as dangling. */
export function danglingReferences(scene: Scene): RefUse[] {
  const ids = new Set((scene.objects ?? []).map((o) => o.id));
  const uses: RefUse[] = [];
  (scene.objects ?? []).forEach((obj, index) => {
    for (const ref of objectRefs(obj)) {
      if (!ids.has(ref.id)) uses.push({ kind: 'object', itemId: obj.id, index, path: ref.path });
    }
  });
  (scene.steps ?? []).forEach((step, index) => {
    for (const ref of stepRefs(step)) {
      if (!ids.has(ref.id)) uses.push({ kind: 'step', itemId: step.id ?? `#${index}`, index, path: ref.path });
    }
  });
  return uses;
}

/** The ids a step acts on, for showing on its card. */
export function stepTargets(step: Step): string[] {
  const fields = step as Record<string, unknown>;
  const out: string[] = [];
  const target = fields.target;
  if (typeof target === 'string' && target) out.push(target);
  else if (Array.isArray(target)) out.push(...target.filter((t): t is string => typeof t === 'string' && t !== ''));
  if (step.do === 'transform' && typeof fields.into === 'string' && fields.into) out.push(fields.into);
  if (step.do === 'camera' && typeof fields.focus === 'string' && fields.focus) out.push(fields.focus);
  if (step.do === 'together' && Array.isArray(fields.steps)) {
    for (const inner of fields.steps as Json[]) {
      if (isObject(inner) && typeof inner.do === 'string') {
        for (const id of stepTargets(inner as unknown as Step)) if (!out.includes(id)) out.push(id);
      }
    }
  }
  return out;
}
