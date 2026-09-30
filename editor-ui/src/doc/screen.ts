/**
 * What is on screen after a given step, worked out from the document alone (as
 * check_on_screen in validate.py does), so the editor can say "not on screen yet" without
 * waiting for a render.
 */
import type { Json, Scene, SceneObject, Step } from './types';

function asList(target: Json | undefined): string[] {
  if (typeof target === 'string') return target ? [target] : [];
  if (Array.isArray(target)) return target.filter((t): t is string => typeof t === 'string' && t !== '');
  return [];
}

function membersOf(objects: Map<string, SceneObject>, ref: string, seen = new Set<string>()): Set<string> {
  const out = new Set([ref]);
  if (seen.has(ref)) return out;
  seen.add(ref);
  const obj = objects.get(ref);
  if (obj?.type === 'group' && Array.isArray(obj.members)) {
    for (const m of obj.members) if (typeof m === 'string') for (const x of membersOf(objects, m, seen)) out.add(x);
  }
  return out;
}

function follow(step: Step, objects: Map<string, SceneObject>, before: Set<string>): Set<string> {
  const after = new Set(before);
  const add = (ref: string) => membersOf(objects, ref).forEach((m) => after.add(m));
  const drop = (ref: string) => membersOf(objects, ref).forEach((m) => after.delete(m));
  switch (step.do) {
    case 'show':
    case 'add':
      asList(step.target).forEach(add);
      break;
    case 'hide':
    case 'remove':
      asList(step.target).forEach(drop);
      break;
    case 'clear':
      after.clear();
      break;
    case 'transform':
      if (step.keep !== true && typeof step.target === 'string') drop(step.target);
      if (typeof step.into === 'string' && step.into) add(step.into);
      break;
    case 'together':
      if (Array.isArray(step.steps)) {
        for (const inner of step.steps as unknown as Step[]) {
          const next = follow(inner, objects, before);
          next.forEach((id) => {
            if (!before.has(id)) after.add(id);
          });
          before.forEach((id) => {
            if (!next.has(id)) after.delete(id);
          });
        }
      }
      break;
    default:
      break;
  }
  return after;
}

/** A group is on screen when all its members are, however they got there. */
function withGroups(objects: Map<string, SceneObject>, onScreen: Set<string>): Set<string> {
  const out = new Set(onScreen);
  const groups = [...objects.values()].filter((o) => o.type === 'group' && Array.isArray(o.members));
  let changed = true;
  while (changed) {
    changed = false;
    for (const group of groups) {
      const members = (group.members as Json[]).filter((m): m is string => typeof m === 'string');
      const shown = members.length > 0 && members.every((m) => out.has(m));
      if (shown && !out.has(group.id)) {
        out.add(group.id);
        changed = true;
      } else if (!shown && out.has(group.id)) {
        out.delete(group.id);
        changed = true;
      }
    }
  }
  return out;
}

/** Ids on screen once step `stepIndex` has run (-1: before the first step). */
export function onScreenAfter(scene: Scene, stepIndex: number): Set<string> {
  const objects = new Map((scene.objects ?? []).map((o) => [o.id, o]));
  let current = withGroups(objects, new Set((scene.objects ?? []).filter((o) => o.shown === true).map((o) => o.id)));
  const steps = scene.steps ?? [];
  for (let i = 0; i <= Math.min(stepIndex, steps.length - 1); i += 1) {
    current = withGroups(objects, follow(steps[i]!, objects, current));
  }
  return current;
}

/** Objects which no step (up to the end of the scene) ever brings on screen. */
export function neverShown(scene: Scene): string[] {
  const seen = new Set<string>();
  const steps = scene.steps ?? [];
  for (let i = -1; i < steps.length; i += 1) onScreenAfter(scene, i).forEach((id) => seen.add(id));
  return (scene.objects ?? []).map((o) => o.id).filter((id) => !seen.has(id));
}
