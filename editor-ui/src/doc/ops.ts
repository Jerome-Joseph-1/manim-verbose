/**
 * Every edit the editor makes to a document, as pure functions: each takes a document and
 * returns a new one, leaving the old one untouched (so undo is keeping the old one).
 *
 * Ops throw DocOpError when asked for something which can't be done, such as renaming an
 * object to a name already taken; the message is meant to be shown to the user as is.
 */
import { produce, type Draft } from 'immer';
import {
  isValidId, iterSteps, newObjectId, newSceneId, newStepId, objectIds, sceneIds, stepIds, uniqueId,
} from './ids';
import { forEachObjectRef, forEachStepRef, findReferences, type RefUse } from './refs';
import { getIn, setInMutable } from './paths';
import type { Document, Json, JsonObject, Loc, Scene, SceneObject, Step } from './types';

export class DocOpError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DocOpError';
  }
}

// Finding things

export function findScene(doc: Document, sceneId: string): Scene | undefined {
  return doc.scenes.find((s) => s.id === sceneId);
}

function sceneIndex(doc: Document, sceneId: string): number {
  const index = doc.scenes.findIndex((s) => s.id === sceneId);
  if (index < 0) throw new DocOpError(`There's no scene called '${sceneId}'`);
  return index;
}

function objectIndex(scene: Scene, objectId: string): number {
  const index = (scene.objects ?? []).findIndex((o) => o.id === objectId);
  if (index < 0) throw new DocOpError(`There's no object called '${objectId}' in scene '${scene.id}'`);
  return index;
}

function stepIndex(scene: Scene, stepId: string): number {
  const index = (scene.steps ?? []).findIndex((s) => s.id === stepId);
  if (index < 0) throw new DocOpError(`There's no step called '${stepId}' in scene '${scene.id}'`);
  return index;
}

export function findObject(doc: Document, sceneId: string, objectId: string): SceneObject | undefined {
  return findScene(doc, sceneId)?.objects?.find((o) => o.id === objectId);
}

/** The path of a step (top level or nested in `together`) inside its scene's steps. */
export function findStepPath(steps: Step[] | undefined, stepId: string, prefix: Loc = []): Loc | null {
  const list = steps ?? [];
  for (let i = 0; i < list.length; i += 1) {
    const step = list[i]!;
    if (step.id === stepId) return [...prefix, i];
    if (step.do === 'together' && Array.isArray(step.steps)) {
      const inner = findStepPath(step.steps as unknown as Step[], stepId, [...prefix, i, 'steps']);
      if (inner) return inner;
    }
  }
  return null;
}

export function findStep(doc: Document, sceneId: string, stepId: string): Step | undefined {
  const scene = findScene(doc, sceneId);
  if (!scene) return undefined;
  const path = findStepPath(scene.steps, stepId);
  return path ? (getIn(scene.steps, path) as Step) : undefined;
}

export type ItemKind = 'document' | 'scene' | 'object' | 'step';

export interface ItemRef {
  kind: ItemKind;
  sceneId?: string | null;
  id?: string | null;
}

/** Where an item lives in the document, as a loc. */
export function itemLoc(doc: Document, ref: ItemRef): Loc | null {
  if (ref.kind === 'document') return [];
  const s = doc.scenes.findIndex((scene) => scene.id === ref.sceneId);
  if (s < 0) return null;
  const scene = doc.scenes[s]!;
  if (ref.kind === 'scene') return ['scenes', s];
  if (ref.kind === 'object') {
    const o = (scene.objects ?? []).findIndex((obj) => obj.id === ref.id);
    return o < 0 ? null : ['scenes', s, 'objects', o];
  }
  const path = ref.id ? findStepPath(scene.steps, ref.id) : null;
  return path ? ['scenes', s, 'steps', ...path] : null;
}

export function getItem(doc: Document, ref: ItemRef): unknown {
  const loc = itemLoc(doc, ref);
  return loc === null ? undefined : getIn(doc, loc);
}

// Small helpers

function clone<T>(value: T): T {
  return structuredClone(value) as T;
}

function moveInList<T>(list: T[], from: number, to: number): void {
  if (from < 0 || from >= list.length) throw new DocOpError('Nothing to move there');
  const target = Math.max(0, Math.min(list.length - 1, to));
  const [item] = list.splice(from, 1);
  list.splice(target, 0, item!);
}

function checkNewId(id: string, taken: Set<string>, what: string): void {
  if (!isValidId(id)) {
    throw new DocOpError(`'${id}' can't be a name: use letters, digits and _, not starting with a digit`);
  }
  if (taken.has(id)) throw new DocOpError(`There's already ${what} called '${id}'`);
}

/** Put id, then type or do, first, as the server's canonical form does. */
function ordered<T extends Record<string, unknown>>(value: T, first: string[]): T {
  const out: Record<string, unknown> = {};
  for (const key of first) if (key in value) out[key] = value[key];
  for (const key of Object.keys(value)) if (!(key in out)) out[key] = value[key];
  return out as T;
}

/** Give a step, and any steps nested in it, fresh ids. */
function reassignStepIds(step: Step, sceneId: string, taken: Set<string>): void {
  for (const s of iterSteps([step])) {
    const id = newStepId(sceneId, taken);
    s.id = id;
    taken.add(id);
  }
}

// Scenes

export function addScene(doc: Document, options: { id?: string; title?: string; index?: number } = {}) {
  const id = options.id ?? newSceneId(doc);
  checkNewId(id, sceneIds(doc), 'a scene');
  const scene: Scene = options.title ? { id, title: options.title } : { id };
  const index = options.index ?? doc.scenes.length;
  const next = produce(doc, (draft) => {
    draft.scenes.splice(index, 0, scene as Draft<Scene>);
  });
  return { doc: next, sceneId: id };
}

export function removeScene(doc: Document, sceneId: string): Document {
  const index = sceneIndex(doc, sceneId);
  if (doc.scenes.length <= 1) throw new DocOpError("A video needs at least one scene, so the last one can't be deleted");
  return produce(doc, (draft) => {
    draft.scenes.splice(index, 1);
  });
}

export function duplicateScene(doc: Document, sceneId: string) {
  const index = sceneIndex(doc, sceneId);
  const original = doc.scenes[index]!;
  const id = uniqueId(sceneId, sceneIds(doc), { bare: false });
  const copy = clone(original) as Scene;
  copy.id = id;
  if (copy.title) copy.title = `${copy.title} (copy)`;
  const taken = stepIds(doc);
  for (const step of copy.steps ?? []) reassignStepIds(step, id, taken);
  const next = produce(doc, (draft) => {
    draft.scenes.splice(index + 1, 0, ordered(copy, ['id']) as Draft<Scene>);
  });
  return { doc: next, sceneId: id };
}

export function renameScene(doc: Document, sceneId: string, newId: string): Document {
  const index = sceneIndex(doc, sceneId);
  if (newId === sceneId) return doc;
  checkNewId(newId, sceneIds(doc), 'a scene');
  return produce(doc, (draft) => {
    draft.scenes[index]!.id = newId;
  });
}

export function moveScene(doc: Document, from: number, to: number): Document {
  if (from === to) return doc;
  return produce(doc, (draft) => {
    moveInList(draft.scenes, from, to);
  });
}

// Objects

export function addObject(
  doc: Document,
  sceneId: string,
  template: { type: string } & Record<string, unknown>,
  options: { id?: string; index?: number } = {},
) {
  const s = sceneIndex(doc, sceneId);
  const scene = doc.scenes[s]!;
  const id = options.id ?? newObjectId(scene, template.type);
  checkNewId(id, objectIds(scene), 'an object');
  const { id: _ignored, ...rest } = clone(template);
  void _ignored;
  const obj = ordered({ id, ...rest } as SceneObject, ['id', 'type']);
  const next = produce(doc, (draft) => {
    const target = draft.scenes[s]!;
    target.objects ??= [];
    const index = options.index ?? target.objects.length;
    target.objects.splice(index, 0, obj as Draft<SceneObject>);
  });
  return { doc: next, id };
}

export function duplicateObject(doc: Document, sceneId: string, objectId: string) {
  const s = sceneIndex(doc, sceneId);
  const scene = doc.scenes[s]!;
  const o = objectIndex(scene, objectId);
  const id = uniqueId(objectId, objectIds(scene), { bare: false });
  const copy = clone(scene.objects![o]!);
  copy.id = id;
  const next = produce(doc, (draft) => {
    draft.scenes[s]!.objects!.splice(o + 1, 0, copy as Draft<SceneObject>);
  });
  return { doc: next, id };
}

export function moveObject(doc: Document, sceneId: string, from: number, to: number): Document {
  const s = sceneIndex(doc, sceneId);
  if (from === to) return doc;
  return produce(doc, (draft) => {
    moveInList(draft.scenes[s]!.objects ?? [], from, to);
  });
}

/** Rename an object and every reference to it in its scene. */
export function renameObject(doc: Document, sceneId: string, oldId: string, newId: string): Document {
  const s = sceneIndex(doc, sceneId);
  const scene = doc.scenes[s]!;
  const o = objectIndex(scene, oldId);
  if (newId === oldId) return doc;
  checkNewId(newId, objectIds(scene), 'an object');
  const swap = (id: string, _path: Loc, replace: (next: string) => void) => {
    if (id === oldId) replace(newId);
  };
  return produce(doc, (draft) => {
    const target = draft.scenes[s]!;
    target.objects![o]!.id = newId;
    for (const obj of target.objects ?? []) forEachObjectRef(obj as SceneObject, swap);
    for (const step of target.steps ?? []) forEachStepRef(step as Step, swap);
  });
}

export interface RemovalPlan {
  /** The object asked for, then everything which can't exist without it. */
  objects: string[];
  /** Top level steps which would be removed outright. */
  steps: string[];
  /** Top level steps which would lose a reference but stay. */
  editedSteps: string[];
  /** Objects which would lose a reference (a `next_to`, a group member) but stay. */
  editedObjects: string[];
  /** Everything referring to the object, as found. */
  uses: RefUse[];
}

/** References an object can't do without: it means nothing once they are gone. */
function hardRefs(obj: SceneObject): string[] {
  const out: string[] = [];
  if ((obj.type === 'brace' || obj.type === 'box') && typeof obj.target === 'string') out.push(obj.target);
  if (obj.type === 'graph' && typeof obj.on === 'string') out.push(obj.on);
  return out;
}

function groupMembers(obj: SceneObject): string[] {
  if (obj.type !== 'group' || !Array.isArray(obj.members)) return [];
  return obj.members.filter((m): m is string => typeof m === 'string');
}

/** The object, and everything which can't exist without it: braces around it, a group of only it. */
function objectsToRemove(scene: Scene, objectId: string): Set<string> {
  const gone = new Set([objectId]);
  const objects = scene.objects ?? [];
  let changed = true;
  while (changed) {
    changed = false;
    for (const obj of objects) {
      if (gone.has(obj.id)) continue;
      const members = groupMembers(obj);
      const orphaned = hardRefs(obj).some((r) => gone.has(r));
      const emptied = members.length > 0 && members.every((m) => gone.has(m));
      if (orphaned || emptied) {
        gone.add(obj.id);
        changed = true;
      }
    }
  }
  return gone;
}

/** Strip references to `gone` from an object in place; true if anything changed. */
function stripObjectRefs(obj: Draft<SceneObject>, gone: Set<string>): boolean {
  let changed = false;
  const place = obj.place as Draft<JsonObject> | undefined;
  if (place && typeof place === 'object' && !Array.isArray(place)) {
    if (typeof place.next_to === 'string' && gone.has(place.next_to)) {
      delete place.next_to;
      delete place.side;
      changed = true;
    }
    if (typeof place.on === 'string' && gone.has(place.on)) {
      // `at` was in that system's coordinates; without it, it reads as frame units
      delete place.on;
      changed = true;
    }
    if (Object.keys(place).length === 0) delete obj.place;
  }
  if (typeof obj.on === 'string' && gone.has(obj.on) && obj.type !== 'graph') {
    delete obj.on;
    changed = true;
  }
  if (Array.isArray(obj.members)) {
    const kept = (obj.members as Json[]).filter((m) => !(typeof m === 'string' && gone.has(m)));
    if (kept.length !== obj.members.length) {
      obj.members = kept as Draft<Json>[];
      changed = true;
    }
  }
  return changed;
}

type StepFate = 'keep' | 'edited' | 'remove';

/** Strip references to `gone` from a step in place, saying whether it survives. */
function stripStepRefs(step: Draft<Step>, gone: Set<string>): StepFate {
  const has = (value: unknown) => typeof value === 'string' && gone.has(value);
  let fate: StepFate = 'keep';
  const fields = step as Draft<Record<string, Json>>;
  if (Array.isArray(fields.target)) {
    const kept = (fields.target as Json[]).filter((t) => !has(t));
    if (kept.length === 0) return 'remove';
    if (kept.length !== fields.target.length) {
      fields.target = kept as Draft<Json>[];
      fate = 'edited';
    }
  } else if (has(fields.target)) {
    return 'remove';
  }
  if (step.do === 'transform' && has(fields.into)) return 'remove';
  if (step.do === 'move') {
    const to = fields.to as Draft<JsonObject> | undefined;
    if (to && typeof to === 'object' && !Array.isArray(to)) {
      if (has(to.next_to)) return 'remove';
      if (has(to.on)) {
        delete to.on;
        fate = 'edited';
      }
    }
  }
  if (step.do === 'camera' && has(fields.focus)) {
    delete fields.focus;
    const stillDoes = fields.reset === true || ['zoom', 'center', 'orientation'].some((k) => fields[k] !== undefined && fields[k] !== null);
    if (!stillDoes) return 'remove';
    fate = 'edited';
  }
  if (step.do === 'change' && fields.set && typeof fields.set === 'object' && !Array.isArray(fields.set)) {
    const set = fields.set as Draft<JsonObject>;
    let touched = false;
    for (const key of ['on', 'target']) {
      if (has(set[key])) {
        delete set[key];
        touched = true;
      }
    }
    const place = set.place as Draft<JsonObject> | undefined;
    if (place && typeof place === 'object' && !Array.isArray(place) && (has(place.next_to) || has(place.on))) {
      delete set.place;
      touched = true;
    }
    if (Array.isArray(set.members)) {
      const kept = (set.members as Json[]).filter((m) => !has(m));
      if (kept.length !== set.members.length) {
        if (kept.length === 0) delete set.members;
        else set.members = kept as Draft<Json>[];
        touched = true;
      }
    }
    if (touched) {
      if (Object.keys(set).length === 0) return 'remove';
      fate = 'edited';
    }
  }
  if (step.do === 'together' && Array.isArray(fields.steps)) {
    const inner = fields.steps as unknown as Draft<Step>[];
    for (let i = inner.length - 1; i >= 0; i -= 1) {
      const innerFate = stripStepRefs(inner[i]!, gone);
      if (innerFate === 'remove') {
        inner.splice(i, 1);
        fate = 'edited';
      } else if (innerFate === 'edited') {
        fate = 'edited';
      }
    }
    if (inner.length === 0) return 'remove';
  }
  return fate;
}

/**
 * A `together` left with one step becomes that step, keeping the together's caption if the
 * step has none of its own.
 */
function unwrapLoneTogether(steps: Draft<Step>[]): void {
  for (let i = 0; i < steps.length; i += 1) {
    const step = steps[i]!;
    if (step.do === 'together' && Array.isArray(step.steps)) {
      const inner = step.steps as unknown as Draft<Step>[];
      unwrapLoneTogether(inner);
      if (inner.length === 1) {
        const only = inner[0]!;
        if ((only.caption === undefined || only.caption === null) && step.caption !== undefined) {
          only.caption = step.caption;
        }
        steps[i] = only;
      }
    }
  }
}

/** What removing an object would take with it, for asking the user first. */
export function planObjectRemoval(doc: Document, sceneId: string, objectId: string): RemovalPlan {
  const scene = doc.scenes[sceneIndex(doc, sceneId)]!;
  objectIndex(scene, objectId);
  const uses = findReferences(scene, objectId);
  const gone = objectsToRemove(scene, objectId);
  const plan: RemovalPlan = { objects: [...gone], steps: [], editedSteps: [], editedObjects: [], uses };
  produce(scene, (draft) => {
    for (const obj of draft.objects ?? []) {
      if (!gone.has(obj.id) && stripObjectRefs(obj, gone)) plan.editedObjects.push(obj.id);
    }
    for (const step of draft.steps ?? []) {
      const fate = stripStepRefs(step, gone);
      if (fate === 'remove') plan.steps.push(step.id ?? '');
      else if (fate === 'edited') plan.editedSteps.push(step.id ?? '');
    }
  });
  return plan;
}

/**
 * Remove an object. With `cascade`, also remove what can't work without it (steps acting
 * on it alone, braces and boxes around it, graphs on it, groups of nothing but it) and
 * drop it from what can (lists of targets, group members, `next_to`), so that no
 * reference is left dangling. Without, only the object goes and references to it stay,
 * for the user to fix.
 */
export function removeObject(doc: Document, sceneId: string, objectId: string, options: { cascade?: boolean } = {}): Document {
  const s = sceneIndex(doc, sceneId);
  const scene = doc.scenes[s]!;
  objectIndex(scene, objectId);
  const gone = options.cascade ? objectsToRemove(scene, objectId) : new Set([objectId]);
  return produce(doc, (draft) => {
    const target = draft.scenes[s]!;
    target.objects = (target.objects ?? []).filter((o) => !gone.has(o.id));
    if (target.objects.length === 0) delete target.objects;
    if (!options.cascade) return;
    for (const obj of target.objects ?? []) stripObjectRefs(obj, gone);
    if (target.steps) {
      target.steps = target.steps.filter((step) => stripStepRefs(step, gone) !== 'remove');
      unwrapLoneTogether(target.steps);
      if (target.steps.length === 0) delete target.steps;
    }
  });
}

// Steps

export function addStep(
  doc: Document,
  sceneId: string,
  template: { do: string } & Record<string, unknown>,
  options: { index?: number } = {},
) {
  const s = sceneIndex(doc, sceneId);
  const step = clone(template) as Step;
  reassignStepIds(step, sceneId, stepIds(doc));
  const id = step.id!;
  const next = produce(doc, (draft) => {
    const scene = draft.scenes[s]!;
    scene.steps ??= [];
    const index = options.index ?? scene.steps.length;
    scene.steps.splice(Math.max(0, Math.min(index, scene.steps.length)), 0, ordered(step, ['id', 'do']) as Draft<Step>);
  });
  return { doc: next, id };
}

/** Add a step inside a `together` step. */
export function addNestedStep(
  doc: Document,
  sceneId: string,
  parentId: string,
  template: { do: string } & Record<string, unknown>,
) {
  const s = sceneIndex(doc, sceneId);
  const path = findStepPath(doc.scenes[s]!.steps, parentId);
  if (!path) throw new DocOpError(`There's no step called '${parentId}'`);
  const parent = getIn(doc.scenes[s]!.steps, path) as Step;
  if (parent.do !== 'together') throw new DocOpError('Only a "together" step holds other steps');
  const step = clone(template) as Step;
  reassignStepIds(step, sceneId, stepIds(doc));
  const next = produce(doc, (draft) => {
    const target = getIn(draft.scenes[s]!.steps, path) as Draft<Step>;
    const inner = (Array.isArray(target.steps) ? target.steps : (target.steps = [])) as Draft<Json>[];
    inner.push(ordered(step, ['id', 'do']) as unknown as Draft<Json>);
  });
  return { doc: next, id: step.id! };
}

export function duplicateStep(doc: Document, sceneId: string, stepId: string) {
  const s = sceneIndex(doc, sceneId);
  const scene = doc.scenes[s]!;
  const path = findStepPath(scene.steps, stepId);
  if (!path) throw new DocOpError(`There's no step called '${stepId}' in scene '${sceneId}'`);
  const copy = clone(getIn(scene.steps, path) as Step);
  reassignStepIds(copy, sceneId, stepIds(doc));
  const index = path[path.length - 1] as number;
  const listPath = path.slice(0, -1);
  const next = produce(doc, (draft) => {
    const list = (listPath.length ? getIn(draft.scenes[s]!.steps, listPath) : draft.scenes[s]!.steps) as Draft<Step>[];
    list.splice(index + 1, 0, copy as Draft<Step>);
  });
  return { doc: next, id: copy.id! };
}

export function removeStep(doc: Document, sceneId: string, stepId: string): Document {
  const s = sceneIndex(doc, sceneId);
  const path = findStepPath(doc.scenes[s]!.steps, stepId);
  if (!path) throw new DocOpError(`There's no step called '${stepId}' in scene '${sceneId}'`);
  return produce(doc, (draft) => {
    const scene = draft.scenes[s]!;
    setInMutable(scene.steps, path, undefined);
    if (scene.steps && scene.steps.length === 0) delete scene.steps;
  });
}

export function moveStep(doc: Document, sceneId: string, from: number, to: number): Document {
  const s = sceneIndex(doc, sceneId);
  if (from === to) return doc;
  return produce(doc, (draft) => {
    moveInList(draft.scenes[s]!.steps ?? [], from, to);
  });
}

export function renameStep(doc: Document, sceneId: string, stepId: string, newId: string): Document {
  const s = sceneIndex(doc, sceneId);
  const path = findStepPath(doc.scenes[s]!.steps, stepId);
  if (!path) throw new DocOpError(`There's no step called '${stepId}' in scene '${sceneId}'`);
  if (newId === stepId) return doc;
  checkNewId(newId, stepIds(doc), 'a step');
  return produce(doc, (draft) => {
    (getIn(draft.scenes[s]!.steps, path) as Draft<Step>).id = newId;
  });
}

export { stepIndex as indexOfStep, objectIndex as indexOfObject };

// Fields

/** Nested mappings which mean nothing when empty, and are dropped then. */
const PRUNE_WHEN_EMPTY = new Set(['place', 'colors', 'captions', 'settings']);

/**
 * Set the value at `loc` in the document; `undefined` removes it (and, for a few nested
 * mappings such as `place`, the mapping too once it is empty). Ids are not changed this
 * way: use the rename ops, which keep references in step.
 */
export function setField(doc: Document, loc: Loc, value: unknown): Document {
  const last = loc[loc.length - 1];
  if (last === 'id' && loc.length > 1) throw new DocOpError('Use rename to change an id');
  if (value !== undefined && JSON.stringify(getIn(doc, loc)) === JSON.stringify(value)) return doc;
  if (value === undefined && getIn(doc, loc) === undefined) return doc;
  return produce(doc, (draft) => {
    setInMutable(draft, loc, value === undefined ? undefined : clone(value));
    if (value === undefined) {
      for (let depth = loc.length - 1; depth > 0; depth -= 1) {
        const key = loc[depth - 1];
        const node = getIn(draft, loc.slice(0, depth));
        const empty = node && typeof node === 'object' && !Array.isArray(node) && Object.keys(node).length === 0;
        if (empty && typeof key === 'string' && PRUNE_WHEN_EMPTY.has(key)) {
          setInMutable(draft, loc.slice(0, depth), undefined);
        } else {
          break;
        }
      }
    }
  });
}

/** Set a field of an object, step, scene or the document, by the item's id. */
export function setItemField(doc: Document, ref: ItemRef, path: Loc, value: unknown): Document {
  const base = itemLoc(doc, ref);
  if (base === null) throw new DocOpError("That item isn't in the document any more");
  return setField(doc, [...base, ...path], value);
}

/** Rename whatever an item ref points at, keeping references to it. */
export function renameItem(doc: Document, ref: ItemRef, newId: string): Document {
  if (ref.kind === 'scene' && ref.sceneId) return renameScene(doc, ref.sceneId, newId);
  if (ref.kind === 'object' && ref.sceneId && ref.id) return renameObject(doc, ref.sceneId, ref.id, newId);
  if (ref.kind === 'step' && ref.sceneId && ref.id) return renameStep(doc, ref.sceneId, ref.id, newId);
  throw new DocOpError("That can't be renamed");
}

/** Give every step without an id one, as the server does when it loads a file. */
export function ensureStepIds(doc: Document): Document {
  const missing = doc.scenes.some((scene) => [...iterSteps(scene.steps)].some((step) => !step.id));
  if (!missing) return doc;
  const taken = stepIds(doc);
  return produce(doc, (draft) => {
    for (const scene of draft.scenes) {
      for (const step of iterSteps(scene.steps as Step[])) {
        if (!step.id) {
          const id = newStepId(scene.id, taken);
          (step as Draft<Step>).id = id;
          taken.add(id);
        }
      }
    }
  });
}
