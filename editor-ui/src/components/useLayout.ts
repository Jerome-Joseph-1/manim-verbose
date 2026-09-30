/**
 * Layout warnings (POST /api/layout): a moment after edits stop, the scene on show is checked
 * for things off the edge of the picture or on top of each other, step by step. The warnings
 * land in the Problems panel and outline the objects on the canvas in orange.
 *
 * A server without the endpoint (404, or 405) turns the feature off for the session; any
 * other failure just leaves the scene without warnings until the next edit.
 */
import { useEffect } from 'react';
import { api, ApiError, isAbortError } from '../lib/api';
import { isRequestProblem } from '../lib/problems';
import type { Document, Problem } from '../doc/types';
import { currentSceneId, setLayoutProblems, useEditor } from '../state/store';

export const LAYOUT_DEBOUNCE_MS = 700;

/**
 * A layout problem as the rest of the editor wants it: a warning about the object it names,
 * wherever the server's `loc` pointed, so it shows beside that object whichever step it is in.
 */
export function asObjectWarning(problem: Problem, doc: Document, sceneId: string): Problem | null {
  if (isRequestProblem(problem)) return null;
  const s = doc.scenes.findIndex((sc) => sc.id === sceneId);
  if (s < 0) return null;
  const objects = doc.scenes[s]!.objects ?? [];
  const o = problem.item_id ? objects.findIndex((obj) => obj.id === problem.item_id) : -1;
  const loc = o >= 0 ? ['scenes', s, 'objects', o] : problem.loc?.length ? problem.loc : ['scenes', s];
  return { ...problem, severity: problem.severity === 'error' ? 'error' : 'warning', loc, scene_id: sceneId, item_id: o >= 0 ? problem.item_id : (problem.item_id ?? null) };
}

export function useLayoutWarnings(): void {
  const doc = useEditor((s) => s.history?.present ?? null);
  const sceneId = useEditor((s) => currentSceneId(s));
  const available = useEditor((s) => s.layoutAvailable);
  const scene = doc && sceneId ? doc.scenes.find((s) => s.id === sceneId) : undefined;
  const settings = doc?.settings;

  useEffect(() => {
    if (!doc || !sceneId || !scene || available === false) return undefined;
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await api.layout(doc, sceneId, abort.signal);
        if (abort.signal.aborted) return;
        const warnings = (response.problems ?? []).map((p) => asObjectWarning(p, doc, sceneId)).filter((p): p is Problem => p !== null);
        useEditor.setState({ layoutAvailable: true });
        setLayoutProblems(sceneId, warnings);
      } catch (error) {
        if (isAbortError(error) || abort.signal.aborted) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 405 || error.status === 501)) {
          useEditor.setState({ layoutAvailable: false, layoutProblems: {} });
          return;
        }
        // The document's own problems are shown already; warnings wait for a document that checks
        setLayoutProblems(sceneId, []);
      }
    }, LAYOUT_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
    // Layout depends on this scene (and scenes it carries from) and the settings
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, settings, sceneId, available, scene?.carry?.length ? doc : null]);
}
