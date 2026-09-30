import { describe, expect, it } from 'vitest';
import {
  checkNumber, documentFields, fieldSpec, firstParagraph, hasPlacement, humanize, objectFields, objectKind, placementFields,
  sceneFields, settableFields, stepFields, stepKind, type FieldSpec, type WidgetKind,
} from './schema';
import { schemaIndex } from '../test/fixtures';

function field(fields: FieldSpec[], name: string): FieldSpec {
  const f = fields.find((x) => x.name === name);
  if (!f) throw new Error(`no field ${name} in ${fields.map((x) => x.name).join(', ')}`);
  return f;
}

describe('the schema index', () => {
  it('lists every kind of object with its label and category', () => {
    expect(schemaIndex.objectKinds).toHaveLength(23);
    expect(objectKind(schemaIndex, 'tex')).toMatchObject({ label: 'Equation', category: 'Text & math', description: 'A LaTeX formula, in math mode.' });
    expect(objectKind(schemaIndex, 'number_plane')?.category).toBe('Coordinates');
    // Sorted by category order: text and math first
    expect(schemaIndex.objectKinds[0]!.category).toBe('Text & math');
  });

  it('lists every kind of step with its label', () => {
    expect(schemaIndex.stepKinds.map((k) => k.name).sort()).toEqual(
      ['add', 'apply_matrix', 'camera', 'change', 'clear', 'hide', 'highlight', 'move', 'remove', 'show', 'together', 'transform', 'wait'],
    );
    expect(stepKind(schemaIndex, 'clear')?.label).toBe('Clear screen');
    expect(stepKind(schemaIndex, 'together')?.description).toBe(firstParagraph(stepKind(schemaIndex, 'together')!.description));
  });
});

describe('fields of objects', () => {
  it('gives every field of every kind an input (none fall back to raw JSON)', () => {
    for (const kind of schemaIndex.objectKinds) {
      for (const f of objectFields(schemaIndex, kind.name)) {
        expect(f.kind, `${kind.name}.${f.name}`).not.toBe('json');
      }
    }
  });

  it('never offers type or do as a field', () => {
    for (const kind of schemaIndex.objectKinds) expect(objectFields(schemaIndex, kind.name).map((f) => f.name)).not.toContain('type');
    for (const kind of schemaIndex.stepKinds) expect(stepFields(schemaIndex, kind.name).map((f) => f.name)).not.toContain('do');
  });

  it('puts the name first, then what the kind is about, then position and look', () => {
    const names = objectFields(schemaIndex, 'text').map((f) => f.name);
    expect(names[0]).toBe('id');
    expect(names.indexOf('text')).toBeLessThan(names.indexOf('place'));
    expect(names.indexOf('place')).toBeLessThan(names.indexOf('color'));
    expect(field(objectFields(schemaIndex, 'text'), 'fixed').group).toBe('style');
    expect(field(objectFields(schemaIndex, 'text'), 'backdrop').group).toBe('style');
  });

  const expectations: [string, string, WidgetKind, Partial<FieldSpec>?][] = [
    ['text', 'id', 'id'],
    ['text', 'text', 'multiline', { required: true }],
    ['text', 'font', 'text', { required: false, nullable: true }],
    ['text', 'font_size', 'number', { default: 48, exclusiveMinimum: 0 }],
    ['text', 'bold', 'boolean', { default: false }],
    ['text', 'fixed', 'boolean', { default: false }],
    ['text', 'backdrop', 'boolean', { default: false }],
    ['text', 'align', 'enum', { enumValues: ['left', 'center', 'right'], default: 'center' }],
    ['text', 'color', 'color', { nullable: true }],
    ['text', 'colors', 'color-map'],
    ['text', 'opacity', 'number', { minimum: 0, maximum: 1 }],
    ['text', 'z', 'number', { integer: true, default: 0 }],
    ['text', 'place', 'placement'],
    ['text', 'rotate', 'number'],
    ['tex', 'tex', 'tex'],
    ['title', 'underline', 'boolean', { default: true }],
    ['bullets', 'items', 'string-list', { minItems: 1 }],
    ['matrix', 'entries', 'matrix'],
    ['matrix', 'bracket', 'enum'],
    ['matrix', 'row_colors', 'color-list'],
    ['number_plane', 'x_range', 'range', { default: [-8, 8, 1] }],
    ['axes', 'x_label', 'tex', { nullable: true }],
    ['axes_3d', 'z_range', 'range'],
    ['number_line', 'length', 'number', { nullable: true }],
    ['graph', 'on', 'object-ref', { refTypes: ['axes', 'number_plane'], required: true }],
    ['graph', 'function', 'expression'],
    ['graph', 'x_range', 'number-list', { maxItems: 2 }],
    ['dot', 'point', 'point', { maxItems: 3 }],
    ['dot', 'on', 'object-ref', { refTypes: ['number_plane', 'axes', 'axes_3d', 'number_line'], nullable: true }],
    ['dot', 'label_side', 'enum'],
    ['vector', 'tail', 'point', { default: [0, 0] }],
    ['vector', 'show_coordinates', 'boolean'],
    ['line', 'dashed', 'boolean'],
    ['polygon', 'points', 'point-list', { minItems: 3 }],
    ['polygon', 'fill_opacity', 'number', { minimum: 0, maximum: 1 }],
    ['circle', 'fill', 'color'],
    ['rectangle', 'corner_radius', 'number', { minimum: 0 }],
    ['square', 'side', 'number'],
    ['brace', 'target', 'object-ref', { refTypes: null, required: true }],
    ['brace', 'label', 'tex'],
    ['box', 'buff', 'number'],
    ['image', 'path', 'file', { accept: 'image/*' }],
    ['svg', 'path', 'file', { accept: '.svg' }],
    ['group', 'members', 'ref-list', { minItems: 1 }],
    ['group', 'arrange', 'enum'],
  ];

  it.each(expectations)('%s.%s is a %s field', (type, name, kind, extra) => {
    const spec = field(objectFields(schemaIndex, type), name);
    expect(spec.kind).toBe(kind);
    if (extra) expect(spec).toMatchObject(extra);
  });

  it('knows which kinds are placed as a whole', () => {
    expect(hasPlacement(schemaIndex, 'text')).toBe(true);
    expect(hasPlacement(schemaIndex, 'group')).toBe(true);
    expect(hasPlacement(schemaIndex, 'dot')).toBe(false);
    expect(hasPlacement(schemaIndex, 'graph')).toBe(false);
    expect(hasPlacement(schemaIndex, 'brace')).toBe(false);
  });

  it('labels fields in plain words, with help from the schema', () => {
    expect(field(objectFields(schemaIndex, 'text'), 'font_size').label).toBe('Font size');
    expect(field(objectFields(schemaIndex, 'text'), 'z').label).toBe('Layer');
    expect(field(objectFields(schemaIndex, 'text'), 'shown').description).toMatch(/On screen from the start/);
    expect(field(objectFields(schemaIndex, 'graph'), 'on').label).toBe('Coordinate system');
  });
});

describe('fields of steps', () => {
  it('gives every field of every step an input', () => {
    for (const kind of schemaIndex.stepKinds) {
      for (const f of stepFields(schemaIndex, kind.name)) expect(f.kind, `${kind.name}.${f.name}`).not.toBe('json');
    }
  });

  const expectations: [string, string, WidgetKind, Partial<FieldSpec>?][] = [
    ['show', 'target', 'targets', { required: true }],
    ['show', 'style', 'enum', { default: 'auto' }],
    ['show', 'lag', 'number', { minimum: 0, maximum: 1 }],
    ['show', 'caption', 'multiline', { nullable: true }],
    ['show', 'run_time', 'number', { exclusiveMinimum: 0, maximum: 600 }],
    ['show', 'id', 'id'],
    ['transform', 'target', 'object-ref'],
    ['transform', 'into', 'object-ref'],
    ['transform', 'keep', 'boolean'],
    ['change', 'set', 'properties', { required: true }],
    ['move', 'to', 'placement'],
    ['move', 'by', 'point', { maxItems: 2 }],
    ['highlight', 'part', 'text'],
    ['highlight', 'color', 'color'],
    ['wait', 'duration', 'number', { default: 1 }],
    ['camera', 'zoom', 'number'],
    ['camera', 'center', 'point'],
    ['camera', 'focus', 'object-ref'],
    ['camera', 'orientation', 'number-list', { minItems: 2, maxItems: 3 }],
    ['camera', 'reset', 'boolean'],
    ['apply_matrix', 'matrix', 'number-matrix'],
    ['together', 'steps', 'steps', { minItems: 2 }],
  ];

  it.each(expectations)('%s.%s is a %s field', (kind, name, widget, extra) => {
    const spec = field(stepFields(schemaIndex, kind), name);
    expect(spec.kind).toBe(widget);
    if (extra) expect(spec).toMatchObject(extra);
  });

  it('orders a step: what it does, then its caption, then timing', () => {
    const names = stepFields(schemaIndex, 'show').map((f) => f.name);
    expect(names.indexOf('target')).toBeLessThan(names.indexOf('caption'));
    expect(names.indexOf('caption')).toBeLessThan(names.indexOf('run_time'));
  });
});

describe('other models', () => {
  it('describes scenes and the document', () => {
    expect(sceneFields(schemaIndex).map((f) => [f.name, f.kind])).toEqual([
      ['id', 'id'],
      ['title', 'text'],
      ['background', 'color'],
    ]);
    const doc = documentFields(schemaIndex);
    expect(doc.map((f) => f.name)).toEqual(['title', 'settings']);
    const settings = field(doc, 'settings');
    expect(settings.kind).toBe('object');
    expect(settings.fields!.map((f) => [f.name, f.kind])).toEqual([
      ['resolution', 'number-list'],
      ['fps', 'number'],
      ['background', 'color'],
      ['captions', 'object'],
    ]);
    expect(field(settings.fields!, 'captions').fields!.map((f) => f.kind)).toEqual(['number', 'color', 'enum', 'boolean']);
  });

  it('describes a placement, with `on` for coordinates', () => {
    const fields = placementFields(schemaIndex);
    expect(fields.map((f) => [f.name, f.kind])).toEqual([
      ['at', 'point'],
      ['on', 'object-ref'],
      ['edge', 'enum'],
      ['next_to', 'object-ref'],
      ['side', 'enum'],
      ['buff', 'number'],
      ['shift', 'point'],
    ]);
    expect(field(fields, 'on').refTypes).toEqual(['number_plane', 'axes', 'axes_3d', 'number_line']);
  });

  it('lists what a change step can set on each kind', () => {
    const names = settableFields(schemaIndex, 'vector').map((f) => f.name);
    expect(names).toContain('tip');
    expect(names).toContain('color');
    expect(names).not.toContain('id');
    expect(names).not.toContain('type');
  });

  it('falls back to JSON for a shape it does not know', () => {
    expect(fieldSpec(schemaIndex, 'odd', { type: 'array', items: { type: 'object' } }, false).kind).toBe('json');
    expect(fieldSpec(schemaIndex, 'odd', {}, false).kind).toBe('json');
  });
});

describe('small helpers', () => {
  it('humanizes names', () => {
    expect(humanize('font_size')).toBe('Font size');
    expect(humanize('Font Size')).toBe('Font size');
    expect(humanize('xLabel')).toBe('X label');
  });

  it('checks numbers against a field', () => {
    const spec = { label: 'x', minimum: 0, maximum: 1 };
    expect(checkNumber(spec, 0.5)).toBeNull();
    expect(checkNumber(spec, 2)).toMatch(/at most 1/);
    expect(checkNumber(spec, -1)).toMatch(/at least 0/);
    expect(checkNumber({ label: 'x', exclusiveMinimum: 0 }, 0)).toMatch(/more than 0/);
    expect(checkNumber({ label: 'x', exclusiveMaximum: 1 }, 1)).toMatch(/less than 1/);
    expect(checkNumber({ label: 'x', integer: true }, 1.5)).toMatch(/whole/);
    expect(checkNumber({ label: 'x' }, Number.NaN)).toMatch(/number/);
  });
});
