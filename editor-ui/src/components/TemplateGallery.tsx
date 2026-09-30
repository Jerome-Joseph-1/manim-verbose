/**
 * Starting from a template: a gallery of the videos the server offers (GET /api/templates),
 * each with a picture, its title and a line on what it is. Picking one replaces the whole
 * video with it as a single edit, so undo brings back what was there; a video with anything
 * in it asks first. The same templates are offered on the canvas of a brand new video.
 *
 * A server without templates (404, or an empty list) hides all of this.
 */
import { useEffect } from 'react';
import { create } from 'zustand';
import { api, ApiError, type TemplateSummary } from '../lib/api';
import { ensureStepIds } from '../doc/ops';
import { applyTemplateDocument, isBlankDocument } from '../state/actions';
import { askConfirm, currentDoc, openModal, toast, useEditor } from '../state/store';
import { Dialog } from './Dialog';

interface TemplatesState {
  status: 'idle' | 'loading' | 'ready' | 'unavailable';
  templates: TemplateSummary[];
  /** The template being fetched to apply, for a spinner on its card. */
  applying: string | null;
}

export const useTemplates = create<TemplatesState>()(() => ({ status: 'idle', templates: [], applying: null }));

/** Load the list once; later calls reuse it. */
export async function loadTemplates(force = false): Promise<void> {
  const { status } = useTemplates.getState();
  if (!force && (status === 'loading' || status === 'ready')) return;
  useTemplates.setState({ status: 'loading' });
  try {
    const { templates } = await api.templates();
    useTemplates.setState({ status: 'ready', templates: Array.isArray(templates) ? templates : [] });
  } catch {
    useTemplates.setState({ status: 'unavailable', templates: [] });
  }
}

function useTemplateList(): TemplatesState {
  const state = useTemplates();
  useEffect(() => {
    void loadTemplates();
  }, []);
  return state;
}

/** Fetch a template and put it in place of the video, asking first unless the video is blank. */
export async function chooseTemplate(template: TemplateSummary): Promise<void> {
  const go = async () => {
    useTemplates.setState({ applying: template.name });
    try {
      const detail = await api.template(template.name);
      openModal(null);
      applyTemplateDocument(ensureStepIds(detail.document), detail.title || template.title);
    } catch (error) {
      toast(error instanceof ApiError ? `That template couldn't be opened: ${error.message}` : "That template couldn't be opened", 'error');
    } finally {
      useTemplates.setState({ applying: null });
    }
  };
  if (isBlankDocument(currentDoc())) {
    await go();
    return;
  }
  askConfirm({
    title: `Start from “${template.title}”?`,
    message: 'This replaces everything in your video with the template. Undo (Ctrl+Z) brings your video back.',
    confirmLabel: 'Use this template',
    onConfirm: () => void go(),
  });
}

function Thumbnail({ template }: { template: TemplateSummary }) {
  if (template.thumbnail_url) return <img src={template.thumbnail_url} alt="" loading="lazy" draggable={false} />;
  return (
    <span className="template-blank" aria-hidden="true">
      {template.title.slice(0, 1).toUpperCase()}
    </span>
  );
}

function TemplateCard({ template, compact }: { template: TemplateSummary; compact?: boolean }) {
  const applying = useTemplates((s) => s.applying === template.name);
  return (
    <button
      type="button"
      className={`template-card${compact ? ' compact' : ''}`}
      onClick={() => void chooseTemplate(template)}
      disabled={applying}
      data-template={template.name}
      aria-label={`Start from the template ${template.title}${template.description ? `: ${template.description}` : ''}`}
    >
      <span className="template-thumb">
        <Thumbnail template={template} />
        {applying ? (
          <span className="template-busy">
            <span className="spinner" />
          </span>
        ) : null}
      </span>
      <span className="template-title">{template.title}</span>
      {!compact && template.description ? <span className="template-desc">{template.description}</span> : null}
    </button>
  );
}

export function TemplateGallery() {
  const open = useEditor((s) => s.modal === 'templates');
  if (!open) return null;
  return <GalleryDialog />;
}

function GalleryDialog() {
  const { status, templates } = useTemplateList();
  return (
    <Dialog title="Start from a template" onClose={() => openModal(null)} wide testId="template-gallery">
      <p className="field-help" style={{ marginTop: 0 }}>
        Pick a video to start from, then change anything in it. It replaces what is in the editor now; undo brings that back.
      </p>
      {status === 'loading' || status === 'idle' ? (
        <div className="inline" role="status">
          <span className="spinner" /> Loading templates…
        </div>
      ) : templates.length === 0 ? (
        <p>There are no templates to start from.</p>
      ) : (
        <div className="template-grid" data-testid="template-grid">
          {templates.map((t) => (
            <TemplateCard key={t.name} template={t} />
          ))}
        </div>
      )}
    </Dialog>
  );
}

/** A few templates on the canvas of a brand new video. */
export function TemplateStrip() {
  const { status, templates } = useTemplateList();
  if (status !== 'ready' || templates.length === 0) return null;
  const few = templates.slice(0, 4);
  return (
    <div className="template-strip" data-testid="template-strip">
      <div className="template-strip-head">
        <span>Or start from a template</span>
        {templates.length > few.length ? (
          <button type="button" className="btn btn-sm" onClick={() => openModal('templates')}>
            See all {templates.length}
          </button>
        ) : null}
      </div>
      <div className="template-strip-cards">
        {few.map((t) => (
          <TemplateCard key={t.name} template={t} compact />
        ))}
      </div>
    </div>
  );
}

/** Whether to offer templates at all (for the button in the top bar). */
export function useTemplatesAvailable(): boolean {
  const { status, templates } = useTemplateList();
  return status === 'ready' && templates.length > 0;
}

