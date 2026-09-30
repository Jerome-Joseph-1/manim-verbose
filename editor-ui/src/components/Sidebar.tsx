/**
 * The left hand side: the scenes of the video, the steps of the scene in order (the
 * timeline), and the objects the scene declares.
 */
import { memo, useMemo } from 'react';
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Catalog, TimelineStep } from '../lib/api';
import { CATEGORY_ORDER, objectKind, stepKind, type SchemaIndex } from '../lib/schema';
import { catalogFromSchema } from '../lib/templates';
import { problemsForItem, worstSeverity } from '../lib/problems';
import { stepTargets } from '../doc/refs';
import { onScreenAfter } from '../doc/screen';
import type { Problem, Scene, SceneObject, Step } from '../doc/types';
import {
  currentSceneId, frameStepIndex, requestFocus, select, selectScene, setFrameStep, useEditor,
} from '../state/store';
import {
  addNewScene, addObjectFrom, addStepFrom, duplicateObjectById, duplicateSceneById, duplicateStepById, removeStepById,
  reorderScene, reorderStep, requestRemoveObject, requestRemoveScene, showObjects,
} from '../state/actions';
import { Icon, categoryIcon, stepIcon } from './Icon';
import { Menu, type MenuEntry } from './Menu';

export function useCatalog(): Catalog | null {
  const catalog = useEditor((s) => s.catalog);
  const schema = useEditor((s) => s.schema);
  return useMemo(() => {
    if (catalog && catalog.objects?.length && catalog.steps?.length) return catalog;
    return schema ? catalogFromSchema(schema) : null;
  }, [catalog, schema]);
}

function useAllProblems(): Problem[] {
  const saveProblems = useEditor((s) => s.saveProblems);
  const renderProblems = useEditor((s) => s.renderProblems);
  return useMemo(() => [...saveProblems, ...Object.values(renderProblems).flat()], [saveProblems, renderProblems]);
}

function useSortSensors() {
  return useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
}

export function Sidebar() {
  return (
    <nav className="sidebar" aria-label="Scenes, steps and objects">
      <ScenesSection />
      <StepsSection />
      <ObjectsSection />
    </nav>
  );
}

// Scenes

function ScenesSection() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const sceneId = useEditor((s) => currentSceneId(s));
  const selection = useEditor((s) => s.selection);
  const timelines = useEditor((s) => s.timelines);
  const sensors = useSortSensors();
  if (!doc) return null;
  const ids = doc.scenes.map((s) => `scene:${s.id}`);
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    reorderScene(ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
  };
  return (
    <section className="section section-scenes" aria-labelledby="scenes-heading">
      <div className="section-header">
        <h2 id="scenes-heading">Scenes</h2>
        <span className="count">{doc.scenes.length}</span>
        <button type="button" className="btn btn-sm push" onClick={addNewScene} data-testid="add-scene">
          <Icon name="plus" /> Scene
        </button>
      </div>
      <div className="section-body">
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={ids} strategy={verticalListSortingStrategy}>
            <ul className="list" data-testid="scene-list">
              {doc.scenes.map((scene, index) => (
                <SceneRow
                  key={scene.id}
                  scene={scene}
                  index={index}
                  count={doc.scenes.length}
                  current={scene.id === sceneId}
                  selected={selection.kind === 'scene' && selection.sceneId === scene.id}
                  duration={timelines[scene.id]?.duration}
                />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      </div>
    </section>
  );
}

function SceneRow({ scene, index, count, current, selected, duration }: { scene: Scene; index: number; count: number; current: boolean; selected: boolean; duration: number | undefined }) {
  const sortable = useSortable({ id: `scene:${scene.id}` });
  const style = { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition };
  return (
    <li
      ref={sortable.setNodeRef}
      style={style}
      className={`row${current ? ' selected' : ''}${sortable.isDragging ? ' dragging' : ''}`}
      data-scene-id={scene.id}
      onPointerDown={sortable.listeners?.onPointerDown as React.PointerEventHandler | undefined}
    >
      <button
        type="button"
        className="row-main"
        aria-current={current ? 'true' : undefined}
        aria-pressed={selected}
        onClick={() => selectScene(scene.id)}
        onKeyDown={(e) => {
          if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
            e.preventDefault();
            const to = index + (e.key === 'ArrowUp' ? -1 : 1);
            if (to < 0 || to >= count) return;
            reorderScene(index, to);
            // Moving the row in the page loses its focus; give it back
            requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-scene-id="${scene.id}"] .row-main`)?.focus());
          }
        }}
      >
        <span className="kind-badge" aria-hidden="true">
          {index + 1}
        </span>
        <span className="row-label">{scene.title || scene.id}</span>
        {duration ? <span className="row-sub">{formatDuration(duration)}</span> : null}
      </button>
      <div className="row-actions">
        <button type="button" className="icon-btn drag-handle" aria-label={`Reorder scene ${scene.title || scene.id}`} {...sortable.attributes} onKeyDown={sortable.listeners?.onKeyDown as React.KeyboardEventHandler | undefined}>
          <Icon name="grip" />
        </button>
        <button type="button" className="icon-btn" aria-label={`Rename scene ${scene.title || scene.id}`} title="Rename" onClick={() => requestFocus({ kind: 'scene', sceneId: scene.id }, ['title'])}>
          <Icon name="text" />
        </button>
        <button type="button" className="icon-btn" aria-label={`Duplicate scene ${scene.title || scene.id}`} title="Duplicate" onClick={() => duplicateSceneById(scene.id)}>
          <Icon name="copy" />
        </button>
        <button
          type="button"
          className="icon-btn danger"
          aria-label={`Delete scene ${scene.title || scene.id}`}
          title={count <= 1 ? 'The only scene can’t be deleted' : 'Delete'}
          disabled={count <= 1}
          onClick={() => requestRemoveScene(scene.id)}
        >
          <Icon name="trash" />
        </button>
      </div>
    </li>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Steps

export function stepSummary(schema: SchemaIndex, step: Step): string {
  switch (step.do) {
    case 'wait':
      return `${typeof step.duration === 'number' ? step.duration : 1} s`;
    case 'clear':
      return 'everything';
    case 'camera': {
      const parts: string[] = [];
      if (typeof step.zoom === 'number') parts.push(`zoom ×${step.zoom}`);
      if (typeof step.focus === 'string') parts.push(`on ${step.focus}`);
      if (step.reset === true) parts.push('reset');
      if (Array.isArray(step.orientation)) parts.push('turn');
      return parts.join(', ');
    }
    case 'transform':
      return `${String(step.target ?? '?')} → ${String(step.into ?? '?')}`;
    case 'together': {
      const inner = Array.isArray(step.steps) ? (step.steps as unknown as Step[]) : [];
      return inner.map((s) => `${stepKind(schema, s.do)?.label.toLowerCase() ?? s.do} ${stepTargets(s).join(', ')}`.trim()).join(' + ');
    }
    default: {
      const targets = stepTargets(step);
      return targets.length ? targets.join(', ') : '(no object chosen)';
    }
  }
}

function StepsSection() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const schema = useEditor((s) => s.schema);
  const sceneId = useEditor((s) => currentSceneId(s));
  const selection = useEditor((s) => s.selection);
  const frameIndex = useEditor((s) => (sceneId ? frameStepIndex(s, sceneId) : -1));
  const timeline = useEditor((s) => (sceneId ? s.timelines[sceneId] : undefined));
  const catalog = useCatalog();
  const problems = useAllProblems();
  const sensors = useSortSensors();
  const scene = doc && sceneId ? doc.scenes.find((s) => s.id === sceneId) : undefined;
  const steps = useMemo(() => scene?.steps ?? [], [scene]);
  const ids = useMemo(() => steps.map((s, i) => s.id ?? `#${i}`), [steps]);
  const timings = useMemo(() => new Map((timeline?.steps ?? []).map((t) => [t.step_id, t])), [timeline]);

  if (!doc || !schema || !scene) return null;
  const entries: MenuEntry[] = (catalog?.steps ?? []).map((entry) => ({
    key: String(entry.do),
    label: entry.label,
    description: entry.description,
    icon: stepIcon(String(entry.do)),
    onSelect: () => addStepFrom(entry),
  }));
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    reorderStep(scene.id, ids.indexOf(String(active.id)), ids.indexOf(String(over.id)));
  };
  const objects = scene.objects ?? [];
  return (
    <section className="section section-steps" aria-labelledby="steps-heading">
      <div className="section-header">
        <h2 id="steps-heading">Steps</h2>
        <span className="count">{steps.length}</span>
        {timeline ? <span className="count">· {formatDuration(timeline.duration)}</span> : null}
        <div className="push">
          <Menu label="Add a step" buttonLabel="Step" entries={entries} testId="add-step" />
        </div>
      </div>
      <div className="section-body">
        <button
          type="button"
          className={`row${frameIndex === -1 ? ' selected' : ''}`}
          style={{ width: '100%', background: 'none', marginBottom: 3, minHeight: 28, fontSize: 13, color: 'var(--text-muted)' }}
          aria-pressed={frameIndex === -1}
          onClick={() => {
            setFrameStep(scene.id, null);
            select({ kind: 'scene', sceneId: scene.id, id: null });
          }}
        >
          <Icon name="first" /> Start of the scene
        </button>
        {steps.length === 0 ? (
          <div className="empty-hint">
            <strong>Steps play one after another.</strong> Nothing appears in the video until a step shows it.{' '}
            {objects.length ? (
              <>
                <br />
                <button type="button" className="btn btn-sm" style={{ marginTop: 8 }} onClick={() => showObjects(objects.map((o) => o.id))}>
                  <Icon name="eye" /> Show all {objects.length} object{objects.length === 1 ? '' : 's'}
                </button>
              </>
            ) : (
              'Add an object first, then a step to show it.'
            )}
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={ids} strategy={verticalListSortingStrategy}>
              <ol className="list" data-testid="step-list" aria-label="Steps, in the order they play">
                {steps.map((step, index) => (
                  <StepCard
                    key={ids[index]}
                    id={ids[index]!}
                    schema={schema}
                    sceneId={scene.id}
                    step={step}
                    index={index}
                    count={steps.length}
                    selected={selection.kind === 'step' && selection.id === step.id}
                    framed={index === frameIndex}
                    timing={step.id ? timings.get(step.id) : undefined}
                    severity={worstSeverity(problemsForItem(problems, { kind: 'step', sceneId: scene.id, itemId: step.id ?? null }, doc).concat(nestedProblems(problems, scene.id, step, doc)))}
                  />
                ))}
              </ol>
            </SortableContext>
          </DndContext>
        )}
      </div>
    </section>
  );
}

function nestedProblems(problems: Problem[], sceneId: string, step: Step, doc: import('../doc/types').Document): Problem[] {
  if (step.do !== 'together' || !Array.isArray(step.steps)) return [];
  return (step.steps as unknown as Step[]).flatMap((inner) => problemsForItem(problems, { kind: 'step', sceneId, itemId: inner.id ?? null }, doc));
}

const StepCard = memo(function StepCard({
  id, schema, sceneId, step, index, count, selected, framed, timing, severity,
}: {
  id: string;
  schema: SchemaIndex;
  sceneId: string;
  step: Step;
  index: number;
  count: number;
  selected: boolean;
  framed: boolean;
  timing: TimelineStep | undefined;
  severity: 'error' | 'warning' | null;
}) {
  const sortable = useSortable({ id });
  const style = { transform: CSS.Transform.toString(sortable.transform), transition: sortable.transition };
  const kind = stepKind(schema, step.do);
  const summary = stepSummary(schema, step);
  const caption = typeof step.caption === 'string' ? step.caption : null;
  const label = `Step ${index + 1}: ${kind?.label ?? step.do} ${summary}`;
  const selectMe = () => step.id && select({ kind: 'step', sceneId, id: step.id });
  return (
    <li
      ref={sortable.setNodeRef}
      style={style}
      className={`step-card${selected ? ' selected' : ''}${framed ? ' framed' : ''}${sortable.isDragging ? ' dragging' : ''}`}
      data-step-id={step.id ?? undefined}
      data-testid="step-card"
      onClick={selectMe}
      onPointerDown={sortable.listeners?.onPointerDown as React.PointerEventHandler | undefined}
    >
      <span className="step-index" aria-hidden="true">
        {index + 1}
      </span>
      <button
        type="button"
        className="step-title"
        aria-label={label}
        aria-pressed={selected}
        onClick={(e) => {
          e.stopPropagation();
          selectMe();
        }}
        onKeyDown={(e) => {
          if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
            e.preventDefault();
            e.stopPropagation();
            const to = index + (e.key === 'ArrowUp' ? -1 : 1);
            if (to >= 0 && to < count) {
              reorderStep(sceneId, index, to);
              requestAnimationFrame(() => {
                document.querySelector<HTMLElement>(`[data-step-id="${step.id}"] .step-title`)?.focus();
              });
            }
          }
        }}
      >
        <Icon name={stepIcon(step.do)} />
        <span>{kind?.label ?? step.do}</span>
        <span className="targets">{summary}</span>
        {severity ? <span className={`problem-dot ${severity}`} title={severity === 'error' ? 'Has a problem' : 'Has a warning'} /> : null}
      </button>
      <span className="step-duration" title="How long this step takes">
        {timing ? `${timing.duration.toFixed(1)} s` : ''}
      </span>
      {caption !== null ? (
        <span className="step-meta">
          <span className="step-caption">“{caption || 'clears the caption'}”</span>
        </span>
      ) : null}
      <span className="step-actions" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="icon-btn drag-handle" aria-label={`Move step ${index + 1}`} {...sortable.attributes} onKeyDown={sortable.listeners?.onKeyDown as React.KeyboardEventHandler | undefined}>
          <Icon name="grip" />
        </button>
        <button type="button" className="icon-btn" aria-label={`Duplicate step ${index + 1}`} title="Duplicate" onClick={() => step.id && duplicateStepById(sceneId, step.id)}>
          <Icon name="copy" />
        </button>
        <button type="button" className="icon-btn danger" aria-label={`Delete step ${index + 1}`} title="Delete" onClick={() => step.id && removeStepById(sceneId, step.id)}>
          <Icon name="trash" />
        </button>
      </span>
    </li>
  );
});

// Objects

function ObjectsSection() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const schema = useEditor((s) => s.schema);
  const sceneId = useEditor((s) => currentSceneId(s));
  const selection = useEditor((s) => s.selection);
  const frameIndex = useEditor((s) => (sceneId ? frameStepIndex(s, sceneId) : -1));
  const catalog = useCatalog();
  const problems = useAllProblems();
  const scene = doc && sceneId ? doc.scenes.find((s) => s.id === sceneId) : undefined;
  const onScreen = useMemo(() => (scene ? onScreenAfter(scene, frameIndex) : new Set<string>()), [scene, frameIndex]);

  if (!doc || !schema || !scene) return null;
  const objects = scene.objects ?? [];
  const entries: MenuEntry[] = [];
  let lastCategory: string | null = null;
  const sortedCatalog = [...(catalog?.objects ?? [])].sort(
    (a, b) => rank(a.category) - rank(b.category),
  );
  for (const entry of sortedCatalog) {
    const category = entry.category ?? 'Other';
    entries.push({
      key: String(entry.type),
      label: entry.label,
      description: entry.description,
      icon: categoryIcon(category),
      heading: category !== lastCategory ? category : undefined,
      onSelect: () => addObjectFrom(entry),
    });
    lastCategory = category;
  }
  const groups = new Map<string, SceneObject[]>();
  for (const obj of objects) {
    const category = objectKind(schema, obj.type)?.category ?? 'Other';
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category)!.push(obj);
  }
  const categories = [...groups.keys()].sort((a, b) => rank(a) - rank(b));
  return (
    <section className="section section-objects" aria-labelledby="objects-heading">
      <div className="section-header">
        <h2 id="objects-heading">Objects</h2>
        <span className="count">{objects.length}</span>
        <div className="push">
          <Menu label="Add an object" buttonLabel="Object" entries={entries} testId="add-object" />
        </div>
      </div>
      <div className="section-body" data-testid="object-list">
        {objects.length === 0 ? (
          <div className="empty-hint">
            <strong>Objects are the things in your video:</strong> text, equations, shapes, graphs. Add one with the Object button.
          </div>
        ) : null}
        {categories.map((category) => (
          <div key={category}>
            <div className="category-label">{category}</div>
            <ul className="list" aria-label={category}>
              {groups.get(category)!.map((obj) => {
                const severity = worstSeverity(problemsForItem(problems, { kind: 'object', sceneId: scene.id, itemId: obj.id }, doc));
                const selected = selection.kind === 'object' && selection.id === obj.id && selection.sceneId === scene.id;
                const label = objectKind(schema, obj.type)?.label ?? obj.type;
                return (
                  <li key={obj.id} className={`row${selected ? ' selected' : ''}`} data-object-id={obj.id}>
                    <button type="button" className="row-main" aria-pressed={selected} onClick={() => select({ kind: 'object', sceneId: scene.id, id: obj.id })}>
                      <span className="kind-badge" aria-hidden="true">
                        <Icon name={categoryIcon(category)} />
                      </span>
                      <span className="row-label mono">{obj.id}</span>
                      <span className="row-sub">{label}</span>
                      {!onScreen.has(obj.id) ? (
                        <span className="offscreen" title="Not on screen at this point of the scene">
                          hidden
                        </span>
                      ) : null}
                      {severity ? <span className={`problem-dot ${severity}`} title={severity === 'error' ? 'Has a problem' : 'Has a warning'} /> : null}
                    </button>
                    <div className="row-actions">
                      <button type="button" className="icon-btn" aria-label={`Duplicate ${obj.id}`} title="Duplicate" onClick={() => duplicateObjectById(scene.id, obj.id)}>
                        <Icon name="copy" />
                      </button>
                      <button type="button" className="icon-btn danger" aria-label={`Delete ${obj.id}`} title="Delete" onClick={() => requestRemoveObject(scene.id, obj.id)}>
                        <Icon name="trash" />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function rank(category: string | undefined): number {
  const i = CATEGORY_ORDER.indexOf(category ?? '');
  return i < 0 ? CATEGORY_ORDER.length : i;
}
