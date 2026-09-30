/**
 * Making the finished video: pick a quality, watch it render, download it. The job keeps
 * going with the dialog closed; the top bar shows how far it has got.
 */
import { useState } from 'react';
import { create } from 'zustand';
import { api, ApiError, type Job, type Quality } from '../lib/api';
import type { Problem } from '../doc/types';
import { currentDoc, openModal, useEditor } from '../state/store';
import { Dialog } from './Dialog';
import { FieldProblems } from './form/Field';
import { Icon } from './Icon';

interface ExportState {
  job: Job | null;
  starting: boolean;
  error: string | null;
  problems: Problem[];
}

export const useExport = create<ExportState>(() => ({ job: null, starting: false, error: null, problems: [] }));

const POLL_MS = 500;
let pollTimer: ReturnType<typeof setTimeout> | null = null;

function poll(jobId: string): void {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const job = await api.job(jobId);
      if (useExport.getState().job?.job_id !== jobId) return;
      useExport.setState({ job });
      if (job.status === 'queued' || job.status === 'running') poll(jobId);
    } catch (error) {
      if (useExport.getState().job?.job_id !== jobId) return;
      if (error instanceof ApiError && error.status === 404) {
        useExport.setState({ error: 'The export job was lost (was the server restarted?)', job: null });
      } else {
        poll(jobId);
      }
    }
  }, POLL_MS);
}

export async function startExport(quality: Quality): Promise<void> {
  const doc = currentDoc();
  if (!doc) return;
  useExport.setState({ starting: true, error: null, problems: [], job: null });
  try {
    const { job_id } = await api.exportVideo(doc, quality);
    useExport.setState({
      starting: false,
      job: { job_id, status: 'queued', progress: 0, message: 'Waiting to start', output_url: null, problems: [] },
    });
    poll(job_id);
  } catch (error) {
    const problems = error instanceof ApiError ? error.problems : [];
    useExport.setState({
      starting: false,
      error: error instanceof ApiError && error.status === 422 ? 'The video can’t be made until these problems are fixed:' : 'The export could not start.',
      problems,
    });
  }
}

export async function cancelExport(): Promise<void> {
  const job = useExport.getState().job;
  if (!job) return;
  try {
    const { status } = await api.cancelJob(job.job_id);
    useExport.setState({ job: { ...job, status, message: 'Cancelled' } });
  } catch {
    useExport.setState({ job: { ...job, status: 'cancelled', message: 'Cancelled' } });
  }
  if (pollTimer) clearTimeout(pollTimer);
}

export function exportRunning(job: Job | null): boolean {
  return job !== null && (job.status === 'queued' || job.status === 'running');
}

const QUALITIES: { value: Quality; label: string; detail: string }[] = [
  { value: 'low', label: 'Draft', detail: '854×480, 15 fps: quick, for checking' },
  { value: 'medium', label: 'Medium', detail: '1280×720' },
  { value: 'hd', label: 'Full HD', detail: 'the video’s own size, 1920×1080 unless changed' },
  { value: 'uhd', label: '4K', detail: '3840×2160: slow' },
];

export function ExportModal() {
  const open = useEditor((s) => s.modal === 'export');
  if (!open) return null;
  return <ExportDialog />;
}

function ExportDialog() {
  const { job, starting, error, problems } = useExport();
  const [quality, setQuality] = useState<Quality>('hd');
  const title = useEditor((s) => s.history?.present.title ?? 'video');
  const running = exportRunning(job) || starting;
  const percent = Math.round((job?.progress ?? 0) * 100);

  return (
    <Dialog
      title="Export the video"
      onClose={() => openModal(null)}
      testId="export-dialog"
      footer={
        <>
          {running ? (
            <button type="button" className="btn left" onClick={cancelExport}>
              Cancel export
            </button>
          ) : null}
          <button type="button" className="btn" onClick={() => openModal(null)}>
            {running ? 'Hide' : 'Close'}
          </button>
          <button type="button" className="btn btn-primary" disabled={running} onClick={() => startExport(quality)}>
            <Icon name="film" /> {job && !running ? 'Export again' : 'Start export'}
          </button>
        </>
      }
    >
      <fieldset style={{ border: 'none', padding: 0, margin: '0 0 10px' }} disabled={running}>
        <legend className="field-label">Quality</legend>
        {QUALITIES.map((q) => (
          <label key={q.value} className="checkbox" style={{ margin: '6px 0' }}>
            <input type="radio" name="quality" value={q.value} checked={quality === q.value} onChange={() => setQuality(q.value)} />
            <span>
              {q.label} <span className="row-sub">{q.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {job ? (
        <div aria-live="polite" data-testid="export-status">
          <div
            className="progress"
            role="progressbar"
            aria-label="Export progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
          >
            <div style={{ width: `${percent}%` }} />
          </div>
          <div className="inline" style={{ justifyContent: 'space-between' }}>
            <span>{job.status === 'done' ? 'Your video is ready.' : job.status === 'failed' ? 'The export failed.' : job.status === 'cancelled' ? 'Export cancelled.' : job.message ?? 'Rendering…'}</span>
            <span className="row-sub">{percent}%</span>
          </div>
          {job.status === 'done' && job.output_url ? (
            <p style={{ marginTop: 12 }}>
              <a className="btn btn-primary" href={job.output_url} download={`${title || 'video'}.mp4`} data-testid="download-link">
                <Icon name="download" /> Download the video
              </a>
            </p>
          ) : null}
          <FieldProblems problems={job.problems ?? []} />
        </div>
      ) : null}
      {starting ? (
        <div className="inline">
          <span className="spinner" aria-hidden="true" /> Starting…
        </div>
      ) : null}
      {error ? (
        <div role="alert">
          <p style={{ color: 'var(--danger)' }}>{error}</p>
          <FieldProblems problems={problems} />
        </div>
      ) : null}
    </Dialog>
  );
}
