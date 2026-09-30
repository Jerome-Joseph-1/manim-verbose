/**
 * Where the document is kept: every load and save of the document goes through `storage()`,
 * never to the server directly, so that another way of keeping documents (in the browser, for
 * a hosted editor with no file to save to) can be put in with `setStorage` before the editor
 * starts, without touching any component.
 *
 * The default, `serverStorage`, is the scene file the local server edits (GET and PUT
 * /api/document). Another implementation has to behave the same way:
 *
 *   load()     resolves with the document (null when it can't be read at all, with problems
 *              saying why), a revision number, a path or name to show, and the problems found.
 *   save()     saves a document edited from `baseRevision`, resolving with the new revision,
 *              the document as saved (it may be tidier than what was sent) and its problems.
 *              It rejects with an ApiError: status 409 with `{document, revision}` as its body
 *              when something else saved in between (another tab), 422 with problems when the
 *              document can't be read at all, 0 when the storage can't be reached. Saving what
 *              is already saved keeps the revision.
 *   uploadAsset()  keeps a picture for an image or svg object, resolving with the path to
 *              write in the object. Left out when the storage can't keep files, which hides
 *              the upload buttons and drops pictures on the canvas.
 */
import { api, type DocumentResponse, type SaveResponse, type UploadedAsset } from '../lib/api';
import type { Document, Problem } from './types';

export interface LoadedDocument {
  /** Null when what is stored can't be read as a document at all. */
  document: Document | null;
  revision: number;
  /** Where it is kept, as shown to the user ("/home/you/lesson.yaml"). */
  path: string;
  problems: Problem[];
}

export interface DocumentStorage {
  load(signal?: AbortSignal): Promise<LoadedDocument>;
  save(document: Document, baseRevision: number, signal?: AbortSignal): Promise<SaveResponse>;
  uploadAsset?: (file: Blob, filename: string, signal?: AbortSignal) => Promise<UploadedAsset>;
}

/** The scene file the editor's server was started on. */
export const serverStorage: DocumentStorage = {
  load: async () => {
    const response: DocumentResponse = await api.getDocument();
    return { document: response.document ?? null, revision: response.revision, path: response.path, problems: response.problems ?? [] };
  },
  save: (document, baseRevision, signal) => api.putDocument(document, baseRevision, signal),
  uploadAsset: (file, filename, signal) => api.uploadAsset(file, filename, signal),
};

let current: DocumentStorage = serverStorage;

export function storage(): DocumentStorage {
  return current;
}

/** Use another storage from now on; call it before the editor loads its document. */
export function setStorage(next: DocumentStorage): void {
  current = next;
}
