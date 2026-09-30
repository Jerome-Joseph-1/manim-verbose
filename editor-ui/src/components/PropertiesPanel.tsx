/**
 * The right hand panel: every field of whatever is selected, built from the schema, with
 * problems beside the fields they are about.
 */
import { useEffect, useMemo, useRef } from 'react';
import { DocOpError, findObject, findScene, findStep, renameItem, setItemField, type ItemRef } from '../doc/ops';
import { formatLoc } from '../doc/paths';
import { onScreenAfter } from '../doc/screen';
import { fieldOf, type Document, type Json, type Problem, type Scene } from '../doc/types';
import {
  documentFields, objectFields, objectKind, sceneFields, stepFields, stepKind, type FieldGroup, type FieldSpec, type SchemaIndex,
} from '../lib/schema';
import { dedupeProblems, problemsForField, type ItemAddress } from '../lib/problems';
import { apply, frameStepIndex, select, useEditor } from '../state/store';
import {
  duplicateObjectById, duplicateSceneById, duplicateStepById, removeStepById, requestRemoveObject, requestRemoveScene, showObjects,
} from '../state/actions';
import { openPreview } from './PreviewModal';
import { FormContext, type FormCtx } from './form/context';
import { Field, FieldProblems } from './form/Field';
import { Icon, categoryIcon, stepIcon } from './Icon';

const GROUP_TITLES: Record<FieldGroup, string> = {
  identity: '',
  main: '',
  caption: 'Caption',
  position: 'Position and size',
  style: 'Look',
  timing: 'Timing',
};

function useProblems(): Problem[] {
  const saveProblems = useEditor((s) => s.saveProblems);
  const renderProblems = useEditor((s) => s.renderProblems);
  return useMemo(() => dedupeProblems([...saveProblems, ...Object.values(renderProblems).flat()]), [saveProblems, renderProblems]);
}

function makeContext(
  schema: SchemaIndex,
  doc: Document,
  scene: Scene | null,
  ref: ItemRef,
  problems: Problem[],
  prefix: string,
): FormCtx {
  const item: ItemAddress = { kind: ref.kind, sceneId: ref.sceneId ?? null, itemId: ref.id ?? null };
  const keyBase = `field:${ref.kind}:${ref.sceneId ?? ''}:${ref.id ?? ''}`;
  return {
    schema,
    doc,
    scene,
    item,
    problems,
    idPrefix: prefix,
    commit: (path, value, options) => {
      apply((d) => setItemField(d, ref, path, value), options?.coalesce ? { key: `${keyBase}:${formatLoc(path)}` } : {});
    },
    rename: ref.kind === 'document' ? undefined : (newId: string) => {
      const current = useEditor.getState().history?.present;
      if (!current) return null;
      try {
        const next = renameItem(current, ref, newId);
        apply(() => next);
        if (ref.kind === 'scene') select({ kind: 'scene', sceneId: newId, id: null });
        else select({ kind: ref.kind, sceneId: ref.sceneId ?? null, id: newId });
        return null;
      } catch (error) {
        if (error instanceof DocOpError) return error.message;
        throw error;
      }
    },
  };
}

function FieldGroups({ fields, values, selfId, currentCentre, order }: { fields: FieldSpec[]; values: Record<string, Json | undefined>; selfId?: string | null; currentCentre?: [number, number] | null; order?: FieldGroup[] }) {
  const groups = order ?? (['identity', 'main', 'caption', 'position', 'style', 'timing'] as FieldGroup[]);
  return (
    <>
      {groups.map((group) => {
        const inGroup = fields.filter((f) => f.group === group);
        if (inGroup.length === 0) return null;
        return (
          <section key={group} aria-label={GROUP_TITLES[group] || 'Main'}>
            {GROUP_TITLES[group] ? <h3 className="group-title">{GROUP_TITLES[group]}</h3> : null}
            {inGroup.map((f) => (
              <Field key={f.name} spec={f} path={[f.name]} value={values[f.name]} selfId={selfId} currentCentre={currentCentre} />
            ))}
          </section>
        );
      })}
    </>
  );
}

export function PropertiesPanel() {
  const doc = useEditor((s) => s.history?.present ?? null);
  const schema = useEditor((s) => s.schema);
  const selection = useEditor((s) => s.selection);
  const focusRequest = useEditor((s) => s.focusRequest);
  const problems = useProblems();
  const body = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!focusRequest || !body.current) return undefined;
    const root = body.current;
    // The input for the field itself, else for the closest field enclosing it
    const frame = requestAnimationFrame(() => {
      for (let loc = focusRequest.field; loc.length > 0; loc = loc.slice(0, -1)) {
        const key = formatLoc(loc).replace(/["\\]/g, '\\$&');
        const target = root.querySelector<HTMLElement>(`[data-field="${key}"]`);
        const focusable = target && (target.matches('input, select, textarea, button') ? target : target.querySelector<HTMLElement>('input, select, textarea, button'));
        if (focusable) {
          focusable.scrollIntoView({ block: 'center' });
          focusable.focus();
          return;
        }
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [focusRequest]);

  if (!doc || !schema) return <aside className="properties" aria-label="Properties" />;
  const scene = selection.sceneId ? (findScene(doc, selection.sceneId) ?? null) : null;

  let content: React.ReactNode;
  if (selection.kind === 'object' && scene && selection.id) {
    content = <ObjectProperties doc={doc} schema={schema} scene={scene} objectId={selection.id} problems={problems} />;
  } else if (selection.kind === 'step' && scene && selection.id) {
    content = <StepProperties doc={doc} schema={schema} scene={scene} stepId={selection.id} problems={problems} />;
  } else if (selection.kind === 'scene' && scene) {
    content = <SceneProperties doc={doc} schema={schema} scene={scene} problems={problems} />;
  } else if (selection.kind === 'document') {
    content = <DocumentProperties doc={doc} schema={schema} problems={problems} />;
  } else {
    content = <NothingSelected />;
  }
  return (
    <aside className="properties" aria-label="Properties">
      <div ref={body} style={{ display: 'contents' }}>
        {content}
      </div>
    </aside>
  );
}

function NothingSelected() {
  return (
    <div className="props-empty">
      <h2>Nothing selected</h2>
      <p>Select something to change it here:</p>
      <ul>
        <li>click an object on the picture,</li>
        <li>or pick an object or a step from the lists on the left.</li>
      </ul>
      <p>
        New here? Add an <strong>object</strong> (text, an equation, a shape), then a <strong>step</strong> to show it. Steps play one after
        another; the picture shows the moment after the selected step.
      </p>
      <button type="button" className="btn btn-sm" onClick={() => select({ kind: 'document', sceneId: null, id: null })}>
        <Icon name="settings" /> Video settings
      </button>
    </div>
  );
}

function ItemHeader({ icon, title, subtitle, description, children }: { icon: string; title: string; subtitle?: string; description?: string; children?: React.ReactNode }) {
  return (
    <div className="props-header">
      <h2 className="kind" style={{ margin: 0 }}>
        <span className="kind-badge">
          <Icon name={icon} />
        </span>
        <span>{title}</span>
        {subtitle ? <span className="row-sub mono" style={{ fontWeight: 400 }}>{subtitle}</span> : null}
      </h2>
      {description ? <p className="desc">{description}</p> : null}
      {children ? <div className="actions">{children}</div> : null}
    </div>
  );
}

function ObjectProperties({ doc, schema, scene, objectId, problems }: { doc: Document; schema: SchemaIndex; scene: Scene; objectId: string; problems: Problem[] }) {
  const obj = findObject(doc, scene.id, objectId);
  const still = useEditor((s) => s.still);
  const frameIndex = useEditor((s) => frameStepIndex(s, scene.id));
  const ctx = useMemo(
    () => makeContext(schema, doc, scene, { kind: 'object', sceneId: scene.id, id: objectId }, problems, `obj-${objectId}`),
    [schema, doc, scene, objectId, problems],
  );
  if (!obj) return <NothingSelected />;
  const kind = objectKind(schema, obj.type);
  const fields = objectFields(schema, obj.type);
  const onScreen = onScreenAfter(scene, frameIndex).has(obj.id);
  const box = still?.sceneId === scene.id ? still.objects.find((o) => o.id === obj.id) : undefined;
  const centre: [number, number] | null = box ? [(box.frame_bbox[0] + box.frame_bbox[2]) / 2, (box.frame_bbox[1] + box.frame_bbox[3]) / 2] : null;
  const own = problemsForField(problems, ctx.item, [], { exact: true, doc });
  return (
    <FormContext.Provider value={ctx}>
      <ItemHeader icon={categoryIcon(kind?.category)} title={kind?.label ?? obj.type} subtitle={obj.id} description={kind?.description}>
        <button type="button" className="btn btn-sm" onClick={() => duplicateObjectById(scene.id, obj.id)}>
          <Icon name="copy" /> Duplicate
        </button>
        <button type="button" className="btn btn-sm" onClick={() => requestRemoveObject(scene.id, obj.id)}>
          <Icon name="trash" /> Delete
        </button>
      </ItemHeader>
      <div className="props-body" data-item-kind="object" data-item-id={obj.id}>
        {!onScreen ? (
          <div className="offscreen-note" style={{ margin: '10px 0 0' }}>
            <span>Not on screen at this point of the scene.</span>
            <button type="button" className="btn btn-sm" onClick={() => showObjects([obj.id])}>
              <Icon name="eye" /> Add a step to show it
            </button>
          </div>
        ) : null}
        <FieldProblems problems={own} />
        <FieldGroups fields={fields} values={obj} selfId={obj.id} currentCentre={centre} />
      </div>
    </FormContext.Provider>
  );
}

function StepProperties({ doc, schema, scene, stepId, problems }: { doc: Document; schema: SchemaIndex; scene: Scene; stepId: string; problems: Problem[] }) {
  const step = findStep(doc, scene.id, stepId);
  const ctx = useMemo(
    () => makeContext(schema, doc, scene, { kind: 'step', sceneId: scene.id, id: stepId }, problems, `step-${stepId}`),
    [schema, doc, scene, stepId, problems],
  );
  if (!step) return <NothingSelected />;
  const kind = stepKind(schema, step.do);
  const fields = stepFields(schema, step.do);
  const index = (scene.steps ?? []).findIndex((s) => s.id === stepId);
  const own = problemsForField(problems, ctx.item, [], { exact: true, doc });
  return (
    <FormContext.Provider value={ctx}>
      <ItemHeader
        icon={stepIcon(step.do)}
        title={`${kind?.label ?? step.do} step`}
        subtitle={index >= 0 ? `${index + 1} of ${scene.steps?.length ?? 0}` : 'inside together'}
        description={kind?.description}
      >
        {index >= 0 ? (
          <button type="button" className="btn btn-sm" onClick={() => openPreview({ sceneId: scene.id, start: index, end: index })}>
            <Icon name="play" /> Preview step
          </button>
        ) : null}
        <button type="button" className="btn btn-sm" onClick={() => duplicateStepById(scene.id, stepId)}>
          <Icon name="copy" /> Duplicate
        </button>
        <button type="button" className="btn btn-sm" onClick={() => removeStepById(scene.id, stepId)}>
          <Icon name="trash" /> Delete
        </button>
      </ItemHeader>
      <div className="props-body" data-item-kind="step" data-item-id={stepId}>
        <FieldProblems problems={own} />
        <FieldGroups fields={fields} values={step} order={['main', 'caption', 'timing', 'identity']} />
      </div>
    </FormContext.Provider>
  );
}

function SceneProperties({ doc, schema, scene, problems }: { doc: Document; schema: SchemaIndex; scene: Scene; problems: Problem[] }) {
  const ctx = useMemo(
    () => makeContext(schema, doc, scene, { kind: 'scene', sceneId: scene.id }, problems, `scene-${scene.id}`),
    [schema, doc, scene, problems],
  );
  const timeline = useEditor((s) => s.timelines[scene.id]);
  const index = doc.scenes.findIndex((s) => s.id === scene.id);
  const own = problemsForField(problems, ctx.item, [], { exact: true, doc });
  return (
    <FormContext.Provider value={ctx}>
      <ItemHeader
        icon="scene"
        title={scene.title || scene.id}
        subtitle={`scene ${index + 1} of ${doc.scenes.length}`}
        description={`${scene.objects?.length ?? 0} objects, ${scene.steps?.length ?? 0} steps${timeline ? `, ${timeline.duration.toFixed(1)} s` : ''}.`}
      >
        <button type="button" className="btn btn-sm" onClick={() => openPreview({ sceneId: scene.id, start: 0, end: Math.max(0, (scene.steps?.length ?? 1) - 1) })} disabled={!scene.steps?.length}>
          <Icon name="play" /> Preview scene
        </button>
        <button type="button" className="btn btn-sm" onClick={() => duplicateSceneById(scene.id)}>
          <Icon name="copy" /> Duplicate
        </button>
        <button type="button" className="btn btn-sm" onClick={() => requestRemoveScene(scene.id)} disabled={doc.scenes.length <= 1}>
          <Icon name="trash" /> Delete
        </button>
      </ItemHeader>
      <div className="props-body" data-item-kind="scene" data-item-id={scene.id}>
        <FieldProblems problems={own} />
        {sceneFields(schema).map((f) => (
          <Field key={f.name} spec={f} path={[f.name]} value={fieldOf(scene, f.name)} />
        ))}
      </div>
    </FormContext.Provider>
  );
}

function DocumentProperties({ doc, schema, problems }: { doc: Document; schema: SchemaIndex; problems: Problem[] }) {
  const ctx = useMemo(() => makeContext(schema, doc, null, { kind: 'document' }, problems, 'doc'), [schema, doc, problems]);
  return (
    <FormContext.Provider value={ctx}>
      <ItemHeader icon="settings" title="Video settings" description="Settings for the whole video: its title, size, frame rate, background and captions." />
      <div className="props-body" data-item-kind="document">
        {documentFields(schema).map((f) => (
          <Field key={f.name} spec={f} path={[f.name]} value={fieldOf(doc, f.name)} />
        ))}
      </div>
    </FormContext.Provider>
  );
}
