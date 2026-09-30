/** Inputs for single values: text, numbers, switches, choices. */
import { useState } from 'react';
import { checkNumber, humanize, type FieldSpec } from '../../lib/schema';
import type { Json } from '../../doc/types';
import { endEditBurst } from '../../state/store';

export interface WidgetProps {
  spec: FieldSpec;
  value: Json | undefined;
  onChange: (value: unknown, options?: { coalesce?: boolean }) => void;
  inputId: string;
  dataField: string;
  describedBy?: string;
  invalid?: boolean;
}

function placeholderFor(spec: FieldSpec): string {
  if (spec.default !== undefined && spec.default !== null && typeof spec.default !== 'object') return `${spec.default} (default)`;
  if (!spec.required) return 'Not set';
  return '';
}

/** Plain text on one line. Empty clears an optional field. */
export function TextWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, mono }: WidgetProps & { mono?: boolean }) {
  return (
    <input
      id={inputId}
      data-field={dataField}
      className={`input${mono ? ' mono' : ''}${invalid ? ' invalid' : ''}`}
      type="text"
      value={typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value)}
      placeholder={placeholderFor(spec)}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      spellCheck={!mono}
      onChange={(e) => {
        const text = e.target.value;
        onChange(text === '' && !spec.required ? undefined : text, { coalesce: true });
      }}
      onBlur={endEditBurst}
    />
  );
}

/** Text over several lines, growing as it fills. */
export function MultilineWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, mono, rows }: WidgetProps & { mono?: boolean; rows?: number }) {
  const text = typeof value === 'string' ? value : '';
  const lines = Math.min(10, Math.max(rows ?? 2, text.split('\n').length));
  return (
    <textarea
      id={inputId}
      data-field={dataField}
      className={`input${mono ? ' mono' : ''}${invalid ? ' invalid' : ''}`}
      rows={lines}
      value={text}
      placeholder={placeholderFor(spec)}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      spellCheck={!mono}
      onChange={(e) => {
        const next = e.target.value;
        onChange(next === '' && !spec.required ? undefined : next, { coalesce: true });
      }}
      onBlur={endEditBurst}
    />
  );
}

export function TexWidget(props: WidgetProps) {
  return <MultilineWidget {...props} mono rows={1} />;
}

export function ExpressionWidget(props: WidgetProps) {
  return <TextWidget {...props} mono />;
}

function formatNumber(value: Json | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
}

/**
 * A number, kept as typed while it is being typed (so "0." or "-" don't get eaten), and
 * written to the document only once it is a number within the field's limits.
 */
export function NumberWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, ariaLabel, compact }: WidgetProps & { ariaLabel?: string; compact?: boolean }) {
  const [draft, setDraft] = useState(formatNumber(value));
  const [error, setError] = useState<string | null>(null);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    // The value changed from outside (undo, a drag on the canvas): show it, unless the
    // draft already says the same thing in its own way ("1." for 1)
    setSeen(value);
    if (draft.trim() === '' || Number(draft) !== value) {
      setDraft(formatNumber(value));
      setError(null);
    }
  }
  const step = spec.integer ? 1 : Math.abs((spec.maximum ?? 10) - (spec.minimum ?? 0)) <= 1 ? 0.05 : 0.1;
  return (
    <div className={compact ? 'coord' : undefined} style={compact ? undefined : { width: '100%' }}>
      <input
        id={inputId}
        data-field={dataField}
        className={`input${invalid || error ? ' invalid' : ''}`}
        type="number"
        inputMode="decimal"
        step={step}
        min={spec.minimum ?? spec.exclusiveMinimum}
        max={spec.maximum ?? spec.exclusiveMaximum}
        value={draft}
        placeholder={compact ? '' : placeholderFor(spec)}
        aria-label={ariaLabel}
        aria-describedby={describedBy}
        aria-invalid={invalid || error ? true : undefined}
        onBlur={() => {
          setDraft(formatNumber(value));
          setError(null);
          endEditBurst();
        }}
        onChange={(e) => {
          const text = e.target.value;
          setDraft(text);
          if (text.trim() === '') {
            if (spec.required) {
              setError('Enter a number');
            } else {
              setError(null);
              onChange(undefined, { coalesce: true });
            }
            return;
          }
          const n = Number(text);
          const problem = checkNumber(spec, n);
          setError(problem);
          if (!problem) onChange(n, { coalesce: true });
        }}
      />
      {error && !compact ? <div className="local-error" role="alert">{error}</div> : null}
    </div>
  );
}

export function BooleanWidget({ spec, value, onChange, inputId, dataField, describedBy }: WidgetProps) {
  const checked = typeof value === 'boolean' ? value : spec.default === true;
  return (
    <label className="checkbox" htmlFor={inputId}>
      <input
        id={inputId}
        data-field={dataField}
        type="checkbox"
        checked={checked}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.checked === (spec.default === true) && !spec.required ? undefined : e.target.checked)}
      />
      {spec.label}
    </label>
  );
}

export function EnumWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid }: WidgetProps) {
  const options = spec.enumValues ?? [];
  const current = typeof value === 'string' ? value : typeof spec.default === 'string' ? spec.default : '';
  if (options.length <= 4 && options.every((o) => o.length <= 8)) {
    return (
      <div className="segmented" role="radiogroup" aria-labelledby={`${inputId}-label`} data-field={dataField}>
        {options.map((option, i) => (
          <button
            key={option}
            type="button"
            role="radio"
            id={i === 0 ? inputId : undefined}
            aria-checked={current === option}
            tabIndex={current === option || (!options.includes(current) && i === 0) ? 0 : -1}
            onClick={() => onChange(option === spec.default && !spec.required ? undefined : option)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                const next = options[(i + (e.key === 'ArrowRight' ? 1 : options.length - 1)) % options.length]!;
                onChange(next === spec.default && !spec.required ? undefined : next);
                const buttons = (e.currentTarget.parentElement?.querySelectorAll('button') ?? []) as NodeListOf<HTMLButtonElement>;
                buttons[options.indexOf(next)]?.focus();
              }
            }}
          >
            {humanize(option)}
          </button>
        ))}
      </div>
    );
  }
  return (
    <select
      id={inputId}
      data-field={dataField}
      className={`select${invalid ? ' invalid' : ''}`}
      value={current}
      aria-labelledby={`${inputId}-label`}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value === spec.default && !spec.required ? undefined : e.target.value)}
    >
      {!options.includes(current) ? <option value={current}>{current || 'Choose…'}</option> : null}
      {options.map((option) => (
        <option key={option} value={option}>
          {humanize(option)}
          {option === spec.default ? ' (default)' : ''}
        </option>
      ))}
    </select>
  );
}

export function FileWidget(props: WidgetProps) {
  return (
    <div>
      <TextWidget {...props} mono />
      <p className="field-help">
        A file in the same folder as the scene file (or below it){props.spec.accept ? `, such as ${props.spec.accept === '.svg' ? 'drawing.svg' : 'picture.png'}` : ''}.
      </p>
    </div>
  );
}

/** Anything the editor has no better input for: its JSON, checked before it is written. */
export function JsonWidget({ value, onChange, inputId, dataField, describedBy }: WidgetProps) {
  const [draft, setDraft] = useState(() => (value === undefined ? '' : JSON.stringify(value)));
  const [error, setError] = useState<string | null>(null);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    let same = false;
    try {
      same = JSON.stringify(JSON.parse(draft)) === JSON.stringify(value);
    } catch {
      same = false;
    }
    if (!same) {
      setDraft(value === undefined ? '' : JSON.stringify(value));
      setError(null);
    }
  }
  return (
    <div>
      <textarea
        id={inputId}
        data-field={dataField}
        className={`input mono${error ? ' invalid' : ''}`}
        rows={2}
        value={draft}
        aria-describedby={describedBy}
        onChange={(e) => {
          setDraft(e.target.value);
          if (e.target.value.trim() === '') {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value), { coalesce: true });
            setError(null);
          } catch {
            setError('Not valid yet: write it as JSON, such as [1, 2] or "text"');
          }
        }}
        onBlur={endEditBurst}
      />
      {error ? <div className="local-error">{error}</div> : null}
    </div>
  );
}
