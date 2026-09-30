/**
 * Rendering requests send only the scene being looked at (with the document's settings),
 * so that a mistake in some other scene doesn't stop this one from being drawn. Problems
 * come back located in that one-scene document, and are moved back to the real scene.
 */
import type { Document, Problem } from '../doc/types';
import { formatLoc } from '../doc/paths';

export function sceneOnly(doc: Document, sceneId: string): Document {
  const scene = doc.scenes.find((s) => s.id === sceneId);
  return { ...doc, scenes: scene ? [scene] : [] };
}

export function relocateProblems(problems: Problem[], doc: Document, sceneId: string): Problem[] {
  const index = doc.scenes.findIndex((s) => s.id === sceneId);
  if (index <= 0) return problems.map((p) => (p.scene_id === null && p.loc[0] === 'scenes' ? { ...p, scene_id: sceneId } : p));
  return problems.map((p) => {
    if (p.loc[0] !== 'scenes' || p.loc[1] !== 0) return p;
    const loc = ['scenes', index, ...p.loc.slice(2)];
    return { ...p, loc, path: formatLoc(loc), scene_id: p.scene_id ?? sceneId };
  });
}
