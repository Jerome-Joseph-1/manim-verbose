/**
 * The properties panel draws the right input for every field of every kind of object and
 * step in the schema, edits write the right values, and problems show under their fields.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { PropertiesPanel, applicableFields } from './PropertiesPanel';
import { objectFields, stepFields, type FieldSpec, type WidgetKind } from '../lib/schema';
import { catalogFromSchema, fillObjectTemplate, fillStepTemplate } from '../lib/templates';
import { findObject, findStep } from '../doc/ops';
import type { Document, Problem, Scene } from '../doc/types';
import { schemaIndex } from '../test/fixtures';
import { editorDoc, setupEditor } from '../test/editor';
import { useEditor } from '../state/store';

const catalog = catalogFromSchema(schemaIndex);

/** A scene with something of every kind a reference might need. */
function baseScene(): Scene {
  return {
    id: 's',
    objects: [
      { id: 'plane', type: 'number_plane' },
      { id: 'ax', type: 'axes' },
      { id: 'words', type: 'text', text: 'Hello' },
      { id: 'formula', type: 'tex', tex: 'x^2' },
    ],
    steps: [{ id: 's_1', do: 'show', target: ['plane', 'words'] }],
  };
}

function docWithObject(type: string): Document {
  const scene = baseScene();
  const template = catalog.objects.find((o) => o.type === type)!.template;
  const filled = fillObjectTemplate(schemaIndex, template, { scene, frameIndex: 0, selectedObjectId: 'formula' });
  scene.objects!.push({ ...filled, id: 'thing' } as Scene['objects'] extends (infer T)[] | undefined ? T : never);
  return { version: 1, title: 'Test', scenes: [scene] };
}

function docWithStep(kind: string): Document {
  const scene = baseScene();
  const template = catalog.steps.find((s) => s.do === kind)!.template;
  const filled = fillStepTemplate(schemaIndex, template, { scene, frameIndex: 0, selectedObjectId: 'words' });
  scene.steps!.push({ ...filled, id: 'the_step', ...(kind === 'together' ? { steps: (filled.steps as object[]).map((s, i) => ({ ...s, id: `inner_${i}` })) } : {}) } as never);
  return { version: 1, title: 'Test', scenes: [scene] };
}

/** What each kind of field has to render as. */
const CONTROLS: Record<WidgetKind, (el: HTMLElement) => void> = {
  id: (el) => expect(el.querySelector('input.mono')).not.toBeNull(),
  text: (el) => expect(el.querySelector('input[type="text"]')).not.toBeNull(),
  multiline: (el) => expect(el.querySelector('textarea')).not.toBeNull(),
  tex: (el) => expect(el.querySelector('textarea.mono')).not.toBeNull(),
  expression: (el) => expect(el.querySelector('input.mono')).not.toBeNull(),
  number: (el) => expect(el.querySelector('input[type="number"]')).not.toBeNull(),
  boolean: (el) => expect(el.querySelector('input[type="checkbox"]')).not.toBeNull(),
  enum: (el) => expect(el.querySelector('select, [role="radiogroup"]')).not.toBeNull(),
  color: (el) => {
    expect(el.querySelector('button.swatch-btn')).not.toBeNull();
    expect(el.querySelector('input[type="text"]')).not.toBeNull();
  },
  point: (el) => expect(el.querySelectorAll('input[type="number"]').length).toBeGreaterThanOrEqual(2),
  range: (el) => expect(el.querySelectorAll('input[type="number"]').length).toBe(3),
  'number-list': (el) => expect(el.querySelectorAll('input[type="number"]').length).toBeGreaterThanOrEqual(2),
  'object-ref': (el) => expect(el.querySelector('select')).not.toBeNull(),
  targets: (el) => expect(el.querySelector('select')).not.toBeNull(),
  'ref-list': (el) => expect(el.querySelector('select')).not.toBeNull(),
  // A placement, or for a move by an offset, the button to move to a place instead
  placement: (el) =>
    expect(el.querySelectorAll('[role="radiogroup"] [role="radio"]').length === 4 || within(el).queryByRole('button', { name: /move to a place/i }) !== null).toBe(true),
  'color-map': (el) => expect(within(el).getByRole('button', { name: /color it/i })).toBeTruthy(),
  'color-list': (el) => expect(within(el).getByRole('button', { name: /add a color/i })).toBeTruthy(),
  matrix: (el) => expect(el.querySelectorAll('.matrix-grid input').length).toBeGreaterThanOrEqual(1),
  'number-matrix': (el) => expect(el.querySelectorAll('.matrix-grid input').length).toBe(4),
  'string-list': (el) => expect(el.querySelectorAll('input').length).toBeGreaterThanOrEqual(1),
  'point-list': (el) => expect(el.querySelectorAll('input[type="number"]').length).toBeGreaterThanOrEqual(6),
  properties: (el) => expect(el.querySelector('select')).not.toBeNull(),
  steps: (el) => expect(el.querySelectorAll('.nested').length).toBeGreaterThanOrEqual(2),
  file: (el) => expect(el.querySelector('input.mono')).not.toBeNull(),
  object: (el) => expect(el.querySelector('.sub-fields')).not.toBeNull(),
  json: (el) => expect(el.querySelector('textarea')).not.toBeNull(),
  choice: (el) => expect(el.querySelectorAll('[role="radiogroup"] [role="radio"]').length).toBeGreaterThanOrEqual(2),
  part: (el) => expect(el.querySelector('input[type="text"], select')).not.toBeNull(),
  carry: (el) => expect(el.querySelector('fieldset, .field-help')).not.toBeNull(),
};

function fieldEl(container: HTMLElement, name: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`.field[data-name="${name}"]`);
  if (!el) throw new Error(`no field ${name}`);
  return el;
}

function checkFields(container: HTMLElement, fields: FieldSpec[]) {
  for (const spec of fields) {
    const el = fieldEl(container, spec.name);
    expect(el.dataset.kind, spec.name).toBe(spec.kind);
    CONTROLS[spec.kind](el);
  }
}

describe('every kind of object', () => {
  it.each(schemaIndex.objectKinds.map((k) => [k.name, k.label]))('%s (%s) gets an input for each field', (type, label) => {
    setupEditor(docWithObject(type), { selection: { kind: 'object', sceneId: 's', id: 'thing' } });
    const { container } = render(<PropertiesPanel />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(label);
    const obj = editorDoc().scenes[0]!.objects!.find((o) => o.id === 'thing')!;
    checkFields(container, applicableFields(obj, objectFields(schemaIndex, type)));
  });
});

describe('every kind of step', () => {
  it.each(schemaIndex.stepKinds.map((k) => [k.name, k.label]))('%s (%s) gets an input for each field', (kind, label) => {
    setupEditor(docWithStep(kind), { selection: { kind: 'step', sceneId: 's', id: 'the_step' } });
    const { container } = render(<PropertiesPanel />);
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(`${label} step`);
    checkFields(container, stepFields(schemaIndex, kind));
  });
});

describe('editing', () => {
  function editText(): { container: HTMLElement } {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'thing' } });
    return render(<PropertiesPanel />);
  }
  const thing = () => findObject(editorDoc(), 's', 'thing')!;

  it('writes typed text, as one undo step', async () => {
    const { container } = editText();
    const box = fieldEl(container, 'text').querySelector('textarea')!;
    await userEvent.clear(box);
    await userEvent.type(box, 'New words');
    expect(thing().text).toBe('New words');
    expect(useEditor.getState().history!.past.length).toBe(1);
  });

  it('writes numbers within their limits only', async () => {
    const { container } = editText();
    const input = fieldEl(container, 'font_size').querySelector('input')!;
    await userEvent.clear(input);
    expect('font_size' in thing()).toBe(false);
    await userEvent.type(input, '60');
    expect(thing().font_size).toBe(60);
    // Out of range: said beside the field, and not written
    fireEvent.change(input, { target: { value: '-1' } });
    expect(thing().font_size).toBe(60);
    expect(fieldEl(container, 'font_size')).toHaveTextContent('Has to be more than 0');
    // Emptied: back to the default
    await userEvent.clear(input);
    expect('font_size' in thing()).toBe(false);
  });

  it('toggles booleans, leaving defaults out', async () => {
    const { container } = editText();
    const box = fieldEl(container, 'bold').querySelector('input')!;
    await userEvent.click(box);
    expect(thing().bold).toBe(true);
    await userEvent.click(box);
    expect('bold' in thing()).toBe(false);
  });

  it('picks from a short list of choices', async () => {
    const { container } = editText();
    await userEvent.click(within(fieldEl(container, 'align')).getByRole('radio', { name: 'Left' }));
    expect(thing().align).toBe('left');
    await userEvent.click(within(fieldEl(container, 'align')).getByRole('radio', { name: 'Center' }));
    expect('align' in thing()).toBe(false);
  });

  it('picks colors from the palette or typed', async () => {
    const { container } = editText();
    const field = fieldEl(container, 'color');
    await userEvent.click(within(field).getByRole('button', { name: /pick from manim's colors/ }));
    await userEvent.click(within(field).getByRole('button', { name: 'Red E' }));
    expect(thing().color).toBe('RED_E');
    const input = field.querySelector<HTMLInputElement>('input[type="text"]')!;
    await userEvent.clear(input);
    await userEvent.type(input, '#123456');
    expect(thing().color).toBe('#123456');
    await userEvent.clear(input);
    await userEvent.type(input, 'blu');
    expect(thing().color).toBeUndefined();
    expect(field).toHaveTextContent('Not a color yet');
    await userEvent.clear(input);
    await userEvent.type(input, 'blue');
    expect(thing().color).toBe('BLUE');
  });

  it('places an object against an edge, beside another, or at a point on a system', async () => {
    const { container } = editText();
    const field = () => fieldEl(container, 'place');
    await userEvent.click(within(field()).getByRole('radio', { name: 'Edge' }));
    expect(thing().place).toEqual({ edge: 'top' });
    await userEvent.click(within(field()).getByRole('button', { name: 'Bottom left' }));
    expect(thing().place).toEqual({ edge: 'bottom_left' });
    await userEvent.click(within(field()).getByRole('radio', { name: 'Next to' }));
    expect(thing().place).toEqual({ next_to: 'plane' });
    await userEvent.selectOptions(within(field()).getByRole('combobox', { name: /beside which object/ }), 'formula');
    await userEvent.click(within(field()).getByRole('radio', { name: 'Right' }));
    expect(thing().place).toEqual({ next_to: 'formula', side: 'right' });
    await userEvent.click(within(field()).getByRole('radio', { name: 'Point' }));
    expect(thing().place).toEqual({ at: [0, 0] });
    await userEvent.selectOptions(within(field()).getByRole('combobox', { name: /coordinates of/ }), 'plane');
    expect(thing().place).toEqual({ at: [0, 0], on: 'plane' });
    await userEvent.click(within(field()).getByRole('radio', { name: 'Centre' }));
    expect(thing().place).toBeUndefined();
  });

  it('adds and removes colored parts', async () => {
    const { container } = editText();
    const field = fieldEl(container, 'colors');
    await userEvent.type(within(field).getByRole('textbox', { name: /new part/ }), 'Hel');
    await userEvent.click(within(field).getByRole('button', { name: /color it/i }));
    expect(thing().colors).toEqual({ Hel: 'YELLOW' });
    await userEvent.click(within(fieldEl(container, 'colors')).getByRole('button', { name: 'Remove colored part Hel' }));
    expect('colors' in thing()).toBe(false);
  });

  it('renames an object, updating the steps which use it', async () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'words' } });
    const { container } = render(<PropertiesPanel />);
    const input = fieldEl(container, 'id').querySelector('input')!;
    await userEvent.clear(input);
    await userEvent.type(input, 'greeting{Enter}');
    expect(findObject(editorDoc(), 's', 'greeting')).toBeDefined();
    expect(findStep(editorDoc(), 's', 's_1')!.target).toEqual(['plane', 'greeting']);
    expect(useEditor.getState().selection.id).toBe('greeting');
  });

  it('refuses a taken name, saying why', async () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'words' } });
    const { container } = render(<PropertiesPanel />);
    const input = fieldEl(container, 'id').querySelector('input')!;
    await userEvent.clear(input);
    await userEvent.type(input, 'formula{Enter}');
    expect(fieldEl(container, 'id')).toHaveTextContent("There's already an object called 'formula'");
    expect(findObject(editorDoc(), 's', 'words')).toBeDefined();
  });

  it('edits the objects a step acts on', async () => {
    setupEditor(docWithStep('show'), { selection: { kind: 'step', sceneId: 's', id: 's_1' } });
    const { container } = render(<PropertiesPanel />);
    const step = () => findStep(editorDoc(), 's', 's_1')!;
    await userEvent.click(within(fieldEl(container, 'target')).getByRole('button', { name: 'Remove plane from Object' }));
    expect(step().target).toBe('words');
    await userEvent.selectOptions(within(fieldEl(container, 'target')).getByRole('combobox'), 'formula');
    expect(step().target).toEqual(['words', 'formula']);
  });

  it('writes a caption', async () => {
    setupEditor(docWithStep('show'), { selection: { kind: 'step', sceneId: 's', id: 's_1' } });
    const { container } = render(<PropertiesPanel />);
    await userEvent.type(fieldEl(container, 'caption').querySelector('textarea')!, 'Look at this');
    expect(findStep(editorDoc(), 's', 's_1')!.caption).toBe('Look at this');
  });

  it('picks what a change step changes from the target kind', async () => {
    setupEditor(docWithStep('change'), { selection: { kind: 'step', sceneId: 's', id: 'the_step' } });
    const { container } = render(<PropertiesPanel />);
    const step = () => findStep(editorDoc(), 's', 'the_step')!;
    expect(step().target).toBe('words');
    const set = fieldEl(container, 'set');
    await userEvent.selectOptions(within(set).getByRole('combobox', { name: /add a property of the text to change/i }), 'text');
    expect(step().set).toEqual({ color: 'YELLOW', text: 'Hello' });
    // The new value gets the input its field has on a text object
    expect(fieldEl(container, 'set').querySelector('.field[data-name="text"] textarea')).not.toBeNull();
    await userEvent.click(within(fieldEl(container, 'set')).getByRole('button', { name: 'Stop changing color' }));
    expect(step().set).toEqual({ text: 'Hello' });
  });

  it('adds a step inside together', async () => {
    setupEditor(docWithStep('together'), { selection: { kind: 'step', sceneId: 's', id: 'the_step' } });
    const { container } = render(<PropertiesPanel />);
    await userEvent.selectOptions(within(fieldEl(container, 'steps')).getByRole('combobox', { name: /add a step to run at the same time/i }), 'hide');
    const inner = findStep(editorDoc(), 's', 'the_step')!.steps as { do: string; id: string }[];
    expect(inner.map((s) => s.do)).toEqual(['show', 'show', 'hide']);
    expect(new Set(inner.map((s) => s.id)).size).toBe(3);
  });

  it('edits the video settings', async () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'document', sceneId: null, id: null } });
    const { container } = render(<PropertiesPanel />);
    const fps = container.querySelector<HTMLInputElement>('.field[data-name="fps"] input')!;
    await userEvent.clear(fps);
    await userEvent.type(fps, '60');
    expect(editorDoc().settings).toEqual({ fps: 60 });
  });

  it('shows the defaults a schema leaves to default_factory', () => {
    setupEditor(docWithObject('number_plane'), { selection: { kind: 'object', sceneId: 's', id: 'thing' } });
    const { container } = render(<PropertiesPanel />);
    const inputs = [...fieldEl(container, 'x_range').querySelectorAll('input')].map((i) => i.value);
    expect(inputs).toEqual(['-8', '8', '1']);
  });
});

describe('problems beside their fields', () => {
  const problems: Problem[] = [
    { message: "LaTeX couldn't compile this formula", severity: 'error', loc: ['scenes', 0, 'objects', 3, 'tex'], path: '', scene_id: 's', item_id: 'formula' },
    { message: "'formula' isn't on screen at this point", severity: 'warning', loc: ['scenes', 0, 'steps', 0, 'target'], path: '', scene_id: 's', item_id: 's_1' },
    { message: 'About the whole object', severity: 'error', loc: ['scenes', 0, 'objects', 3], path: '', scene_id: 's', item_id: 'formula' },
    { message: 'Somewhere else', severity: 'error', loc: ['scenes', 0, 'objects', 2, 'text'], path: '', scene_id: 's', item_id: 'words' },
  ];

  it('puts an object problem under its field, and none of the others', () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'formula' }, problems });
    const { container } = render(<PropertiesPanel />);
    expect(fieldEl(container, 'tex')).toHaveTextContent("LaTeX couldn't compile this formula");
    expect(fieldEl(container, 'tex')).toHaveClass('has-error');
    expect(container.querySelector('.props-body')).toHaveTextContent('About the whole object');
    expect(container).not.toHaveTextContent('Somewhere else');
    expect(fieldEl(container, 'tex').querySelector('textarea')).toHaveAttribute('aria-invalid', 'true');
  });

  it('puts a step warning under its field', () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'step', sceneId: 's', id: 's_1' }, problems });
    const { container } = render(<PropertiesPanel />);
    expect(fieldEl(container, 'target')).toHaveTextContent("'formula' isn't on screen at this point");
    expect(fieldEl(container, 'target')).not.toHaveClass('has-error');
  });

  it('shows problems from a render beside the field too', () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'formula' } });
    act(() => useEditor.setState({ renderProblems: { s: [problems[0]!] } }));
    const { container } = render(<PropertiesPanel />);
    expect(fieldEl(container, 'tex')).toHaveTextContent("LaTeX couldn't compile");
  });

  it('focuses the field a problem is about when asked', async () => {
    setupEditor(docWithObject('text'), { selection: { kind: 'object', sceneId: 's', id: 'words' }, problems });
    const { container } = render(<PropertiesPanel />);
    const { requestFocus } = await import('../state/store');
    act(() => requestFocus({ kind: 'object', sceneId: 's', itemId: 'formula' }, ['tex']));
    await act(() => new Promise((r) => requestAnimationFrame(() => r(null))));
    expect(document.activeElement).toBe(fieldEl(container, 'tex').querySelector('textarea'));
  });
});

describe('nothing selected', () => {
  it('explains what to do', () => {
    setupEditor(docWithObject('text'));
    render(<PropertiesPanel />);
    expect(screen.getByText('Nothing selected')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /video settings/i }));
    expect(useEditor.getState().selection.kind).toBe('document');
  });
});
