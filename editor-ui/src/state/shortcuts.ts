/** Keyboard shortcuts for the whole editor (see ShortcutsModal for the list shown to users). */
import { autosaver } from './autosave';
import { deleteSelection, duplicateSelection, nudgeSelection, stepFrame } from './actions';
import { openModal, redo, select, undo, useEditor } from './store';

const TEXT_INPUTS = new Set(['text', 'search', 'number', 'email', 'url', 'password', 'tel']);

/** Whether the key goes to something being typed into, rather than to the editor. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) return TEXT_INPUTS.has(target.type);
  return false;
}

/** Places whose own arrow keys matter more than nudging: menus, choices, dragging. */
function ownsArrows(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest('[role="radiogroup"], [role="menu"], [role="dialog"], .drag-handle, .edge-grid, .palette') !== null;
}

export const NUDGE = 0.1;
export const BIG_NUDGE = 1;

export function handleShortcut(event: KeyboardEvent): void {
  const state = useEditor.getState();
  if (state.status !== 'ready' || event.defaultPrevented) return;
  const dialogOpen = state.confirm !== null || state.modal !== null || document.querySelector('[role="dialog"][aria-modal="true"]') !== null;
  if (dialogOpen) return;
  const mod = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  const typing = isTyping(event.target);

  if (mod && !event.altKey) {
    if (key === 'z' && !event.shiftKey) {
      event.preventDefault();
      undo();
    } else if ((key === 'z' && event.shiftKey) || key === 'y') {
      event.preventDefault();
      redo();
    } else if (key === 's') {
      event.preventDefault();
      void autosaver()?.flush();
    } else if (key === 'd') {
      event.preventDefault();
      if (!typing) duplicateSelection();
    }
    return;
  }
  if (typing || event.altKey) return;

  switch (event.key) {
    case 'Delete':
    case 'Backspace':
      if (state.selection.kind === 'object' || state.selection.kind === 'step' || state.selection.kind === 'scene') {
        event.preventDefault();
        deleteSelection();
      }
      break;
    case 'ArrowLeft':
    case 'ArrowRight':
    case 'ArrowUp':
    case 'ArrowDown': {
      if (state.selection.kind !== 'object' || ownsArrows(event.target)) return;
      event.preventDefault();
      const d = event.shiftKey ? BIG_NUDGE : NUDGE;
      const [dx, dy] = { ArrowLeft: [-d, 0], ArrowRight: [d, 0], ArrowUp: [0, d], ArrowDown: [0, -d] }[event.key] as [number, number];
      nudgeSelection(dx, dy);
      break;
    }
    case '[':
      event.preventDefault();
      stepFrame(-1);
      break;
    case ']':
      event.preventDefault();
      stepFrame(1);
      break;
    case 'Escape':
      if (state.selection.kind === 'object' || state.selection.kind === 'step') {
        select({ kind: 'scene', sceneId: state.selection.sceneId, id: null });
      } else if (state.selection.kind !== null) {
        select({ kind: null, sceneId: state.selection.sceneId, id: null });
      }
      break;
    case '?':
      event.preventDefault();
      openModal('shortcuts');
      break;
    default:
      break;
  }
}
