/**
 * The inputs for the newer fields: parts of objects, carrying objects over, anchors and
 * following in a placement, a transform's keep, a brace between points, pictures uploaded.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fc from 'fast-check';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PropertiesPanel } from '../PropertiesPanel';
import { formatMatrixPart, parseMatrixPart } from './extra';
import { acceptFor } from './basic';
import { findObject, findStep } from '../../doc/ops';
import type { Document } from '../../doc/types';
import { serverStorage, setStorage } from '../../doc/storage';
import { ApiError } from '../../lib/api';
import { editorDoc, setupEditor } from '../../test/editor';
import { undo, useEditor } from '../../state/store';

function doc(): Document {
  return {
    version: 1,
    title: 'Parts',
    scenes: [
      {
        id: 'one',
        objects: [
          { id: 'plane', type: 'number_plane' },
          { id: 'v', type: 'vector', on: 'plane', tip: [2, 1] },
          { id: 'seg', type: 'line', start: [0, 0], end: [1, 0] },
          { id: 'm', type: 'matrix', entries: [[1, 2, 3], [4, 5, 6]] },
          { id: 'eq', type: 'tex', tex: 'a^2 + b^2 = c^2' },
          { id: 'circ', type: 'circle' },
          { id: 'box', type: 'box', target: 'm' },
          { id: 'lab', type: 'text', text: 'v', place: { next_to: 'v', anchor: 'tip' } },
          { id: 'br', type: 'brace', target: 'eq' },
        ],
        steps: [
          { id: 'one_1', do: 'show', target: ['plane', 'v', 'm', 'eq'] },
          { id: 'one_2', do: 'highlight', target: 'eq', part: 'c^2' },
          { id: 'one_3', do: 'transform', target: 'eq', into: 'lab' },
        ],
      },
      { id: 'two', carry: ['plane'], objects: [{ id: 'w', type: 'vector', on: 'plane', tip: [1, 1] }] },
    ],
  };
}

function open(selection: { kind: 'object' | 'step' | 'scene'; sceneId: string; id: string | null }) {
  setupEditor(doc(), { selection });
  return render(<PropertiesPanel />);
}

function field(container: HTMLElement, name: string): HTMLElement {
  return container.querySelector<HTMLElement>(`.field[data-name="${name}"]`)!;
}

afterEach(() => {
  setStorage(serverStorage);
});

describe('parts of a matrix', () => {
  it('reads and writes rows, columns and entries, counting from 1', () => {
    expect(parseMatrixPart('row 2')).toEqual({ kind: 'row', row: 2, column: 1 });
    expect(parseMatrixPart('Column 3')).toEqual({ kind: 'column', row: 1, column: 3 });
    expect(parseMatrixPart('entry 2, 1')).toEqual({ kind: 'entry', row: 2, column: 1 });
    expect(parseMatrixPart('entry 2')).toBeNull();
    expect(parseMatrixPart('row 1 2')).toBeNull();
    expect(parseMatrixPart('x')).toBeNull();
    fc.assert(
      fc.property(fc.constantFrom('row', 'column', 'entry'), fc.integer({ min: 1, max: 20 }), fc.integer({ min: 1, max: 20 }), (kind, row, column) => {
        const part = { kind: kind as 'row' | 'column' | 'entry', row: kind === 'column' ? 1 : row, column: kind === 'row' ? 1 : column };
        expect(parseMatrixPart(formatMatrixPart(part))).toEqual(part);
      }),
    );
  });

  it('are picked from lists sized to the matrix, or by clicking an entry', async () => {
    const { container } = open({ kind: 'object', sceneId: 'one', id: 'box' });
    const part = field(container, 'part');
    const kind = within(part).getByRole('combobox', { name: /which part of m/ });
    await userEvent.selectOptions(kind, 'row');
    expect(findObject(editorDoc(), 'one', 'box')!.part).toBe('row 1');
    const rows = within(part).getByRole('combobox', { name: 'Row' });
    expect(within(rows).getAllByRole('option')).toHaveLength(2);
    await userEvent.selectOptions(rows, '2');
    expect(findObject(editorDoc(), 'one', 'box')!.part).toBe('row 2');
    await userEvent.selectOptions(kind, 'column');
    expect(within(within(part).getByRole('combobox', { name: 'Column' })).getAllByRole('option')).toHaveLength(3);
    expect(findObject(editorDoc(), 'one', 'box')!.part).toBe('column 1');
    await userEvent.click(within(part).getByRole('button', { name: 'Entry 2 3: 6' }));
    expect(findObject(editorDoc(), 'one', 'box')!.part).toBe('entry 2 3');
    expect(within(part).getByRole('button', { name: 'Entry 2 3: 6' })).toHaveClass('picked');
    await userEvent.selectOptions(kind, 'all');
    expect(findObject(editorDoc(), 'one', 'box')!.part).toBeUndefined();
  });
});

describe('parts of text', () => {
  it('show where the part is in the text, and say when it is not there', async () => {
    const { container } = open({ kind: 'step', sceneId: 'one', id: 'one_2' });
    const part = field(container, 'part');
    expect(part.querySelector('mark')).toHaveTextContent('c^2');
    const input = within(part).getByRole('textbox');
    await userEvent.clear(input);
    await userEvent.type(input, 'd^2');
    expect(findStep(editorDoc(), 'one', 'one_2')!.part).toBe('d^2');
    expect(part).toHaveTextContent("“d^2” doesn't appear in eq");
    expect(part.querySelector('mark')).toBeNull();
    await userEvent.click(within(part).getByRole('button', { name: 'All of it' }));
    expect(findStep(editorDoc(), 'one', 'one_2')!.part).toBeUndefined();
  });

  it('picks out the text selected in the preview', async () => {
    const { container } = open({ kind: 'step', sceneId: 'one', id: 'one_2' });
    const part = field(container, 'part');
    const text = part.querySelector('.part-text')!;
    // Select "b^2" in the preview, as dragging over it would
    const node = text.firstChild!;
    const range = document.createRange();
    range.setStart(node, 6);
    range.setEnd(node, 9);
    window.getSelection()!.removeAllRanges();
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(text);
    await userEvent.click(within(part).getByRole('button', { name: 'Pick out the selected text' }));
    expect(findStep(editorDoc(), 'one', 'one_2')!.part).toBe('b^2');
  });

  it('asks for a selection first', async () => {
    const { container } = open({ kind: 'step', sceneId: 'one', id: 'one_2' });
    window.getSelection()!.removeAllRanges();
    await userEvent.click(within(field(container, 'part')).getByRole('button', { name: 'Pick out the selected text' }));
    expect(field(container, 'part')).toHaveTextContent('Select some of eq');
  });

  it('explains which kinds of object have parts', () => {
    const d = doc();
    d.scenes[0]!.steps![1] = { id: 'one_2', do: 'highlight', target: 'circ' };
    setupEditor(d, { selection: { kind: 'step', sceneId: 'one', id: 'one_2' } });
    const { container } = render(<PropertiesPanel />);
    expect(field(container, 'part')).toHaveTextContent('circ is a circle');
  });
});

describe('carrying objects over', () => {
  it('offers the objects of the scene before, and carries what they are built on too', async () => {
    const { container } = open({ kind: 'scene', sceneId: 'two', id: null });
    const carry = field(container, 'carry');
    const boxes = within(carry).getAllByRole('checkbox');
    expect(boxes.map((b) => b.closest('label')!.querySelector('.mono')!.textContent)).toEqual(['plane', 'v', 'seg', 'm', 'eq', 'circ', 'box', 'lab', 'br']);
    await userEvent.click(within(carry).getByRole('checkbox', { name: /^lab/ }));
    // lab is beside v, which is on the plane
    expect(editorDoc().scenes[1]!.carry).toEqual(['plane', 'v', 'lab']);
    // Leaving out the plane leaves out what is built on it
    await userEvent.click(within(carry).getByRole('checkbox', { name: /^plane/ }));
    expect(editorDoc().scenes[1]!.carry).toBeUndefined();
  });

  it("marks objects which aren't on screen when the scene before ends", () => {
    const { container } = open({ kind: 'scene', sceneId: 'two', id: null });
    const row = within(field(container, 'carry')).getByRole('checkbox', { name: /^seg/ }).closest('label')!;
    expect(row).toHaveTextContent('hidden there');
  });

  it('has nothing to offer in the first scene', () => {
    const { container } = open({ kind: 'scene', sceneId: 'one', id: null });
    expect(field(container, 'carry')).toHaveTextContent('The first scene has no scene before it');
  });

  it('lets references in the scene name carried objects', () => {
    const { container } = open({ kind: 'object', sceneId: 'two', id: 'w' });
    const on = within(field(container, 'on')).getByRole('combobox');
    expect(within(on).getByRole('option', { name: /plane/ })).toBeInTheDocument();
  });

  it('shows where a carried object comes from when it is selected', async () => {
    open({ kind: 'object', sceneId: 'two', id: 'plane' });
    expect(screen.getByTestId('carried-note')).toHaveTextContent('Carried over from scene one');
    await userEvent.click(screen.getByRole('button', { name: /Edit it in scene one/ }));
    expect(useEditor.getState().selection).toEqual({ kind: 'object', sceneId: 'one', id: 'plane' });
  });
});

describe('beside part of an object', () => {
  it('offers a vector tip and tail, a line ends, and nothing more for other objects', async () => {
    const { container } = open({ kind: 'object', sceneId: 'one', id: 'lab' });
    const place = field(container, 'place');
    const anchors = within(place).getByRole('radiogroup', { name: /beside which part/ });
    expect(within(anchors).getAllByRole('radio').map((r) => r.textContent)).toEqual(['Whole object', 'Its tip', 'Its tail']);
    expect(within(anchors).getByRole('radio', { name: 'Its tip' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(anchors).getByRole('radio', { name: 'Its tail' }));
    expect(findObject(editorDoc(), 'one', 'lab')!.place).toMatchObject({ next_to: 'v', anchor: 'tail' });
    // A line has a start and an end
    await userEvent.selectOptions(within(place).getByRole('combobox', { name: /beside which object/ }), 'seg');
    expect(findObject(editorDoc(), 'one', 'lab')!.place).toEqual({ next_to: 'seg' });
    expect(within(within(place).getByRole('radiogroup', { name: /beside which part/ })).getAllByRole('radio').map((r) => r.textContent)).toEqual(['Whole object', 'Its start', 'Its end']);
    // A circle has neither
    await userEvent.selectOptions(within(place).getByRole('combobox', { name: /beside which object/ }), 'circ');
    expect(within(place).queryByRole('radiogroup', { name: /beside which part/ })).toBeNull();
  });

  it('keeps an object beside another as it moves, if asked', async () => {
    const { container } = open({ kind: 'object', sceneId: 'one', id: 'lab' });
    await userEvent.click(within(field(container, 'place')).getByRole('checkbox', { name: 'Follow it as it moves' }));
    expect(findObject(editorDoc(), 'one', 'lab')!.place).toMatchObject({ follow: true });
    // Neither means anything without next_to
    await userEvent.click(within(field(container, 'place')).getByRole('radio', { name: 'Edge' }));
    expect(findObject(editorDoc(), 'one', 'lab')!.place).toEqual({ edge: 'top' });
  });
});

describe('keeping the original of a transform', () => {
  it('is no, yes or dimmed', async () => {
    const { container } = open({ kind: 'step', sceneId: 'one', id: 'one_3' });
    const keep = within(field(container, 'keep')).getByRole('radiogroup');
    expect(within(keep).getAllByRole('radio').map((r) => r.textContent)).toEqual(['No', 'Yes', 'Yes, dimmed']);
    expect(within(keep).getByRole('radio', { name: 'No' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(keep).getByRole('radio', { name: 'Yes, dimmed' }));
    expect(findStep(editorDoc(), 'one', 'one_3')!.keep).toBe('dim');
    await userEvent.click(within(keep).getByRole('radio', { name: 'Yes' }));
    expect(findStep(editorDoc(), 'one', 'one_3')!.keep).toBe(true);
    await userEvent.click(within(keep).getByRole('radio', { name: 'No' }));
    expect(findStep(editorDoc(), 'one', 'one_3')!.keep).toBeUndefined();
  });
});

describe('a brace', () => {
  it('goes around an object, or between two points', async () => {
    const { container } = open({ kind: 'object', sceneId: 'one', id: 'br' });
    expect(field(container, 'target')).not.toBeNull();
    expect(field(container, 'start')).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Between two points' }));
    expect(findObject(editorDoc(), 'one', 'br')).toEqual({ id: 'br', type: 'brace', start: [-2, -1], end: [2, -1] });
    expect(field(container, 'target')).toBeNull();
    expect(field(container, 'start')).not.toBeNull();
    expect(field(container, 'on')).not.toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Around an object' }));
    expect(findObject(editorDoc(), 'one', 'br')).toMatchObject({ target: 'eq' });
    expect(findObject(editorDoc(), 'one', 'br')!.start).toBeUndefined();
    // One undo step each
    act(() => undo());
    expect(findObject(editorDoc(), 'one', 'br')!.start).toEqual([-2, -1]);
  });
});

describe('the video description', () => {
  it('is a field of the video settings', async () => {
    setupEditor(doc(), { selection: { kind: 'document', sceneId: null, id: null } });
    const { container } = render(<PropertiesPanel />);
    await userEvent.type(within(field(container, 'description')).getByRole('textbox'), 'About vectors');
    expect(editorDoc().description).toBe('About vectors');
  });
});

describe('pictures', () => {
  const imageDoc = (): Document => ({ version: 1, title: 'P', scenes: [{ id: 's', objects: [{ id: 'pic', type: 'image', path: 'old.png' }] }] });

  it('can be uploaded into an image field', async () => {
    const upload = vi.fn(async () => ({ path: 'assets/cat.png', kind: 'png' }));
    setStorage({ ...serverStorage, uploadAsset: upload });
    setupEditor(imageDoc(), { selection: { kind: 'object', sceneId: 's', id: 'pic' } });
    const { container } = render(<PropertiesPanel />);
    const input = container.querySelector<HTMLInputElement>('[data-testid="upload-input"]')!;
    expect(input.accept).toBe(acceptFor('image/*'));
    const file = new File(['png'], 'cat.png', { type: 'image/png' });
    await userEvent.upload(input, file);
    expect(upload).toHaveBeenCalledWith(file, 'cat.png');
    await screen.findByDisplayValue('assets/cat.png');
    expect(findObject(editorDoc(), 's', 'pic')!.path).toBe('assets/cat.png');
  });

  it('says why an upload was refused', async () => {
    setStorage({ ...serverStorage, uploadAsset: vi.fn(async () => { throw new ApiError(415, { problems: [{ message: "That isn't a picture", severity: 'error', loc: ['file'] }] }); }) });
    setupEditor(imageDoc(), { selection: { kind: 'object', sceneId: 's', id: 'pic' } });
    const { container } = render(<PropertiesPanel />);
    await userEvent.upload(container.querySelector<HTMLInputElement>('[data-testid="upload-input"]')!, new File(['x'], 'x.png', { type: 'image/png' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("That isn't a picture");
    expect(findObject(editorDoc(), 's', 'pic')!.path).toBe('old.png');
  });

  it('have no upload button where there is nowhere to keep them', () => {
    const { uploadAsset: _unused, ...withoutUploads } = serverStorage;
    void _unused;
    setStorage(withoutUploads);
    setupEditor(imageDoc(), { selection: { kind: 'object', sceneId: 's', id: 'pic' } });
    render(<PropertiesPanel />);
    expect(screen.queryByTestId('upload-file')).toBeNull();
  });

  it('accept only drawings in an svg field', () => {
    expect(acceptFor('.svg')).toBe('.svg,image/svg+xml');
    expect(acceptFor('image/*')).toContain('image/png');
  });
});
