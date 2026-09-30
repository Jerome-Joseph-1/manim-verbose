/** The lists on the left, the top bar, the problems panel, dialogs and keyboard shortcuts. */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Sidebar } from './Sidebar';
import { ProblemsPanel } from './ProblemsPanel';
import { ConflictBanner, SaveStatus, TopBar } from './TopBar';
import { ConfirmDialog } from './ConfirmDialog';
import { Menu } from './Menu';
import { PropertiesPanel } from './PropertiesPanel';
import { handleShortcut, isTyping } from '../state/shortcuts';
import { currentDoc, select, useEditor } from '../state/store';
import { findObject, findStep } from '../doc/ops';
import type { Problem } from '../doc/types';
import { sampleDoc } from '../test/fixtures';
import { setupEditor } from '../test/editor';

beforeEach(() => {
  setupEditor(sampleDoc());
});

describe('the scenes list', () => {
  it('lists scenes and switches between them', async () => {
    render(<Sidebar />);
    const list = screen.getByTestId('scene-list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    await userEvent.click(within(list).getByRole('button', { name: 'second' }));
    expect(useEditor.getState().selection).toEqual({ kind: 'scene', sceneId: 'second', id: null });
    expect(screen.getByTestId('step-list')).toHaveTextContent('Show');
  });

  it('adds, duplicates, reorders and deletes scenes', async () => {
    render(<><Sidebar /><ConfirmDialog /></>);
    await userEvent.click(screen.getByTestId('add-scene'));
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro', 'second', 'scene_1']);
    await userEvent.click(screen.getByRole('button', { name: 'Duplicate scene Introduction' }));
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro', 'intro_2', 'second', 'scene_1']);
    // Alt+Down moves a scene later
    const row = screen.getByTestId('scene-list').querySelector('[data-scene-id="intro"] .row-main') as HTMLElement;
    fireEvent.keyDown(row, { key: 'ArrowDown', altKey: true });
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro_2', 'intro', 'second', 'scene_1']);
    await userEvent.click(screen.getByRole('button', { name: 'Delete scene scene_1' }));
    await userEvent.click(within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Delete scene' }));
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro_2', 'intro', 'second']);
  });
});

describe('the steps list', () => {
  it('shows each step with what it acts on, its caption and duration', () => {
    useEditor.setState({ timelines: { intro: { steps: [{ step_id: 'intro_2', index: 1, start: 1, duration: 2.5 }], duration: 12 } } });
    render(<Sidebar />);
    const cards = screen.getAllByTestId('step-card');
    expect(cards).toHaveLength(10);
    expect(cards[1]).toHaveTextContent('Show');
    expect(cards[1]).toHaveTextContent('eq, label');
    expect(cards[1]).toHaveTextContent('The oldest theorem you know');
    expect(cards[1]).toHaveTextContent('2.5 s');
    expect(cards[3]).toHaveTextContent('label → eq');
    expect(cards[7]).toHaveTextContent('show brace + highlight eq');
  });

  it('adds a step from the menu, using only the keyboard', async () => {
    render(<Sidebar />);
    const button = screen.getByTestId('add-step');
    button.focus();
    await userEvent.keyboard('{Enter}');
    const menu = await screen.findByRole('menu', { name: 'Add a step' });
    await act(() => new Promise((r) => requestAnimationFrame(() => r(null))));
    expect(document.activeElement).toBe(within(menu).getAllByRole('menuitem')[0]);
    await userEvent.keyboard('{ArrowDown}{Enter}');
    const added = currentDoc()!.scenes[0]!.steps!.at(-1)!;
    expect(added.do).toBe('hide');
    expect(useEditor.getState().selection).toMatchObject({ kind: 'step', id: added.id });
  });

  it('reorders with Alt+arrows, duplicates and deletes', async () => {
    render(<Sidebar />);
    const title = screen.getAllByTestId('step-card')[0]!.querySelector('.step-title') as HTMLElement;
    fireEvent.keyDown(title, { key: 'ArrowDown', altKey: true });
    expect(currentDoc()!.scenes[0]!.steps!.slice(0, 2).map((s) => s.id)).toEqual(['intro_2', 'intro_1']);
    await userEvent.click(screen.getByRole('button', { name: 'Duplicate step 1' }));
    expect(currentDoc()!.scenes[0]!.steps![1]!.id).toBe('intro_13');
    await userEvent.click(screen.getByRole('button', { name: 'Delete step 1' }));
    expect(findStep(currentDoc()!, 'intro', 'intro_2')).toBeUndefined();
  });

  it('marks steps with problems', () => {
    const problem: Problem = { message: 'x', severity: 'error', loc: ['scenes', 0, 'steps', 2, 'part'], path: '', scene_id: 'intro', item_id: 'intro_3' };
    useEditor.setState({ saveProblems: [problem] });
    render(<Sidebar />);
    expect(screen.getAllByTestId('step-card')[2]!.querySelector('.problem-dot.error')).not.toBeNull();
  });

  it('helps when a scene has no steps', async () => {
    render(<Sidebar />);
    await userEvent.click(within(screen.getByTestId('scene-list')).getByRole('button', { name: 'second' }));
    expect(screen.getByTestId('step-list')).toBeInTheDocument();
    act(() => useEditor.setState({ history: { ...useEditor.getState().history!, present: { ...currentDoc()!, scenes: [currentDoc()!.scenes[0]!, { id: 'second', objects: [{ id: 'x', type: 'circle' }] }] } } }));
    expect(screen.getByText(/Steps play one after another/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Show all 1 object/ }));
    expect(currentDoc()!.scenes[1]!.steps).toEqual([{ id: 'second_1', do: 'show', target: 'x' }]);
  });
});

describe('the objects list', () => {
  it('groups objects by category, marking those not on screen', () => {
    render(<Sidebar />);
    const list = screen.getByTestId('object-list');
    expect(within(list).getByRole('list', { name: 'Coordinates' })).toHaveTextContent('plane');
    expect(within(list).getByRole('list', { name: 'Text & math' })).toHaveTextContent('eq');
    // intro ends with a clear, so nothing is on screen at its end
    expect(list.querySelectorAll('.offscreen').length).toBe(8);
  });

  it('adds an object from the menu and selects it', async () => {
    render(<Sidebar />);
    await userEvent.click(screen.getByTestId('add-object'));
    await userEvent.click(screen.getByRole('menuitem', { name: /^Circle/ }));
    expect(findObject(currentDoc()!, 'intro', 'circle')).toBeDefined();
    expect(useEditor.getState().selection).toMatchObject({ kind: 'object', id: 'circle' });
  });

  it('asks before deleting an object in use', async () => {
    render(<><Sidebar /><ConfirmDialog /></>);
    await userEvent.click(screen.getByRole('button', { name: 'Delete eq' }));
    const dialog = screen.getByTestId('confirm-dialog');
    expect(dialog).toHaveTextContent("'eq' is used elsewhere in this scene");
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(findObject(currentDoc()!, 'intro', 'eq')).toBeDefined();
    await userEvent.click(screen.getByRole('button', { name: 'Delete eq' }));
    await userEvent.click(within(screen.getByTestId('confirm-dialog')).getByRole('button', { name: 'Delete it and what uses it' }));
    expect(findObject(currentDoc()!, 'intro', 'eq')).toBeUndefined();
  });
});

describe('keyboard shortcuts', () => {
  afterEach(() => {
    window.removeEventListener('keydown', handleShortcut);
  });

  const key = (init: KeyboardEventInit, target: EventTarget = document.body) => {
    const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
    Object.defineProperty(event, 'target', { value: target });
    act(() => handleShortcut(event));
    return event;
  };

  it('undoes, redoes, duplicates and deletes', () => {
    useEditor.setState({ selection: { kind: 'object', sceneId: 'intro', id: 'axes' } });
    key({ key: 'd', ctrlKey: true });
    expect(findObject(currentDoc()!, 'intro', 'axes_2')).toBeDefined();
    key({ key: 'z', ctrlKey: true });
    expect(findObject(currentDoc()!, 'intro', 'axes_2')).toBeUndefined();
    key({ key: 'z', ctrlKey: true, shiftKey: true });
    expect(findObject(currentDoc()!, 'intro', 'axes_2')).toBeDefined();
    act(() => select({ kind: 'object', sceneId: 'intro', id: 'axes_2' }));
    key({ key: 'Delete' });
    expect(findObject(currentDoc()!, 'intro', 'axes_2')).toBeUndefined();
    key({ key: 'y', metaKey: true });
    expect(findObject(currentDoc()!, 'intro', 'axes_2')).toBeUndefined();
  });

  it('nudges the selected object with the arrows, further with Shift', () => {
    useEditor.setState({ selection: { kind: 'object', sceneId: 'intro', id: 'axes' } });
    key({ key: 'ArrowRight' });
    key({ key: 'ArrowUp', shiftKey: true });
    expect(findObject(currentDoc()!, 'intro', 'axes')!.place).toEqual({ at: [0.1, 1] });
  });

  it('leaves keys alone while typing, but undo still works', () => {
    useEditor.setState({ selection: { kind: 'object', sceneId: 'intro', id: 'axes' } });
    const input = document.createElement('input');
    const before = currentDoc();
    key({ key: 'Delete' }, input);
    key({ key: 'ArrowRight' }, input);
    expect(currentDoc()).toBe(before);
    expect(isTyping(input)).toBe(true);
    expect(isTyping(document.createElement('button'))).toBe(false);
  });

  it('steps through frames, deselects and opens help', () => {
    act(() => select({ kind: 'step', sceneId: 'intro', id: 'intro_2' }));
    key({ key: ']' });
    expect(useEditor.getState().selection.id).toBe('intro_3');
    key({ key: 'Escape' });
    expect(useEditor.getState().selection.kind).toBe('scene');
    key({ key: '?' });
    expect(useEditor.getState().modal).toBe('shortcuts');
    // With a dialog open, shortcuts wait
    const before = currentDoc();
    key({ key: 'd', ctrlKey: true });
    expect(currentDoc()).toBe(before);
  });
});

describe('the problems panel', () => {
  const problems: Problem[] = [
    { message: "'c^2' doesn't appear in 'eq'", severity: 'error', loc: ['scenes', 0, 'steps', 2, 'part'], path: 'scenes[0].steps[2].part', scene_id: 'intro', item_id: 'intro_3' },
    { message: "'plane' is already on screen", severity: 'warning', loc: ['scenes', 0, 'steps', 0, 'target'], path: '', scene_id: 'intro', item_id: 'intro_1' },
    { message: 'Bad step index', severity: 'error', loc: ['step_index'], path: '', scene_id: null, item_id: null },
  ];

  it('counts problems and lists them, errors first, leaving out request problems', async () => {
    useEditor.setState({ saveProblems: problems });
    render(<ProblemsPanel />);
    const header = screen.getByRole('button', { name: /Problems/ });
    expect(header).toHaveTextContent('1 error');
    expect(header).toHaveTextContent('1 warning');
    await userEvent.click(header);
    const items = screen.getAllByTestId('problem-item');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("'c^2' doesn't appear in 'eq'");
    expect(items[0]).toHaveTextContent('intro › step 3 › part');
  });

  it('goes to the field a problem is about', async () => {
    useEditor.setState({ saveProblems: problems, problemsOpen: true });
    const { container } = render(<><ProblemsPanel /><PropertiesPanel /></>);
    await userEvent.click(screen.getAllByTestId('problem-item')[0]!);
    expect(useEditor.getState().selection).toEqual({ kind: 'step', sceneId: 'intro', id: 'intro_3' });
    await act(() => new Promise((r) => requestAnimationFrame(() => r(null))));
    expect(document.activeElement).toBe(container.querySelector('.field[data-name="part"] input'));
  });

  it('says so when all is well', () => {
    render(<ProblemsPanel />);
    expect(screen.getByRole('button', { name: /Problems/ })).toHaveTextContent('None');
  });
});

describe('the top bar', () => {
  it('shows the save state', () => {
    render(<SaveStatus />);
    expect(screen.getByTestId('save-status')).toHaveTextContent('Saved');
    act(() => useEditor.setState({ saveState: 'conflict' }));
    expect(screen.getByTestId('save-status')).toHaveTextContent('Conflict');
    act(() => useEditor.setState({ saveState: 'error', saveMessage: 'Not saved yet' }));
    expect(screen.getByTestId('save-status')).toHaveTextContent('Not saved');
  });

  it('edits the title and undoes it', async () => {
    render(<TopBar />);
    const title = screen.getByRole('textbox', { name: 'Video title' });
    await userEvent.clear(title);
    await userEvent.type(title, 'Right triangles');
    expect(currentDoc()!.title).toBe('Right triangles');
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(currentDoc()!.title).toBe('Pythagoras');
    expect(screen.getByRole('button', { name: 'Redo' })).toBeEnabled();
  });

  it('explains why a scene without steps has nothing to preview', async () => {
    setupEditor({ version: 1, title: 'T', scenes: [{ id: 'blank' }] });
    render(<TopBar />);
    await userEvent.click(screen.getByRole('button', { name: /Preview/ }));
    expect(useEditor.getState().toasts.at(-1)?.message).toMatch(/add a step first/);
  });

  it('switches themes', async () => {
    render(<TopBar />);
    await userEvent.click(screen.getByRole('button', { name: 'Switch to the light theme' }));
    expect(useEditor.getState().theme).toBe('light');
  });

  it('offers a way out of a conflict', () => {
    useEditor.setState({ conflict: { document: null, revision: 3 } });
    render(<ConflictBanner />);
    expect(screen.getByTestId('conflict-banner')).toHaveTextContent('changed somewhere else');
    expect(screen.getByRole('button', { name: 'Load their version' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Keep mine' })).toBeEnabled();
  });
});

describe('menus and dialogs', () => {
  it('moves through a menu with the arrows and closes on Escape', async () => {
    const picked: string[] = [];
    render(<Menu label="Things" buttonLabel="Add" entries={['a', 'b', 'c'].map((k) => ({ key: k, label: k.toUpperCase(), onSelect: () => picked.push(k) }))} />);
    await userEvent.click(screen.getByRole('button', { name: /Add/ }));
    await act(() => new Promise((r) => requestAnimationFrame(() => r(null))));
    await userEvent.keyboard('{ArrowUp}');
    expect(document.activeElement).toHaveTextContent('C');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Add/ }));
    await userEvent.click(screen.getByRole('button', { name: /Add/ }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'B' }));
    expect(picked).toEqual(['b']);
  });

  it('keeps focus inside a dialog and closes it with Escape', async () => {
    let confirmed = false;
    useEditor.setState({ confirm: { title: 'Sure?', message: 'Really', confirmLabel: 'Yes', onConfirm: () => (confirmed = true) } });
    render(<ConfirmDialog />);
    const dialog = screen.getByRole('dialog', { name: 'Sure?' });
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Yes' }));
    await userEvent.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(confirmed).toBe(false);
  });
});
