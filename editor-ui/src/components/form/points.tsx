/** Points, ranges and short lists of numbers, one small input per coordinate. */
import { useState } from 'react';
import type { Json } from '../../doc/types';
import { endEditBurst } from '../../state/store';
import { Icon } from '../Icon';
import type { WidgetProps } from './basic';

function fmt(value: Json | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
}

/** One number of a tuple. Commits only numbers; empty reports null. */
export function CoordInput({
  value, label, onChange, id, dataField, invalid, placeholder, min, max,
}: {
  value: Json | undefined;
  label: string;
  onChange: (value: number | null) => void;
  id?: string;
  dataField?: string;
  invalid?: boolean;
  placeholder?: string;
  min?: number;
  max?: number;
}) {
  const [draft, setDraft] = useState(fmt(value));
  const [seen, setSeen] = useState(value);
  const [bad, setBad] = useState(false);
  if (value !== seen) {
    setSeen(value);
    if (draft.trim() === '' || Number(draft) !== value) {
      setDraft(fmt(value));
      setBad(false);
    }
  }
  return (
    <input
      id={id}
      data-field={dataField}
      className={`input${invalid || bad ? ' invalid' : ''}`}
      type="number"
      step={0.1}
      min={min}
      max={max}
      inputMode="decimal"
      aria-label={label}
      aria-invalid={invalid || bad ? true : undefined}
      placeholder={placeholder}
      value={draft}
      onChange={(e) => {
        const text = e.target.value;
        setDraft(text);
        if (text.trim() === '') {
          setBad(false);
          onChange(null);
          return;
        }
        const n = Number(text);
        if (Number.isFinite(n)) {
          setBad(false);
          onChange(n);
        } else {
          setBad(true);
        }
      }}
      onBlur={() => {
        setDraft(fmt(value));
        setBad(false);
        endEditBurst();
      }}
    />
  );
}

/**
 * A fixed-length list of numbers with a name for each place. Places past `minItems` are
 * optional: leaving the last one empty drops it.
 */
export function TupleEditor({
  value, names, minItems, onChange, inputId, dataField, invalid, required, defaults, groupLabel,
}: {
  value: Json | undefined;
  names: string[];
  minItems: number;
  onChange: (value: unknown, options?: { coalesce?: boolean }) => void;
  inputId: string;
  dataField: string;
  invalid?: boolean;
  required: boolean;
  defaults?: number[];
  groupLabel: string;
}) {
  const list = Array.isArray(value) ? (value as Json[]) : null;
  const base: (number | null)[] = names.map((_, i) => {
    const v = list?.[i];
    return typeof v === 'number' ? v : null;
  });
  const commit = (index: number, n: number | null) => {
    const next = [...base];
    next[index] = n;
    if (next.every((v) => v === null)) {
      onChange(required ? (defaults ?? next.map(() => 0)).slice(0, minItems) : undefined, { coalesce: true });
      return;
    }
    // Trailing empty optional places are dropped; others count as 0
    let length = next.length;
    while (length > minItems && next[length - 1] === null) length -= 1;
    const out = next.slice(0, length).map((v, i) => (v === null ? (defaults?.[i] ?? 0) : v));
    onChange(out, { coalesce: true });
  };
  return (
    <div className="inline" role="group" aria-label={groupLabel}>
      {names.map((name, i) => (
        <label className="coord" key={name}>
          <span aria-hidden="true">{name}</span>
          <CoordInput
            id={i === 0 ? inputId : undefined}
            dataField={i === 0 ? dataField : `${dataField}[${i}]`}
            label={`${groupLabel} ${name}`}
            value={list?.[i]}
            placeholder={i >= minItems ? '–' : defaults ? String(defaults[i] ?? '') : ''}
            invalid={invalid}
            onChange={(n) => commit(i, n)}
          />
        </label>
      ))}
      {!required && list ? (
        <button type="button" className="icon-btn" aria-label={`Clear ${groupLabel}`} title="Clear" onClick={() => onChange(undefined)}>
          <Icon name="x" />
        </button>
      ) : null}
    </div>
  );
}

export function PointWidget({ spec, value, onChange, inputId, dataField, invalid, ariaLabel }: WidgetProps & { ariaLabel?: string }) {
  const three = (spec.maxItems ?? 3) >= 3;
  const defaults = Array.isArray(spec.default) ? (spec.default as number[]) : undefined;
  return (
    <TupleEditor
      value={value}
      names={three ? ['x', 'y', 'z'] : ['x', 'y']}
      minItems={2}
      onChange={onChange}
      inputId={inputId}
      dataField={dataField}
      invalid={invalid}
      required={spec.required}
      defaults={defaults}
      groupLabel={ariaLabel ?? spec.label}
    />
  );
}

export function RangeWidget({ spec, value, onChange, inputId, dataField, invalid }: WidgetProps) {
  const defaults = Array.isArray(spec.default) ? (spec.default as number[]) : undefined;
  return (
    <TupleEditor
      value={value ?? (defaults as Json | undefined)}
      names={['from', 'to', 'step']}
      minItems={2}
      onChange={onChange}
      inputId={inputId}
      dataField={dataField}
      invalid={invalid}
      required
      defaults={defaults}
      groupLabel={spec.label}
    />
  );
}

const TUPLE_NAMES: Record<string, string[]> = {
  orientation: ['θ', 'φ', 'γ'],
  resolution: ['width', 'height'],
  x_range: ['from', 'to'],
};

export function NumberListWidget({ spec, value, onChange, inputId, dataField, invalid }: WidgetProps) {
  const max = spec.maxItems ?? 3;
  const names = (TUPLE_NAMES[spec.name] ?? ['1', '2', '3', '4']).slice(0, max);
  const defaults = Array.isArray(spec.default) ? (spec.default as number[]) : undefined;
  return (
    <TupleEditor
      value={value ?? (spec.required ? (defaults as Json | undefined) : undefined)}
      names={names}
      minItems={spec.minItems ?? names.length}
      onChange={onChange}
      inputId={inputId}
      dataField={dataField}
      invalid={invalid}
      required={spec.required || spec.default !== undefined && spec.default !== null}
      defaults={defaults}
      groupLabel={spec.label}
    />
  );
}

export function PointListWidget({ spec, value, onChange, inputId, dataField, invalid }: WidgetProps) {
  const points = Array.isArray(value) ? (value as Json[]) : [];
  const min = spec.minItems ?? 0;
  // A list of a fixed number of points (an angle's three) has a name for each and no add or remove
  const fixed = spec.maxItems !== undefined && spec.maxItems === spec.minItems;
  const set = (next: Json[], coalesce = false) => onChange(next, { coalesce });
  return (
    <div className="list-editor">
      {points.map((point, i) => (
        <div className="list-row" key={i}>
          {spec.itemNames?.[i] ? <span className="list-row-name">{spec.itemNames[i]}</span> : null}
          <TupleEditor
            value={point}
            names={['x', 'y']}
            minItems={2}
            onChange={(p) => set(points.map((q, j) => (j === i ? (p as Json) : q)), true)}
            inputId={i === 0 ? inputId : `${inputId}-${i}`}
            dataField={`${dataField}[${i}]`}
            invalid={invalid}
            required
            groupLabel={spec.itemNames?.[i] ?? `Point ${i + 1}`}
          />
          {fixed ? null : (
            <button
              type="button"
              className="icon-btn danger"
              aria-label={`Remove point ${i + 1}`}
              disabled={points.length <= min}
              title={points.length <= min ? `A ${spec.label.toLowerCase()} list needs at least ${min}` : 'Remove'}
              onClick={() => set(points.filter((_, j) => j !== i))}
            >
              <Icon name="trash" />
            </button>
          )}
        </div>
      ))}
      <div hidden={fixed && points.length >= (spec.maxItems ?? 0)}>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            const last = points.at(-1);
            const next = Array.isArray(last) && typeof last[0] === 'number' && typeof last[1] === 'number' ? [last[0] + 1, last[1]] : [0, 0];
            set([...points, next]);
          }}
        >
          <Icon name="plus" /> Add point
        </button>
      </div>
    </div>
  );
}
