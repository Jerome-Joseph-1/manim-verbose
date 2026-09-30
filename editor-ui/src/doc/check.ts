/**
 * The invariants document ops keep: ids valid and unique where they have to be, and
 * (optionally) every reference naming an object in its scene. Used by tests, and by the
 * chaos run to check the editor never makes a document it can't save.
 */
import { isValidId, iterSteps } from './ids';
import { danglingReferences } from './refs';
import type { Document } from './types';
import { formatLoc } from './paths';

export function invariantViolations(doc: Document, options: { references?: boolean } = {}): string[] {
  const out: string[] = [];
  if (!Array.isArray(doc.scenes) || doc.scenes.length === 0) out.push('a document needs at least one scene');
  const sceneIds = new Set<string>();
  const stepIds = new Set<string>();
  for (const scene of doc.scenes ?? []) {
    if (!isValidId(scene.id)) out.push(`scene id '${scene.id}' is not valid`);
    if (sceneIds.has(scene.id)) out.push(`two scenes are called '${scene.id}'`);
    sceneIds.add(scene.id);
    const objectIds = new Set<string>();
    for (const obj of scene.objects ?? []) {
      if (!isValidId(obj.id)) out.push(`object id '${obj.id}' in '${scene.id}' is not valid`);
      if (objectIds.has(obj.id)) out.push(`two objects in '${scene.id}' are called '${obj.id}'`);
      if (typeof obj.type !== 'string') out.push(`object '${obj.id}' has no type`);
      objectIds.add(obj.id);
    }
    for (const step of iterSteps(scene.steps)) {
      if (typeof step.do !== 'string') out.push(`a step in '${scene.id}' has no do`);
      if (!step.id) {
        out.push(`a '${step.do}' step in '${scene.id}' has no id`);
        continue;
      }
      if (!isValidId(step.id)) out.push(`step id '${step.id}' is not valid`);
      if (stepIds.has(step.id)) out.push(`two steps are called '${step.id}'`);
      stepIds.add(step.id);
    }
    if (options.references) {
      for (const use of danglingReferences(scene)) {
        out.push(`${use.kind} '${use.itemId}' in '${scene.id}' refers to a missing object at ${formatLoc(use.path)}`);
      }
    }
  }
  return out;
}
