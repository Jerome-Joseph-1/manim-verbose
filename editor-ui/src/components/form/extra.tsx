/**
 * Inputs for the fields that need to know about the rest of the document: the part of an
 * object a brace, box or highlight picks out (a row of a matrix, some of a formula), the
 * objects a scene carries over from the one before, and fields with a few values of mixed
 * types (a transform's `keep`: no, yes, or dimmed).
 */
import { useRef, useState } from 'react';
import { carryCandidates, withDependencies, type CarriedObject } from '../../doc/carry';
import { findObject, findStep } from '../../doc/ops';
import { objectRefs } from '../../doc/refs';
import { onScreenAfter } from '../../doc/screen';
import type { Json, SceneObject } from '../../doc/types';
import { objectKind, type Choice } from '../../lib/schema';
import { endEditBurst } from '../../state/store';
import { useForm } from './context';
import type { WidgetProps } from './basic';

// Choices

function sameValue(a: Json | undefined, b: Json | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

export function ChoiceWidget({ spec, value, onChange, inputId, dataField }: WidgetProps) {
  const choices: Choice[] = spec.choices ?? [];
  const current = value === undefined ? (spec.default ?? choices[0]?.value) : value;
  const write = (choice: Choice) => onChange(sameValue(choice.value, spec.default) && !spec.required ? undefined : choice.value);
  return (
    <div className="segmented" role="radiogroup" aria-labelledby={`${inputId}-label`} data-field={dataField}>
      {choices.map((choice, i) => {
        const checked = sameValue(current, choice.value);
        return (
          <button
            key={String(choice.value)}
            type="button"
            role="radio"
            id={i === 0 ? inputId : undefined}
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            onClick={() => write(choice)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                e.preventDefault();
                const next = (i + (e.key === 'ArrowRight' ? 1 : choices.length - 1)) % choices.length;
                write(choices[next]!);
                const buttons = (e.currentTarget.parentElement?.querySelectorAll('button') ?? []) as NodeListOf<HTMLButtonElement>;
                buttons[next]?.focus();
              }
            }}
          >
            {choice.label}
          </button>
        );
      })}
    </div>
  );
}

// Parts

/** Which field holds the text of a kind of object a part can be found in. */
export const PART_FIELDS: Record<string, string> = { text: 'text', tex: 'tex', title: 'text', quote: 'text' };

const MATRIX_PART = /^\s*(row|column|entry)\s+(\d+)(?:\s*[, ]\s*(\d+))?\s*$/i;

export interface MatrixPart {
  kind: 'row' | 'column' | 'entry';
  row: number;
  column: number;
}

/** "row 2", "column 1", "entry 2 1" (counting from 1) as a MatrixPart; null for anything else. */
export function parseMatrixPart(part: string): MatrixPart | null {
  const match = MATRIX_PART.exec(part);
  if (!match) return null;
  const kind = match[1]!.toLowerCase() as MatrixPart['kind'];
  const first = Number(match[2]);
  const second = match[3] === undefined ? null : Number(match[3]);
  if ((kind === 'entry') !== (second !== null)) return null;
  return kind === 'row' ? { kind, row: first, column: 1 } : kind === 'column' ? { kind, row: 1, column: first } : { kind, row: first, column: second! };
}

export function formatMatrixPart(part: MatrixPart): string {
  return part.kind === 'row' ? `row ${part.row}` : part.kind === 'column' ? `column ${part.column}` : `entry ${part.row} ${part.column}`;
}

/** The object whose part a `part` field picks out: the `target` of the object or step it is in. */
function usePartTarget(): SceneObject | null {
  const ctx = useForm();
  const { item } = ctx;
  let targetId: Json | undefined;
  if (item.kind === 'object' && item.sceneId && item.itemId) targetId = findObject(ctx.doc, item.sceneId, item.itemId)?.target;
  else if (item.kind === 'step' && item.sceneId && item.itemId) targetId = findStep(ctx.doc, item.sceneId, item.itemId)?.target;
  if (typeof targetId !== 'string') return null;
  return ctx.scene?.objects?.find((o) => o.id === targetId) ?? null;
}

export function PartWidget(props: WidgetProps) {
  const target = usePartTarget();
  if (target?.type === 'matrix' && Array.isArray(target.entries)) return <MatrixPartPicker {...props} matrix={target} />;
  const field = target ? PART_FIELDS[target.type] : undefined;
  return <TextPartPicker {...props} target={target} text={field && typeof target?.[field] === 'string' ? (target[field] as string) : null} />;
}

/** The text selected inside an element, if the selection is all inside it. */
function selectedWithin(el: HTMLElement | null): string {
  const selection = typeof window !== 'undefined' ? window.getSelection() : null;
  if (!el || !selection || selection.isCollapsed || !selection.anchorNode || !selection.focusNode) return '';
  return el.contains(selection.anchorNode) && el.contains(selection.focusNode) ? selection.toString() : '';
}

function TextPartPicker({ spec, value, onChange, inputId, dataField, describedBy, invalid, target, text }: WidgetProps & { target: SceneObject | null; text: string | null }) {
  const part = typeof value === 'string' ? value : '';
  const preview = useRef<HTMLDivElement>(null);
  const [chosen, setChosen] = useState('');
  const [hint, setHint] = useState<string | null>(null);
  const at = text !== null && part ? text.indexOf(part) : -1;
  const remember = () => {
    setChosen(selectedWithin(preview.current));
    setHint(null);
  };
  return (
    <div className="part-picker">
      <input
        id={inputId}
        data-field={dataField}
        className={`input mono${invalid ? ' invalid' : ''}`}
        type="text"
        value={part}
        placeholder={text ? 'All of it' : spec.required ? '' : 'Not set'}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value === '' && !spec.required ? undefined : e.target.value, { coalesce: true })}
        onBlur={endEditBurst}
      />
      {text !== null ? (
        <div className="part-preview" data-testid="part-preview">
          <div
            ref={preview}
            className="part-text"
            aria-label={`The text of ${target?.id}, with the part picked out. Select some of it to pick that out instead.`}
            onMouseUp={remember}
            onKeyUp={remember}
          >
            {at >= 0 ? (
              <>
                {text.slice(0, at)}
                <mark>{text.slice(at, at + part.length)}</mark>
                {text.slice(at + part.length)}
              </>
            ) : (
              text
            )}
          </div>
          {part && at < 0 ? (
            <div className="local-error" role="status">
              “{part}” doesn't appear in {target?.id}
            </div>
          ) : null}
          <div className="inline part-select">
            <button
              type="button"
              className="btn btn-sm"
              // Keep the selection in the text above while the button is pressed
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                const picked = selectedWithin(preview.current) || chosen;
                if (picked.trim()) onChange(picked);
                else setHint(`Select some of ${target?.id}'s text above first, by dragging over it`);
              }}
            >
              Pick out the selected text
            </button>
            {part ? (
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => onChange(spec.required ? '' : undefined)}>
                All of it
              </button>
            ) : null}
          </div>
          {hint ? <p className="field-help">{hint}</p> : null}
        </div>
      ) : target ? (
        <p className="field-help">Only parts of text, formulas, titles, quotes and matrices can be picked out, and {target.id} is a {target.type.replace(/_/g, ' ')}.</p>
      ) : null}
    </div>
  );
}

function MatrixPartPicker({ spec, value, onChange, inputId, dataField, matrix }: WidgetProps & { matrix: SceneObject }) {
  const entries = (matrix.entries as Json[][]).filter(Array.isArray);
  const rows = entries.length;
  const columns = entries[0]?.length ?? 0;
  const part = typeof value === 'string' ? value : '';
  const parsed = part ? parseMatrixPart(part) : null;
  const mode: 'all' | MatrixPart['kind'] | 'text' = !part ? 'all' : parsed ? parsed.kind : 'text';
  const current: MatrixPart = parsed ?? { kind: 'row', row: 1, column: 1 };
  const write = (next: MatrixPart | null) => onChange(next ? formatMatrixPart(next) : spec.required ? '' : undefined);
  const numbers = (n: number) => Array.from({ length: n }, (_, i) => i + 1);
  const chosen = (r: number, c: number) =>
    parsed !== null && (parsed.kind === 'row' ? parsed.row === r : parsed.kind === 'column' ? parsed.column === c : parsed.row === r && parsed.column === c);
  return (
    <div className="part-picker" data-field={dataField}>
      <div className="inline">
        <select
          id={inputId}
          className="select"
          value={mode}
          aria-label={`${spec.label}: which part of ${matrix.id}`}
          onChange={(e) => {
            const kind = e.target.value;
            if (kind === 'all') write(null);
            else if (kind === 'text') onChange(String(entries[0]?.[0] ?? ''));
            else write({ ...current, kind: kind as MatrixPart['kind'] });
          }}
        >
          <option value="all">The whole matrix</option>
          <option value="row">A row</option>
          <option value="column">A column</option>
          <option value="entry">One entry</option>
          <option value="text">Entries showing…</option>
        </select>
        {mode === 'row' || mode === 'entry' ? (
          <select className="select narrow" aria-label="Row" value={current.row} onChange={(e) => write({ ...current, row: Number(e.target.value) })}>
            {numbers(rows).map((n) => (
              <option key={n} value={n}>
                row {n}
              </option>
            ))}
          </select>
        ) : null}
        {mode === 'column' || mode === 'entry' ? (
          <select className="select narrow" aria-label="Column" value={current.column} onChange={(e) => write({ ...current, column: Number(e.target.value) })}>
            {numbers(columns).map((n) => (
              <option key={n} value={n}>
                column {n}
              </option>
            ))}
          </select>
        ) : null}
        {mode === 'text' ? (
          <input className="input mono" type="text" value={part} aria-label="The text of an entry" onChange={(e) => onChange(e.target.value, { coalesce: true })} onBlur={endEditBurst} />
        ) : null}
      </div>
      <table className="matrix-preview" data-testid="matrix-preview">
        <tbody>
          {entries.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td key={c}>
                  <button
                    type="button"
                    className={chosen(r + 1, c + 1) || (mode === 'text' && String(cell) === part) ? 'picked' : ''}
                    aria-label={`Entry ${r + 1} ${c + 1}: ${String(cell)}`}
                    tabIndex={-1}
                    onClick={() => write({ kind: 'entry', row: r + 1, column: c + 1 })}
                  >
                    {String(cell)}
                  </button>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="field-help">Or click an entry above to pick it.</p>
    </div>
  );
}

// Carrying objects over

export function CarryWidget({ value, onChange, inputId, dataField }: WidgetProps) {
  const ctx = useForm();
  const sceneId = ctx.item.sceneId ?? '';
  const index = ctx.doc.scenes.findIndex((s) => s.id === sceneId);
  const candidates = carryCandidates(ctx.doc, sceneId);
  const carried = Array.isArray(value) ? (value as Json[]).filter((v): v is string => typeof v === 'string') : [];
  if (index <= 0) return <p className="field-help" id={inputId}>The first scene has no scene before it to carry objects over from.</p>;
  if (candidates.length === 0) return <p className="field-help" id={inputId}>The scene before has no objects to carry over.</p>;
  const previous = ctx.doc.scenes[index - 1]!;
  const atEnd = onScreenAfter(previous, (previous.steps ?? []).length - 1);
  const own = new Set((ctx.doc.scenes[index]!.objects ?? []).map((o) => o.id));
  const dependsOn = (candidate: CarriedObject, id: string) => withDependencies(candidates, [candidate.object.id]).includes(id);
  const toggle = (id: string, on: boolean) => {
    let next: string[];
    if (on) {
      const wanted = withDependencies(candidates, [...carried, id]);
      // In the order of the scene before, so the list reads the same way
      next = candidates.map((c) => c.object.id).filter((c) => wanted.includes(c) || carried.includes(c));
    } else {
      // Anything built on it has to go too
      next = carried.filter((c) => c !== id && !candidates.some((cand) => cand.object.id === c && dependsOn(cand, id)));
    }
    onChange(next.length ? next : undefined);
  };
  return (
    <fieldset className="carry-list" id={inputId} data-field={dataField}>
      <legend className="sr-only">Objects to carry over from scene {previous.title || previous.id}</legend>
      {candidates.map(({ object: obj }) => {
        const checked = carried.includes(obj.id);
        const clash = own.has(obj.id);
        const needs = objectRefs(obj).map((r) => r.id).filter((r) => candidates.some((c) => c.object.id === r));
        return (
          <label key={obj.id} className={`checkbox carry-item${clash ? ' disabled' : ''}`}>
            <input type="checkbox" checked={checked} disabled={clash && !checked} onChange={(e) => toggle(obj.id, e.target.checked)} />
            <span className="mono">{obj.id}</span>
            <span className="row-sub">{objectKind(ctx.schema, obj.type)?.label ?? obj.type}</span>
            {clash ? <span className="row-sub">(this scene has its own {obj.id})</span> : null}
            {!atEnd.has(obj.id) ? <span className="offscreen" title={`Not on screen at the end of scene ${previous.id}`}>hidden there</span> : null}
            {needs.length ? <span className="row-sub" title="Carried along with it">+ {needs.join(', ')}</span> : null}
          </label>
        );
      })}
      <p className="field-help">Anything one of them is built on (the plane a vector is on) is carried along with it.</p>
    </fieldset>
  );
}
