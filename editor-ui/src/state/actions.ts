/**
 * What the user does, in their terms: add an equation, delete this step, nudge that. Each
 * turns into one or more document ops through `apply`, with the selection following along.
 */
import type { CatalogEntry } from '../lib/api';
import { fillObjectTemplate, fillStepTemplate, suggestPosition, unfilledReferences } from '../lib/templates';
import { hasPlacement, objectFields, type SchemaIndex } from '../lib/schema';
import { roundFrame, type Box } from '../lib/geometry';
import { snap, tidy, type Vec2 } from '../lib/coords';
import { movePoint, translatePoints as translatedPoints, type HandleRef } from '../lib/handles';
import { effectiveScene } from '../doc/carry';
import {
  addNestedStep, addObject, addScene, addStep, duplicateObject, duplicateScene, duplicateStep, findObject, findScene, findStepPath,
  moveNestedStep, moveScene, moveStep, parentStep, planObjectRemoval, removeObject, removeScene, removeStep, setItemField, setField, itemLoc,
} from '../doc/ops';
import type { Document, Json, Placement, SceneObject } from '../doc/types';
import {
  apply, askConfirm, currentDoc, currentSceneId, frameStepIndex, select, setFrameStep, toast, useEditor, type Selection,
} from './store';

function state() {
  return useEditor.getState();
}

function selectedObjectId(): string | null {
  const s = state();
  return s.selection.kind === 'object' ? s.selection.id : null;
}

// Objects

/** "a set of axes or a number plane", for what an object's references need. */
function describeNeeds(schema: SchemaIndex, type: string): string {
  const refs = objectFields(schema, type).filter((f) => f.required && (f.kind === 'object-ref' || f.kind === 'ref-list'));
  const kinds = refs.flatMap((f) => f.refTypes ?? []);
  const phrase: Record<string, string> = { axes: 'a set of axes', axes_3d: 'a set of 3D axes', number_plane: 'a number plane', number_line: 'a number line' };
  return kinds.length ? [...new Set(kinds)].map((k) => phrase[k] ?? `a ${k.replace(/_/g, ' ')}`).join(' or ') : 'another object';
}

export function addObjectFrom(entry: CatalogEntry, options: { at?: [number, number]; fields?: Record<string, Json> } = {}): string | null {
  const s = state();
  const doc = currentDoc(s);
  const sceneId = currentSceneId(s);
  if (!doc || !sceneId || !s.schema) return null;
  const scene = effectiveScene(doc, findScene(doc, sceneId)!);
  const template = fillObjectTemplate(s.schema, { ...(entry.template as Record<string, Json>), ...(options.fields ?? {}) }, {
    scene,
    frameIndex: frameStepIndex(s, sceneId),
    selectedObjectId: selectedObjectId(),
  });
  const type = String(template.type);
  if (unfilledReferences(s.schema, template).length) {
    toast(`${entry.label} goes with another object (${describeNeeds(s.schema, type)}); add that first`, 'error');
    return null;
  }
  if (hasPlacement(s.schema, type) && template.place === undefined) {
    if (options.at) {
      template.place = { at: [roundFrame(options.at[0]), roundFrame(options.at[1])] };
    } else if (s.still?.sceneId === sceneId) {
      const occupied: Box[] = s.still.objects.map((o) => o.frame_bbox);
      const at = suggestPosition(occupied);
      if (at) template.place = { at };
    }
  }
  let newId: string | null = null;
  apply(
    (d) => {
      const result = addObject(d, sceneId, template as { type: string });
      newId = result.id;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'object', sceneId, id: newId } : null) },
  );
  return newId;
}

/** Remove an object, first asking what to do with anything which uses it. */
export function requestRemoveObject(sceneId: string, objectId: string): void {
  const doc = currentDoc();
  if (!doc) return;
  const plan = planObjectRemoval(doc, sceneId, objectId);
  const others = plan.objects.filter((id) => id !== objectId);
  const affected = plan.steps.length + plan.editedSteps.length + others.length + plan.editedObjects.length + plan.carriedBy.length;
  const remove = (cascade: boolean) => {
    apply((d) => removeObject(d, sceneId, objectId, { cascade }), { select: { kind: null, sceneId, id: null } });
  };
  if (affected === 0) {
    remove(false);
    toast(`Deleted '${objectId}'. Undo with Ctrl+Z.`);
    return;
  }
  // Steps by their number in the list, as the user sees them
  const scene = findScene(doc, sceneId);
  const stepName = (id: string) => {
    const index = (scene?.steps ?? []).findIndex((s) => s.id === id);
    return index >= 0 ? `${index + 1}` : id;
  };
  const steps = (ids: string[]) => `${ids.length === 1 ? 'step' : 'steps'} ${ids.map(stepName).join(', ')}`;
  const parts: string[] = [];
  if (plan.steps.length) parts.push(`${steps(plan.steps)}, which only ${plan.steps.length === 1 ? 'acts' : 'act'} on it, will be deleted`);
  if (plan.editedSteps.length) parts.push(`${steps(plan.editedSteps)} will stop using it`);
  if (others.length) parts.push(`${others.join(', ')} can't exist without it and will be deleted too`);
  if (plan.editedObjects.length) parts.push(`${plan.editedObjects.join(', ')} will stop referring to it`);
  if (plan.carriedBy.length) {
    parts.push(`${plan.carriedBy.length === 1 ? 'scene' : 'scenes'} ${plan.carriedBy.map((id) => `'${id}'`).join(', ')} will stop carrying it over`);
  }
  if (parts[0]) parts[0] = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
  askConfirm({
    title: `Delete '${objectId}'?`,
    message: `'${objectId}' is used elsewhere${plan.carriedBy.length ? '' : ' in this scene'}. ${parts.join('; ')}. You can undo this.`,
    confirmLabel: 'Delete it and what uses it',
    danger: true,
    altLabel: `Delete only '${objectId}'`,
    onConfirm: () => remove(true),
    onAlt: () => remove(false),
  });
}

export function duplicateObjectById(sceneId: string, objectId: string): void {
  let newId: string | null = null;
  apply(
    (d) => {
      const result = duplicateObject(d, sceneId, objectId);
      newId = result.id;
      // Offset the copy a little so it doesn't hide exactly on top of the original
      const copy = findObject(result.doc, sceneId, result.id)!;
      const place = copy.place as Placement | undefined;
      if (place && typeof place === 'object' && !Array.isArray(place) && Array.isArray(place.at)) {
        const step = typeof place.on === 'string' ? 1 : 0.5;
        return setItemField(result.doc, { kind: 'object', sceneId, id: result.id }, ['place', 'at'], [tidy(place.at[0]! + step), tidy(place.at[1]! - step)]);
      }
      const moved = translatedPoints(copy, typeof copy.on === 'string' ? 1 : 0.5, typeof copy.on === 'string' ? -1 : -0.5, 0.01);
      return moved ? patchObject(result.doc, sceneId, result.id, moved) : result.doc;
    },
    { select: () => (newId ? { kind: 'object', sceneId, id: newId } : null) },
  );
}

function patchObject(doc: Document, sceneId: string, objectId: string, patch: Record<string, Json>): Document {
  let next = doc;
  for (const [field, value] of Object.entries(patch)) next = setItemField(next, { kind: 'object', sceneId, id: objectId }, [field], value);
  return next;
}

/** Put an object's centre at a point, in frame units (from dragging on the canvas). */
export function placeObjectAt(sceneId: string, objectId: string, at: [number, number], key?: string): void {
  const point = [roundFrame(at[0]), roundFrame(at[1])];
  apply((d) => setItemField(d, { kind: 'object', sceneId, id: objectId }, ['place'], { at: point }), key ? { key } : {});
}

/**
 * Move a placed object whose placement is a point on a coordinate system (`place: {at, on}`)
 * by a move in that system's units, keeping it on the system.
 */
export function moveOnSystem(sceneId: string, objectId: string, delta: Vec2, step: number, key?: string): boolean {
  const doc = currentDoc();
  const obj = doc ? findObject(doc, sceneId, objectId) : undefined;
  const place = obj?.place as Placement | undefined;
  if (!place || typeof place !== 'object' || Array.isArray(place) || !Array.isArray(place.at) || typeof place.on !== 'string') return false;
  const at = [tidy(place.at[0]! + snap(delta[0], step)), tidy(place.at[1]! + snap(delta[1], step))];
  apply((d) => setItemField(d, { kind: 'object', sceneId, id: objectId }, ['place', 'at'], at), key ? { key } : {});
  return true;
}

/**
 * Move an object given by points (dot, vector, line, polygon, angle, arc, a brace between
 * points) by an offset in its own units: frame units, or its coordinate system's.
 */
export function translatePoints(sceneId: string, objectId: string, dx: number, dy: number, key?: string, step = 0.01): boolean {
  const doc = currentDoc();
  const obj = doc ? findObject(doc, sceneId, objectId) : undefined;
  if (!obj) return false;
  const patch = translatedPoints(obj, dx, dy, step);
  if (!patch) return false;
  apply((d) => patchObject(d, sceneId, objectId, patch), key ? { key } : {});
  return true;
}

/** Put one point of an object (a vector's tip, a corner) somewhere, in its own units. */
export function movePointTo(sceneId: string, objectId: string, handle: Pick<HandleRef, 'field' | 'index'>, to: Vec2, step: number): boolean {
  const doc = currentDoc();
  const obj = doc ? findObject(doc, sceneId, objectId) : undefined;
  if (!obj) return false;
  const patch = movePoint(obj, handle, to, step);
  if (!patch) return false;
  apply((d) => patchObject(d, sceneId, objectId, patch));
  return true;
}

/** Set an object's scale and rotation (from the handles on the canvas); 1 and 0 are left out. */
export function setScaleAndRotation(sceneId: string, objectId: string, values: { scale?: number; rotate?: number }): void {
  apply((d) => {
    let next = d;
    const ref = { kind: 'object' as const, sceneId, id: objectId };
    if (values.scale !== undefined) next = setItemField(next, ref, ['scale'], values.scale === 1 ? undefined : values.scale);
    if (values.rotate !== undefined) next = setItemField(next, ref, ['rotate'], values.rotate === 0 ? undefined : values.rotate);
    return next;
  });
}

/** Arrow keys: move the selected object by a small step, in its own units. */
export function nudgeSelection(dx: number, dy: number): void {
  const s = state();
  const doc = currentDoc(s);
  if (!doc || s.selection.kind !== 'object' || !s.selection.sceneId || !s.selection.id || !s.schema) return;
  const { sceneId, id } = s.selection;
  const obj = findObject(doc, sceneId, id);
  if (!obj) {
    toast(`'${id}' is carried over from the scene before; move it there`, 'info');
    return;
  }
  const key = `nudge:${sceneId}:${id}`;
  if (hasPlacement(s.schema, obj.type)) {
    const place = obj.place as Placement | string | number[] | undefined;
    if (place && typeof place === 'object' && !Array.isArray(place) && Array.isArray(place.at) && typeof place.on === 'string') {
      moveOnSystem(sceneId, id, [dx, dy], 0.01, key);
      return;
    }
    let at: number[] | null = null;
    if (place && typeof place === 'object' && !Array.isArray(place) && Array.isArray(place.at)) at = place.at;
    else if (Array.isArray(place)) at = place as number[];
    if (!at) {
      const box = s.still?.sceneId === sceneId ? s.still.objects.find((o) => o.id === id)?.frame_bbox : undefined;
      at = box ? [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] : [0, 0];
    }
    placeObjectAt(sceneId, id, [at[0]! + dx, at[1]! + dy], key);
  } else if (!translatePoints(sceneId, id, dx, dy, key)) {
    toast(`'${id}' goes where the object it belongs to is, so it can't be moved on its own`, 'info');
  }
}

/** A picture dropped on the canvas: upload it, then add an image (or svg) object where it fell. */
export function addPictureObject(path: string, at: [number, number] | undefined): string | null {
  const s = state();
  if (!s.schema) return null;
  const type = path.toLowerCase().endsWith('.svg') ? 'svg' : 'image';
  const entry: CatalogEntry = { type, label: type === 'svg' ? 'Drawing' : 'Image', template: { type, path } };
  const id = addObjectFrom(entry, { at });
  if (id) showObjects([id]);
  return id;
}

// Steps

export function addStepFrom(entry: CatalogEntry): string | null {
  const s = state();
  const doc = currentDoc(s);
  const sceneId = currentSceneId(s);
  if (!doc || !sceneId || !s.schema) return null;
  const scene = effectiveScene(doc, findScene(doc, sceneId)!);
  const frameIndex = frameStepIndex(s, sceneId);
  const template = fillStepTemplate(s.schema, entry.template as Record<string, Json>, {
    scene,
    frameIndex,
    selectedObjectId: selectedObjectId(),
  });
  if (unfilledReferences(s.schema, template).length) {
    toast(`A ${entry.label.toLowerCase()} step acts on an object: add an object to this scene first`, 'error');
    return null;
  }
  let newId: string | null = null;
  apply(
    (d) => {
      const result = addStep(d, sceneId, template as { do: string }, { index: frameIndex + 1 });
      newId = result.id;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'step', sceneId, id: newId } : null) },
  );
  return newId;
}

/** Add a step inside a `together` step, filled in the way a new step is. */
export function addNestedStepFrom(sceneId: string, parentId: string, entry: CatalogEntry): string | null {
  const s = state();
  const doc = currentDoc(s);
  if (!doc || !s.schema) return null;
  const scene = findScene(doc, sceneId);
  if (!scene) return null;
  const topIndex = (scene.steps ?? []).findIndex((st) => st.id === parentId);
  const template = fillStepTemplate(s.schema, entry.template as Record<string, Json>, {
    scene: effectiveScene(doc, scene),
    frameIndex: Math.max(-1, (topIndex >= 0 ? topIndex : frameStepIndex(s, sceneId)) - 1),
    selectedObjectId: selectedObjectId(),
  });
  if (unfilledReferences(s.schema, template).length) {
    toast(`A ${entry.label.toLowerCase()} step acts on an object: add an object to this scene first`, 'error');
    return null;
  }
  let newId: string | null = null;
  apply(
    (d) => {
      const result = addNestedStep(d, sceneId, parentId, template as { do: string });
      newId = result.id;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'step', sceneId, id: newId } : null) },
  );
  return newId;
}

export function reorderNestedStep(sceneId: string, parentId: string, from: number, to: number): void {
  apply((d) => moveNestedStep(d, sceneId, parentId, from, to));
}

/** Add a "show" step for objects which aren't on screen, after the current frame. */
export function showObjects(ids: string[]): void {
  const sceneId = currentSceneId();
  if (!sceneId || ids.length === 0) return;
  const s = state();
  const index = frameStepIndex(s, sceneId) + 1;
  let newId: string | null = null;
  const keepObject = s.selection.kind === 'object';
  apply(
    (d) => {
      const result = addStep(d, sceneId, { do: 'show', target: ids.length === 1 ? ids[0]! : ids }, { index });
      newId = result.id;
      return result.doc;
    },
    { select: () => (newId && !keepObject ? { kind: 'step', sceneId, id: newId } : null) },
  );
  if (newId) setFrameStep(sceneId, newId);
}

export function duplicateStepById(sceneId: string, stepId: string): void {
  let newId: string | null = null;
  apply(
    (d) => {
      const result = duplicateStep(d, sceneId, stepId);
      newId = result.id;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'step', sceneId, id: newId } : null) },
  );
}

export function removeStepById(sceneId: string, stepId: string): void {
  const doc = currentDoc();
  const scene = doc ? findScene(doc, sceneId) : undefined;
  if (!doc || !scene) return;
  const steps = scene.steps ?? [];
  const parent = parentStep(doc, sceneId, stepId);
  let next: Selection;
  if (parent) {
    // Inside `together`: select its neighbour, or the step it leaves once unwrapped
    const inner = (parent.steps as unknown as { id?: string }[]) ?? [];
    const at = inner.findIndex((st) => st.id === stepId);
    const neighbour = inner[at + 1] ?? inner[at - 1];
    next = neighbour?.id ? { kind: 'step', sceneId, id: neighbour.id } : { kind: null, sceneId, id: null };
  } else {
    const index = steps.findIndex((s) => s.id === stepId);
    const neighbour = index >= 0 ? (steps[index + 1] ?? steps[index - 1]) : undefined;
    next = neighbour?.id ? { kind: 'step', sceneId, id: neighbour.id } : { kind: null, sceneId, id: null };
  }
  const ok = apply((d) => removeStep(d, sceneId, stepId), { select: next });
  if (ok) toast('Step deleted. Undo with Ctrl+Z.');
}

export function reorderStep(sceneId: string, from: number, to: number): void {
  apply((d) => moveStep(d, sceneId, from, to));
}

/** Show the frame after the previous or next step. */
export function stepFrame(delta: number): void {
  const s = state();
  const doc = currentDoc(s);
  const sceneId = currentSceneId(s);
  if (!doc || !sceneId) return;
  const steps = findScene(doc, sceneId)?.steps ?? [];
  const index = Math.max(-1, Math.min(steps.length - 1, frameStepIndex(s, sceneId) + delta));
  const step = steps[index];
  if (index < 0) {
    setFrameStep(sceneId, null);
    if (s.selection.kind === 'step') select({ kind: 'scene', sceneId, id: null });
  } else if (step?.id) {
    if (s.selection.kind === 'step' || s.selection.kind === null) select({ kind: 'step', sceneId, id: step.id });
    else setFrameStep(sceneId, step.id);
  }
}

// Scenes

export function addNewScene(): void {
  let newId: string | null = null;
  apply(
    (d) => {
      const result = addScene(d);
      newId = result.sceneId;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'scene', sceneId: newId, id: null } : null) },
  );
}

export function duplicateSceneById(sceneId: string): void {
  let newId: string | null = null;
  apply(
    (d) => {
      const result = duplicateScene(d, sceneId);
      newId = result.sceneId;
      return result.doc;
    },
    { select: () => (newId ? { kind: 'scene', sceneId: newId, id: null } : null) },
  );
}

export function requestRemoveScene(sceneId: string): void {
  const doc = currentDoc();
  const scene = doc ? findScene(doc, sceneId) : undefined;
  if (!doc || !scene) return;
  if (doc.scenes.length <= 1) {
    toast("A video needs at least one scene, so the last one can't be deleted", 'error');
    return;
  }
  const objects = scene.objects?.length ?? 0;
  const steps = scene.steps?.length ?? 0;
  askConfirm({
    title: `Delete scene '${scene.title || scene.id}'?`,
    message: `It has ${objects} object${objects === 1 ? '' : 's'} and ${steps} step${steps === 1 ? '' : 's'}. You can undo this with Ctrl+Z.`,
    confirmLabel: 'Delete scene',
    danger: true,
    onConfirm: () => {
      const index = doc.scenes.findIndex((s) => s.id === sceneId);
      const neighbour = doc.scenes[index + 1] ?? doc.scenes[index - 1];
      apply((d) => removeScene(d, sceneId), { select: { kind: 'scene', sceneId: neighbour?.id ?? null, id: null } });
    },
  });
}

export function reorderScene(from: number, to: number): void {
  apply((d) => moveScene(d, from, to));
}

// Templates

/** Whether a document is as good as new: one scene with nothing in it. */
export function isBlankDocument(doc: Document | null): boolean {
  if (!doc) return false;
  return doc.scenes.length === 1 && !(doc.scenes[0]!.objects ?? []).length && !(doc.scenes[0]!.steps ?? []).length && !(doc.scenes[0]!.carry ?? []).length;
}

/** Replace the whole document with a template's, as one edit that undo takes back. */
export function applyTemplateDocument(template: Document, title: string): void {
  const first = template.scenes[0]?.id ?? null;
  const ok = apply(() => template, { select: { kind: null, sceneId: first, id: null } });
  if (ok) {
    useEditor.setState({ frameStep: {} });
    toast(`Started from “${title}”. Undo (Ctrl+Z) brings back what you had.`);
  }
}

// Whatever is selected

export function duplicateSelection(): void {
  const { selection } = state();
  if (!selection.sceneId) return;
  if (selection.kind === 'object' && selection.id) duplicateObjectById(selection.sceneId, selection.id);
  else if (selection.kind === 'step' && selection.id) duplicateStepById(selection.sceneId, selection.id);
  else if (selection.kind === 'scene') duplicateSceneById(selection.sceneId);
}

export function deleteSelection(): void {
  const { selection } = state();
  if (!selection.sceneId) return;
  if (selection.kind === 'object' && selection.id) {
    const doc = currentDoc();
    if (doc && !findObject(doc, selection.sceneId, selection.id)) {
      toast(`'${selection.id}' is carried over from the scene before: take it out of this scene's “Carried over” list instead`, 'info');
      return;
    }
    requestRemoveObject(selection.sceneId, selection.id);
  } else if (selection.kind === 'step' && selection.id) removeStepById(selection.sceneId, selection.id);
  else if (selection.kind === 'scene') requestRemoveScene(selection.sceneId);
}

/** Set a field of the document, by loc (used by the document settings form). */
export function setDocField(loc: (string | number)[], value: unknown, key?: string): void {
  apply((d: Document) => setField(d, loc, value), key ? { key } : {});
}

export type { SceneObject };
export { itemLoc, findStepPath };
