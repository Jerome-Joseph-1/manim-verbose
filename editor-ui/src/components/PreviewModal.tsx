/** A quick low quality video of a step or a whole scene. */
import { useEffect, useState } from 'react';
import { create } from 'zustand';
import { api, ApiError, isAbortError } from '../lib/api';
import { findScene } from '../doc/ops';
import type { Problem } from '../doc/types';
import { currentDoc, useEditor } from '../state/store';
import { Dialog } from './Dialog';
import { FieldProblems } from './form/Field';

export interface PreviewRequest {
  sceneId: string;
  start: number;
  end: number;
}

const usePreview = create<{ request: PreviewRequest | null }>(() => ({ request: null }));

export function openPreview(request: PreviewRequest): void {
  usePreview.setState({ request });
}

export function closePreview(): void {
  usePreview.setState({ request: null });
}

type State =
  | { phase: 'rendering' }
  | { phase: 'ready'; url: string }
  | { phase: 'failed'; message: string; problems: Problem[] };

export function PreviewModal() {
  const request = usePreview((s) => s.request);
  if (!request) return null;
  return <Preview key={`${request.sceneId}:${request.start}:${request.end}`} request={request} />;
}

function Preview({ request }: { request: PreviewRequest }) {
  const [state, setState] = useState<State>({ phase: 'rendering' });
  const [playError, setPlayError] = useState(false);
  const doc = useEditor((s) => s.history?.present ?? null);
  const scene = doc ? findScene(doc, request.sceneId) : undefined;

  useEffect(() => {
    const document = currentDoc();
    if (!document) return undefined;
    const abort = new AbortController();
    api
      .clip({ document, scene_id: request.sceneId, start_step: request.start, end_step: request.end }, abort.signal)
      .then((r) => setState({ phase: 'ready', url: r.video_url }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        if (error instanceof ApiError) {
          setState({
            phase: 'failed',
            message: error.status === 422 ? "The preview couldn't be made, because of these problems:" : error.message,
            problems: error.problems,
          });
        } else {
          setState({ phase: 'failed', message: 'The preview failed.', problems: [] });
        }
      });
    return () => abort.abort();
  }, [request]);

  const what =
    request.start === request.end
      ? `step ${request.start + 1}${scene?.steps?.[request.start] ? ` (${scene.steps[request.start]!.do})` : ''}`
      : `steps ${request.start + 1} to ${request.end + 1}`;

  return (
    <Dialog title={`Preview: ${scene?.title || request.sceneId}, ${what}`} onClose={closePreview} wide testId="preview-dialog">
      <div className="video-frame" aria-live="polite">
        {state.phase === 'rendering' ? (
          <div className="inline">
            <span className="spinner" aria-hidden="true" /> Rendering a quick preview…
          </div>
        ) : null}
        {state.phase === 'ready' && !playError ? (
          <video src={state.url} controls autoPlay playsInline data-testid="preview-video" onError={() => setPlayError(true)} />
        ) : null}
        {state.phase === 'ready' && playError ? (
          <p style={{ padding: 16 }}>
            This browser can't play the preview here. <a href={state.url} target="_blank" rel="noreferrer">Open the video</a>
          </p>
        ) : null}
        {state.phase === 'failed' ? <p style={{ padding: 16 }}>{state.message}</p> : null}
      </div>
      {state.phase === 'failed' ? <FieldProblems problems={state.problems} /> : null}
      <p className="field-help">Previews are low quality to be quick. Export makes the full quality video.</p>
    </Dialog>
  );
}
