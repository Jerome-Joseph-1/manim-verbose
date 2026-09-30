/**
 * The editor's state: the document with its undo history, what is selected, what the
 * server last said, and the dialogs open. Edits go through `apply`, which runs one of the
 * pure ops from doc/ops.ts and records the result for undo.
 */
import { useMemo } from 'react';
import { create } from 'zustand';
import type { Catalog, Timeline } from '../lib/api';
import type { StillObject } from '../lib/geometry';
import { buildSchemaIndex, type JsonSchema, type SchemaIndex } from '../lib/schema';
import { dedupeProblems, type ItemAddress } from '../lib/problems';
import {
  breakCoalescing, canRedo, canUndo, commit, createHistory, redo as redoHistory, replacePresent,
  selectionAfterRedo, selectionAfterUndo, undo as undoHistory, type History,
} from '../doc/history';
import { DocOpError, findObject, findScene, findStep, findStepPath, type RemovalPlan } from '../doc/ops';
import type { Document, Loc, Problem } from '../doc/types';

export type SaveState = 'loading' | 'saved' | 'saving' | 'unsaved' | 'conflict' | 'error' | 'offline';

export type SelectionKind = 'document' | 'scene' | 'object' | 'step';

export interface Selection {
  kind: SelectionKind | null;
  sceneId: string | null;
  id: string | null;
}

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  /** A second way to confirm, such as "Delete only this". */
  altLabel?: string;
  onConfirm: () => void;
  onAlt?: () => void;
}

export interface Toast {
  id: number;
  message: string;
  kind: 'info' | 'error';
}

export interface FocusRequest {
  item: ItemAddress;
  field: Loc;
  nonce: number;
}

export interface StillInfo {
  sceneId: string;
  stepIndex: number;
  objects: StillObject[];
  width: number;
  height: number;
}

/** Whether the server checks layout (POST /api/layout): null until it has been asked. */
export type LayoutAvailability = boolean | null;

export type Theme = 'dark' | 'light';

export interface EditorState {
  status: 'loading' | 'ready' | 'failed';
  loadError: string | null;
  schema: SchemaIndex | null;
  catalog: Catalog | null;
  path: string;

  history: History<Document, Selection> | null;
  revision: number;
  /** The document as the server last confirmed it (what is on disk). */
  savedDoc: Document | null;
  saveState: SaveState;
  saveMessage: string | null;
  saveProblems: Problem[];
  /** Problems from the last render of each scene, such as LaTeX which didn't compile. */
  renderProblems: Record<string, Problem[]>;
  /** Layout warnings for each scene (things off screen or on top of each other). */
  layoutProblems: Record<string, Problem[]>;
  layoutAvailable: LayoutAvailability;
  /** The other version after a 409; its document is null when the file can't be read. */
  conflict: { document: Document | null; revision: number } | null;
  timelines: Record<string, Timeline>;
  /** The objects in the still showing now, for hit testing and the "not on screen" hints. */
  still: StillInfo | null;

  selection: Selection;
  /** Per scene, the step whose end the canvas shows: undefined for the last, null for before the first. */
  frameStep: Record<string, string | null | undefined>;
  focusRequest: FocusRequest | null;
  confirm: ConfirmRequest | null;
  toasts: Toast[];
  theme: Theme;
  problemsOpen: boolean;
  modal: 'code' | 'export' | 'preview' | 'shortcuts' | 'templates' | null;
  /** The first-run tour's step, or null when it isn't showing. */
  tourStep: number | null;
}

const THEME_KEY = 'manim-editor-theme';

function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // storage unavailable: fall through to the default
  }
  return 'dark';
}

export const initialState = (): EditorState => ({
  status: 'loading',
  loadError: null,
  schema: null,
  catalog: null,
  path: '',
  history: null,
  revision: 0,
  savedDoc: null,
  saveState: 'loading',
  saveMessage: null,
  saveProblems: [],
  renderProblems: {},
  layoutProblems: {},
  layoutAvailable: null,
  conflict: null,
  timelines: {},
  still: null,
  selection: { kind: null, sceneId: null, id: null },
  frameStep: {},
  focusRequest: null,
  confirm: null,
  toasts: [],
  theme: initialTheme(),
  problemsOpen: false,
  modal: null,
  tourStep: null,
});

export const useEditor = create<EditorState>()(() => initialState());

// Reading

export function currentDoc(state: EditorState = useEditor.getState()): Document | null {
  return state.history?.present ?? null;
}

export function currentSceneId(state: EditorState = useEditor.getState()): string | null {
  const doc = currentDoc(state);
  if (!doc) return null;
  const wanted = state.selection.sceneId;
  if (wanted && doc.scenes.some((s) => s.id === wanted)) return wanted;
  return doc.scenes[0]?.id ?? null;
}

/** Index of the step whose end the canvas shows in a scene (-1: before the first step). */
export function frameStepIndex(state: EditorState, sceneId: string): number {
  const doc = currentDoc(state);
  const steps = doc ? (findScene(doc, sceneId)?.steps ?? []) : [];
  const wanted = state.frameStep[sceneId];
  if (wanted === null) return -1;
  if (wanted !== undefined) {
    const index = steps.findIndex((s) => s.id === wanted);
    if (index >= 0) return index;
  }
  return steps.length - 1;
}

export function allProblems(state: EditorState): Problem[] {
  return dedupeProblems([...state.saveProblems, ...Object.values(state.renderProblems).flat(), ...Object.values(state.layoutProblems).flat()]);
}

/** Every problem the editor knows of, for components: kept the same array while nothing changes. */
export function useAllProblems(): Problem[] {
  const saveProblems = useEditor((s) => s.saveProblems);
  const renderProblems = useEditor((s) => s.renderProblems);
  const layoutProblems = useEditor((s) => s.layoutProblems);
  return useMemo(
    () => dedupeProblems([...saveProblems, ...Object.values(renderProblems).flat(), ...Object.values(layoutProblems).flat()]),
    [saveProblems, renderProblems, layoutProblems],
  );
}

// Changing

let toastCounter = 0;

export function toast(message: string, kind: Toast['kind'] = 'info'): void {
  const id = (toastCounter += 1);
  useEditor.setState((s) => ({ toasts: [...s.toasts.slice(-3), { id, message, kind }] }));
  setTimeout(() => dismissToast(id), kind === 'error' ? 6000 : 3500);
}

export function dismissToast(id: number): void {
  useEditor.setState((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
}

export interface ApplyOptions {
  /** Edits with the same key in quick succession are one undo step. */
  key?: string;
  /**
   * What to select once the edit is made (by default the selection stays). A function is
   * called after the edit, with the new document, so it can name what the edit made.
   */
  select?: Selection | ((doc: Document) => Selection | null | undefined);
}

/**
 * Run an edit. Returns false (and says why in a toast) when the op refused, as when a name
 * is already taken. The selection before and after is recorded with it, for undo and redo.
 */
export function apply(edit: (doc: Document) => Document, options: ApplyOptions = {}): boolean {
  const state = useEditor.getState();
  if (!state.history) return false;
  let next: Document;
  try {
    next = edit(state.history.present);
  } catch (error) {
    if (error instanceof DocOpError) {
      toast(error.message, 'error');
      return false;
    }
    throw error;
  }
  const wanted = typeof options.select === 'function' ? options.select(next) : options.select;
  const selection = wanted ?? state.selection;
  const changes: Partial<EditorState> = wanted ? selectionChanges(state, selection, next) : {};
  if (next !== state.history.present) {
    changes.history = commit(state.history, next, { key: options.key ?? null, meta: { before: state.selection, after: selection } });
  }
  useEditor.setState(changes);
  return true;
}

/** Keep the selection pointing at something which exists after the document changed under it. */
function repairSelection(doc: Document, selection: Selection): Selection {
  const scene = selection.sceneId ? findScene(doc, selection.sceneId) : undefined;
  if (!scene) {
    if (selection.kind === 'document') return selection;
    return { kind: null, sceneId: doc.scenes[0]?.id ?? null, id: null };
  }
  if (selection.kind === 'object' && selection.id && !findObject(doc, scene.id, selection.id)) {
    return { kind: null, sceneId: scene.id, id: null };
  }
  if (selection.kind === 'step' && selection.id && !findStep(doc, scene.id, selection.id)) {
    return { kind: null, sceneId: scene.id, id: null };
  }
  return selection;
}

/** Undo the last edit, selecting again what was selected when it was made. */
export function undo(): void {
  const state = useEditor.getState();
  const { history } = state;
  if (!history || !canUndo(history)) return;
  const wanted = selectionAfterUndo(history) ?? state.selection;
  const next = undoHistory(history);
  const selection = repairSelection(next.present, wanted);
  useEditor.setState({ ...selectionChanges(state, selection, next.present), history: next });
}

/** Redo the edit undone last, selecting what it selected. */
export function redo(): void {
  const state = useEditor.getState();
  const { history } = state;
  if (!history || !canRedo(history)) return;
  const wanted = selectionAfterRedo(history) ?? state.selection;
  const next = redoHistory(history);
  const selection = repairSelection(next.present, wanted);
  useEditor.setState({ ...selectionChanges(state, selection, next.present), history: next });
}

/** End the current run of merged edits (called when a field loses focus). */
export function endEditBurst(): void {
  const { history } = useEditor.getState();
  if (history) useEditor.setState({ history: breakCoalescing(history) });
}

/**
 * What selecting something changes: the selection, and for a step the frame the canvas shows
 * (the frame after it; for a step nested in `together`, after the whole together step).
 */
function selectionChanges(state: EditorState, selection: Selection, doc: Document | null = currentDoc(state)): Partial<EditorState> {
  const changes: Partial<EditorState> = { selection };
  if (selection.kind === 'step' && selection.sceneId && selection.id) {
    const scene = doc ? findScene(doc, selection.sceneId) : undefined;
    const path = scene ? findStepPath(scene.steps, selection.id) : null;
    const top = path && scene?.steps ? scene.steps[path[0] as number] : undefined;
    changes.frameStep = { ...state.frameStep, [selection.sceneId]: top?.id ?? selection.id };
  }
  return changes;
}

export function select(selection: Selection): void {
  const state = useEditor.getState();
  useEditor.setState(selectionChanges(state, selection));
}

export function selectScene(sceneId: string): void {
  select({ kind: 'scene', sceneId, id: null });
}

export function setFrameStep(sceneId: string, stepId: string | null | undefined): void {
  useEditor.setState((s) => ({ frameStep: { ...s.frameStep, [sceneId]: stepId } }));
}

export function requestFocus(item: ItemAddress, field: Loc): void {
  const selection: Selection = {
    kind: item.kind,
    sceneId: item.sceneId ?? null,
    id: item.kind === 'object' || item.kind === 'step' ? (item.itemId ?? null) : null,
  };
  select(selection);
  useEditor.setState((s) => ({ focusRequest: { item, field, nonce: (s.focusRequest?.nonce ?? 0) + 1 } }));
}

export function askConfirm(request: ConfirmRequest): void {
  useEditor.setState({ confirm: request });
}

export function closeConfirm(): void {
  useEditor.setState({ confirm: null });
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // not remembered, which is fine
  }
  useEditor.setState({ theme });
}

export function openModal(modal: EditorState['modal']): void {
  useEditor.setState({ modal });
}

// Loading and the server

export function loaded(payload: {
  document: Document;
  revision: number;
  path: string;
  problems: Problem[];
  schema: JsonSchema;
  catalog: Catalog;
}): void {
  const doc = payload.document;
  useEditor.setState({
    status: 'ready',
    loadError: null,
    schema: buildSchemaIndex(payload.schema),
    catalog: payload.catalog,
    path: payload.path,
    history: createHistory<Document, Selection>(doc),
    revision: payload.revision,
    savedDoc: doc,
    saveState: 'saved',
    saveMessage: null,
    saveProblems: payload.problems,
    selection: { kind: null, sceneId: doc.scenes[0]?.id ?? null, id: null },
  });
}

export function loadFailed(message: string): void {
  useEditor.setState({ status: 'failed', loadError: message });
}

/** Take the server's copy of the document in place of ours (after a conflict). */
export function adoptServerDocument(document: Document, revision: number): void {
  const state = useEditor.getState();
  const selection = repairSelection(document, state.selection);
  const history = state.history
    ? commit(state.history, document, { meta: { before: state.selection, after: selection } })
    : createHistory<Document, Selection>(document);
  useEditor.setState({
    history,
    revision,
    savedDoc: document,
    saveState: 'saved',
    conflict: null,
    selection,
  });
}

/** The server's canonical form of what we just saved, replacing ours without an undo step. */
export function adoptCanonical(document: Document): void {
  const state = useEditor.getState();
  if (!state.history) return;
  useEditor.setState({ history: replacePresent(state.history, document) });
}

export function setRenderProblems(sceneId: string, problems: Problem[]): void {
  useEditor.setState((s) => ({ renderProblems: { ...s.renderProblems, [sceneId]: problems } }));
}

export function setLayoutProblems(sceneId: string, problems: Problem[]): void {
  useEditor.setState((s) => ({ layoutProblems: { ...s.layoutProblems, [sceneId]: problems } }));
}

export type { RemovalPlan };
