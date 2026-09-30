/** Picking other objects of the scene: one, one or several, or a list. */
import type { Json, Scene } from '../../doc/types';
import { objectKind, type SchemaIndex } from '../../lib/schema';
import { Icon } from '../Icon';
import type { WidgetProps } from './basic';

export interface RefOption {
  id: string;
  label: string;
}

/** Objects of the scene a reference may name, filtered by the kinds it allows. */
export function refOptions(schema: SchemaIndex, scene: Scene | null, types: string[] | null | undefined, exclude?: string | null): RefOption[] {
  return (scene?.objects ?? [])
    .filter((o) => o.id !== exclude && (!types || types.includes(o.type)))
    .map((o) => ({ id: o.id, label: `${o.id} (${objectKind(schema, o.type)?.label ?? o.type})` }));
}

function kindsText(types: string[] | null | undefined): string {
  if (!types) return 'objects';
  return types.map((t) => t.replace(/_/g, ' ')).join(' or ');
}

export function RefSelect({
  value, options, onChange, inputId, dataField, describedBy, invalid, allowNone, noneLabel, ariaLabel, types,
}: {
  value: string;
  options: RefOption[];
  onChange: (id: string | undefined) => void;
  inputId?: string;
  dataField?: string;
  describedBy?: string;
  invalid?: boolean;
  allowNone: boolean;
  noneLabel?: string;
  ariaLabel?: string;
  types?: string[] | null;
}) {
  const missing = value !== '' && !options.some((o) => o.id === value);
  return (
    <select
      id={inputId}
      data-field={dataField}
      className={`select${invalid || missing ? ' invalid' : ''}`}
      value={value}
      aria-label={ariaLabel}
      aria-describedby={describedBy}
      aria-invalid={invalid || missing || undefined}
      onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)}
    >
      {allowNone || value === '' ? <option value="">{allowNone ? (noneLabel ?? 'None') : `Choose… (${kindsText(types)})`}</option> : null}
      {missing ? <option value={value}>{value} (not in this scene)</option> : null}
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function ObjectRefWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, scene, schema, selfId }: WidgetProps & { scene: Scene | null; schema: SchemaIndex; selfId?: string | null }) {
  const options = refOptions(schema, scene, spec.refTypes, selfId);
  return (
    <div>
      <RefSelect
        value={typeof value === 'string' ? value : ''}
        options={options}
        onChange={(id) => onChange(id ?? (spec.required ? '' : undefined))}
        inputId={inputId}
        dataField={dataField}
        describedBy={describedBy}
        invalid={invalid}
        allowNone={!spec.required}
        types={spec.refTypes}
      />
      {options.length === 0 ? (
        <p className="field-help">There are no {kindsText(spec.refTypes)} in this scene yet: add one from Objects on the left.</p>
      ) : null}
    </div>
  );
}

/** Chips for the chosen objects and a menu to add another. */
function RefChips({
  ids, options, onChange, inputId, dataField, describedBy, invalid, label, min,
}: {
  ids: string[];
  options: RefOption[];
  onChange: (ids: string[]) => void;
  inputId: string;
  dataField: string;
  describedBy?: string;
  invalid?: boolean;
  label: string;
  min: number;
}) {
  const known = new Set(options.map((o) => o.id));
  const remaining = options.filter((o) => !ids.includes(o.id));
  return (
    <div>
      {ids.length ? (
        <ul className="chips" aria-label={`${label}: chosen`} style={{ listStyle: 'none', padding: 0, margin: '0 0 6px' }}>
          {ids.map((id, i) => (
            <li key={`${id}-${i}`} className={`chip${known.has(id) ? '' : ' missing'}`}>
              <span>{id || '(empty)'}</span>
              <button
                type="button"
                aria-label={`Remove ${id || 'empty entry'} from ${label}`}
                title="Remove"
                disabled={ids.length <= min}
                onClick={() => onChange(ids.filter((_, j) => j !== i))}
              >
                <Icon name="x" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <select
        id={inputId}
        data-field={dataField}
        className={`select${invalid ? ' invalid' : ''}`}
        value=""
        aria-label={`${label}: add an object`}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        disabled={remaining.length === 0}
        onChange={(e) => {
          if (e.target.value) onChange([...ids.filter((id) => id !== ''), e.target.value]);
        }}
      >
        <option value="">{remaining.length ? (ids.length ? 'Add another…' : 'Choose an object…') : 'No more objects to add'}</option>
        {remaining.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** `target`: one object, or several at once. Written as a string for one, a list for more. */
export function TargetsWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, scene, schema }: WidgetProps & { scene: Scene | null; schema: SchemaIndex }) {
  const ids = typeof value === 'string' ? (value ? [value] : []) : Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
  return (
    <RefChips
      ids={ids}
      options={refOptions(schema, scene, spec.refTypes)}
      onChange={(next) => onChange(next.length === 0 ? '' : next.length === 1 ? next[0] : next)}
      inputId={inputId}
      dataField={dataField}
      describedBy={describedBy}
      invalid={invalid}
      label={spec.label}
      min={0}
    />
  );
}

export function RefListWidget({ spec, value, onChange, inputId, dataField, describedBy, invalid, scene, schema, selfId }: WidgetProps & { scene: Scene | null; schema: SchemaIndex; selfId?: string | null }) {
  const ids = Array.isArray(value) ? (value as Json[]).filter((v): v is string => typeof v === 'string') : [];
  return (
    <RefChips
      ids={ids}
      options={refOptions(schema, scene, spec.refTypes, selfId)}
      onChange={(next) => onChange(next)}
      inputId={inputId}
      dataField={dataField}
      describedBy={describedBy}
      invalid={invalid}
      label={spec.label}
      min={0}
    />
  );
}
