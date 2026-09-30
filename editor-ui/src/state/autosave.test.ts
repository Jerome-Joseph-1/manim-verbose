import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Autosaver, SAVE_DELAY_MS } from './autosave';
import { ApiError, type SaveResponse, type Timeline } from '../lib/api';
import { apply, currentDoc, undo, useEditor } from './store';
import { setItemField } from '../doc/ops';
import type { Document } from '../doc/types';
import { setupEditor } from '../test/editor';

function doc(title = 'A'): Document {
  return { version: 1, title, scenes: [{ id: 's', objects: [{ id: 'a', type: 'text', text: 'a' }], steps: [{ id: 's_1', do: 'show', target: 'a' }] }] };
}

interface FakeApi {
  putDocument: ReturnType<typeof vi.fn>;
  timeline: ReturnType<typeof vi.fn>;
}

function fakeApi(): FakeApi {
  let revision = 1;
  return {
    putDocument: vi.fn(async (document: Document, base: number): Promise<SaveResponse> => {
      if (base !== revision) throw new ApiError(409, { document: doc('Theirs'), revision, problems: [] });
      revision += 1;
      return { revision, problems: [], document };
    }),
    timeline: vi.fn(async (): Promise<Timeline> => ({ steps: [{ step_id: 's_1', index: 0, start: 0, duration: 2 }], duration: 2 })),
  };
}

const retitle = (title: string) => apply((d) => setItemField(d, { kind: 'document' }, ['title'], title), { key: 'title' });

describe('autosave', () => {
  let api: FakeApi;
  let saver: Autosaver;

  beforeEach(() => {
    vi.useFakeTimers();
    setupEditor(doc());
    api = fakeApi();
    saver = new Autosaver(api as never);
    saver.start();
  });

  afterEach(() => {
    saver.stop();
    vi.useRealTimers();
  });

  it('saves once a burst of edits stops, with the revision it was based on', async () => {
    retitle('B');
    retitle('Bo');
    retitle('Bob');
    expect(useEditor.getState().saveState).toBe('unsaved');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS - 100);
    expect(api.putDocument).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(200);
    expect(api.putDocument).toHaveBeenCalledTimes(1);
    expect(api.putDocument.mock.calls[0]![0].title).toBe('Bob');
    expect(api.putDocument.mock.calls[0]![1]).toBe(1);
    expect(useEditor.getState()).toMatchObject({ saveState: 'saved', revision: 2 });
    expect(useEditor.getState().timelines.s?.duration).toBe(2);
  });

  it('saves again after edits made while saving', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const real = api.putDocument.getMockImplementation() as (document: Document, base: number) => Promise<SaveResponse>;
    api.putDocument.mockImplementationOnce(async (document: Document, base: number) => {
      await gate;
      return real(document, base);
    });
    retitle('B');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState().saveState).toBe('saving');
    retitle('C');
    release();
    await vi.advanceTimersByTimeAsync(0);
    expect(useEditor.getState().saveState).toBe('unsaved');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(api.putDocument).toHaveBeenCalledTimes(2);
    expect(api.putDocument.mock.calls[1]![0].title).toBe('C');
    expect(api.putDocument.mock.calls[1]![1]).toBe(2);
    expect(useEditor.getState().saveState).toBe('saved');
  });

  it("takes the server's canonical form without an undo step", async () => {
    api.putDocument.mockImplementationOnce(async (document: Document) => ({ revision: 2, problems: [], document: { ...document, title: 'Canonical' } }));
    retitle('B');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(currentDoc()!.title).toBe('Canonical');
    expect(useEditor.getState().history!.past.length).toBe(1);
    expect(useEditor.getState().saveState).toBe('saved');
  });

  it('keeps problems from the save', async () => {
    const problems = [{ message: 'x', severity: 'warning' as const, loc: [], path: '', scene_id: null, item_id: null }];
    api.putDocument.mockImplementationOnce(async (document: Document) => ({ revision: 2, problems, document }));
    retitle('B');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState().saveProblems).toEqual(problems);
  });

  it('shows a conflict, and can keep ours', async () => {
    api.putDocument.mockImplementationOnce(async () => {
      throw new ApiError(409, { document: doc('Theirs'), revision: 5, problems: [] });
    });
    retitle('Mine');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState().saveState).toBe('conflict');
    expect(useEditor.getState().conflict?.revision).toBe(5);
    // Edits during a conflict wait for the choice
    retitle('Mine 2');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 3);
    expect(api.putDocument).toHaveBeenCalledTimes(1);
    api.putDocument.mockImplementationOnce(async (document: Document, base: number) => ({ revision: base + 1, problems: [], document }));
    await saver.keepMine();
    expect(api.putDocument.mock.calls[1]![1]).toBe(5);
    expect(api.putDocument.mock.calls[1]![0].title).toBe('Mine 2');
    expect(useEditor.getState()).toMatchObject({ saveState: 'saved', revision: 6, conflict: null });
  });

  it('can take theirs after a conflict, undoably', async () => {
    api.putDocument.mockImplementationOnce(async () => {
      throw new ApiError(409, { document: doc('Theirs'), revision: 5, problems: [] });
    });
    retitle('Mine');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    saver.takeTheirs();
    expect(currentDoc()!.title).toBe('Theirs');
    expect(useEditor.getState()).toMatchObject({ saveState: 'saved', revision: 5, conflict: null });
    undo();
    expect(currentDoc()!.title).toBe('Mine');
  });

  it("can't take theirs when their file can't be read", async () => {
    api.putDocument.mockImplementationOnce(async () => {
      throw new ApiError(409, { document: null, revision: 5, problems: [] });
    });
    retitle('Mine');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    saver.takeTheirs();
    expect(currentDoc()!.title).toBe('Mine');
    expect(useEditor.getState().saveState).toBe('conflict');
  });

  it('says a document the server cannot read was not saved, and tries again on the next edit', async () => {
    const problems = [{ message: "'blu' isn't a color", severity: 'error' as const, loc: ['scenes', 0, 'objects', 0, 'color'], path: '', scene_id: 's', item_id: 'a' }];
    api.putDocument.mockImplementationOnce(async () => {
      throw new ApiError(422, { problems });
    });
    retitle('B');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState()).toMatchObject({ saveState: 'error', saveProblems: problems });
    retitle('C');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState().saveState).toBe('saved');
    expect(useEditor.getState().saveProblems).toEqual([]);
  });

  it('retries when the server is unreachable', async () => {
    api.putDocument.mockImplementationOnce(async () => {
      throw new ApiError(0, null);
    });
    retitle('B');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    expect(useEditor.getState().saveState).toBe('offline');
    await vi.advanceTimersByTimeAsync(2100);
    expect(api.putDocument).toHaveBeenCalledTimes(2);
    expect(useEditor.getState().saveState).toBe('saved');
  });

  it('counts undoing back to what is saved as saved', async () => {
    retitle('B');
    expect(useEditor.getState().saveState).toBe('unsaved');
    undo();
    expect(useEditor.getState().saveState).toBe('saved');
    await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS * 2);
    expect(api.putDocument).not.toHaveBeenCalled();
  });

  it('saves at once when asked (Ctrl+S)', async () => {
    retitle('B');
    await saver.flush();
    expect(api.putDocument).toHaveBeenCalledTimes(1);
    expect(useEditor.getState().saveState).toBe('saved');
  });
});
