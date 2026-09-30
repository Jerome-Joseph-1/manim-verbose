/** Lists and tables: colored parts, row colors, matrix entries, bullet items. */
import { useState } from 'react';
import type { Json, JsonObject } from '../../doc/types';
import { endEditBurst } from '../../state/store';
import { Icon } from '../Icon';
import type { WidgetProps } from './basic';
import { ColorWidget } from './color';
import type { FieldSpec } from '../../lib/schema';

const colorSpec = (label: string, required = true): FieldSpec => ({ name: 'color', label, kind: 'color', required, nullable: false, group: 'main' });

/** {part: color}: which pieces of a text or formula get which color. */
export function ColorMapWidget({ spec, value, onChange, inputId, dataField }: WidgetProps) {
  const map: JsonObject = value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonObject) : {};
  const entries = Object.entries(map);
  const [newPart, setNewPart] = useState('');
  const write = (next: [string, Json][], coalesce = false) => onChange(next.length ? Object.fromEntries(next) : undefined, { coalesce });
  const add = () => {
    const part = newPart.trim();
    if (!part || part in map) return;
    write([...entries, [part, 'YELLOW']]);
    setNewPart('');
  };
  return (
    <div className="list-editor" data-field={dataField}>
      {entries.map(([part, color], i) => (
        <div className="list-row" key={i}>
          <input
            className="input mono"
            style={{ flex: '0 0 38%' }}
            aria-label={`Colored part ${i + 1}`}
            value={part}
            data-field={`${dataField}.${part}`}
            onChange={(e) => {
              const key = e.target.value;
              if (key === '' || (key !== part && key in map)) return;
              write(entries.map(([k, v], j) => (j === i ? [key, v] : [k, v])), true);
            }}
            onBlur={endEditBurst}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <ColorWidget
              spec={colorSpec(`Color of ${part}`)}
              value={color}
              onChange={(c) => c !== undefined && write(entries.map(([k, v], j) => (j === i ? [k, c as Json] : [k, v])), true)}
              inputId={`${inputId}-c${i}`}
              dataField={`${dataField}.${part}`}
              ariaLabel={`Color of ${part}`}
            />
          </div>
          <button type="button" className="icon-btn danger" aria-label={`Remove colored part ${part}`} onClick={() => write(entries.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div className="inline">
        <input
          id={inputId}
          className="input mono"
          placeholder={spec.description?.includes('tex') || spec.name === 'colors' ? 'Part, such as c^2' : 'Part'}
          aria-label={`${spec.label}: new part to color`}
          value={newPart}
          onChange={(e) => setNewPart(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="btn btn-sm" onClick={add} disabled={!newPart.trim() || newPart.trim() in map}>
          <Icon name="plus" /> Color it
        </button>
      </div>
    </div>
  );
}

export function ColorListWidget({ spec, value, onChange, inputId, dataField }: WidgetProps) {
  const colors = Array.isArray(value) ? (value as Json[]) : [];
  const write = (next: Json[], coalesce = false) => onChange(next.length ? next : undefined, { coalesce });
  return (
    <div className="list-editor" data-field={dataField}>
      {colors.map((color, i) => (
        <div className="list-row" key={i}>
          <span className="row-sub" style={{ width: 18 }}>{i + 1}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <ColorWidget
              spec={colorSpec(`${spec.label} ${i + 1}`)}
              value={color}
              onChange={(c) => c !== undefined && write(colors.map((x, j) => (j === i ? (c as Json) : x)), true)}
              inputId={`${inputId}-${i}`}
              dataField={`${dataField}[${i}]`}
              ariaLabel={`${spec.label} ${i + 1}`}
            />
          </div>
          <button type="button" className="icon-btn danger" aria-label={`Remove ${spec.label.toLowerCase()} ${i + 1}`} onClick={() => write(colors.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" id={inputId} className="btn btn-sm" onClick={() => write([...colors, 'BLUE'])}>
          <Icon name="plus" /> Add a color
        </button>
      </div>
    </div>
  );
}

function cellText(value: Json | undefined): string {
  if (value === undefined || value === null) return '';
  return String(value);
}

/**
 * A grid of entries. Matrix objects hold LaTeX (a number typed stays a number); an
 * apply-matrix step holds numbers only, 2x2 or 3x3.
 */
export function MatrixWidget({ spec, value, onChange, inputId, dataField, numeric }: WidgetProps & { numeric?: boolean }) {
  const rows: Json[][] = Array.isArray(value) && value.every(Array.isArray) ? (value as Json[][]) : [[1, 0], [0, 1]];
  const cols = Math.max(1, ...rows.map((r) => r.length));
  const write = (next: Json[][]) => onChange(next, { coalesce: true });
  const setCell = (r: number, c: number, text: string) => {
    let cell: Json = text;
    const n = Number(text);
    if (text.trim() !== '' && Number.isFinite(n)) cell = n;
    else if (numeric) return;
    write(rows.map((row, i) => (i === r ? Array.from({ length: cols }, (_, j) => (j === c ? cell : (row[j] ?? 0))) : row)));
  };
  const square = (n: number) => write(Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (rows[i]?.[j] ?? (i === j ? 1 : 0)))));
  return (
    <div data-field={dataField}>
      <div className="matrix-grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }} role="group" aria-label={spec.label}>
        {rows.map((row, r) =>
          Array.from({ length: cols }, (_, c) => (
            <MatrixCell
              key={`${r}-${c}`}
              id={r === 0 && c === 0 ? inputId : undefined}
              dataField={`${dataField}[${r}][${c}]`}
              label={`Row ${r + 1}, column ${c + 1}`}
              value={row[c]}
              numeric={numeric}
              onChange={(text) => setCell(r, c, text)}
            />
          )),
        )}
      </div>
      <div className="inline" style={{ flexWrap: 'wrap' }}>
        {numeric ? (
          <div className="segmented" style={{ width: 'auto' }} role="radiogroup" aria-label="Matrix size">
            {[2, 3].map((n) => (
              <button key={n} type="button" role="radio" aria-checked={rows.length === n} style={{ padding: '0 10px' }} onClick={() => square(n)}>
                {n}×{n}
              </button>
            ))}
          </div>
        ) : (
          <>
            <button type="button" className="btn btn-sm" onClick={() => write([...rows, Array.from({ length: cols }, () => 0)])}>
              <Icon name="plus" /> Row
            </button>
            <button type="button" className="btn btn-sm" onClick={() => write(rows.map((row) => [...row, 0]))}>
              <Icon name="plus" /> Column
            </button>
            <button type="button" className="btn btn-sm" disabled={rows.length <= 1} onClick={() => write(rows.slice(0, -1))}>
              − Row
            </button>
            <button type="button" className="btn btn-sm" disabled={cols <= 1} onClick={() => write(rows.map((row) => row.slice(0, cols - 1)))}>
              − Column
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function MatrixCell({ id, dataField, label, value, numeric, onChange }: { id?: string; dataField: string; label: string; value: Json | undefined; numeric?: boolean; onChange: (text: string) => void }) {
  const [draft, setDraft] = useState(cellText(value));
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    if (cellText(value) !== draft && !(Number(draft) === value && draft.trim() !== '')) setDraft(cellText(value));
  }
  return (
    <input
      id={id}
      data-field={dataField}
      className={`input${numeric ? '' : ' mono'}`}
      aria-label={label}
      inputMode={numeric ? 'decimal' : undefined}
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value);
        onChange(e.target.value);
      }}
      onBlur={() => {
        setDraft(cellText(value));
        endEditBurst();
      }}
    />
  );
}

export function StringListWidget({ spec, value, onChange, inputId, dataField }: WidgetProps) {
  const items = Array.isArray(value) ? (value as Json[]).map((v) => (typeof v === 'string' ? v : String(v))) : [];
  const min = spec.minItems ?? 0;
  const write = (next: string[], coalesce = false) => onChange(next, { coalesce });
  return (
    <div className="list-editor" data-field={dataField}>
      {items.map((item, i) => (
        <div className="list-row" key={i}>
          <input
            id={i === 0 ? inputId : undefined}
            data-field={`${dataField}[${i}]`}
            className="input"
            aria-label={`${spec.label} ${i + 1}`}
            value={item}
            onChange={(e) => write(items.map((x, j) => (j === i ? e.target.value : x)), true)}
            onBlur={endEditBurst}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                write([...items.slice(0, i + 1), '', ...items.slice(i + 1)]);
                requestAnimationFrame(() => {
                  const inputs = (e.currentTarget.closest('.list-editor')?.querySelectorAll('input') ?? []) as NodeListOf<HTMLInputElement>;
                  inputs[i + 1]?.focus();
                });
              }
            }}
          />
          <button type="button" className="icon-btn" aria-label={`Move ${spec.label.toLowerCase()} ${i + 1} up`} disabled={i === 0} onClick={() => write(items.map((x, j) => (j === i - 1 ? items[i]! : j === i ? items[i - 1]! : x)))}>
            <Icon name="up" />
          </button>
          <button type="button" className="icon-btn danger" aria-label={`Remove ${spec.label.toLowerCase()} ${i + 1}`} disabled={items.length <= min} onClick={() => write(items.filter((_, j) => j !== i))}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      <div>
        <button type="button" id={items.length === 0 ? inputId : undefined} className="btn btn-sm" onClick={() => write([...items, ''])}>
          <Icon name="plus" /> Add
        </button>
      </div>
    </div>
  );
}
