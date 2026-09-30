/**
 * One field of the properties panel: its label, the right input for its kind, a line of
 * help, and any problems the server found with it, right underneath.
 */
import { useState } from 'react';
import type { Json, Loc, Problem } from '../../doc/types';
import { formatLoc } from '../../doc/paths';
import { problemsForField } from '../../lib/problems';
import type { FieldSpec, WidgetKind } from '../../lib/schema';
import { useForm } from './context';
import {
  BooleanWidget, EnumWidget, ExpressionWidget, FileWidget, JsonWidget, MultilineWidget, NumberWidget, TexWidget, TextWidget,
  type WidgetProps,
} from './basic';
import { ColorWidget } from './color';
import { NumberListWidget, PointListWidget, PointWidget, RangeWidget } from './points';
import { ObjectRefWidget, RefListWidget, TargetsWidget } from './refs';
import { PlacementWidget } from './placement';
import { ColorListWidget, ColorMapWidget, MatrixWidget, StringListWidget } from './collections';
import { NestedObjectWidget, PropertiesWidget, StepsWidget } from './nested';

/** Kinds whose inner fields show their own problems; the row shows only its own. */
const DELEGATING: WidgetKind[] = ['properties', 'steps', 'object'];

/** Kinds which draw their own label (a checkbox has it beside the box). */
const SELF_LABELLED: WidgetKind[] = ['boolean'];

export function FieldProblems({ problems, id }: { problems: Problem[]; id?: string }) {
  if (problems.length === 0) return null;
  return (
    <ul className="field-problems" id={id} aria-live="polite">
      {problems.map((p, i) => (
        <li key={i} className={`field-problem ${p.severity}`}>
          <span className="sr-only">{p.severity === 'error' ? 'Error: ' : 'Warning: '}</span>
          {p.message}
        </li>
      ))}
    </ul>
  );
}

export interface FieldProps {
  spec: FieldSpec;
  /** Path of the field inside the item. */
  path: Loc;
  value: Json | undefined;
  /** Id of the item itself, when a reference shouldn't offer it (a group can't contain itself). */
  selfId?: string | null;
  /** The object's centre in frame units, for starting a "point" placement where it is. */
  currentCentre?: [number, number] | null;
}

export function Field({ spec, path, value, selfId, currentCentre }: FieldProps) {
  const ctx = useForm();
  const key = formatLoc(path);
  const inputId = `${ctx.idPrefix}-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  const helpId = `${inputId}-help`;
  const problemsId = `${inputId}-problems`;
  const delegating = DELEGATING.includes(spec.kind);
  const problems = problemsForField(ctx.problems, ctx.item, path, { exact: delegating, doc: ctx.doc });
  const invalid = problems.some((p) => p.severity === 'error');
  const describedBy = [spec.description ? helpId : null, problems.length ? problemsId : null].filter(Boolean).join(' ') || undefined;
  const onChange = (next: unknown, options?: { coalesce?: boolean }) => ctx.commit(path, next, options);
  const props: WidgetProps = { spec, value, onChange, inputId, dataField: key, describedBy, invalid };

  if (spec.kind === 'id') return <IdField spec={spec} value={value} inputId={inputId} dataField={key} problems={problems} helpId={helpId} problemsId={problemsId} />;

  let widget;
  switch (spec.kind) {
    case 'text':
      widget = <TextWidget {...props} />;
      break;
    case 'multiline':
      widget = <MultilineWidget {...props} />;
      break;
    case 'tex':
      widget = <TexWidget {...props} />;
      break;
    case 'expression':
      widget = <ExpressionWidget {...props} />;
      break;
    case 'number':
      widget = <NumberWidget {...props} />;
      break;
    case 'boolean':
      widget = <BooleanWidget {...props} />;
      break;
    case 'enum':
      widget = <EnumWidget {...props} />;
      break;
    case 'color':
      widget = <ColorWidget {...props} />;
      break;
    case 'point':
      widget = <PointWidget {...props} />;
      break;
    case 'range':
      widget = <RangeWidget {...props} />;
      break;
    case 'number-list':
      widget = <NumberListWidget {...props} />;
      break;
    case 'point-list':
      widget = <PointListWidget {...props} />;
      break;
    case 'object-ref':
      widget = <ObjectRefWidget {...props} scene={ctx.scene} schema={ctx.schema} selfId={selfId} />;
      break;
    case 'targets':
      widget = <TargetsWidget {...props} scene={ctx.scene} schema={ctx.schema} />;
      break;
    case 'ref-list':
      widget = <RefListWidget {...props} scene={ctx.scene} schema={ctx.schema} selfId={selfId} />;
      break;
    case 'placement':
      widget = <PlacementWidget {...props} scene={ctx.scene} schema={ctx.schema} selfId={selfId} currentCentre={currentCentre} />;
      break;
    case 'color-map':
      widget = <ColorMapWidget {...props} />;
      break;
    case 'color-list':
      widget = <ColorListWidget {...props} />;
      break;
    case 'matrix':
      widget = <MatrixWidget {...props} />;
      break;
    case 'number-matrix':
      widget = <MatrixWidget {...props} numeric />;
      break;
    case 'string-list':
      widget = <StringListWidget {...props} />;
      break;
    case 'file':
      widget = <FileWidget {...props} />;
      break;
    case 'properties':
      widget = <PropertiesWidget {...props} path={path} />;
      break;
    case 'steps':
      widget = <StepsWidget {...props} path={path} />;
      break;
    case 'object':
      widget = <NestedObjectWidget {...props} path={path} />;
      break;
    default:
      widget = <JsonWidget {...props} />;
  }

  const labelled = !SELF_LABELLED.includes(spec.kind);
  const usesLabelFor = ['text', 'multiline', 'tex', 'expression', 'number', 'color', 'object-ref', 'file', 'json'].includes(spec.kind);
  return (
    <div className={`field${invalid ? ' has-error' : ''}`} data-kind={spec.kind} data-name={spec.name}>
      {labelled ? (
        usesLabelFor ? (
          <label className="field-label" htmlFor={inputId} id={`${inputId}-label`}>
            {spec.label}
            {!spec.required && spec.default === undefined && spec.kind !== 'placement' ? <span className="optional">optional</span> : null}
          </label>
        ) : (
          <div className="field-label" id={`${inputId}-label`}>
            {spec.label}
          </div>
        )
      ) : null}
      {usesLabelFor || !labelled ? widget : <div role="group" aria-labelledby={`${inputId}-label`}>{widget}</div>}
      {spec.description ? (
        <p className="field-help" id={helpId}>
          {spec.description}
        </p>
      ) : null}
      <FieldProblems problems={problems} id={problemsId} />
    </div>
  );
}

function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

/** The item's name: renamed on Enter or leaving the field, with every reference updated. */
function IdField({ spec, value, inputId, dataField, problems, helpId, problemsId }: { spec: FieldSpec; value: Json | undefined; inputId: string; dataField: string; problems: Problem[]; helpId: string; problemsId: string }) {
  const ctx = useForm();
  const current = typeof value === 'string' ? value : '';
  const [draft, setDraft] = useState(current);
  const [seen, setSeen] = useState(current);
  const [error, setError] = useState<string | null>(null);
  if (current !== seen) {
    setSeen(current);
    setDraft(current);
    setError(null);
  }
  const submit = () => {
    if (draft === current) return;
    const message = ctx.rename ? ctx.rename(draft) : 'This name can’t be changed here';
    setError(message);
    if (message) return;
  };
  const invalid = Boolean(error) || problems.some((p) => p.severity === 'error');
  return (
    <div className={`field${invalid ? ' has-error' : ''}`} data-kind="id" data-name={spec.name}>
      <label className="field-label" htmlFor={inputId}>
        {spec.label}
      </label>
      <input
        id={inputId}
        data-field={dataField}
        className={`input mono${invalid ? ' invalid' : ''}`}
        value={draft}
        spellCheck={false}
        aria-describedby={`${helpId}${problems.length ? ` ${problemsId}` : ''}`}
        aria-invalid={invalid || undefined}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
        onBlur={submit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit();
          } else if (e.key === 'Escape') {
            setDraft(current);
            setError(null);
          }
        }}
      />
      {error ? <div className="local-error" role="alert">{error}</div> : null}
      <p className="field-help" id={helpId}>
        {sentence(spec.description ?? 'Other parts of the video refer to it by this name')} Renaming updates every use.
      </p>
      <FieldProblems problems={problems} id={problemsId} />
    </div>
  );
}
