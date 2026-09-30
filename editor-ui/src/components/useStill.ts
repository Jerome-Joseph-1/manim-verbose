/**
 * The still for what the canvas shows, kept in step with the document: asked for a moment
 * after edits stop, with older requests abandoned, and swapped in only once the new picture
 * has loaded, so the canvas never flashes blank.
 */
import { useEffect, useRef, useState } from 'react';
import { api, ApiError, isAbortError } from '../lib/api';
import { fitMapping, type FrameMapping, type StillObject } from '../lib/geometry';
import { isRequestProblem } from '../lib/problems';
import type { Document, Problem } from '../doc/types';
import { setRenderProblems, useEditor } from '../state/store';

export const STILL_DEBOUNCE_MS = 250;

export interface StillView {
  url: string;
  width: number;
  height: number;
  objects: StillObject[];
  mapping: FrameMapping;
  sceneId: string;
  stepIndex: number;
}

export interface StillError {
  message: string;
  problems: Problem[];
}

/** Preload an image so it can be swapped in without a blank moment. */
function preload(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve();
    img.src = url;
  });
}

export function useStill(doc: Document | null, sceneId: string | null, stepIndex: number, width: number) {
  const [still, setStill] = useState<StillView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<StillError | null>(null);
  const seq = useRef(0);
  const scene = doc && sceneId ? doc.scenes.find((s) => s.id === sceneId) : undefined;
  const settings = doc?.settings;

  useEffect(() => {
    if (!doc || !sceneId || !scene || width <= 0) return undefined;
    const mine = (seq.current += 1);
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const response = await api.still({ document: doc, scene_id: sceneId, step_index: stepIndex, width }, abort.signal);
        if (mine !== seq.current) return;
        await preload(response.image_url);
        if (mine !== seq.current) return;
        const view: StillView = {
          url: response.image_url,
          width: response.width,
          height: response.height,
          objects: response.objects ?? [],
          mapping: fitMapping(response.objects ?? [], response.width, response.height),
          sceneId,
          stepIndex,
        };
        setStill(view);
        setError(null);
        setLoading(false);
        setRenderProblems(sceneId, (response.problems ?? []).filter((p) => !isRequestProblem(p) && (p.scene_id === sceneId || p.scene_id === null)));
        useEditor.setState({ still: { sceneId, stepIndex, objects: view.objects, width: view.width, height: view.height } });
      } catch (err) {
        if (isAbortError(err) || mine !== seq.current) return;
        if (err instanceof ApiError && err.superseded) return; // a newer request is on its way
        setLoading(false);
        if (err instanceof ApiError) {
          // Only a 422 is about the document; anything else is the server failing, said on the canvas
          if (err.status === 422) {
            const docProblems = err.problems.filter((p) => !isRequestProblem(p));
            setRenderProblems(sceneId, docProblems.filter((p) => p.scene_id === sceneId || p.scene_id === null));
          } else {
            // What an earlier render said was about an earlier document
            setRenderProblems(sceneId, []);
          }
          setError({
            message: err.status === 422 ? "This picture can't be drawn until this is fixed:" : err.status === 0 ? "Can't reach the editor server." : 'Drawing the picture failed.',
            problems: err.problems,
          });
        } else {
          setError({ message: 'Drawing the picture failed.', problems: [] });
        }
      }
    }, STILL_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
    // The still depends on this scene, the settings and the request, not on other scenes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene, settings, sceneId, stepIndex, width]);

  const current = still && still.sceneId === sceneId ? still : null;
  return { still: current, anyStill: still, loading, error };
}
