/**
 * Filling in what a new object or step needs to be useful at once: the catalog's templates
 * leave references empty, and a step which shows nothing helps nobody. So a new "show"
 * shows the selected object, or the next one not on screen yet; a new brace goes around
 * the selected object; a graph goes on the first set of axes; and so on.
 */
import type { Catalog, CatalogEntry } from './api';
import { objectFields, stepFields, type FieldSpec, type SchemaIndex } from './schema';
import { onScreenAfter } from '../doc/screen';
import type { Json, Scene } from '../doc/types';
import type { Box } from './geometry';

export interface AddContext {
  scene: Scene;
  /** Index of the step whose end is showing; new steps go after it. */
  frameIndex: number;
  selectedObjectId: string | null;
}

type Template = Record<string, Json>;

function isEmptyRef(value: Json | undefined): boolean {
  return value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0);
}

function objectsOfTypes(scene: Scene, types: string[] | null | undefined, exclude: string | null = null): string[] {
  return (scene.objects ?? []).filter((o) => o.id !== exclude && (!types || types.includes(o.type))).map((o) => o.id);
}

/**
 * Fill a new object's empty references ("" in the catalog's templates) from what is in the
 * scene: the selected object if it is of a kind that fits, else the latest one that does.
 * A list of references ("members": ["", ""]) gets as many different objects as it has
 * places, as far as the scene has them; places left over are dropped.
 */
export function fillObjectTemplate(schema: SchemaIndex, template: Template, ctx: AddContext): Template {
  const out: Template = structuredClone(template);
  const type = String(out.type);
  const selected = ctx.selectedObjectId;
  for (const field of objectFields(schema, type)) {
    const value = out[field.name];
    if (field.kind === 'object-ref' && (value === '' || (field.required && value === undefined))) {
      const candidates = objectsOfTypes(ctx.scene, field.refTypes);
      const pick = selected && candidates.includes(selected) ? selected : candidates.at(-1);
      if (pick) out[field.name] = pick;
      else if (!field.required) delete out[field.name];
    } else if (field.kind === 'ref-list' && (Array.isArray(value) || (field.required && value === undefined))) {
      const list = Array.isArray(value) ? value : [''];
      const candidates = objectsOfTypes(ctx.scene, field.refTypes);
      const ordered = selected && candidates.includes(selected) ? [selected, ...candidates.filter((c) => c !== selected)] : candidates;
      const taken = new Set(list.filter((v): v is string => typeof v === 'string' && v !== ''));
      const free = ordered.filter((c) => !taken.has(c));
      const filled = list
        .map((v) => (v === '' ? (free.shift() ?? null) : v))
        .filter((v): v is Json => v !== null);
      out[field.name] = filled;
    }
  }
  return out;
}

/** Fill a new step's empty references: what to show, hide, move or change. */
export function fillStepTemplate(schema: SchemaIndex, template: Template, ctx: AddContext): Template {
  const out: Template = structuredClone(template);
  const kind = String(out.do);
  const onScreen = onScreenAfter(ctx.scene, ctx.frameIndex);
  const all = (ctx.scene.objects ?? []).map((o) => o.id);
  const offScreen = all.filter((id) => !onScreen.has(id));
  const selected = ctx.selectedObjectId && all.includes(ctx.selectedObjectId) ? ctx.selectedObjectId : null;
  const bringsOn = kind === 'show' || kind === 'add';
  const pickTarget = (): string | undefined => {
    if (bringsOn) return selected && !onScreen.has(selected) ? selected : (offScreen[0] ?? selected ?? all[0]);
    return selected && onScreen.has(selected) ? selected : (selected ?? [...onScreen].at(-1) ?? all[0]);
  };
  const specs = stepFields(schema, kind);
  const has = (name: string) => specs.some((f: FieldSpec) => f.name === name);
  if (has('target') && isEmptyRef(out.target)) {
    const target = pickTarget();
    if (target) out.target = target;
  }
  if (kind === 'transform' && isEmptyRef(out.into)) {
    const target = typeof out.target === 'string' ? out.target : null;
    const into = offScreen.find((id) => id !== target) ?? all.find((id) => id !== target);
    if (into) out.into = into;
  }
  if (kind === 'together' && Array.isArray(out.steps)) {
    const queue = [...offScreen];
    out.steps = out.steps.map((inner) => {
      if (inner && typeof inner === 'object' && !Array.isArray(inner) && isEmptyRef(inner.target)) {
        const next = queue.shift() ?? selected ?? all[0];
        return next ? { ...inner, target: next } : inner;
      }
      return inner;
    });
  }
  return out;
}

/**
 * Required references a filled-in template still leaves empty. An empty reference isn't a
 * valid id, so the server couldn't even read a document holding one; the editor doesn't add
 * such an object or step, and says what is missing instead.
 */
export function unfilledReferences(schema: SchemaIndex, template: Template): string[] {
  const isObject = typeof template.type === 'string';
  const fields = isObject ? objectFields(schema, String(template.type)) : stepFields(schema, String(template.do));
  const out: string[] = [];
  for (const field of fields) {
    const value = template[field.name];
    const refKind = field.kind === 'object-ref' || field.kind === 'targets' || field.kind === 'ref-list';
    if (!refKind) continue;
    if (value === '' || (Array.isArray(value) && (value.length === 0 || value.includes(''))) || (field.required && value === undefined)) {
      out.push(field.name);
    }
  }
  if (!isObject && Array.isArray(template.steps)) {
    for (const inner of template.steps) {
      if (inner && typeof inner === 'object' && !Array.isArray(inner)) out.push(...unfilledReferences(schema, inner as Template).map((n) => `steps.${n}`));
    }
  }
  return out;
}

/** A catalog made from the schema alone, for a server which doesn't offer one. */
export function catalogFromSchema(schema: SchemaIndex): Catalog {
  const defaultFor = (field: FieldSpec): Json | undefined => {
    switch (field.kind) {
      case 'text':
      case 'multiline':
        return field.name === 'text' ? 'Text' : '';
      case 'tex':
        return 'x^2';
      case 'expression':
        return 'x';
      case 'point':
        return [0, 0];
      case 'string-list':
        return ['Item'];
      case 'point-list':
        return [[-1, -1], [1, -1], [0, 1]];
      case 'matrix':
      case 'number-matrix':
        return [[1, 0], [0, 1]];
      case 'targets':
      case 'object-ref':
        return '';
      case 'ref-list':
        return [];
      case 'properties':
        return { color: 'YELLOW' };
      case 'file':
        return '';
      default:
        return undefined;
    }
  };
  const objects: CatalogEntry[] = schema.objectKinds.map((kind) => {
    const template: Template = { type: kind.name };
    for (const f of objectFields(schema, kind.name)) {
      if (f.required && f.name !== 'id') {
        const value = defaultFor(f);
        if (value !== undefined) template[f.name] = value;
      }
    }
    return { type: kind.name, label: kind.label, category: kind.category, description: kind.description, template };
  });
  const steps: CatalogEntry[] = schema.stepKinds.map((kind) => {
    const template: Template = { do: kind.name };
    for (const f of stepFields(schema, kind.name)) {
      if (f.required) {
        const value = kind.name === 'together' && f.name === 'steps' ? [{ do: 'show', target: '' }, { do: 'show', target: '' }] : defaultFor(f);
        if (value !== undefined) template[f.name] = value;
      }
    }
    if (kind.name === 'camera') template.zoom = 1.5;
    if (kind.name === 'move') template.by = [1, 0];
    return { do: kind.name, label: kind.label, description: kind.description, template };
  });
  return { objects, steps };
}

/**
 * Where to put a new object so it doesn't land on top of what is there: the centre if it is
 * free, else the first free band above or below it. Returns null for "leave it centred".
 */
export function suggestPosition(occupied: Box[]): [number, number] | null {
  const candidates = [0, -2, 2, -3, 1, -1, 3];
  const bandFree = (y: number) => !occupied.some(([, y0, , y1]) => y0 < y + 0.45 && y1 > y - 0.45 && !(y1 - y0 > 6));
  for (const y of candidates) {
    if (bandFree(y)) return y === 0 ? null : [0, y];
  }
  return null;
}
