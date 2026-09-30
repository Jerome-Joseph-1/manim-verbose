import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  STORAGE_KEY, browserStorage, buildDownload, clearDocument, documentToText, hasSavedDocument,
  loadDocument, parseDocumentText, readDocumentFile, saveDocument,
} from './browserStorage';
import type { Document } from './types';

const DOC: Document = {
  version: 1,
  title: 'Test',
  scenes: [{
    id: 'intro',
    objects: [{ id: 'eq', type: 'tex', tex: 'e^{i\\pi} + 1 = 0' }],
    steps: [{ id: 'intro_1', do: 'show', target: 'eq' }, { do: 'wait', duration: 2 }],
  }],
};

/** A localStorage stand-in, so tests don't depend on jsdom's (and can simulate failure). */
function fakeStorage(): Storage & { fail?: boolean } {
  const map = new Map<string, string>();
  return {
    get length() { return map.size; },
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    getItem(k: string) { if ((this as { fail?: boolean }).fail) throw new Error('blocked'); return map.get(k) ?? null; },
    setItem(k: string, v: string) { if ((this as { fail?: boolean }).fail) throw new Error('blocked'); map.set(k, v); },
    removeItem(k: string) { map.delete(k); },
  } as Storage & { fail?: boolean };
}

describe('localStorage autosave', () => {
  it('saves and loads a document', () => {
    const storage = fakeStorage();
    expect(loadDocument(storage)).toBeNull();
    expect(saveDocument(DOC, storage)).toBe(true);
    expect(hasSavedDocument(storage)).toBe(true);
    expect(loadDocument(storage)).toEqual(DOC);
  });

  it('clears the saved document', () => {
    const storage = fakeStorage();
    saveDocument(DOC, storage);
    clearDocument(storage);
    expect(loadDocument(storage)).toBeNull();
  });

  it('stores under the documented key, wrapped with a timestamp', () => {
    const storage = fakeStorage();
    saveDocument(DOC, storage);
    const stored = JSON.parse(storage.getItem(STORAGE_KEY)!);
    expect(stored.document).toEqual(DOC);
    expect(typeof stored.savedAt).toBe('number');
  });

  it('survives a storage that throws (private window, blocked site data)', () => {
    const storage = fakeStorage();
    storage.fail = true;
    expect(() => loadDocument(storage)).not.toThrow();
    expect(loadDocument(storage)).toBeNull();
    expect(saveDocument(DOC, storage)).toBe(false);
    expect(() => clearDocument(storage)).not.toThrow();
  });

  it('ignores corrupt or foreign data', () => {
    const storage = fakeStorage();
    storage.setItem(STORAGE_KEY, 'not json');
    expect(loadDocument(storage)).toBeNull();
    storage.setItem(STORAGE_KEY, JSON.stringify({ document: { nope: true } }));
    expect(loadDocument(storage)).toBeNull();
  });

  it('reads an older bare-document shape too', () => {
    const storage = fakeStorage();
    storage.setItem(STORAGE_KEY, JSON.stringify(DOC));
    expect(loadDocument(storage)).toEqual(DOC);
  });

  it('null storage (no localStorage at all) is handled', () => {
    expect(loadDocument(null)).toBeNull();
    expect(saveDocument(DOC, null)).toBe(false);
  });
});

describe('browserStorage() DocumentStorage', () => {
  it('implements load/save/clear over a store', () => {
    const storage = fakeStorage();
    const store = browserStorage(storage);
    expect(store.load()).toBeNull();
    store.save(DOC);
    expect(store.load()).toEqual(DOC);
    store.clear();
    expect(store.load()).toBeNull();
  });
});

describe('Download', () => {
  it('serializes to YAML by default and round-trips', () => {
    const yaml = documentToText(DOC);
    expect(yaml.startsWith('version: 1')).toBe(true); // block YAML, not a JSON object
    expect(yaml).toContain('\nscenes:');
    expect(parseDocumentText(yaml, 'video.yaml')).toEqual(DOC);
  });

  it('serializes to JSON when the name ends in .json', () => {
    const json = documentToText(DOC, 'video.json');
    expect(JSON.parse(json)).toEqual(DOC);
    expect(parseDocumentText(json, 'video.json')).toEqual(DOC);
  });

  it('buildDownload produces a named blob without touching the DOM', () => {
    const download = buildDownload(DOC, 'my video.yaml');
    expect(download.filename).toBe('my video.yaml');
    expect(download.blob.size).toBe(download.text.length);
    expect(parseDocumentText(download.text, download.filename)).toEqual(DOC);
  });
});

describe('Open', () => {
  it('reads a YAML file into a document', async () => {
    const text = documentToText(DOC, 'video.yaml');
    const file = { name: 'video.yaml', text: () => Promise.resolve(text) };
    expect(await readDocumentFile(file)).toEqual(DOC);
  });

  it('reads a JSON file into a document', async () => {
    const file = { name: 'video.json', text: () => Promise.resolve(JSON.stringify(DOC)) };
    expect(await readDocumentFile(file)).toEqual(DOC);
  });

  it('accepts JSON content even under a .yaml name', () => {
    expect(parseDocumentText(JSON.stringify(DOC), 'video.yaml')).toEqual(DOC);
  });

  it('refuses a file that is not a scene file, with a plain message', () => {
    expect(() => parseDocumentText('title: hi\nno_scenes: true', 'x.yaml')).toThrow(/scene file/);
    expect(() => parseDocumentText('{ this is: not valid', 'x.yaml')).toThrow();
  });
});

describe('download to the browser', () => {
  it('creates an object URL and clicks an anchor', async () => {
    const { downloadDocument } = await import('./browserStorage');
    const createObjectURL = vi.fn(() => 'blob:fake');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    downloadDocument(DOC, 'video.yaml');
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
    vi.unstubAllGlobals();
  });
});

describe('hosted banner', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });
  it('mounts a status banner at the top of a container', async () => {
    const { mountHostedBanner, HOSTED_BANNER_TEXT } = await import('./browserStorage');
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const banner = mountHostedBanner(parent);
    expect(parent.firstChild).toBe(banner);
    expect(banner.getAttribute('role')).toBe('status');
    expect(banner.textContent).toBe(HOSTED_BANNER_TEXT);
  });
});
