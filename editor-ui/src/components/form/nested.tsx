/**
 * Fields holding other fields: the new values a change step sets (each drawn with the
 * input of the target's field), the steps inside a "together" step, and nested settings.
 */
import { useMemo } from 'react';
import type { Json, JsonObject, Loc, Step } from '../../doc/types';
import { findStep } from '../../doc/ops';
import { newStepId, stepIds } from '../../doc/ids';
import { fillStepTemplate } from '../../lib/templates';
import { objectKind, settableFields, stepFields, stepKind, type FieldSpec } from '../../lib/schema';
import { problemsForField } from '../../lib/problems';
import { useEditor, frameStepIndex } from '../../state/store';
import { Icon, stepIcon } from '../Icon';
import { FormContext, useForm } from './context';
import type { WidgetProps } from './basic';
import { Field, FieldProblems } from './Field';

/** A starting value for a field being added to a change step. */
function startingValue(spec: FieldSpec, current: Json | undefined): Json {
  if (current !== undefined) return structuredClone(current);
  if (spec.default !== undefined && spec.default !== null) return structuredClone(spec.default);
  switch (spec.kind) {
    case 'color':
      return 'YELLOW';
    case 'number':
      return spec.minimum ?? (spec.exclusiveMinimum !== undefined ? spec.exclusiveMinimum + 1 : 1);
    case 'boolean':
      return true;
    case 'point':
      return [0, 0];
    case 'placement':
      return { edge: 'top' };
    case 'string-list':
      return [''];
    default:
      return '';
  }
}

/** `set` of a change step: pick properties of the target's kind, then their values. */
export function PropertiesWidget({ value, inputId, path }: WidgetProps & { path: Loc }) {
  const ctx = useForm();
  const set: JsonObject = value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : {};
  const step = ctx.item.itemId && ctx.item.sceneId ? findStep(ctx.doc, ctx.item.sceneId, ctx.item.itemId) : undefined;
  const targetId = typeof step?.target === 'string' ? step.target : null;
  const target = targetId ? ctx.scene?.objects?.find((o) => o.id === targetId) : undefined;
  const fields = useMemo(() => (target ? settableFields(ctx.schema, target.type) : []), [ctx.schema, target]);
  if (!target) {
    return <p className="field-help">Choose the object to change first; then pick which of its properties to change.</p>;
  }
  const kindLabel = objectKind(ctx.schema, target.type)?.label ?? target.type;
  const available = fields.filter((f) => !(f.name in set));
  return (
    <div>
      {Object.entries(set).map(([key, v]) => {
        // A property the target doesn't have still gets an input (as JSON), so it can be fixed
        const spec: FieldSpec = fields.find((f) => f.name === key) ?? { name: key, label: key, kind: 'json', required: true, nullable: false, group: 'main' };
        return (
          <div className="set-row" key={key}>
            <div className="set-row-head">
              <span className="sr-only">{spec.label}</span>
              <button type="button" className="icon-btn danger" aria-label={`Stop changing ${spec.label.toLowerCase()}`} title="Don't change this" onClick={() => ctx.commit([...path, key], undefined)}>
                <Icon name="trash" />
              </button>
            </div>
            <Field spec={{ ...spec, required: true, description: undefined }} path={[...path, key]} value={v} selfId={target.id} />
          </div>
        );
      })}
      {Object.keys(set).length === 0 ? <p className="field-help">Nothing to change yet: pick a property below.</p> : null}
      <select
        id={inputId}
        data-field={formatPath(path)}
        className="select"
        value=""
        aria-label={`Add a property of the ${kindLabel.toLowerCase()} to change`}
        onChange={(e) => {
          const spec = fields.find((f) => f.name === e.target.value);
          if (spec) ctx.commit([...path, spec.name], startingValue(spec, target[spec.name]));
        }}
      >
        <option value="">Change another property of {target.id}…</option>
        {available.map((f) => (
          <option key={f.name} value={f.name}>
            {f.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function formatPath(path: Loc): string {
  return path.map((p, i) => (typeof p === 'number' ? `[${p}]` : i ? `.${p}` : p)).join('');
}

const NOT_INSIDE_TOGETHER = new Set(['wait', 'together']);

/** The steps of a "together" step, each with its own fields. */
export function StepsWidget({ value, inputId, path }: WidgetProps & { path: Loc }) {
  const ctx = useForm();
  const steps = Array.isArray(value) ? (value as unknown as Step[]) : [];
  const frameIndex = useEditor((s) => (ctx.item.sceneId ? frameStepIndex(s, ctx.item.sceneId) : -1));
  const kinds = ctx.schema.stepKinds.filter((k) => !NOT_INSIDE_TOGETHER.has(k.name));
  const add = (kind: string) => {
    if (!ctx.scene) return;
    const template = fillStepTemplate(ctx.schema, { do: kind, ...(kind === 'show' || kind === 'hide' ? { target: '' } : {}) }, {
      scene: ctx.scene,
      frameIndex: Math.max(-1, frameIndex - 1),
      selectedObjectId: null,
    });
    const id = newStepId(ctx.scene.id, stepIds(ctx.doc));
    ctx.commit(path, [...steps, { id, ...template }]);
  };
  return (
    <div>
      {steps.map((inner, i) => (
        <NestedStep key={inner.id ?? i} step={inner} index={i} path={[...path, i]} canRemove={steps.length > 2} />
      ))}
      <select
        id={inputId}
        data-field={formatPath(path)}
        className="select"
        value=""
        aria-label="Add a step to run at the same time"
        onChange={(e) => e.target.value && add(e.target.value)}
      >
        <option value="">Add a step to run at the same time…</option>
        {kinds.map((k) => (
          <option key={k.name} value={k.name}>
            {k.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function NestedStep({ step, index, path, canRemove }: { step: Step; index: number; path: Loc; canRemove: boolean }) {
  const ctx = useForm();
  const kind = stepKind(ctx.schema, step.do);
  const fields = stepFields(ctx.schema, step.do).filter((f) => f.name !== 'id' && f.name !== 'caption');
  const inner = useMemo(
    () => ({
      ...ctx,
      item: { kind: 'step' as const, sceneId: ctx.item.sceneId ?? null, itemId: step.id ?? null },
      commit: (p: Loc, v: unknown, o?: { coalesce?: boolean }) => ctx.commit([...path, ...p], v, o),
      idPrefix: `${ctx.idPrefix}-s${index}`,
      rename: undefined,
    }),
    [ctx, step.id, path, index],
  );
  const own = problemsForField(ctx.problems, inner.item, [], { exact: true, doc: ctx.doc });
  return (
    <div className="nested" data-step-id={step.id ?? undefined}>
      <div className="nested-head">
        <Icon name={stepIcon(step.do)} />
        <span>
          {index + 1}. {kind?.label ?? step.do}
        </span>
        <button
          type="button"
          className="icon-btn danger push"
          aria-label={`Remove ${kind?.label ?? step.do} step ${index + 1} from together`}
          title={canRemove ? 'Remove' : '"Together" needs at least two steps'}
          disabled={!canRemove}
          onClick={() => ctx.commit(path, undefined)}
        >
          <Icon name="trash" />
        </button>
      </div>
      <FieldProblems problems={own} />
      <FormContext.Provider value={inner}>
        {fields.map((f) => (
          <Field key={f.name} spec={f} path={[f.name]} value={step[f.name]} />
        ))}
      </FormContext.Provider>
    </div>
  );
}

/** A nested model, such as the document's settings and their captions. */
export function NestedObjectWidget({ spec, value, path }: WidgetProps & { path: Loc }) {
  const obj: JsonObject = value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : {};
  return (
    <div className="sub-fields">
      {(spec.fields ?? []).map((f) => (
        <Field key={f.name} spec={f} path={[...path, f.name]} value={obj[f.name]} />
      ))}
    </div>
  );
}
