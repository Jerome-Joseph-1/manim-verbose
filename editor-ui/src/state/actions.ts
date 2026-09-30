/**
 * What the user does, in their terms: add an equation, delete this step, nudge that. Each
 * turns into one or more document ops through `apply`, with the selection following along.
 */
import type { CatalogEntry } from '../lib/api';
import { fillObjectTemplate, fillStepTemplate, suggestPosition } from '../lib/templates';
import { hasPlacement } from '../lib/schema';
import { roundFrame, type Box } from '../lib/geometry';
import {
  addObject, addScene, addStep, duplicateObject, duplicateScene, duplicateStep, findObject, findScene, findStepPath,
  moveScene, moveStep, planObjectRemoval, removeObject, removeScene, removeStep, setItemField, setField, itemLoc,
} from '../doc/ops';
import type { Document, Json, Placement } from '../doc/types';
import {
  apply, askConfirm, currentDoc, currentSceneId, frameStepIndex, select, setFrameStep, toast, useEditor,
} from './store';

function state() {
  return useEditor.getState();
}

function selectedObjectId(): string | null {
  const s = state();
  return s.selection.kind === 'object' ? s.selection.id : null;
}

// Objects

export function addObjectFrom(entry: CatalogEntry): string | null {
  const s = state();
  const doc = currentDoc(s);
  const sceneId = currentSceneId(s);
  if (!doc || !sceneId || !s.schema) return null;
  const scene = findScene(doc, sceneId)!;
  const template = fillObjectTemplate(s.schema, entry.template as Record<string, Json>, {
    scene,
    frameIndex: frameStepIndex(s, sceneId),
    selectedObjectId: selectedObjectId(),
  });
  const type = String(template.type);
  if (hasPlacement(s.schema, type) && template.place === undefined && s.still?.sceneId === sceneId) {
    const occupied: Box[] = s.still.objects.map((o) => o.frame_bbox);
    const at = suggestPosition(occupied);
    if (at) template.place = { at };
  }
  let newId: string | null = null;
  apply((d) => {
    const result = addObject(d, sceneId, template as { type: string });
    newId = result.id;
    return result.doc;
  });
  if (newId) select({ kind: 'object', sceneId, id: newId });
  return newId;
}

/** Remove an object, first asking what to do with anything which uses it. */
export function requestRemoveObject(sceneId: string, objectId: string): void {
  const doc = currentDoc();
  if (!doc) return;
  const plan = planObjectRemoval(doc, sceneId, objectId);
  const others = plan.objects.filter((id) => id !== objectId);
  const affected = plan.steps.length + plan.editedSteps.length + others.length + plan.editedObjects.length;
  const remove = (cascade: boolean) => {
    apply((d) => removeObject(d, sceneId, objectId, { cascade }), { select: { kind: null, sceneId, id: null } });
  };
  if (affected === 0) {
    remove(false);
    toast(`Deleted '${objectId}'. Undo with Ctrl+Z.`);
    return;
  }
  const parts: string[] = [];
  if (plan.steps.length) parts.push(`${plan.steps.length} step${plan.steps.length === 1 ? '' : 's'} that only act on it (${plan.steps.join(', ')}) will be deleted`);
  if (plan.editedSteps.length) parts.push(`${plan.editedSteps.length} step${plan.editedSteps.length === 1 ? '' : 's'} will stop using it (${plan.editedSteps.join(', ')})`);
  if (others.length) parts.push(`${others.join(', ')} can't exist without it and will be deleted too`);
  if (plan.editedObjects.length) parts.push(`${plan.editedObjects.join(', ')} will stop referring to it`);
  askConfirm({
    title: `Delete '${objectId}'?`,
    message: `'${objectId}' is used elsewhere in this scene. ${parts.join('; ')}.`,
    confirmLabel: 'Delete it and what uses it',
    danger: true,
    altLabel: `Delete only '${objectId}'`,
    onConfirm: () => remove(true),
    onAlt: () => remove(false),
  });
}

export function duplicateObjectById(sceneId: string, objectId: string): void {
  let newId: string | null = null;
  apply((d) => {
    const result = duplicateObject(d, sceneId, objectId);
    newId = result.id;
    // Offset the copy a little so it doesn't hide exactly on top of the original
    const place = findObject(result.doc, sceneId, result.id)?.place as Placement | undefined;
    if (place && typeof place === 'object' && !Array.isArray(place) && Array.isArray(place.at)) {
      return setItemField(result.doc, { kind: 'object', sceneId, id: result.id }, ['place', 'at'], [roundFrame(place.at[0]! + 0.5), roundFrame(place.at[1]! - 0.5)]);
    }
    return result.doc;
  });
  if (newId) select({ kind: 'object', sceneId, id: newId });
}

/** Put an object's centre at a point, in frame units (from dragging on the canvas). */
export function placeObjectAt(sceneId: string, objectId: string, at: [number, number], key?: string): void {
  const point = [roundFrame(at[0]), roundFrame(at[1])];
  apply((d) => setItemField(d, { kind: 'object', sceneId, id: objectId }, ['place'], { at: point }), key ? { key } : {});
}

/** Move an object whose geometry is given by points (dot, vector, line, polygon), by an offset. */
export function translatePoints(sceneId: string, objectId: string, dx: number, dy: number, key?: string): boolean {
  const doc = currentDoc();
  const obj = doc ? findObject(doc, sceneId, objectId) : undefined;
  if (!obj || typeof obj.on === 'string') return false;
  const shift = (p: Json | undefined): Json | undefined =>
    Array.isArray(p) && typeof p[0] === 'number' && typeof p[1] === 'number' ? [roundFrame(p[0] + dx), roundFrame(p[1] + dy), ...p.slice(2)] : p;
  const fields: Record<string, (v: Json | undefined) => Json | undefined> = {
    point: shift,
    tip: shift,
    tail: (v) => shift(v ?? [0, 0]),
    start: shift,
    end: shift,
    points: (v) => (Array.isArray(v) ? v.map((p) => shift(p) ?? p) : v),
  };
  const kinds: Record<string, string[]> = { dot: ['point'], vector: ['tip', 'tail'], line: ['start', 'end'], polygon: ['points'] };
  const names = kinds[obj.type];
  if (!names) return false;
  apply((d) => {
    let next = d;
    for (const name of names) {
      next = setItemField(next, { kind: 'object', sceneId, id: objectId }, [name], fields[name]!(obj[name]));
    }
    return next;
  }, key ? { key } : {});
  return true;
}

/** Arrow keys: move the selected object by a small step. */
export function nudgeSelection(dx: number, dy: number): void {
  const s = state();
  const doc = currentDoc(s);
  if (!doc || s.selection.kind !== 'object' || !s.selection.sceneId || !s.selection.id || !s.schema) return;
  const { sceneId, id } = s.selection;
  const obj = findObject(doc, sceneId, id);
  if (!obj) return;
  const key = `nudge:${sceneId}:${id}`;
  if (hasPlacement(s.schema, obj.type)) {
    const place = obj.place as Placement | string | number[] | undefined;
    let at: number[] | null = null;
    if (place && typeof place === 'object' && !Array.isArray(place) && Array.isArray(place.at)) at = place.at;
    else if (Array.isArray(place)) at = place as number[];
    if (!at) {
      const box = s.still?.sceneId === sceneId ? s.still.objects.find((o) => o.id === id)?.frame_bbox : undefined;
      at = box ? [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] : [0, 0];
    }
    placeObjectAt(sceneId, id, [at[0]! + dx, at[1]! + dy], key);
  } else if (!translatePoints(sceneId, id, dx, dy, key)) {
    toast(`'${id}' is placed by its coordinate system, so it can't be nudged`, 'info');
  }
}

// Steps

export function addStepFrom(entry: CatalogEntry): string | null {
  const s = state();
  const doc = currentDoc(s);
  const sceneId = currentSceneId(s);
  if (!doc || !sceneId || !s.schema) return null;
  const scene = findScene(doc, sceneId)!;
  const frameIndex = frameStepIndex(s, sceneId);
  const template = fillStepTemplate(s.schema, entry.template as Record<string, Json>, {
    scene,
    frameIndex,
    selectedObjectId: selectedObjectId(),
  });
  let newId: string | null = null;
  apply((d) => {
    const result = addStep(d, sceneId, template as { do: string }, { index: frameIndex + 1 });
    newId = result.id;
    return result.doc;
  });
  if (newId) select({ kind: 'step', sceneId, id: newId });
  return newId;
}

/** Add a "show" step for objects which aren't on screen, after the current frame. */
export function showObjects(ids: string[]): void {
  const sceneId = currentSceneId();
  if (!sceneId || ids.length === 0) return;
  const s = state();
  const index = frameStepIndex(s, sceneId) + 1;
  let newId: string | null = null;
  apply((d) => {
    const result = addStep(d, sceneId, { do: 'show', target: ids.length === 1 ? ids[0]! : ids }, { index });
    newId = result.id;
    return result.doc;
  });
  if (newId) {
    setFrameStep(sceneId, newId);
    const selection = s.selection;
    if (selection.kind !== 'object') select({ kind: 'step', sceneId, id: newId });
  }
}

export function duplicateStepById(sceneId: string, stepId: string): void {
  let newId: string | null = null;
  apply((d) => {
    const result = duplicateStep(d, sceneId, stepId);
    newId = result.id;
    return result.doc;
  });
  if (newId) select({ kind: 'step', sceneId, id: newId });
}

export function removeStepById(sceneId: string, stepId: string): void {
  const doc = currentDoc();
  const scene = doc ? findScene(doc, sceneId) : undefined;
  const steps = scene?.steps ?? [];
  const index = steps.findIndex((s) => s.id === stepId);
  const neighbour = index >= 0 ? (steps[index + 1] ?? steps[index - 1]) : undefined;
  const ok = apply((d) => removeStep(d, sceneId, stepId), {
    select: neighbour?.id ? { kind: 'step', sceneId, id: neighbour.id } : { kind: null, sceneId, id: null },
  });
  if (ok && neighbour?.id) setFrameStep(sceneId, neighbour.id);
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
  apply((d) => {
    const result = addScene(d);
    newId = result.sceneId;
    return result.doc;
  });
  if (newId) select({ kind: 'scene', sceneId: newId, id: null });
}

export function duplicateSceneById(sceneId: string): void {
  let newId: string | null = null;
  apply((d) => {
    const result = duplicateScene(d, sceneId);
    newId = result.sceneId;
    return result.doc;
  });
  if (newId) select({ kind: 'scene', sceneId: newId, id: null });
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
  if (selection.kind === 'object' && selection.id) requestRemoveObject(selection.sceneId, selection.id);
  else if (selection.kind === 'step' && selection.id) removeStepById(selection.sceneId, selection.id);
  else if (selection.kind === 'scene') requestRemoveScene(selection.sceneId);
}

/** Set a field of the document, by loc (used by the document settings form). */
export function setDocField(loc: (string | number)[], value: unknown, key?: string): void {
  apply((d: Document) => setField(d, loc, value), key ? { key } : {});
}

export { itemLoc, findStepPath };
