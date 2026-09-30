/**
 * Keeping a document in the browser, for the hosted editor.
 *
 * Run locally, the editor saves to a file through the server. Hosted, there is no server file
 * (see manim_verbose/editor/hosted.py and /api/config), so the document lives in this browser
 * instead: autosaved to localStorage as you work, and taken in and out as a `.yaml` file with
 * Download and Open so nothing is trapped here.
 *
 * This module is written to sit behind the editor's own storage abstraction (doc/storage.ts):
 * it exposes a `DocumentStorage` the store can call in hosted mode, plus the Download/Open
 * helpers for the toolbar and a banner to tell people where their work is kept. It touches
 * nothing else in the editor, so it can be wired in (or swapped out) on its own. Every
 * localStorage access is guarded, since it can throw or come back empty (private windows,
 * blocked site data), and the editor must still work when it does.
 */
import type { Document } from './types';
import { fromYaml, toYaml, YamlError } from './yamlLite';

export const STORAGE_KEY = 'manim-editor:hosted-document';
export const DEFAULT_FILENAME = 'video.yaml';

export const HOSTED_BANNER_TEXT =
  'Your work is saved in this browser only. Use Download to keep a copy, and Open to load one.';

export interface StoredDocument {
  document: Document;
  savedAt: number;
}

/** A place the editor's store can load and save a document, matching what the local server
 * offers but backed by the browser. */
export interface DocumentStorage {
  load(): Document | null;
  save(document: Document): void;
  clear(): void;
}

function safeStorage(): Storage | null {
  try {
    // Touching localStorage can throw where site data is blocked
    const s = globalThis.localStorage;
    return s ?? null;
  } catch {
    return null;
  }
}

/** The most recently autosaved document, or null if there isn't one (or it can't be read). */
export function loadDocument(storage: Storage | null = safeStorage()): Document | null {
  if (!storage) return null;
  let raw: string | null;
  try {
    raw = storage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredDocument | Document;
    const document = (parsed as StoredDocument).document ?? (parsed as Document);
    if (document && typeof document === 'object' && Array.isArray((document as Document).scenes)) {
      return document as Document;
    }
  } catch {
    return null;
  }
  return null;
}

/** Autosave the document. Safe to call on every edit; failures (a full or blocked store) are
 * swallowed, since losing an autosave must never break the editor. */
export function saveDocument(document: Document, storage: Storage | null = safeStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({ document, savedAt: Date.now() } satisfies StoredDocument));
    return true;
  } catch {
    return false;
  }
}

export function clearDocument(storage: Storage | null = safeStorage()): void {
  try {
    storage?.removeItem(STORAGE_KEY);
  } catch {
    // nothing to do
  }
}

export function hasSavedDocument(storage: Storage | null = safeStorage()): boolean {
  return loadDocument(storage) !== null;
}

/** A DocumentStorage backed by localStorage, for the editor's store to use in hosted mode. */
export function browserStorage(storage: Storage | null = safeStorage()): DocumentStorage {
  return {
    load: () => loadDocument(storage),
    save: (document: Document) => void saveDocument(document, storage),
    clear: () => clearDocument(storage),
  };
}

// --- Download / Open ---------------------------------------------------------------------

/** The document as `.yaml` text (or `.json` when the name ends in .json). */
export function documentToText(document: Document, filename = DEFAULT_FILENAME): string {
  if (filename.toLowerCase().endsWith('.json')) {
    return JSON.stringify(document, null, 2) + '\n';
  }
  return toYaml(document as unknown as import('./types').Json);
}

/** A document read from a downloaded/opened file. JSON is parsed as JSON; anything else is
 * parsed as YAML. Throws a message fit to show the user. */
export function parseDocumentText(text: string, filename = ''): Document {
  const asJson = filename.toLowerCase().endsWith('.json');
  let value: unknown;
  if (asJson) {
    value = JSON.parse(text);
  } else {
    try {
      value = fromYaml(text);
    } catch (error) {
      // A file that is really JSON with a .yaml name still opens (JSON is valid YAML anyway)
      try {
        value = JSON.parse(text);
      } catch {
        throw new Error(error instanceof YamlError ? error.message : "This file isn't a valid scene file");
      }
    }
  }
  if (!value || typeof value !== 'object' || !Array.isArray((value as Document).scenes)) {
    throw new Error("This file doesn't look like a scene file (it has no `scenes`)");
  }
  return value as Document;
}

export interface Download {
  filename: string;
  text: string;
  blob: Blob;
}

/** Everything needed to save a document as a file, without touching the DOM (so it can be
 * tested and reused). */
export function buildDownload(document: Document, filename = DEFAULT_FILENAME): Download {
  const text = documentToText(document, filename);
  return { filename, text, blob: new Blob([text], { type: 'application/x-yaml' }) };
}

/** Save the document as a file the visitor keeps. Uses an object URL and a synthetic click,
 * which is the portable way to trigger a download. */
export function downloadDocument(document: Document, filename = DEFAULT_FILENAME): void {
  const { blob } = buildDownload(document, filename);
  const url = URL.createObjectURL(blob);
  try {
    const anchor = window.document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    window.document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    // Give the browser a moment to start the download before the URL is revoked
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
}

/** Read a picked file into a document. `file` is a File (or anything with `name` and
 * `text()`), so this is testable without a real file input. */
export async function readDocumentFile(file: { name: string; text(): Promise<string> }): Promise<Document> {
  const text = await file.text();
  return parseDocumentText(text, file.name);
}

/** Show the file picker and return the chosen document, or null if the visitor cancels. The
 * caller decides what to do with it (load it into the editor, warn about unsaved work, ...). */
export function openDocumentFile(): Promise<{ document: Document; name: string } | null> {
  return new Promise((resolve, reject) => {
    const input = window.document.createElement('input');
    input.type = 'file';
    input.accept = '.yaml,.yml,.json,application/x-yaml,application/json,text/yaml';
    input.style.display = 'none';
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      input.remove();
      if (!file) {
        resolve(null);
        return;
      }
      readDocumentFile(file)
        .then((document) => resolve({ document, name: file.name }))
        .catch(reject);
    });
    // If the dialog is dismissed some browsers fire no event; a focus check resolves null.
    input.addEventListener('cancel', () => {
      input.remove();
      resolve(null);
    });
    window.document.body.appendChild(input);
    input.click();
  });
}

/** Put a small banner at the top of an element, explaining where hosted work is kept. The
 * editor may render its own instead; this is a no-dependency fallback that can be dropped in. */
export function mountHostedBanner(parent: HTMLElement, text: string = HOSTED_BANNER_TEXT): HTMLElement {
  const banner = window.document.createElement('div');
  banner.className = 'hosted-banner';
  banner.setAttribute('role', 'status');
  banner.textContent = text;
  parent.prepend(banner);
  return banner;
}
