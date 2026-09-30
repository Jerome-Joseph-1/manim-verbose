/** Where documents are kept: the server's file by default, anything else the same way. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../lib/api';
import { serverStorage, setStorage, storage, type DocumentStorage } from './storage';
import { Autosaver } from '../state/autosave';
import { apply, useEditor } from '../state/store';
import { setItemField } from './ops';
import { setupEditor } from '../test/editor';
import type { Document } from './types';

afterEach(() => {
  setStorage(serverStorage);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('the server file', () => {
  it('is the default, loading and saving through the API', async () => {
    expect(storage()).toBe(serverStorage);
    const doc: Document = { version: 1, title: 'T', scenes: [{ id: 's' }] };
    vi.spyOn(api, 'getDocument').mockResolvedValue({ document: doc, path: '/x.yaml', revision: 3, problems: [] });
    vi.spyOn(api, 'putDocument').mockResolvedValue({ document: doc, revision: 4, problems: [] });
    expect(await storage().load()).toEqual({ document: doc, path: '/x.yaml', revision: 3, problems: [] });
    expect(await storage().save(doc, 3)).toMatchObject({ revision: 4 });
    expect(api.putDocument).toHaveBeenCalledWith(doc, 3, undefined);
  });

  it('says so when the file can not be read as a document', async () => {
    vi.spyOn(api, 'getDocument').mockResolvedValue({ document: null as unknown as Document, path: '/x.yaml', revision: 1, problems: [] });
    expect((await storage().load()).document).toBeNull();
  });

  it('uploads pictures', async () => {
    vi.spyOn(api, 'uploadAsset').mockResolvedValue({ path: 'assets/cat.png', kind: 'png' });
    const file = new Blob(['x']);
    expect(await storage().uploadAsset!(file, 'cat.png')).toEqual({ path: 'assets/cat.png', kind: 'png' });
  });
});

describe('another storage', () => {
  it('takes over every save the editor makes', async () => {
    vi.useFakeTimers();
    const saved: Document[] = [];
    let revision = 1;
    const inBrowser: DocumentStorage = {
      load: async () => ({ document: null, revision, path: 'this browser', problems: [] }),
      save: async (document, base) => {
        if (base !== revision) throw new ApiError(409, { document: saved.at(-1) ?? null, revision });
        saved.push(document);
        revision += 1;
        return { document, revision, problems: [] };
      },
    };
    setStorage(inBrowser);
    setupEditor({ version: 1, title: 'A', scenes: [{ id: 's' }] });
    const saver = new Autosaver({ save: (d, b, s) => storage().save(d, b, s) });
    saver.start();
    apply((d) => setItemField(d, { kind: 'document' }, ['title'], 'B'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(saved.map((d) => d.title)).toEqual(['B']);
    expect(useEditor.getState()).toMatchObject({ saveState: 'saved', revision: 2 });
    saver.stop();
  });
});
