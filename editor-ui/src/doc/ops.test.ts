import { describe, expect, it } from 'vitest';
import {
  DocOpError, addNestedStep, addObject, addScene, addStep, duplicateObject, duplicateScene, duplicateStep,
  ensureStepIds, findObject, findScene, findStep, findStepPath, itemLoc, moveObject, moveScene, moveStep,
  planObjectRemoval, removeObject, removeScene, removeStep, renameItem, renameObject, renameScene, renameStep,
  setField, setItemField,
} from './ops';
import { invariantViolations } from './check';
import { findReferences } from './refs';
import type { Document, Step } from './types';
import { sampleDoc } from '../test/fixtures';

function scene(doc: Document, id = 'intro') {
  const s = findScene(doc, id);
  if (!s) throw new Error(`no scene ${id}`);
  return s;
}

function stepById(doc: Document, id: string, sceneId = 'intro'): Step {
  const step = findStep(doc, sceneId, id);
  if (!step) throw new Error(`no step ${id}`);
  return step;
}

describe('immutability', () => {
  it('never changes the document it is given', () => {
    const doc = sampleDoc();
    const before = JSON.stringify(doc);
    renameObject(doc, 'intro', 'eq', 'formula');
    removeObject(doc, 'intro', 'eq', { cascade: true });
    addObject(doc, 'intro', { type: 'circle' });
    duplicateScene(doc, 'intro');
    setField(doc, ['scenes', 0, 'objects', 1, 'tex'], 'x');
    expect(JSON.stringify(doc)).toBe(before);
  });

  it('returns the same document when nothing changes', () => {
    const doc = sampleDoc();
    expect(setField(doc, ['scenes', 0, 'objects', 1, 'tex'], 'a^2 + b^2 = c^2')).toBe(doc);
    expect(renameObject(doc, 'intro', 'eq', 'eq')).toBe(doc);
    expect(moveStep(doc, 'intro', 2, 2)).toBe(doc);
  });
});

describe('scenes', () => {
  it('adds a scene with a fresh id', () => {
    const { doc, sceneId } = addScene(sampleDoc());
    expect(sceneId).toBe('scene_1');
    expect(doc.scenes.at(-1)).toEqual({ id: 'scene_1' });
    const again = addScene(doc);
    expect(again.sceneId).toBe('scene_2');
  });

  it('adds a scene at an index with a title', () => {
    const { doc } = addScene(sampleDoc(), { id: 'middle', title: 'Middle', index: 1 });
    expect(doc.scenes.map((s) => s.id)).toEqual(['intro', 'middle', 'second']);
    expect(doc.scenes[1]!.title).toBe('Middle');
  });

  it('refuses a taken or invalid scene id', () => {
    expect(() => addScene(sampleDoc(), { id: 'intro' })).toThrow(DocOpError);
    expect(() => addScene(sampleDoc(), { id: '1bad' })).toThrow(/can't be a name/);
  });

  it('removes a scene but never the last one', () => {
    const doc = removeScene(sampleDoc(), 'second');
    expect(doc.scenes.map((s) => s.id)).toEqual(['intro']);
    expect(() => removeScene(doc, 'intro')).toThrow(/at least one scene/);
    expect(() => removeScene(doc, 'nope')).toThrow(/no scene/);
  });

  it('duplicates a scene with new step ids, keeping object ids', () => {
    const { doc, sceneId } = duplicateScene(sampleDoc(), 'intro');
    expect(sceneId).toBe('intro_2');
    expect(doc.scenes.map((s) => s.id)).toEqual(['intro', 'intro_2', 'second']);
    const copy = scene(doc, 'intro_2');
    expect(copy.title).toBe('Introduction (copy)');
    expect(copy.objects!.map((o) => o.id)).toEqual(scene(doc).objects!.map((o) => o.id));
    expect(invariantViolations(doc, { references: true })).toEqual([]);
    // nested steps got new ids too
    const together = copy.steps!.find((s) => s.do === 'together')!;
    expect((together.steps as Step[]).every((s) => s.id!.startsWith('intro_2_'))).toBe(true);
  });

  it('renames a scene', () => {
    const doc = renameScene(sampleDoc(), 'intro', 'opening');
    expect(doc.scenes[0]!.id).toBe('opening');
    expect(() => renameScene(doc, 'opening', 'second')).toThrow(/already a scene/);
  });

  it('reorders scenes', () => {
    const doc = moveScene(sampleDoc(), 0, 1);
    expect(doc.scenes.map((s) => s.id)).toEqual(['second', 'intro']);
    expect(moveScene(doc, 1, 99).scenes.map((s) => s.id)).toEqual(['second', 'intro']);
  });
});

describe('objects', () => {
  it('adds an object from a template with a fresh id, id and type first', () => {
    const { doc, id } = addObject(sampleDoc(), 'intro', { type: 'tex', tex: 'x^2' });
    expect(id).toBe('equation');
    const obj = findObject(doc, 'intro', 'equation')!;
    expect(Object.keys(obj).slice(0, 2)).toEqual(['id', 'type']);
    expect(obj.tex).toBe('x^2');
    const second = addObject(doc, 'intro', { type: 'tex', tex: 'y' });
    expect(second.id).toBe('equation_2');
  });

  it('ignores an id in the template, and accepts one given explicitly', () => {
    const { id } = addObject(sampleDoc(), 'intro', { type: 'circle', id: 'eq' });
    expect(id).toBe('circle');
    const named = addObject(sampleDoc(), 'intro', { type: 'circle' }, { id: 'sun', index: 0 });
    expect(scene(named.doc).objects![0]!.id).toBe('sun');
    expect(() => addObject(sampleDoc(), 'intro', { type: 'circle' }, { id: 'eq' })).toThrow(/already an object called 'eq'/);
  });

  it('adds the first object to an empty scene', () => {
    const { doc } = addScene(sampleDoc(), { id: 'empty' });
    const result = addObject(doc, 'empty', { type: 'text', text: 'Hi' });
    expect(scene(result.doc, 'empty').objects).toEqual([{ id: 'text', type: 'text', text: 'Hi' }]);
  });

  it('duplicates an object next to the original', () => {
    const { doc, id } = duplicateObject(sampleDoc(), 'intro', 'eq');
    expect(id).toBe('eq_2');
    const ids = scene(doc).objects!.map((o) => o.id);
    expect(ids.indexOf('eq_2')).toBe(ids.indexOf('eq') + 1);
    expect(findObject(doc, 'intro', 'eq_2')!.tex).toBe('a^2 + b^2 = c^2');
    const again = duplicateObject(doc, 'intro', 'eq_2');
    expect(again.id).toBe('eq_3');
  });

  it('reorders objects', () => {
    const doc = moveObject(sampleDoc(), 'intro', 0, 2);
    expect(scene(doc).objects!.slice(0, 3).map((o) => o.id)).toEqual(['eq', 'label', 'plane']);
  });
});

describe('renaming an object', () => {
  it('updates every reference in the scene', () => {
    const doc = renameObject(sampleDoc(), 'intro', 'eq', 'formula');
    const s = scene(doc);
    expect(findObject(doc, 'intro', 'formula')).toBeDefined();
    expect(findObject(doc, 'intro', 'eq')).toBeUndefined();
    // place.next_to, brace target, group members
    expect(findObject(doc, 'intro', 'label')!.place).toEqual({ next_to: 'formula', side: 'down' });
    expect(findObject(doc, 'intro', 'brace')!.target).toBe('formula');
    expect(findObject(doc, 'intro', 'group')!.members).toEqual(['formula', 'label']);
    // step target (list and single), into, focus, move.to.next_to, change set, nested together
    expect(stepById(doc, 'intro_2').target).toEqual(['formula', 'label']);
    expect(stepById(doc, 'intro_3').target).toBe('formula');
    expect(stepById(doc, 'intro_4').into).toBe('formula');
    expect(stepById(doc, 'intro_5').focus).toBe('formula');
    expect(stepById(doc, 'intro_6').to).toEqual({ next_to: 'formula', side: 'right' });
    expect(stepById(doc, 'intro_7').set).toEqual({ color: 'RED', place: { next_to: 'formula' } });
    expect(stepById(doc, 'intro_10').target).toBe('formula');
    expect(findReferences(s, 'eq')).toEqual([]);
    expect(invariantViolations(doc, { references: true })).toEqual([]);
  });

  it('updates `on` references to coordinate systems', () => {
    let doc = renameObject(sampleDoc(), 'intro', 'plane', 'grid');
    expect(findObject(doc, 'intro', 'dot')!.on).toBe('grid');
    expect(stepById(doc, 'intro_1').target).toBe('grid');
    doc = renameObject(doc, 'intro', 'axes', 'ax');
    expect(findObject(doc, 'intro', 'graph')!.on).toBe('ax');
  });

  it('leaves other scenes alone', () => {
    const doc = renameObject(sampleDoc(), 'intro', 'eq', 'formula');
    expect(findObject(doc, 'second', 'eq')).toBeDefined();
    expect(stepById(doc, 'second_1', 'second').target).toBe('eq');
  });

  it('refuses a name already taken or not valid', () => {
    expect(() => renameObject(sampleDoc(), 'intro', 'eq', 'label')).toThrow(/already an object called 'label'/);
    expect(() => renameObject(sampleDoc(), 'intro', 'eq', 'my eq')).toThrow(/can't be a name/);
    expect(() => renameObject(sampleDoc(), 'intro', 'nope', 'x')).toThrow(/no object called 'nope'/);
  });

  it('can take a name used in another scene', () => {
    const doc = renameObject(sampleDoc(), 'second', 'eq', 'plane');
    expect(findObject(doc, 'second', 'plane')).toBeDefined();
  });
});

describe('placements on a coordinate system', () => {
  function doc(): Document {
    return {
      scenes: [
        {
          id: 's',
          objects: [
            { id: 'plane', type: 'number_plane' },
            { id: 'lbl', type: 'tex', tex: 'v', place: { at: [1, 2], on: 'plane' } },
          ],
          steps: [
            { id: 's_1', do: 'show', target: ['plane', 'lbl'] },
            { id: 's_2', do: 'move', target: 'lbl', to: { at: [3, 1], on: 'plane' } },
          ],
        },
      ],
    };
  }

  it('renames place.on and move.to.on', () => {
    const next = renameObject(doc(), 's', 'plane', 'grid');
    expect(findObject(next, 's', 'lbl')!.place).toEqual({ at: [1, 2], on: 'grid' });
    expect(findStep(next, 's', 's_2')!.to).toEqual({ at: [3, 1], on: 'grid' });
    expect(invariantViolations(next, { references: true })).toEqual([]);
  });

  it('drops `on` (keeping `at`, now in frame units) when the system is removed', () => {
    const next = removeObject(doc(), 's', 'plane', { cascade: true });
    expect(findObject(next, 's', 'lbl')!.place).toEqual({ at: [1, 2] });
    expect(findStep(next, 's', 's_2')!.to).toEqual({ at: [3, 1] });
    expect(findStep(next, 's', 's_1')!.target).toEqual(['lbl']);
    expect(invariantViolations(next, { references: true })).toEqual([]);
    const plan = planObjectRemoval(doc(), 's', 'plane');
    expect(plan.editedObjects).toEqual(['lbl']);
    expect(plan.editedSteps).toEqual(['s_1', 's_2']);
  });
});

describe('removing an object', () => {
  it('reports what uses it', () => {
    const plan = planObjectRemoval(sampleDoc(), 'intro', 'eq');
    expect(plan.objects.sort()).toEqual(['brace', 'eq'].sort());
    // intro_2 loses eq from its list; intro_8 loses the highlight but keeps showing brace... which goes too
    expect(plan.steps).toEqual(expect.arrayContaining(['intro_3', 'intro_4', 'intro_6', 'intro_8']));
    expect(plan.editedSteps).toEqual(expect.arrayContaining(['intro_2', 'intro_5', 'intro_7']));
    expect(plan.editedObjects).toEqual(expect.arrayContaining(['label', 'group']));
    // Uses are reported by top level step: the highlight inside together intro_8 counts as intro_8
    expect(plan.uses.map((u) => u.itemId)).toEqual(
      ['label', 'brace', 'group', 'intro_2', 'intro_3', 'intro_4', 'intro_5', 'intro_6', 'intro_7', 'intro_8'],
    );
    expect(plan.uses.find((u) => u.itemId === 'intro_8')!.path).toEqual(['steps', 1, 'target']);
  });

  it('without cascade removes only the object', () => {
    const doc = removeObject(sampleDoc(), 'intro', 'eq');
    expect(findObject(doc, 'intro', 'eq')).toBeUndefined();
    expect(findObject(doc, 'intro', 'brace')!.target).toBe('eq');
    expect(stepById(doc, 'intro_3').target).toBe('eq');
    expect(invariantViolations(doc)).toEqual([]);
    expect(invariantViolations(doc, { references: true }).length).toBeGreaterThan(0);
  });

  it('with cascade leaves no dangling reference', () => {
    const doc = removeObject(sampleDoc(), 'intro', 'eq', { cascade: true });
    expect(invariantViolations(doc, { references: true })).toEqual([]);
    const s = scene(doc);
    expect(s.objects!.map((o) => o.id)).toEqual(['plane', 'label', 'dot', 'group', 'axes', 'graph']);
    expect(findObject(doc, 'intro', 'label')!.place).toBeUndefined();
    expect(findObject(doc, 'intro', 'group')!.members).toEqual(['label']);
    expect(stepById(doc, 'intro_2').target).toEqual(['label']);
    expect(findStep(doc, 'intro', 'intro_3')).toBeUndefined();
    expect(findStep(doc, 'intro', 'intro_4')).toBeUndefined();
    expect(stepById(doc, 'intro_5')).toEqual({ id: 'intro_5', do: 'camera', zoom: 2 });
    expect(findStep(doc, 'intro', 'intro_6')).toBeUndefined();
    expect(stepById(doc, 'intro_7').set).toEqual({ color: 'RED' });
    // the together lost both its steps (brace went with eq), so it went too
    expect(findStep(doc, 'intro', 'intro_8')).toBeUndefined();
  });

  it('unwraps a together left with one step', () => {
    let doc = sampleDoc();
    doc = setField(doc, ['scenes', 0, 'steps', 7, 'caption'], 'Both at once');
    doc = removeObject(doc, 'intro', 'brace', { cascade: true });
    const unwrapped = stepById(doc, 'intro_10');
    expect(unwrapped).toEqual({ id: 'intro_10', do: 'highlight', target: 'eq', caption: 'Both at once' });
    expect(scene(doc).steps!.some((s) => s.do === 'together')).toBe(false);
  });

  it('removes a group whose members all go, and graphs on removed axes', () => {
    let doc = removeObject(sampleDoc(), 'intro', 'axes', { cascade: true });
    expect(findObject(doc, 'intro', 'graph')).toBeUndefined();
    doc = removeObject(doc, 'intro', 'label', { cascade: true });
    doc = removeObject(doc, 'intro', 'eq', { cascade: true });
    expect(findObject(doc, 'intro', 'group')).toBeUndefined();
    expect(invariantViolations(doc, { references: true })).toEqual([]);
  });

  it('drops the optional `on` of a plotted object', () => {
    const doc = removeObject(sampleDoc(), 'intro', 'plane', { cascade: true });
    expect(findObject(doc, 'intro', 'dot')).toEqual({ id: 'dot', type: 'dot', point: [1, 2] });
    expect(findStep(doc, 'intro', 'intro_1')).toBeUndefined();
  });

  it('removes the objects list when the last object goes', () => {
    const doc = removeObject(sampleDoc(), 'second', 'eq', { cascade: true });
    expect(scene(doc, 'second')).toEqual({ id: 'second' });
  });
});

describe('steps', () => {
  it('adds a step with the next free id', () => {
    const { doc, id } = addStep(sampleDoc(), 'intro', { do: 'show', target: 'axes' });
    expect(id).toBe('intro_13');
    expect(scene(doc).steps!.at(-1)).toEqual({ id: 'intro_13', do: 'show', target: 'axes' });
  });

  it('fills gaps in step numbering and inserts at an index', () => {
    const doc = removeStep(sampleDoc(), 'intro', 'intro_3');
    const { doc: next, id } = addStep(doc, 'intro', { do: 'wait' }, { index: 0 });
    expect(id).toBe('intro_3');
    expect(scene(next).steps![0]!.id).toBe('intro_3');
  });

  it('gives nested steps of a template ids too', () => {
    const { doc } = addStep(sampleDoc(), 'second', {
      do: 'together',
      steps: [{ do: 'show', target: 'eq' }, { do: 'wait' }],
    });
    expect(invariantViolations(doc)).toEqual([]);
    const added = scene(doc, 'second').steps!.at(-1)!;
    expect((added.steps as Step[]).map((s) => s.id)).toEqual(['second_3', 'second_4']);
  });

  it('adds a step inside a together', () => {
    const { doc, id } = addNestedStep(sampleDoc(), 'intro', 'intro_8', { do: 'show', target: 'axes' });
    expect(findStepPath(scene(doc).steps, id)).toEqual([7, 'steps', 2]);
    expect(() => addNestedStep(sampleDoc(), 'intro', 'intro_1', { do: 'wait' })).toThrow(/together/);
  });

  it('duplicates a step (and its nested steps) with new ids', () => {
    const { doc, id } = duplicateStep(sampleDoc(), 'intro', 'intro_8');
    expect(id).toBe('intro_13');
    const copy = stepById(doc, id);
    expect((copy.steps as Step[]).map((s) => s.id)).toEqual(['intro_14', 'intro_15']);
    expect(scene(doc).steps![8]!.id).toBe('intro_13');
    expect(invariantViolations(doc)).toEqual([]);
  });

  it('duplicates a nested step inside its together', () => {
    const { doc, id } = duplicateStep(sampleDoc(), 'intro', 'intro_9');
    expect(findStepPath(scene(doc).steps, id)).toEqual([7, 'steps', 1]);
  });

  it('removes steps, top level and nested', () => {
    let doc = removeStep(sampleDoc(), 'intro', 'intro_1');
    expect(findStep(doc, 'intro', 'intro_1')).toBeUndefined();
    doc = removeStep(doc, 'intro', 'intro_9');
    expect((stepById(doc, 'intro_8').steps as Step[]).map((s) => s.id)).toEqual(['intro_10']);
    doc = removeStep(doc, 'second', 'second_1');
    expect(scene(doc, 'second').steps).toBeUndefined();
    expect(() => removeStep(doc, 'intro', 'nope')).toThrow(/no step/);
  });

  it('reorders steps', () => {
    const doc = moveStep(sampleDoc(), 'intro', 0, 3);
    expect(scene(doc).steps!.slice(0, 4).map((s) => s.id)).toEqual(['intro_2', 'intro_3', 'intro_4', 'intro_1']);
    const back = moveStep(doc, 'intro', 3, 0);
    expect(back.scenes[0]!.steps).toEqual(sampleDoc().scenes[0]!.steps);
  });

  it('renames a step, keeping ids unique across scenes', () => {
    const doc = renameStep(sampleDoc(), 'intro', 'intro_1', 'show_plane');
    expect(stepById(doc, 'show_plane').target).toBe('plane');
    expect(() => renameStep(doc, 'intro', 'intro_2', 'second_1')).toThrow(/already a step/);
    const nested = renameStep(doc, 'intro', 'intro_9', 'show_brace');
    expect(findStepPath(scene(nested).steps, 'show_brace')).toEqual([7, 'steps', 0]);
  });

  it('fills in missing step ids like the server', () => {
    const doc: Document = { scenes: [{ id: 'a', steps: [{ do: 'wait' }, { id: 'a_1', do: 'clear' }, { do: 'wait' }] }] };
    const next = ensureStepIds(doc);
    expect(next.scenes[0]!.steps!.map((s) => s.id)).toEqual(['a_2', 'a_1', 'a_3']);
    expect(ensureStepIds(next)).toBe(next);
  });
});

describe('fields', () => {
  it('sets and removes a field by path', () => {
    let doc = setField(sampleDoc(), ['scenes', 0, 'objects', 1, 'color'], 'BLUE');
    expect(findObject(doc, 'intro', 'eq')!.color).toBe('BLUE');
    doc = setField(doc, ['scenes', 0, 'objects', 1, 'color'], undefined);
    expect('color' in findObject(doc, 'intro', 'eq')!).toBe(false);
  });

  it('creates nested mappings as needed and prunes empty placements', () => {
    let doc = setField(sampleDoc(), ['scenes', 0, 'objects', 0, 'place', 'at'], [1, 2]);
    expect(findObject(doc, 'intro', 'plane')!.place).toEqual({ at: [1, 2] });
    doc = setField(doc, ['scenes', 0, 'objects', 0, 'place', 'at'], undefined);
    expect('place' in findObject(doc, 'intro', 'plane')!).toBe(false);
  });

  it('prunes an emptied color map but not an emptied change set', () => {
    let doc = setField(sampleDoc(), ['scenes', 0, 'objects', 1, 'colors', 'c^2'], 'RED');
    doc = setField(doc, ['scenes', 0, 'objects', 1, 'colors', 'c^2'], undefined);
    expect('colors' in findObject(doc, 'intro', 'eq')!).toBe(false);
    doc = setField(doc, ['scenes', 0, 'steps', 6, 'set', 'color'], undefined);
    doc = setField(doc, ['scenes', 0, 'steps', 6, 'set', 'place'], undefined);
    expect(stepById(doc, 'intro_7').set).toEqual({});
  });

  it('refuses to change ids directly', () => {
    expect(() => setField(sampleDoc(), ['scenes', 0, 'objects', 1, 'id'], 'x')).toThrow(/rename/);
  });

  it('sets a field of an item by id, wherever it has moved to', () => {
    let doc = moveStep(sampleDoc(), 'intro', 2, 0);
    doc = setItemField(doc, { kind: 'step', sceneId: 'intro', id: 'intro_3' }, ['part'], 'a^2');
    expect(scene(doc).steps![0]).toEqual({ id: 'intro_3', do: 'highlight', target: 'eq', part: 'a^2' });
    doc = setItemField(doc, { kind: 'step', sceneId: 'intro', id: 'intro_10' }, ['caption'], 'Nested');
    expect(stepById(doc, 'intro_10').caption).toBe('Nested');
    doc = setItemField(doc, { kind: 'scene', sceneId: 'second' }, ['title'], 'Second');
    expect(scene(doc, 'second').title).toBe('Second');
    doc = setItemField(doc, { kind: 'document' }, ['title'], 'Renamed');
    expect(doc.title).toBe('Renamed');
    expect(() => setItemField(doc, { kind: 'object', sceneId: 'intro', id: 'ghost' }, ['x'], 1)).toThrow(DocOpError);
  });

  it('locates items', () => {
    const doc = sampleDoc();
    expect(itemLoc(doc, { kind: 'object', sceneId: 'intro', id: 'label' })).toEqual(['scenes', 0, 'objects', 2]);
    expect(itemLoc(doc, { kind: 'step', sceneId: 'intro', id: 'intro_9' })).toEqual(['scenes', 0, 'steps', 7, 'steps', 0]);
    expect(itemLoc(doc, { kind: 'scene', sceneId: 'second' })).toEqual(['scenes', 1]);
    expect(itemLoc(doc, { kind: 'document' })).toEqual([]);
    expect(itemLoc(doc, { kind: 'object', sceneId: 'nope', id: 'x' })).toBeNull();
  });

  it('renames through an item ref', () => {
    const doc = renameItem(sampleDoc(), { kind: 'object', sceneId: 'intro', id: 'eq' }, 'formula');
    expect(stepById(doc, 'intro_3').target).toBe('formula');
    expect(renameItem(doc, { kind: 'scene', sceneId: 'second' }, 'two').scenes[1]!.id).toBe('two');
    expect(() => renameItem(doc, { kind: 'document' }, 'x')).toThrow(DocOpError);
  });
});
