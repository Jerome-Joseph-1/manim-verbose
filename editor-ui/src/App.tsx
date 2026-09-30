import { useEffect, useState } from 'react';
import { api, ApiError, type Catalog } from './lib/api';
import type { Document, Problem } from './doc/types';
import { ensureStepIds } from './doc/ops';
import { invariantViolations } from './doc/check';
import { storage } from './doc/storage';
import { Autosaver, setAutosaver } from './state/autosave';
import { handleShortcut } from './state/shortcuts';
import { currentDoc, dismissToast, loadFailed, loaded, useEditor } from './state/store';
import { Canvas } from './components/Canvas';
import { CodeModal } from './components/CodeModal';
import { ConfirmDialog } from './components/ConfirmDialog';
import { ExportModal } from './components/ExportModal';
import { FieldProblems } from './components/form/Field';
import { Icon } from './components/Icon';
import { PreviewModal } from './components/PreviewModal';
import { ProblemsPanel } from './components/ProblemsPanel';
import { PropertiesPanel } from './components/PropertiesPanel';
import { ShortcutsModal } from './components/ShortcutsModal';
import { Sidebar } from './components/Sidebar';
import { TemplateGallery } from './components/TemplateGallery';
import { Tour, maybeStartTour } from './components/Tour';
import { ConflictBanner, TopBar } from './components/TopBar';
import { useLayoutWarnings } from './components/useLayout';

/** What a new video starts as when the file can't be read and the user starts over. */
const FRESH_DOCUMENT: Document = { version: 1, title: 'Untitled', scenes: [{ id: 'scene_1' }] };

interface Unreadable {
  path: string;
  revision: number;
  problems: Problem[];
}

async function loadEverything(): Promise<Unreadable | null> {
  const [schema, catalog, document] = await Promise.all([
    api.schema(),
    api.catalog().catch((): Catalog | null => null),
    storage().load(),
  ]);
  if (document.document === null) {
    return { path: document.path, revision: document.revision, problems: document.problems ?? [] };
  }
  loaded({
    document: ensureStepIds(document.document),
    revision: document.revision,
    path: document.path,
    problems: document.problems ?? [],
    schema,
    catalog: catalog ?? { objects: [], steps: [] },
  });
  return null;
}

export function App() {
  const status = useEditor((s) => s.status);
  const loadError = useEditor((s) => s.loadError);
  const theme = useEditor((s) => s.theme);
  const [unreadable, setUnreadable] = useState<Unreadable | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    loadEverything()
      .then((result) => {
        if (!cancelled) setUnreadable(result);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        loadFailed(error instanceof ApiError && error.status === 0 ? "Can't reach the editor server. Is manimgl-editor still running?" : String((error as Error).message ?? error));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  useEffect(() => {
    if (status !== 'ready') return undefined;
    const saver = new Autosaver({ save: (doc, base, signal) => storage().save(doc, base, signal), timeline: api.timeline });
    setAutosaver(saver);
    saver.start();
    window.addEventListener('keydown', handleShortcut);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      const state = useEditor.getState().saveState;
      if (state !== 'saved') {
        void saver.flush();
        event.preventDefault();
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    // For tests and for curious people: the document as the editor holds it
    (window as unknown as { __manimEditor: unknown }).__manimEditor = {
      document: () => currentDoc(),
      state: () => useEditor.getState(),
      check: () => {
        const doc = currentDoc();
        return doc ? invariantViolations(doc) : ['no document'];
      },
    };
    maybeStartTour();
    return () => {
      saver.stop();
      setAutosaver(null);
      window.removeEventListener('keydown', handleShortcut);
      window.removeEventListener('beforeunload', beforeUnload);
    };
  }, [status]);

  if (unreadable) {
    return (
      <UnreadableFile
        info={unreadable}
        onStartFresh={async () => {
          try {
            await storage().save(FRESH_DOCUMENT, unreadable.revision);
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 409)) throw error;
          }
          setUnreadable(null);
          setAttempt((a) => a + 1);
        }}
        onRetry={() => {
          setUnreadable(null);
          setAttempt((a) => a + 1);
        }}
      />
    );
  }
  if (status === 'loading') {
    return (
      <div className="splash" role="status">
        <span className="spinner" aria-hidden="true" />
        Opening your video…
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <main className="splash">
        <div className="splash-error">
          <h1>The editor couldn't start</h1>
          <p>{loadError}</p>
          <button type="button" className="btn btn-primary" onClick={() => setAttempt((a) => a + 1)}>
            Try again
          </button>
        </div>
      </main>
    );
  }
  return <Workspace />;
}

function Workspace() {
  useLayoutWarnings();
  return (
    <div className="app">
      <TopBar />
      <ConflictBanner />
      <div className="workspace">
        <Sidebar />
        <main className="center" aria-label="Picture">
          <Canvas />
          <ProblemsPanel />
        </main>
        <PropertiesPanel />
      </div>
      <PreviewModal />
      <CodeModal />
      <ExportModal />
      <ShortcutsModal />
      <TemplateGallery />
      <ConfirmDialog />
      <Tour />
      <Toasts />
    </div>
  );
}

function UnreadableFile({ info, onStartFresh, onRetry }: { info: Unreadable; onStartFresh: () => Promise<void>; onRetry: () => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <main className="splash">
      <div className="splash-error" style={{ maxWidth: 560, textAlign: 'left' }}>
        <h1>This file can't be opened as a video</h1>
        <p>
          <span className="mono">{info.path}</span> isn't a scene file the editor can read, perhaps after an edit made outside the editor. Fix it in a
          text editor and try again, or start a new video in its place.
        </p>
        <FieldProblems problems={info.problems} />
        <div className="inline" style={{ marginTop: 16 }}>
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await onStartFresh();
              setBusy(false);
            }}
          >
            Start a new video in this file
          </button>
        </div>
      </div>
    </main>
  );
}

function Toasts() {
  const toasts = useEditor((s) => s.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'}>
          <span>{t.message}</span>
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => dismissToast(t.id)}>
            <Icon name="x" />
          </button>
        </div>
      ))}
    </div>
  );
}
