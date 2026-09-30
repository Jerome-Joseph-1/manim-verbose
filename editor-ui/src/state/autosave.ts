/**
 * Saving as you go: every edit schedules a save a moment later (so a burst of typing is one
 * save), sent with the revision it was based on. If the file changed somewhere else in the
 * meantime the server says so (409) and the user chooses whose version wins.
 */
import { ApiError, type Api } from '../lib/api';
import type { Document } from '../doc/types';
import { adoptCanonical, adoptServerDocument, currentSceneId, useEditor } from './store';

export const SAVE_DELAY_MS = 800;
const RETRY_DELAYS_MS = [2000, 4000, 8000, 15000];

function jsonEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export class Autosaver {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inFlight: Promise<void> | null = null;
  private retries = 0;
  private unsubscribe: (() => void) | null = null;
  private timelineAbort: AbortController | null = null;

  constructor(
    private readonly api: Pick<Api, 'putDocument' | 'timeline'>,
    private readonly delay = SAVE_DELAY_MS,
  ) {}

  start(): void {
    this.unsubscribe = useEditor.subscribe((state, previous) => {
      if (state.history?.present !== previous.history?.present) this.changed();
      const scene = currentSceneId(state);
      if (scene && scene !== currentSceneId(previous) && !state.timelines[scene]) void this.refreshTimeline(scene);
    });
    const scene = currentSceneId();
    if (scene) void this.refreshTimeline(scene);
  }

  stop(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private changed(): void {
    const state = useEditor.getState();
    if (!state.history) return;
    if (state.history.present === state.savedDoc) {
      if (state.saveState === 'unsaved') useEditor.setState({ saveState: 'saved' });
      return;
    }
    if (state.saveState === 'conflict') return;
    if (!this.inFlight && state.saveState !== 'unsaved') useEditor.setState({ saveState: 'unsaved', saveMessage: null });
    this.schedule(this.delay);
  }

  private schedule(ms: number): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.save();
    }, ms);
  }

  /** Save now rather than after the delay (Ctrl+S, and before leaving). */
  async flush(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.inFlight) await this.inFlight;
    await this.save();
  }

  private save(): Promise<void> {
    if (this.inFlight) {
      // Another save is on its way; go again once it lands
      return this.inFlight.then(() => this.save());
    }
    const state = useEditor.getState();
    if (!state.history || state.conflict) return Promise.resolve();
    const doc = state.history.present;
    if (doc === state.savedDoc) return Promise.resolve();
    useEditor.setState({ saveState: 'saving' });
    this.inFlight = this.send(doc, state.revision).finally(() => {
      this.inFlight = null;
    });
    return this.inFlight;
  }

  private async send(doc: Document, baseRevision: number): Promise<void> {
    try {
      const response = await this.api.putDocument(doc, baseRevision);
      this.retries = 0;
      const now = useEditor.getState();
      const unchanged = now.history?.present === doc;
      let saved: Document = doc;
      if (unchanged && response.document && !jsonEqual(response.document, doc)) {
        adoptCanonical(response.document);
        saved = response.document;
      }
      useEditor.setState({
        revision: response.revision,
        savedDoc: saved,
        saveProblems: response.problems ?? [],
        saveState: unchanged ? 'saved' : 'unsaved',
        saveMessage: null,
      });
      if (!unchanged) this.schedule(this.delay);
      const scene = currentSceneId();
      if (scene) void this.refreshTimeline(scene);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.status === 409) {
        const body = error.body as { document?: Document; revision?: number } | null;
        useEditor.setState({
          saveState: 'conflict',
          conflict: { document: body?.document ?? doc, revision: body?.revision ?? baseRevision },
        });
      } else if (error.status === 422) {
        useEditor.setState({
          saveState: 'error',
          saveProblems: error.problems,
          saveMessage: 'Not saved yet: fix the problem shown in red and it will save',
        });
      } else {
        const wait = RETRY_DELAYS_MS[Math.min(this.retries, RETRY_DELAYS_MS.length - 1)]!;
        this.retries += 1;
        useEditor.setState({
          saveState: 'offline',
          saveMessage: error.status === 0 ? "Can't reach the editor server; trying again" : `Saving failed (${error.status}); trying again`,
        });
        this.schedule(wait);
      }
    }
  }

  /** After a conflict: keep what is in the editor, saving it over the other version. */
  async keepMine(): Promise<void> {
    const { conflict } = useEditor.getState();
    if (!conflict) return;
    useEditor.setState({ conflict: null, revision: conflict.revision, saveState: 'unsaved' });
    await this.save();
  }

  /** After a conflict: load the other version (this is undoable). */
  takeTheirs(): void {
    const { conflict } = useEditor.getState();
    if (!conflict) return;
    adoptServerDocument(conflict.document, conflict.revision);
    const scene = currentSceneId();
    if (scene) void this.refreshTimeline(scene);
  }

  async refreshTimeline(sceneId: string): Promise<void> {
    this.timelineAbort?.abort();
    const abort = new AbortController();
    this.timelineAbort = abort;
    try {
      const timeline = await this.api.timeline(sceneId, abort.signal);
      useEditor.setState((s) => ({ timelines: { ...s.timelines, [sceneId]: timeline } }));
    } catch {
      // Timings are a nicety; a scene not saved yet, or a server without them, shows none
    }
  }
}

let current: Autosaver | null = null;

export function setAutosaver(saver: Autosaver | null): void {
  current = saver;
}

export function autosaver(): Autosaver | null {
  return current;
}
