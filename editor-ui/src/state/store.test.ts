import { beforeEach, describe, expect, it } from 'vitest';
import {
  allProblems, apply, currentDoc, currentSceneId, endEditBurst, frameStepIndex, redo, requestFocus, select, setFrameStep, undo, useEditor,
} from './store';
import {
  addNewScene, addObjectFrom, addStepFrom, deleteSelection, duplicateSelection, nudgeSelection, placeObjectAt, removeStepById,
  requestRemoveObject, requestRemoveScene, showObjects, stepFrame, translatePoints,
} from './actions';
import { findObject, findStep, renameObject, setItemField } from '../doc/ops';
import { invariantViolations } from '../doc/check';
import { catalogFromSchema } from '../lib/templates';
import { sampleDoc, schemaIndex } from '../test/fixtures';
import { setupEditor } from '../test/editor';

const catalog = catalogFromSchema(schemaIndex);
const entry = (type: string) => catalog.objects.find((o) => o.type === type)!;
const stepEntry = (kind: string) => catalog.steps.find((s) => s.do === kind)!;

beforeEach(() => {
  setupEditor(sampleDoc());
});

describe('edits and history', () => {
  it('undoes and redoes edits, restoring the exact document', () => {
    const start = currentDoc();
    apply((d) => renameObject(d, 'intro', 'eq', 'formula'));
    apply((d) => setItemField(d, { kind: 'object', sceneId: 'intro', id: 'formula' }, ['color'], 'RED'));
    const end = currentDoc();
    undo();
    undo();
    expect(currentDoc()).toBe(start);
    redo();
    redo();
    expect(currentDoc()).toBe(end);
  });

  it('refuses an impossible edit without changing anything, and says why', () => {
    const start = currentDoc();
    expect(apply((d) => renameObject(d, 'intro', 'eq', 'label'))).toBe(false);
    expect(currentDoc()).toBe(start);
    expect(useEditor.getState().toasts.at(-1)?.message).toMatch(/already an object called 'label'/);
  });

  it('merges typing into one step until the field is left', () => {
    const title = (t: string) => apply((d) => setItemField(d, { kind: 'document' }, ['title'], t), { key: 'title' });
    title('a');
    title('ab');
    expect(useEditor.getState().history!.past.length).toBe(1);
    endEditBurst();
    title('abc');
    expect(useEditor.getState().history!.past.length).toBe(2);
  });

  it('drops a selection which undo made point at nothing', () => {
    addObjectFrom(entry('circle'));
    expect(useEditor.getState().selection).toMatchObject({ kind: 'object', id: 'circle' });
    undo();
    expect(useEditor.getState().selection).toMatchObject({ kind: null, sceneId: 'intro' });
  });
});

describe('selection and the frame shown', () => {
  it('shows the end of the scene until a step is chosen', () => {
    expect(currentSceneId()).toBe('intro');
    // intro has ten steps at the top level
    expect(frameStepIndex(useEditor.getState(), 'intro')).toBe(9);
    select({ kind: 'step', sceneId: 'intro', id: 'intro_3' });
    expect(frameStepIndex(useEditor.getState(), 'intro')).toBe(2);
    setFrameStep('intro', null);
    expect(frameStepIndex(useEditor.getState(), 'intro')).toBe(-1);
  });

  it('shows the whole together step when one of its steps is chosen', () => {
    select({ kind: 'step', sceneId: 'intro', id: 'intro_10' });
    expect(frameStepIndex(useEditor.getState(), 'intro')).toBe(7);
  });

  it('steps the frame back and forth', () => {
    select({ kind: 'step', sceneId: 'intro', id: 'intro_2' });
    stepFrame(1);
    expect(useEditor.getState().selection.id).toBe('intro_3');
    stepFrame(-1);
    stepFrame(-1);
    stepFrame(-1);
    expect(frameStepIndex(useEditor.getState(), 'intro')).toBe(-1);
  });

  it('selects the item a problem is about, to focus its field', () => {
    requestFocus({ kind: 'step', sceneId: 'intro', itemId: 'intro_4' }, ['into']);
    expect(useEditor.getState().selection).toEqual({ kind: 'step', sceneId: 'intro', id: 'intro_4' });
    expect(useEditor.getState().focusRequest?.field).toEqual(['into']);
  });

  it('merges problems from saving and rendering, once each', () => {
    const p = { message: 'm', severity: 'error' as const, loc: ['x'], path: 'x', scene_id: null, item_id: null };
    useEditor.setState({ saveProblems: [p], renderProblems: { intro: [{ ...p }] } });
    expect(allProblems(useEditor.getState())).toHaveLength(1);
  });
});

describe('user actions', () => {
  it('adds an object with a fresh name and selects it', () => {
    const id = addObjectFrom(entry('tex'));
    expect(id).toBe('equation');
    expect(findObject(currentDoc()!, 'intro', 'equation')).toBeDefined();
    expect(useEditor.getState().selection).toEqual({ kind: 'object', sceneId: 'intro', id: 'equation' });
  });

  it('adds a step after the frame shown, showing the selected object', () => {
    select({ kind: 'step', sceneId: 'intro', id: 'intro_1' });
    select({ kind: 'object', sceneId: 'intro', id: 'axes' });
    const id = addStepFrom(stepEntry('show'))!;
    const steps = currentDoc()!.scenes[0]!.steps!;
    expect(steps[1]).toEqual({ id, do: 'show', target: 'axes' });
    expect(useEditor.getState().selection).toEqual({ kind: 'step', sceneId: 'intro', id });
  });

  it("won't add what the server couldn't read: a step or a brace with nothing to act on", () => {
    setupEditor({ version: 1, title: 'T', scenes: [{ id: 'empty' }] });
    const before = currentDoc();
    expect(addStepFrom(stepEntry('show'))).toBeNull();
    expect(addObjectFrom(entry('brace'))).toBeNull();
    expect(addObjectFrom(entry('graph'))).toBeNull();
    expect(currentDoc()).toBe(before);
    expect(useEditor.getState().toasts.at(-1)?.message).toBe('Function graph goes with another object (a set of axes or a number plane); add that first');
    // Steps which act on nothing are fine
    expect(addStepFrom(stepEntry('wait'))).not.toBeNull();
  });

  it('adds a step showing objects not on screen', () => {
    setFrameStep('intro', null);
    showObjects(['dot', 'axes']);
    expect(currentDoc()!.scenes[0]!.steps![0]).toMatchObject({ do: 'show', target: ['dot', 'axes'] });
  });

  it('asks before deleting an object other things use, then deletes what depends on it', () => {
    requestRemoveObject('intro', 'eq');
    const confirm = useEditor.getState().confirm!;
    expect(confirm.title).toBe("Delete 'eq'?");
    expect(confirm.message).toMatch(/Steps 3, 4, 6, 8, which only act on it, will be deleted; steps 2, 5, 7 will stop using it/);
    confirm.onConfirm();
    expect(findObject(currentDoc()!, 'intro', 'eq')).toBeUndefined();
    expect(invariantViolations(currentDoc()!, { references: true })).toEqual([]);
  });

  it('can delete only the object, leaving references for the user', () => {
    requestRemoveObject('intro', 'eq');
    useEditor.getState().confirm!.onAlt!();
    expect(findObject(currentDoc()!, 'intro', 'eq')).toBeUndefined();
    expect(findStep(currentDoc()!, 'intro', 'intro_3')).toBeDefined();
  });

  it('deletes an unused object at once', () => {
    addObjectFrom(entry('circle'));
    deleteSelection();
    expect(useEditor.getState().confirm).toBeNull();
    expect(findObject(currentDoc()!, 'intro', 'circle')).toBeUndefined();
  });

  it('deletes a step and selects the next one', () => {
    removeStepById('intro', 'intro_2');
    expect(findStep(currentDoc()!, 'intro', 'intro_2')).toBeUndefined();
    expect(useEditor.getState().selection.id).toBe('intro_3');
  });

  it('duplicates whatever is selected', () => {
    select({ kind: 'object', sceneId: 'intro', id: 'eq' });
    duplicateSelection();
    expect(useEditor.getState().selection.id).toBe('eq_2');
    select({ kind: 'step', sceneId: 'intro', id: 'intro_1' });
    duplicateSelection();
    expect(useEditor.getState().selection.id).toBe('intro_13');
    select({ kind: 'scene', sceneId: 'second', id: null });
    duplicateSelection();
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro', 'second', 'second_2']);
  });

  it('asks before deleting a scene, and never deletes the last', () => {
    requestRemoveScene('second');
    useEditor.getState().confirm!.onConfirm();
    expect(currentDoc()!.scenes.map((s) => s.id)).toEqual(['intro']);
    useEditor.setState({ confirm: null });
    requestRemoveScene('intro');
    expect(useEditor.getState().confirm).toBeNull();
    expect(currentDoc()!.scenes).toHaveLength(1);
  });

  it('adds scenes', () => {
    addNewScene();
    expect(useEditor.getState().selection).toEqual({ kind: 'scene', sceneId: 'scene_1', id: null });
  });

  it('nudges a placed object from where it is', () => {
    select({ kind: 'object', sceneId: 'intro', id: 'label' });
    useEditor.setState({ still: { sceneId: 'intro', stepIndex: 11, width: 960, height: 540, objects: [{ id: 'label', bbox: [0, 0, 10, 10], frame_bbox: [1, 1, 3, 2] }] } });
    nudgeSelection(0.1, 0);
    expect(findObject(currentDoc()!, 'intro', 'label')!.place).toEqual({ at: [2.1, 1.5] });
    nudgeSelection(0, -1);
    expect(findObject(currentDoc()!, 'intro', 'label')!.place).toEqual({ at: [2.1, 0.5] });
    // A run of nudges is one undo step
    undo();
    expect(findObject(currentDoc()!, 'intro', 'label')!.place).toEqual({ next_to: 'eq', side: 'down' });
  });

  it('moves objects given by points by moving their points', () => {
    apply((d) => setItemField(d, { kind: 'object', sceneId: 'intro', id: 'dot' }, ['on'], undefined));
    expect(translatePoints('intro', 'dot', 1, -0.5)).toBe(true);
    expect(findObject(currentDoc()!, 'intro', 'dot')!.point).toEqual([2, 1.5]);
    // ...but not while they are on a coordinate system
    apply((d) => setItemField(d, { kind: 'object', sceneId: 'intro', id: 'dot' }, ['on'], 'plane'));
    expect(translatePoints('intro', 'dot', 1, 0)).toBe(false);
  });

  it('writes a drag as a point in frame units, dropping any coordinate system', () => {
    apply((d) => setItemField(d, { kind: 'object', sceneId: 'intro', id: 'label' }, ['place'], { at: [1, 1], on: 'plane' }));
    placeObjectAt('intro', 'label', [1.234, -2.345]);
    expect(findObject(currentDoc()!, 'intro', 'label')!.place).toEqual({ at: [1.23, -2.35] });
  });
});
