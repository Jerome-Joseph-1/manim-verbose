/**
 * Objects carried over from one scene to the next (`carry: [ids]` on a scene): on screen from
 * the start as the scene before left them, and usable by id as if declared in the scene, as
 * validate.py's check_carry has it. A carried object may itself have been carried into the
 * scene before, so carrying goes back as far as it needs to.
 */
import { objectRefs } from './refs';
import type { Document, Scene, SceneObject } from './types';

export interface CarriedObject {
  object: SceneObject;
  /** The scene which declares it. */
  from: string;
}

/**
 * Every object usable in a scene, by id: the carried ones (which resolve) then its own, each
 * with the scene declaring it. An object declared in the scene hides a carried one of the same
 * name, which validation reports.
 */
export function usableObjects(doc: Document, sceneId: string): Map<string, CarriedObject> {
  const index = doc.scenes.findIndex((s) => s.id === sceneId);
  const out = new Map<string, CarriedObject>();
  if (index < 0) return out;
  let previous = new Map<string, CarriedObject>();
  for (let i = 0; i <= index; i += 1) {
    const scene = doc.scenes[i]!;
    const here = new Map<string, CarriedObject>();
    if (i > 0) {
      for (const id of scene.carry ?? []) {
        const found = previous.get(id);
        if (found) here.set(id, found);
      }
    }
    for (const obj of scene.objects ?? []) here.set(obj.id, { object: obj, from: scene.id });
    previous = here;
  }
  for (const [id, entry] of previous) out.set(id, entry);
  return out;
}

/** The objects carried into a scene which resolve, in the order `carry` lists them. */
export function carriedObjects(doc: Document, sceneId: string): CarriedObject[] {
  const scene = doc.scenes.find((s) => s.id === sceneId);
  if (!scene?.carry?.length) return [];
  const usable = usableObjects(doc, sceneId);
  const own = new Set((scene.objects ?? []).map((o) => o.id));
  return scene.carry.filter((id) => !own.has(id) && usable.has(id)).map((id) => usable.get(id)!);
}

/**
 * The scene as its references see it: its carried objects first, then its own. Used for what
 * a field can refer to, and for what a new step can act on.
 */
export function effectiveScene(doc: Document, scene: Scene): Scene {
  const carried = carriedObjects(doc, scene.id);
  if (carried.length === 0) return scene;
  return { ...scene, objects: [...carried.map((c) => c.object), ...(scene.objects ?? [])] };
}

/** What a scene could carry: everything usable in the scene before it. */
export function carryCandidates(doc: Document, sceneId: string): CarriedObject[] {
  const index = doc.scenes.findIndex((s) => s.id === sceneId);
  if (index <= 0) return [];
  return [...usableObjects(doc, doc.scenes[index - 1]!.id).values()];
}

/**
 * The ids to carry for `wanted` to work: each with everything it is built on (the plane a
 * vector is on, what a brace goes around, the members of a group), as far as they go.
 */
export function withDependencies(candidates: CarriedObject[], wanted: string[]): string[] {
  const byId = new Map(candidates.map((c) => [c.object.id, c.object]));
  const out: string[] = [];
  const visit = (id: string) => {
    if (out.includes(id) || !byId.has(id)) return;
    out.push(id);
    for (const ref of objectRefs(byId.get(id)!)) visit(ref.id);
  };
  wanted.forEach(visit);
  return out;
}

/** Scenes after `sceneId` which carry `objectId` on, one after another. */
export function scenesCarrying(doc: Document, sceneId: string, objectId: string): string[] {
  const index = doc.scenes.findIndex((s) => s.id === sceneId);
  const out: string[] = [];
  for (let i = index + 1; i > 0 && i < doc.scenes.length; i += 1) {
    const scene = doc.scenes[i]!;
    if (!(scene.carry ?? []).includes(objectId) || (scene.objects ?? []).some((o) => o.id === objectId)) break;
    out.push(scene.id);
  }
  return out;
}
