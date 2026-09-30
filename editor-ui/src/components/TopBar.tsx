import { canRedo, canUndo } from '../doc/history';
import { findScene, setItemField } from '../doc/ops';
import { autosaver } from '../state/autosave';
import {
  apply, currentSceneId, endEditBurst, frameStepIndex, openModal, redo, select, setTheme, undo, useEditor, type SaveState,
} from '../state/store';
import { exportRunning, useExport } from './ExportModal';
import { Icon } from './Icon';
import { openPreview } from './PreviewModal';

const SAVE_LABELS: Record<SaveState, string> = {
  loading: 'Loading…',
  saved: 'Saved',
  saving: 'Saving…',
  unsaved: 'Unsaved',
  conflict: 'Conflict',
  error: 'Not saved',
  offline: 'Offline',
};

export function SaveStatus() {
  const state = useEditor((s) => s.saveState);
  const message = useEditor((s) => s.saveMessage);
  const path = useEditor((s) => s.path);
  const title =
    message ??
    (state === 'saved' ? `All changes saved to ${path}` : state === 'conflict' ? 'The file was changed somewhere else' : SAVE_LABELS[state]);
  return (
    <span className="save-status" data-state={state} data-testid="save-status" title={title} role="status" aria-live="polite">
      <span className="dot" aria-hidden="true" />
      {SAVE_LABELS[state]}
      <span className="sr-only">{message ? `: ${message}` : ''}</span>
    </span>
  );
}

function Brand() {
  return (
    <div className="brand" aria-label="manim editor">
      <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
        <rect x="1" y="1" width="30" height="30" rx="7" fill="currentColor" opacity="0.14" />
        <path d="M8 22V11l8 7 8-7v11" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function TopBar() {
  const title = useEditor((s) => s.history?.present.title ?? '');
  const history = useEditor((s) => s.history);
  const theme = useEditor((s) => s.theme);
  const job = useExport((s) => s.job);
  const running = exportRunning(job);
  const hasDoc = history !== null;

  const preview = () => {
    const s = useEditor.getState();
    const doc = s.history?.present;
    const sceneId = currentSceneId(s);
    if (!doc || !sceneId) return;
    const steps = findScene(doc, sceneId)?.steps ?? [];
    if (steps.length === 0) return;
    if (s.selection.kind === 'step' && s.selection.id) {
      const index = steps.findIndex((st) => st.id === s.selection.id);
      if (index >= 0) return openPreview({ sceneId, start: index, end: index });
    }
    if (s.selection.kind === 'scene' || s.selection.kind === null) return openPreview({ sceneId, start: 0, end: steps.length - 1 });
    const index = Math.max(0, frameStepIndex(s, sceneId));
    return openPreview({ sceneId, start: index, end: index });
  };

  return (
    <header className="topbar">
      <Brand />
      <label className="sr-only" htmlFor="doc-title">
        Video title
      </label>
      <input
        id="doc-title"
        className="doc-title"
        value={title}
        placeholder="Untitled video"
        disabled={!hasDoc}
        onChange={(e) => apply((d) => setItemField(d, { kind: 'document' }, ['title'], e.target.value), { key: 'field:document:title' })}
        onBlur={endEditBurst}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        }}
      />
      <SaveStatus />
      <div className="topbar-spacer" />
      <div className="topbar-group">
        <button type="button" className="icon-btn" aria-label="Undo" title="Undo (Ctrl+Z)" disabled={!history || !canUndo(history)} onClick={undo}>
          <Icon name="undo" />
        </button>
        <button type="button" className="icon-btn" aria-label="Redo" title="Redo (Ctrl+Shift+Z)" disabled={!history || !canRedo(history)} onClick={redo}>
          <Icon name="redo" />
        </button>
      </div>
      <div className="topbar-divider" />
      <button type="button" className="btn" onClick={preview} disabled={!hasDoc} title="Play a quick preview of the selected step, or of the scene">
        <Icon name="play" /> Preview
      </button>
      <button type="button" className="btn" onClick={() => openModal('code')} disabled={!hasDoc} title="See the Python code">
        <Icon name="code" /> Code
      </button>
      <button type="button" className="btn btn-primary" onClick={() => openModal('export')} disabled={!hasDoc}>
        <Icon name="film" /> {running ? `Exporting ${Math.round((job?.progress ?? 0) * 100)}%` : 'Export'}
      </button>
      <div className="topbar-divider" />
      <button
        type="button"
        className="icon-btn"
        aria-label="Video settings"
        title="Video settings"
        disabled={!hasDoc}
        onClick={() => select({ kind: 'document', sceneId: null, id: null })}
      >
        <Icon name="settings" />
      </button>
      <button
        type="button"
        className="icon-btn"
        aria-label={theme === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme'}
        title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      >
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
      </button>
      <button type="button" className="icon-btn" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" onClick={() => openModal('shortcuts')}>
        <Icon name="keyboard" />
      </button>
    </header>
  );
}

export function ConflictBanner() {
  const conflict = useEditor((s) => s.conflict);
  if (!conflict) return null;
  return (
    <div className="banner banner-conflict" role="alert" data-testid="conflict-banner">
      <Icon name="alert" />
      <span>
        <strong>The file was changed somewhere else</strong> (in another tab, or on disk) since you opened it. Which version do you want to keep?
      </span>
      <div className="actions">
        <button
          type="button"
          className="btn btn-sm"
          disabled={conflict.document === null}
          title={conflict.document === null ? "The other version can't be read as a scene file" : undefined}
          onClick={() => autosaver()?.takeTheirs()}
        >
          Load their version
        </button>
        <button type="button" className="btn btn-sm btn-primary" onClick={() => void autosaver()?.keepMine()}>
          Keep mine
        </button>
      </div>
    </div>
  );
}
