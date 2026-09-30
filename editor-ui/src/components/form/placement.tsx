/**
 * Where an object sits: centred, against an edge, beside another object, or at a point
 * (in frame units, or in a coordinate system's coordinates), then optionally nudged.
 */
import type { Edge, Json, JsonObject, Placement, Scene, Side } from '../../doc/types';
import type { SchemaIndex } from '../../lib/schema';
import { humanize } from '../../lib/schema';
import { Icon } from '../Icon';
import type { WidgetProps } from './basic';
import { NumberWidget } from './basic';
import { TupleEditor } from './points';
import { RefSelect, refOptions } from './refs';

type Mode = 'centre' | 'edge' | 'next_to' | 'at';

const EDGE_GRID: Edge[] = ['top_left', 'top', 'top_right', 'left', 'center', 'right', 'bottom_left', 'bottom', 'bottom_right'];
const SIDES: Side[] = ['up', 'down', 'left', 'right'];
const COORDINATE_SYSTEMS = ['number_plane', 'axes', 'axes_3d', 'number_line'];

/** A placement in its full form, whichever way it was written. */
export function normalizePlacement(value: Json | undefined): Placement | null {
  if (value === undefined || value === null) return null;
  if (typeof value === 'string') return { edge: value as Edge };
  if (Array.isArray(value)) return { at: value as number[] };
  return value as Placement;
}

export function placementMode(place: Placement | null): Mode {
  if (!place) return 'centre';
  if (place.edge) return 'edge';
  if (place.next_to) return 'next_to';
  if (place.at) return 'at';
  return 'centre';
}

function clean(place: Placement): JsonObject {
  const out: JsonObject = {};
  for (const [key, v] of Object.entries(place)) if (v !== undefined && v !== null) out[key] = v as Json;
  return out;
}

export function PlacementWidget({
  spec, value, onChange, inputId, dataField, scene, schema, selfId, currentCentre,
}: WidgetProps & { scene: Scene | null; schema: SchemaIndex; selfId?: string | null; currentCentre?: [number, number] | null }) {
  const place = normalizePlacement(value);
  const mode = placementMode(place);
  // For an object, no placement means centred; for a move, it means "not moving to a place"
  const isMove = spec.name === 'to';
  const unset = place === null;
  const write = (next: Placement | null, coalesce = false) => {
    if (next === null) return onChange(undefined);
    const cleaned = clean(next);
    if (Object.keys(cleaned).length === 0 && !isMove) return onChange(undefined);
    onChange(cleaned, { coalesce });
  };
  const shift = place?.shift ?? null;
  const buff = place?.buff;

  const switchTo = (next: Mode) => {
    const keep: Placement = {};
    if (shift) keep.shift = shift;
    if (next === 'centre') return write(keep);
    if (next === 'edge') return write({ ...keep, edge: 'top', ...(buff !== undefined ? { buff } : {}) });
    if (next === 'next_to') {
      const first = refOptions(schema, scene, null, selfId)[0];
      return write({ ...keep, next_to: first?.id ?? '', ...(buff !== undefined ? { buff } : {}) });
    }
    const at = currentCentre ? [Math.round(currentCentre[0] * 100) / 100, Math.round(currentCentre[1] * 100) / 100] : [0, 0];
    return write({ at });
  };

  const modes: { mode: Mode; label: string }[] = [
    { mode: 'centre', label: 'Centre' },
    { mode: 'edge', label: 'Edge' },
    { mode: 'next_to', label: 'Next to' },
    { mode: 'at', label: 'Point' },
  ];

  if (isMove && unset) {
    return (
      <div>
        <p className="field-help" style={{ marginTop: 0 }}>Not moving to a place. Use this or “Move by”, not both.</p>
        <button type="button" className="btn btn-sm" id={inputId} data-field={dataField} onClick={() => write({ edge: 'top' })}>
          <Icon name="move" /> Move to a place
        </button>
      </div>
    );
  }

  const systems = refOptions(schema, scene, COORDINATE_SYSTEMS, selfId);

  return (
    <div data-field={dataField}>
      <div className="inline">
        <div className="segmented" role="radiogroup" aria-label={`${spec.label}: how it is placed`}>
          {modes.map(({ mode: m, label }, i) => (
            <button
              key={m}
              type="button"
              role="radio"
              id={i === 0 ? inputId : undefined}
              aria-checked={mode === m}
              tabIndex={mode === m ? 0 : -1}
              onClick={() => switchTo(m)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
                  e.preventDefault();
                  const next = modes[(i + (e.key === 'ArrowRight' ? 1 : modes.length - 1)) % modes.length]!.mode;
                  switchTo(next);
                  const buttons = e.currentTarget.parentElement?.querySelectorAll('button');
                  (buttons?.[modes.findIndex((x) => x.mode === next)] as HTMLButtonElement | undefined)?.focus();
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        {isMove ? (
          <button type="button" className="icon-btn" aria-label="Don't move to a place" title="Clear" onClick={() => write(null)}>
            <Icon name="x" />
          </button>
        ) : null}
      </div>

      {mode === 'edge' && place ? (
        <div className="sub-fields">
          <div className="sub-label" id={`${inputId}-edge`}>Edge or corner of the frame</div>
          <div className="edge-grid" role="group" aria-labelledby={`${inputId}-edge`}>
            {EDGE_GRID.map((edge) => (
              <button
                key={edge}
                type="button"
                aria-label={humanize(edge)}
                title={humanize(edge)}
                aria-pressed={place.edge === edge}
                data-field={place.edge === edge ? `${dataField}.edge` : undefined}
                onClick={() => write({ ...place, edge })}
              />
            ))}
          </div>
          <BuffInput place={place} write={write} inputId={`${inputId}-buff`} dataField={`${dataField}.buff`} label="Gap from the edge" />
        </div>
      ) : null}

      {mode === 'next_to' && place ? (
        <div className="sub-fields">
          <div>
            <div className="sub-label">Beside</div>
            <RefSelect
              value={place.next_to ?? ''}
              options={refOptions(schema, scene, null, selfId)}
              onChange={(id) => write({ ...place, next_to: id ?? '' })}
              allowNone={false}
              ariaLabel={`${spec.label}: beside which object`}
              dataField={`${dataField}.next_to`}
            />
          </div>
          <div>
            <div className="sub-label">On its</div>
            <div className="segmented" role="radiogroup" aria-label={`${spec.label}: which side`}>
              {SIDES.map((side) => (
                <button
                  key={side}
                  type="button"
                  role="radio"
                  aria-checked={(place.side ?? 'down') === side}
                  data-field={(place.side ?? 'down') === side ? `${dataField}.side` : undefined}
                  onClick={() => write({ ...place, side: side === 'down' ? undefined : side })}
                >
                  {side === 'up' ? 'Above' : side === 'down' ? 'Below' : side === 'left' ? 'Left' : 'Right'}
                </button>
              ))}
            </div>
          </div>
          <BuffInput place={place} write={write} inputId={`${inputId}-buff`} dataField={`${dataField}.buff`} label="Gap between them" />
        </div>
      ) : null}

      {mode === 'at' && place ? (
        <div className="sub-fields">
          <div>
            <div className="sub-label">Centre at</div>
            <TupleEditor
              value={place.at ?? [0, 0]}
              names={['x', 'y']}
              minItems={2}
              onChange={(at) => write({ ...place, at: (at as number[] | undefined) ?? [0, 0] }, true)}
              inputId={`${inputId}-at`}
              dataField={`${dataField}.at`}
              required
              groupLabel={`${spec.label} point`}
            />
          </div>
          <div>
            <div className="sub-label">In the coordinates of</div>
            <RefSelect
              value={place.on ?? ''}
              options={systems}
              onChange={(id) => write({ ...place, on: id })}
              allowNone
              noneLabel="The frame (x from about −7 to 7, y from −4 to 4)"
              ariaLabel={`${spec.label}: coordinates of`}
              dataField={`${dataField}.on`}
            />
          </div>
        </div>
      ) : null}

      {!unset || !isMove ? (
        <div className="sub-fields" style={{ borderLeftColor: 'transparent', paddingTop: 0 }}>
          <div>
            <div className="sub-label">Then nudge by (optional)</div>
            <TupleEditor
              value={shift ?? undefined}
              names={['x', 'y']}
              minItems={2}
              onChange={(s) => write({ ...(place ?? {}), shift: (s as number[] | undefined) ?? null }, true)}
              inputId={`${inputId}-shift`}
              dataField={`${dataField}.shift`}
              required={false}
              groupLabel={`${spec.label} nudge`}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BuffInput({ place, write, inputId, dataField, label }: { place: Placement; write: (p: Placement, coalesce?: boolean) => void; inputId: string; dataField: string; label: string }) {
  return (
    <div>
      <label className="sub-label" htmlFor={inputId}>{label}</label>
      <NumberWidget
        spec={{ name: 'buff', label, kind: 'number', required: false, nullable: false, default: 0.25, minimum: 0, group: 'main' }}
        value={place.buff}
        onChange={(v) => write({ ...place, buff: v as number | undefined }, true)}
        inputId={inputId}
        dataField={dataField}
      />
    </div>
  );
}
