/** The Python the scene file turns into, to read or copy. */
import { useEffect, useState } from 'react';
import { api, ApiError, isAbortError } from '../lib/api';
import type { Problem } from '../doc/types';
import { currentDoc, currentSceneId, openModal, toast, useEditor } from '../state/store';
import { Dialog } from './Dialog';
import { FieldProblems } from './form/Field';
import { Icon } from './Icon';

type State = { phase: 'loading' } | { phase: 'ready'; code: string } | { phase: 'failed'; message: string; problems: Problem[] };

export function CodeModal() {
  const open = useEditor((s) => s.modal === 'code');
  if (!open) return null;
  return <Code />;
}

function Code() {
  const sceneId = useEditor((s) => currentSceneId(s));
  const [scope, setScope] = useState<'scene' | 'all'>('scene');
  const [code, setCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (code === null) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast("Couldn't copy: select the code and press Ctrl+C", 'error');
    }
  };

  return (
    <Dialog
      title="Python code"
      onClose={() => openModal(null)}
      wide
      testId="code-dialog"
      footer={
        <>
          <div className="segmented left" style={{ width: 'auto' }} role="radiogroup" aria-label="Which code">
            <button type="button" role="radio" aria-checked={scope === 'scene'} style={{ padding: '0 12px' }} onClick={() => setScope('scene')}>
              This scene
            </button>
            <button type="button" role="radio" aria-checked={scope === 'all'} style={{ padding: '0 12px' }} onClick={() => setScope('all')}>
              Whole video
            </button>
          </div>
          <button type="button" className="btn btn-primary" onClick={copy} disabled={code === null}>
            <Icon name={copied ? 'check' : 'copy'} /> {copied ? 'Copied' : 'Copy code'}
          </button>
        </>
      }
    >
      <p>This is the manim code your video is made from. You don't need it, but you can take it into a Python project.</p>
      <CodeView key={`${scope}:${sceneId}`} sceneId={scope === 'scene' ? sceneId : null} onCode={setCode} />
    </Dialog>
  );
}

function CodeView({ sceneId, onCode }: { sceneId: string | null; onCode: (code: string | null) => void }) {
  const [state, setState] = useState<State>({ phase: 'loading' });
  useEffect(() => {
    const doc = currentDoc();
    if (!doc) return undefined;
    const abort = new AbortController();
    onCode(null);
    api
      .code(doc, sceneId, abort.signal)
      .then((r) => {
        setState({ phase: 'ready', code: r.code });
        onCode(r.code);
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        const problems = error instanceof ApiError ? error.problems : [];
        setState({ phase: 'failed', message: error instanceof ApiError && error.status === 422 ? 'Fix these problems to see the code:' : 'The code could not be made.', problems });
      });
    return () => abort.abort();
  }, [sceneId, onCode]);

  if (state.phase === 'loading') {
    return (
      <div className="inline">
        <span className="spinner" aria-hidden="true" /> Making the code…
      </div>
    );
  }
  if (state.phase === 'failed') {
    return (
      <>
        <p>{state.message}</p>
        <FieldProblems problems={state.problems} />
      </>
    );
  }
  return (
    <pre className="code-view mono" tabIndex={0} aria-label="Python code" data-testid="code-view">
      {state.code}
    </pre>
  );
}
