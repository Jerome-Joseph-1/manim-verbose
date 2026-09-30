/**
 * The canvas: it asks for stills a moment after edits, keeps only the newest answer,
 * never goes blank, and turns clicks and drags into selections and positions.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, type StillResponse } from '../lib/api';
import { defaultMapping, frameToPixel, type Box, type StillObject } from '../lib/geometry';
import { Canvas } from './Canvas';
import { apply, currentDoc, useEditor } from '../state/store';
import { findObject, setItemField } from '../doc/ops';
import type { Document } from '../doc/types';
import { setupEditor } from '../test/editor';

const mapping = defaultMapping(960, 540);

function box(id: string, frame: Box): StillObject {
  const [x0, y0] = frameToPixel(mapping, frame[0], frame[3]);
  const [x1, y1] = frameToPixel(mapping, frame[2], frame[1]);
  return { id, bbox: [x0, y0, x1, y1], frame_bbox: frame };
}

const OBJECTS = [box('plane', [-7.11, -4, 7.11, 4]), box('eq', [-1, -0.5, 1, 0.5]), box('small', [-0.25, -0.25, 0.25, 0.25])];

function still(objects = OBJECTS, url = '/files/stills/a.svg'): StillResponse {
  return { image_url: url, width: 960, height: 540, objects, problems: [] };
}

function doc(): Document {
  return {
    version: 1,
    title: 'T',
    scenes: [
      {
        id: 's',
        objects: [
          { id: 'plane', type: 'number_plane' },
          { id: 'eq', type: 'tex', tex: 'x' },
          { id: 'small', type: 'dot', point: [0, 0] },
        ],
        steps: [{ id: 's_1', do: 'show', target: ['plane', 'eq', 'small'] }],
      },
    ],
  };
}

// jsdom has no layout and loads no images: give the canvas a size, and make images load
beforeAll(() => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(992);
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600);
  vi.stubGlobal(
    'Image',
    class {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) {
        setTimeout(() => this.onload?.(), 0);
      }
    },
  );
});

afterAll(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  setupEditor(doc(), { selection: { kind: 'scene', sceneId: 's', id: null } });
});

async function renderWithStill(response: StillResponse = still()) {
  const spy = vi.spyOn(api, 'still').mockResolvedValue(response);
  const utils = render(<Canvas />);
  await waitFor(() => expect(screen.getByTestId('still')).toHaveAttribute('src', response.image_url));
  return { ...utils, spy };
}

function overlay(): HTMLElement {
  return screen.getByTestId('canvas-overlay');
}

function pointer(type: 'pointerDown' | 'pointerMove' | 'pointerUp', x: number, y: number) {
  fireEvent[type](overlay(), { clientX: x, clientY: y, button: 0, pointerId: 1 });
}

describe('the still', () => {
  it('asks for the frame after the step shown, at a width that fits', async () => {
    const { spy } = await renderWithStill();
    const call = spy.mock.calls.at(-1)![0];
    expect(call).toMatchObject({ scene_id: 's', step_index: 0, width: 960 });
    expect(call.document).toBe(currentDoc());
    expect(screen.getAllByTestId('object-box')).toHaveLength(3);
  });

  it('asks again a moment after an edit, keeping the old picture meanwhile', async () => {
    const { spy } = await renderWithStill();
    spy.mockResolvedValue(still(OBJECTS, '/files/stills/b.svg'));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], 'y'));
    });
    expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/a.svg');
    await waitFor(() => expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/b.svg'));
  });

  it('ignores an answer which a newer request has overtaken', async () => {
    const resolvers: ((r: StillResponse) => void)[] = [];
    vi.spyOn(api, 'still').mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)));
    render(<Canvas />);
    await waitFor(() => expect(resolvers).toHaveLength(1));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], 'y'));
    });
    await waitFor(() => expect(resolvers).toHaveLength(2));
    await act(async () => resolvers[1]!(still(OBJECTS, '/files/stills/new.svg')));
    await act(async () => resolvers[0]!(still(OBJECTS, '/files/stills/old.svg')));
    await waitFor(() => expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/new.svg'));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/new.svg');
  });

  it('says nothing about a superseded request', async () => {
    const { spy } = await renderWithStill();
    spy.mockRejectedValue(new ApiError(409, { superseded: true }));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], 'y'));
    });
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.queryByTestId('canvas-error')).toBeNull();
    expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/a.svg');
  });

  it("explains a picture that can't be drawn, keeps the last one, and records the problem", async () => {
    const { spy } = await renderWithStill();
    const problem = { message: "LaTeX couldn't compile this formula", severity: 'error' as const, loc: ['scenes', 0, 'objects', 1, 'tex'], path: '', scene_id: 's', item_id: 'eq' };
    spy.mockRejectedValue(new ApiError(422, { problems: [problem] }));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], '\\frac{'));
    });
    await waitFor(() => expect(screen.getByTestId('canvas-error')).toHaveTextContent("LaTeX couldn't compile this formula"));
    expect(screen.getByTestId('still')).toHaveAttribute('src', '/files/stills/a.svg');
    expect(useEditor.getState().renderProblems.s).toEqual([problem]);
  });
});

describe('a server that fails', () => {
  it('says so on the canvas, without listing it as a problem with the document', async () => {
    const { spy } = await renderWithStill();
    const problem = { message: "'d^2' doesn't appear in 'eq'", severity: 'error' as const, loc: ['scenes', 0, 'steps', 0, 'part'], path: '', scene_id: 's', item_id: 's_1' };
    spy.mockRejectedValue(new ApiError(422, { problems: [problem] }));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], 'y'));
    });
    await waitFor(() => expect(useEditor.getState().renderProblems.s).toEqual([problem]));
    // The next render fails for the server's own reasons: the old problem was about an older document
    spy.mockRejectedValue(new ApiError(500, { problems: [{ message: 'rendering a frame failed', severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] }));
    act(() => {
      apply((d) => setItemField(d, { kind: 'object', sceneId: 's', id: 'eq' }, ['tex'], 'z'));
    });
    await waitFor(() => expect(screen.getByTestId('canvas-error')).toHaveTextContent('Drawing the picture failed'));
    expect(useEditor.getState().renderProblems.s).toEqual([]);
  });
});

describe('pointing at objects', () => {
  const at = (frame: [number, number]) => frameToPixel(mapping, frame[0], frame[1]);

  it('selects the topmost object under a click, and the one beneath on a second click', async () => {
    await renderWithStill();
    const [x, y] = at([0, 0]);
    pointer('pointerDown', x, y);
    pointer('pointerUp', x, y);
    expect(useEditor.getState().selection).toEqual({ kind: 'object', sceneId: 's', id: 'small' });
    pointer('pointerDown', x, y);
    pointer('pointerUp', x, y);
    expect(useEditor.getState().selection.id).toBe('eq');
    pointer('pointerDown', x, y);
    pointer('pointerUp', x, y);
    expect(useEditor.getState().selection.id).toBe('plane');
    pointer('pointerDown', x, y);
    expect(useEditor.getState().selection.id).toBe('small');
  });

  it('highlights what the pointer is over', async () => {
    await renderWithStill();
    const [x, y] = at([0.8, 0]);
    pointer('pointerMove', x, y);
    const eq = document.querySelector('[data-testid="object-box"][data-object-id="eq"]')!;
    expect(eq).toHaveClass('hover');
    expect(eq).toHaveTextContent('eq');
  });

  it('drags an object to a new place, in frame units', async () => {
    await renderWithStill();
    const [x, y] = at([0.8, 0]);
    pointer('pointerDown', x, y);
    // one frame unit right and half a unit up
    pointer('pointerMove', x + mapping.ax, y + 0.5 * mapping.ay);
    expect(document.querySelector('[data-object-id="eq"][data-testid="object-box"]')).toHaveClass('selected');
    pointer('pointerUp', x + mapping.ax, y + 0.5 * mapping.ay);
    expect(findObject(currentDoc()!, 's', 'eq')!.place).toEqual({ at: [1, 0.5] });
  });

  it('drags a dot by moving its point', async () => {
    await renderWithStill();
    const [x, y] = at([0, 0]);
    pointer('pointerDown', x, y);
    pointer('pointerMove', x - 2 * mapping.ax, y);
    pointer('pointerUp', x - 2 * mapping.ax, y);
    expect(findObject(currentDoc()!, 's', 'small')!.point).toEqual([-2, 0]);
  });

  it('treats a tiny movement as a click, not a drag', async () => {
    await renderWithStill();
    const before = currentDoc();
    const [x, y] = at([0.8, 0]);
    pointer('pointerDown', x, y);
    pointer('pointerMove', x + 1, y + 1);
    pointer('pointerUp', x + 1, y + 1);
    expect(currentDoc()).toBe(before);
    expect(useEditor.getState().selection.id).toBe('eq');
  });

  it('deselects on a click on nothing', async () => {
    await renderWithStill(still([box('eq', [-1, -0.5, 1, 0.5])]));
    pointer('pointerDown', 5, 5);
    expect(useEditor.getState().selection).toEqual({ kind: 'scene', sceneId: 's', id: null });
  });
});

describe('first run help', () => {
  it('offers quick ways to add something to an empty scene', async () => {
    setupEditor({ version: 1, title: 'T', scenes: [{ id: 'scene_1' }] });
    vi.spyOn(api, 'still').mockResolvedValue(still([]));
    render(<Canvas />);
    expect(await screen.findByTestId('empty-scene')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Text/ }));
    const scene = currentDoc()!.scenes[0]!;
    expect(scene.objects).toHaveLength(1);
    expect(scene.steps).toEqual([{ id: 'scene_1_1', do: 'show', target: 'text' }]);
  });

  it('points out objects no step shows', async () => {
    setupEditor({ version: 1, title: 'T', scenes: [{ id: 's', objects: [{ id: 'lonely', type: 'circle' }] }] });
    vi.spyOn(api, 'still').mockResolvedValue(still([]));
    render(<Canvas />);
    const note = await screen.findByTestId('never-shown');
    expect(note).toHaveTextContent("lonely isn't shown by any step yet");
    fireEvent.click(screen.getByRole('button', { name: /Add a step showing lonely/ }));
    expect(currentDoc()!.scenes[0]!.steps).toEqual([{ id: 's_1', do: 'show', target: 'lonely' }]);
  });
});
