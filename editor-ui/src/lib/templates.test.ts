import { describe, expect, it } from 'vitest';
import { catalogFromSchema, fillObjectTemplate, fillStepTemplate, suggestPosition } from './templates';
import { schemaIndex, sampleDoc } from '../test/fixtures';
import type { Scene } from '../doc/types';

const scene = (): Scene => sampleDoc().scenes[0]!;

describe('filling in new objects', () => {
  it('puts a brace around the selected object, else the latest one', () => {
    expect(fillObjectTemplate(schemaIndex, { type: 'brace', target: '' }, { scene: scene(), frameIndex: -1, selectedObjectId: 'eq' }).target).toBe('eq');
    expect(fillObjectTemplate(schemaIndex, { type: 'brace', target: '' }, { scene: scene(), frameIndex: -1, selectedObjectId: null }).target).toBe('graph');
  });

  it('puts a graph on axes or a plane only', () => {
    const filled = fillObjectTemplate(schemaIndex, { type: 'graph', on: '', function: 'x' }, { scene: scene(), frameIndex: -1, selectedObjectId: 'eq' });
    expect(filled.on).toBe('axes');
  });

  it('fills each empty member of a group with a different object', () => {
    const filled = fillObjectTemplate(schemaIndex, { type: 'group', members: ['', ''] }, { scene: scene(), frameIndex: -1, selectedObjectId: 'label' });
    expect(filled.members).toEqual(['label', 'plane']);
  });

  it('leaves references empty in an empty scene, to be picked', () => {
    const empty: Scene = { id: 'e' };
    expect(fillObjectTemplate(schemaIndex, { type: 'brace', target: '' }, { scene: empty, frameIndex: -1, selectedObjectId: null }).target).toBe('');
    expect(fillObjectTemplate(schemaIndex, { type: 'group', members: ['', ''] }, { scene: empty, frameIndex: -1, selectedObjectId: null }).members).toEqual([]);
  });

  it('leaves a template without references alone', () => {
    expect(fillObjectTemplate(schemaIndex, { type: 'text', text: 'Hi' }, { scene: scene(), frameIndex: -1, selectedObjectId: 'eq' })).toEqual({ type: 'text', text: 'Hi' });
  });
});

describe('filling in new steps', () => {
  const base = { scene: { id: 's', objects: [{ id: 'a', type: 'text', text: 'a' }, { id: 'b', type: 'text', text: 'b' }], steps: [{ id: 's_1', do: 'show', target: 'a' }] } as Scene };

  it('shows the next object not on screen yet', () => {
    expect(fillStepTemplate(schemaIndex, { do: 'show', target: '' }, { ...base, frameIndex: 0, selectedObjectId: null }).target).toBe('b');
    expect(fillStepTemplate(schemaIndex, { do: 'show', target: '' }, { ...base, frameIndex: -1, selectedObjectId: null }).target).toBe('a');
  });

  it('shows the selected object when it is not on screen', () => {
    expect(fillStepTemplate(schemaIndex, { do: 'show', target: '' }, { ...base, frameIndex: -1, selectedObjectId: 'b' }).target).toBe('b');
  });

  it('hides, highlights and changes what is on screen', () => {
    expect(fillStepTemplate(schemaIndex, { do: 'hide', target: '' }, { ...base, frameIndex: 0, selectedObjectId: null }).target).toBe('a');
    expect(fillStepTemplate(schemaIndex, { do: 'change', target: '', set: { color: 'YELLOW' } }, { ...base, frameIndex: 0, selectedObjectId: 'a' }).target).toBe('a');
  });

  it('transforms into something else', () => {
    const filled = fillStepTemplate(schemaIndex, { do: 'transform', target: '', into: '' }, { ...base, frameIndex: 0, selectedObjectId: 'a' });
    expect(filled).toMatchObject({ target: 'a', into: 'b' });
  });

  it('fills the steps of a together', () => {
    const filled = fillStepTemplate(schemaIndex, { do: 'together', steps: [{ do: 'show', target: '' }, { do: 'show', target: '' }] }, { ...base, frameIndex: -1, selectedObjectId: null });
    expect(filled.steps).toEqual([{ do: 'show', target: 'a' }, { do: 'show', target: 'b' }]);
  });

  it('leaves steps without targets alone', () => {
    expect(fillStepTemplate(schemaIndex, { do: 'wait', duration: 1 }, { ...base, frameIndex: 0, selectedObjectId: 'a' })).toEqual({ do: 'wait', duration: 1 });
    expect(fillStepTemplate(schemaIndex, { do: 'clear' }, { ...base, frameIndex: 0, selectedObjectId: 'a' })).toEqual({ do: 'clear' });
  });
});

describe('a catalog from the schema alone', () => {
  it('has every kind with a template', () => {
    const catalog = catalogFromSchema(schemaIndex);
    expect(catalog.objects).toHaveLength(23);
    expect(catalog.steps).toHaveLength(13);
    expect(catalog.objects.find((o) => o.type === 'text')?.template).toEqual({ type: 'text', text: 'Text' });
    expect(catalog.steps.find((s) => s.do === 'together')?.template.steps).toHaveLength(2);
    expect(catalog.steps.find((s) => s.do === 'move')?.template).toMatchObject({ by: [1, 0] });
  });
});

describe('placing new objects', () => {
  it('uses the centre when it is free, else a free band', () => {
    expect(suggestPosition([])).toBeNull();
    expect(suggestPosition([[-1, -0.3, 1, 0.3]])).toEqual([0, -2]);
    expect(suggestPosition([[-1, -0.3, 1, 0.3], [-1, -2.2, 1, -1.8]])).toEqual([0, 2]);
    // A plane filling the frame doesn't count as taking the space
    expect(suggestPosition([[-7, -4, 7, 4]])).toBeNull();
  });
});
