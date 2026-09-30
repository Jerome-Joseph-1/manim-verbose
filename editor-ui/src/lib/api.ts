/** The editor server's HTTP API (docs/editor/server-api.md). */
import type { Document, Json, Problem } from '../doc/types';
import type { StillObject } from './geometry';
import type { JsonSchema } from './schema';

export interface DocumentResponse {
  document: Document;
  path: string;
  revision: number;
  problems: Problem[];
}

export interface SaveResponse {
  revision: number;
  problems: Problem[];
  document: Document;
}

export interface CatalogEntry {
  type?: string;
  do?: string;
  label: string;
  category?: string;
  description?: string;
  template: Record<string, Json>;
}

export interface Catalog {
  objects: CatalogEntry[];
  steps: CatalogEntry[];
}

export interface StillResponse {
  image_url: string;
  width: number;
  height: number;
  objects: StillObject[];
  problems: Problem[];
}

export interface TimelineStep {
  step_id: string;
  index: number;
  start: number;
  duration: number;
}

export interface Timeline {
  steps: TimelineStep[];
  duration: number;
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface Job {
  job_id: string;
  status: JobStatus;
  progress: number;
  message: string | null;
  output_url: string | null;
  problems: Problem[];
}

export type Quality = 'low' | 'medium' | 'hd' | 'uhd';

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  readonly problems: Problem[];

  constructor(status: number, body: unknown, message?: string) {
    const problems = extractProblems(body);
    super(message ?? problems[0]?.message ?? (status === 0 ? "Couldn't reach the editor server" : `The server answered ${status}`));
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.problems = problems;
  }

  get superseded(): boolean {
    return this.status === 409 && typeof this.body === 'object' && this.body !== null && (this.body as { superseded?: unknown }).superseded === true;
  }
}

function extractProblems(body: unknown): Problem[] {
  if (typeof body === 'object' && body !== null && Array.isArray((body as { problems?: unknown }).problems)) {
    return (body as { problems: Problem[] }).problems.map(normalizeProblem);
  }
  return [];
}

/** Fill in what a problem may leave out, so the rest of the editor can rely on it. */
export function normalizeProblem(p: Partial<Problem> & { message?: string }): Problem {
  return {
    message: String(p.message ?? 'Something went wrong'),
    severity: p.severity === 'warning' ? 'warning' : 'error',
    loc: Array.isArray(p.loc) ? p.loc : [],
    path: typeof p.path === 'string' ? p.path : '',
    scene_id: p.scene_id ?? null,
    item_id: p.item_id ?? null,
  };
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? { Accept: 'application/json' } : { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? null : JSON.stringify(body),
      signal: signal ?? null,
      cache: 'no-store',
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, null);
  }
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) throw new ApiError(response.status, data);
  if (data && typeof data === 'object' && Array.isArray((data as { problems?: unknown }).problems)) {
    (data as { problems: Problem[] }).problems = (data as { problems: Problem[] }).problems.map(normalizeProblem);
  }
  return data as T;
}

export const api = {
  health: () => request<{ ok: boolean; version?: string }>('GET', '/api/health'),
  getDocument: () => request<DocumentResponse>('GET', '/api/document'),
  putDocument: (document: Document, baseRevision: number, signal?: AbortSignal) =>
    request<SaveResponse>('PUT', '/api/document', { document, base_revision: baseRevision }, signal),
  validate: (document: Document, signal?: AbortSignal) =>
    request<{ problems: Problem[] }>('POST', '/api/validate', { document }, signal),
  schema: () => request<JsonSchema>('GET', '/api/schema'),
  catalog: () => request<Catalog>('GET', '/api/catalog'),
  still: (body: { document: Document; scene_id: string; step_index: number; width: number }, signal?: AbortSignal) =>
    request<StillResponse>('POST', '/api/still', body, signal),
  clip: (body: { document: Document; scene_id: string; start_step: number; end_step: number }, signal?: AbortSignal) =>
    request<{ video_url: string }>('POST', '/api/clip', body, signal),
  code: (document: Document, sceneId?: string | null, signal?: AbortSignal) =>
    request<{ code: string }>('POST', '/api/code', sceneId ? { document, scene_id: sceneId } : { document }, signal),
  timeline: (sceneId: string, signal?: AbortSignal) =>
    request<Timeline>('GET', `/api/timeline?scene_id=${encodeURIComponent(sceneId)}`, undefined, signal),
  exportVideo: (document: Document, quality: Quality) =>
    request<{ job_id: string }>('POST', '/api/export', { document, quality }),
  job: (jobId: string, signal?: AbortSignal) => request<Job>('GET', `/api/jobs/${encodeURIComponent(jobId)}`, undefined, signal),
  cancelJob: (jobId: string) => request<{ status: JobStatus }>('DELETE', `/api/jobs/${encodeURIComponent(jobId)}`),
};

export type Api = typeof api;
