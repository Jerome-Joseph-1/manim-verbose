/**
 * The json schema of a document (manim_verbose/scenefile/schema.json), turned into what the
 * properties panel draws: for each kind of object or step, its fields in order, each with
 * the kind of input it needs, its label, help text, default and limits.
 *
 * Fields say which input they want through `x-widget`; the rest is read off the json types.
 * Pydantic puts `x-widget` inside the non-null branch of an optional field (`color`) or on
 * the field itself (`caption`), so both are looked at.
 */
import type { Json } from '../doc/types';

export interface JsonSchema {
  $ref?: string;
  type?: string | string[];
  title?: string;
  description?: string;
  default?: Json;
  const?: Json;
  enum?: Json[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  required?: string[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minItems?: number;
  maxItems?: number;
  minProperties?: number;
  maxLength?: number;
  pattern?: string;
  discriminator?: { propertyName: string; mapping: Record<string, string> };
  $defs?: Record<string, JsonSchema>;
  'x-widget'?: string;
  'x-ref-types'?: string[];
  'x-label'?: string;
  'x-category'?: string;
  accept?: string;
  [key: string]: unknown;
}

export type WidgetKind =
  | 'id'
  | 'text'
  | 'multiline'
  | 'tex'
  | 'expression'
  | 'number'
  | 'boolean'
  | 'enum'
  | 'color'
  | 'point'
  | 'range'
  | 'number-list'
  | 'object-ref'
  | 'targets'
  | 'ref-list'
  | 'placement'
  | 'color-map'
  | 'color-list'
  | 'matrix'
  | 'number-matrix'
  | 'string-list'
  | 'point-list'
  | 'properties'
  | 'steps'
  | 'file'
  | 'object'
  | 'json';

export type FieldGroup = 'identity' | 'main' | 'position' | 'style' | 'caption' | 'timing';

export interface FieldSpec {
  name: string;
  label: string;
  description?: string;
  kind: WidgetKind;
  required: boolean;
  nullable: boolean;
  default?: Json;
  integer?: boolean;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  enumValues?: string[];
  refTypes?: string[] | null;
  accept?: string;
  minItems?: number;
  maxItems?: number;
  group: FieldGroup;
  /** For kind 'object': the fields of the nested mapping. */
  fields?: FieldSpec[];
}

export interface KindInfo {
  /** The value of `type` (objects) or `do` (steps). */
  name: string;
  defName: string;
  label: string;
  category: string;
  description: string;
}

export interface SchemaIndex {
  root: JsonSchema;
  defs: Record<string, JsonSchema>;
  objectKinds: KindInfo[];
  stepKinds: KindInfo[];
}

/** The order categories of object are offered in. */
export const CATEGORY_ORDER = ['Text & math', 'Shapes', 'Geometry', 'Coordinates', 'Annotations', 'Media', 'Layout'];

function defName(ref: string): string {
  return ref.replace(/^#\/\$defs\//, '');
}

export function deref(index: Pick<SchemaIndex, 'defs'>, schema: JsonSchema): JsonSchema {
  let node = schema;
  const seen = new Set<string>();
  while (node.$ref) {
    const name = defName(node.$ref);
    if (seen.has(name)) break;
    seen.add(name);
    const target = index.defs[name];
    if (!target) break;
    const { $ref: _ref, ...rest } = node;
    void _ref;
    node = { ...target, ...rest };
  }
  return node;
}

function kindsFrom(defs: Record<string, JsonSchema>, container: JsonSchema | undefined, tag: string): KindInfo[] {
  const mapping = container?.items?.discriminator?.mapping ?? {};
  return Object.entries(mapping).map(([name, ref]) => {
    const def = defs[defName(ref)] ?? {};
    return {
      name,
      defName: defName(ref),
      label: typeof def['x-label'] === 'string' ? def['x-label'] : humanize(name),
      category: typeof def['x-category'] === 'string' ? def['x-category'] : tag,
      description: firstParagraph(def.description ?? ''),
    };
  });
}

export function buildSchemaIndex(root: JsonSchema): SchemaIndex {
  const defs = root.$defs ?? {};
  const scene = defs.SceneSpec;
  const objectKinds = kindsFrom(defs, scene?.properties?.objects, 'Other');
  const stepKinds = kindsFrom(defs, scene?.properties?.steps, 'Steps');
  const categoryRank = (c: string) => {
    const i = CATEGORY_ORDER.indexOf(c);
    return i < 0 ? CATEGORY_ORDER.length : i;
  };
  objectKinds.sort((a, b) => categoryRank(a.category) - categoryRank(b.category));
  return { root, defs, objectKinds, stepKinds };
}

export function objectKind(index: SchemaIndex, type: string): KindInfo | undefined {
  return index.objectKinds.find((k) => k.name === type);
}

export function stepKind(index: SchemaIndex, name: string): KindInfo | undefined {
  return index.stepKinds.find((k) => k.name === name);
}

// Labels

/** "font_size" -> "Font size"; "Font Size" -> "Font size". */
export function humanize(name: string): string {
  const words = name.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim().split(/\s+/);
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w.toLowerCase())).join(' ');
}

export function firstParagraph(text: string): string {
  return text.split(/\n\s*\n/)[0]!.replace(/\s*\n\s*/g, ' ').trim();
}

/** Plainer words than the field names for a few fields. */
const LABELS: Record<string, string> = {
  id: 'Name',
  z: 'Layer',
  shown: 'On screen from the start',
  place: 'Position',
  rotate: 'Rotation (degrees)',
  run_time: 'Duration (seconds)',
  lag: 'Stagger',
  buff: 'Gap',
  on: 'Coordinate system',
  target: 'Object',
  into: 'Turn into',
  set: 'New values',
  to: 'Move to',
  by: 'Move by',
  tip: 'Tip',
  tail: 'Tail',
  x_range: 'X range',
  y_range: 'Y range',
  z_range: 'Z range',
  fill: 'Fill color',
  label_side: 'Label side',
  show_coordinates: 'Show coordinates',
  font: 'Font',
  keep: 'Keep the original',
  part: 'Part to highlight',
  focus: 'Centre on object',
  reset: 'Back to the normal view',
  steps: 'Steps at the same time',
  members: 'Members',
  entries: 'Entries',
  items: 'Items',
  colors: 'Colored parts',
  function: 'Function of x',
  path: 'File',
  do: 'Kind',
  background: 'Background color',
  resolution: 'Resolution',
  fps: 'Frames per second',
  captions: 'Captions',
};

const DESCRIPTIONS: Record<string, string> = {
  id: 'Steps refer to it by this name. Letters, digits and _, not starting with a digit.',
  z: 'Higher layers are drawn on top.',
  target: 'The object this acts on.',
  opacity: '0 is invisible, 1 is solid.',
  scale: '1 is normal size, 2 twice as big.',
};

function labelFor(name: string, schema: JsonSchema): string {
  return LABELS[name] ?? (schema.title ? humanize(schema.title) : humanize(name));
}

// Fields

function groupFor(name: string, owner: 'object' | 'step' | 'other'): FieldGroup {
  if (name === 'id') return 'identity';
  if (owner === 'object') {
    if (['place', 'scale', 'rotate'].includes(name)) return 'position';
    if (['color', 'opacity', 'z', 'shown'].includes(name)) return 'style';
  }
  if (owner === 'step') {
    if (name === 'caption') return 'caption';
    if (name === 'run_time' || name === 'lag') return 'timing';
  }
  return 'main';
}

function isNull(schema: JsonSchema): boolean {
  return schema.type === 'null';
}

function isRef(schema: JsonSchema): boolean {
  return schema['x-widget'] === 'object-ref';
}

function arrayKind(index: SchemaIndex, inner: JsonSchema): WidgetKind {
  const items = deref(index, inner.items ?? {});
  if (items.discriminator?.propertyName === 'do') return 'steps';
  const widget = items['x-widget'];
  if (widget === 'object-ref') return 'ref-list';
  if (widget === 'color') return 'color-list';
  if (widget === 'point') return 'point-list';
  const itemType = items.type;
  if (itemType === 'array') {
    const cell = items.items ?? {};
    if (cell.anyOf && cell.anyOf.some((c) => c.type === 'string')) return 'matrix';
    if (cell.type === 'number' || cell.type === 'integer') return 'number-matrix';
    return 'json';
  }
  if (itemType === 'string') return 'string-list';
  if (itemType === 'number' || itemType === 'integer') return 'number-list';
  return 'json';
}

/** Describe one property of a model as a form field. */
export function fieldSpec(
  index: SchemaIndex,
  name: string,
  property: JsonSchema,
  required: boolean,
  owner: 'object' | 'step' | 'other' = 'other',
): FieldSpec {
  const outer = deref(index, property);
  let inner = outer;
  let nullable = false;
  let variants: JsonSchema[] = [];
  if (outer.anyOf) {
    const nonNull = outer.anyOf.filter((v) => !isNull(v)).map((v) => deref(index, v));
    nullable = nonNull.length < outer.anyOf.length;
    variants = nonNull;
    if (nonNull.length === 1) inner = { ...nonNull[0]!, ...pick(outer, ['x-widget', 'x-ref-types', 'accept']) };
  }
  const widget = outer['x-widget'] ?? inner['x-widget'];
  const spec: FieldSpec = {
    name,
    label: labelFor(name, outer),
    kind: 'json',
    required,
    nullable,
    group: groupFor(name, owner),
  };
  const description = outer.description ?? inner.description ?? DESCRIPTIONS[name];
  if (description) spec.description = firstParagraph(description);
  if (outer.default !== undefined) spec.default = outer.default;
  else if (inner.default !== undefined) spec.default = inner.default;
  for (const key of ['minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems'] as const) {
    const value = inner[key] ?? outer[key];
    if (typeof value === 'number') spec[key] = value;
  }

  if (name === 'id') {
    spec.kind = 'id';
    return spec;
  }
  if (variants.length > 1) {
    // `target`: one object or a list of them
    const scalar = variants.find((v) => v.type === 'string' && isRef(v));
    const list = variants.find((v) => v.type === 'array' && v.items && isRef(v.items));
    if (scalar && list) {
      spec.kind = 'targets';
      spec.refTypes = scalar['x-ref-types'] ?? null;
      return spec;
    }
  }
  switch (widget) {
    case 'color':
      spec.kind = 'color';
      return spec;
    case 'point':
      spec.kind = 'point';
      return spec;
    case 'range':
      spec.kind = 'range';
      return spec;
    case 'tex':
      spec.kind = 'tex';
      return spec;
    case 'multiline':
      spec.kind = 'multiline';
      return spec;
    case 'expression':
      spec.kind = 'expression';
      return spec;
    case 'object-ref':
      spec.kind = 'object-ref';
      spec.refTypes = inner['x-ref-types'] ?? outer['x-ref-types'] ?? null;
      return spec;
    case 'file':
      spec.kind = 'file';
      if (typeof (inner.accept ?? outer.accept) === 'string') spec.accept = (inner.accept ?? outer.accept) as string;
      return spec;
    case 'properties':
      spec.kind = 'properties';
      return spec;
    default:
      break;
  }
  const refName = property.$ref ? defName(property.$ref) : outer.anyOf?.find((v) => v.$ref)?.$ref;
  if (refName && defName(refName) === 'Placement') {
    spec.kind = 'placement';
    return spec;
  }
  if (inner.const !== undefined) {
    spec.kind = 'json';
    return spec;
  }
  if (Array.isArray(inner.enum)) {
    spec.kind = 'enum';
    spec.enumValues = inner.enum.map(String);
    return spec;
  }
  const type = Array.isArray(inner.type) ? inner.type.find((t) => t !== 'null') : inner.type;
  switch (type) {
    case 'boolean':
      spec.kind = 'boolean';
      return spec;
    case 'integer':
      spec.kind = 'number';
      spec.integer = true;
      return spec;
    case 'number':
      spec.kind = 'number';
      return spec;
    case 'string':
      spec.kind = 'text';
      return spec;
    case 'array':
      spec.kind = arrayKind(index, inner);
      if (spec.kind === 'number-list' && spec.maxItems === undefined) spec.maxItems = inner.maxItems;
      if (spec.kind === 'ref-list') spec.refTypes = deref(index, inner.items ?? {})['x-ref-types'] ?? null;
      return spec;
    case 'object': {
      const additional = inner.additionalProperties;
      if (additional && typeof additional === 'object' && additional['x-widget'] === 'color') {
        spec.kind = 'color-map';
        return spec;
      }
      if (inner.properties) {
        spec.kind = 'object';
        spec.fields = fieldsOf(index, inner, 'other');
        return spec;
      }
      return spec;
    }
    default:
      return spec;
  }
}

function pick(schema: JsonSchema, keys: string[]): Partial<JsonSchema> {
  const out: Partial<JsonSchema> = {};
  for (const key of keys) if (schema[key] !== undefined) out[key] = schema[key];
  return out;
}

const HIDDEN = new Set(['type', 'do', 'version']);

const GROUP_ORDER: FieldGroup[] = ['identity', 'main', 'caption', 'position', 'style', 'timing'];

/** The fields of a model, in the order the panel shows them. */
export function fieldsOf(index: SchemaIndex, model: JsonSchema, owner: 'object' | 'step' | 'other'): FieldSpec[] {
  const required = new Set(model.required ?? []);
  const fields = Object.entries(model.properties ?? {})
    .filter(([name]) => !HIDDEN.has(name))
    .map(([name, prop]) => fieldSpec(index, name, prop, required.has(name), owner));
  // Stable sort by group keeps the schema's order within each group
  return fields
    .map((f, i) => ({ f, i }))
    .sort((a, b) => GROUP_ORDER.indexOf(a.f.group) - GROUP_ORDER.indexOf(b.f.group) || a.i - b.i)
    .map(({ f }) => f);
}

export function objectFields(index: SchemaIndex, type: string): FieldSpec[] {
  const kind = objectKind(index, type);
  const def = kind ? index.defs[kind.defName] : undefined;
  return def ? fieldsOf(index, def, 'object') : [];
}

export function stepFields(index: SchemaIndex, name: string): FieldSpec[] {
  const kind = stepKind(index, name);
  const def = kind ? index.defs[kind.defName] : undefined;
  return def ? fieldsOf(index, def, 'step') : [];
}

export function sceneFields(index: SchemaIndex): FieldSpec[] {
  const def = index.defs.SceneSpec;
  if (!def) return [];
  return fieldsOf(index, { ...def, properties: pick(def.properties ?? {}, ['id', 'title', 'background']) as Record<string, JsonSchema> }, 'other');
}

export function documentFields(index: SchemaIndex): FieldSpec[] {
  const root = index.root;
  const props = pick(root.properties ?? {}, ['title', 'settings']) as Record<string, JsonSchema>;
  return fieldsOf(index, { ...root, properties: props }, 'other');
}

/** Fields a change step can set on an object of the given kind. */
export function settableFields(index: SchemaIndex, type: string): FieldSpec[] {
  return objectFields(index, type).filter((f) => f.name !== 'id');
}

/** The placement model's fields, for the placement editor. */
export function placementFields(index: SchemaIndex): FieldSpec[] {
  const def = index.defs.Placement;
  return def ? fieldsOf(index, def, 'other') : [];
}

/** Whether objects of this kind are placed as a whole (and so can be dragged to a point). */
export function hasPlacement(index: SchemaIndex, type: string): boolean {
  return objectFields(index, type).some((f) => f.kind === 'placement');
}

/** Numeric limits of a field as one check; returns a message when `value` breaks them. */
export function checkNumber(spec: Pick<FieldSpec, 'minimum' | 'maximum' | 'exclusiveMinimum' | 'exclusiveMaximum' | 'integer' | 'label'>, value: number): string | null {
  if (!Number.isFinite(value)) return 'Enter a number';
  if (spec.integer && !Number.isInteger(value)) return 'Enter a whole number';
  if (spec.minimum !== undefined && value < spec.minimum) return `Has to be at least ${spec.minimum}`;
  if (spec.maximum !== undefined && value > spec.maximum) return `Has to be at most ${spec.maximum}`;
  if (spec.exclusiveMinimum !== undefined && value <= spec.exclusiveMinimum) return `Has to be more than ${spec.exclusiveMinimum}`;
  if (spec.exclusiveMaximum !== undefined && value >= spec.exclusiveMaximum) return `Has to be less than ${spec.exclusiveMaximum}`;
  return null;
}
