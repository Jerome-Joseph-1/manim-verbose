import { describe, expect, it } from 'vitest';
import { danglingReferences, findReferences, objectRefs, stepRefs, stepTargets } from './refs';
import type { SceneObject, Step } from './types';
import { sampleDoc, schema } from '../test/fixtures';
import type { JsonSchema } from '../lib/schema';

describe('object references', () => {
  it('finds next_to, on, brace/box target and group members', () => {
    expect(objectRefs({ id: 'a', type: 'text', text: 'x', place: { next_to: 'b' } })).toEqual([{ id: 'b', path: ['place', 'next_to'] }]);
    expect(objectRefs({ id: 'a', type: 'text', text: 'x', place: { at: [1, 2], on: 'plane' } })).toEqual([{ id: 'plane', path: ['place', 'on'] }]);
    expect(objectRefs({ id: 'a', type: 'dot', point: [0, 0], on: 'plane' })).toEqual([{ id: 'plane', path: ['on'] }]);
    expect(objectRefs({ id: 'a', type: 'brace', target: 'eq' })).toEqual([{ id: 'eq', path: ['target'] }]);
    expect(objectRefs({ id: 'a', type: 'box', target: 'eq' })).toEqual([{ id: 'eq', path: ['target'] }]);
    expect(objectRefs({ id: 'g', type: 'group', members: ['x', 'y'] })).toEqual([
      { id: 'x', path: ['members', 0] },
      { id: 'y', path: ['members', 1] },
    ]);
  });

  it('ignores placement shorthands and non-reference fields', () => {
    expect(objectRefs({ id: 'a', type: 'text', text: 'eq', place: 'top' })).toEqual([]);
    expect(objectRefs({ id: 'a', type: 'text', text: 'eq', place: [1, 2] })).toEqual([]);
    expect(objectRefs({ id: 'a', type: 'dot', point: [0, 0], label: 'eq' })).toEqual([]);
  });
});

describe('step references', () => {
  it('finds targets, into, focus, move.to.next_to, change set and nested steps', () => {
    expect(stepRefs({ do: 'show', target: ['a', 'b'] }).map((r) => r.path)).toEqual([['target', 0], ['target', 1]]);
    expect(stepRefs({ do: 'transform', target: 'a', into: 'b' }).map((r) => r.id)).toEqual(['a', 'b']);
    expect(stepRefs({ do: 'camera', focus: 'a' })).toEqual([{ id: 'a', path: ['focus'] }]);
    expect(stepRefs({ do: 'move', target: 'a', to: { next_to: 'b' } }).map((r) => r.path)).toEqual([['target'], ['to', 'next_to']]);
    expect(stepRefs({ do: 'change', target: 'a', set: { place: { next_to: 'b' }, members: ['c'], on: 'd' } }).map((r) => r.id)).toEqual(['a', 'b', 'd', 'c']);
    expect(
      stepRefs({ do: 'together', steps: [{ do: 'show', target: 'a' }, { do: 'hide', target: ['b'] }] }).map((r) => r.path),
    ).toEqual([['steps', 0, 'target'], ['steps', 1, 'target', 0]]);
    expect(stepRefs({ do: 'wait', duration: 1 })).toEqual([]);
    expect(stepRefs({ do: 'clear' })).toEqual([]);
  });

  it('lists what a step acts on, for its card', () => {
    expect(stepTargets({ do: 'show', target: ['a', 'b', ''] })).toEqual(['a', 'b']);
    expect(stepTargets({ do: 'transform', target: 'a', into: 'b' })).toEqual(['a', 'b']);
    expect(stepTargets({ do: 'together', steps: [{ do: 'show', target: 'a' }, { do: 'show', target: ['a', 'c'] }] })).toEqual(['a', 'c']);
    expect(stepTargets({ do: 'show', target: '' })).toEqual([]);
  });
});

describe('scene references', () => {
  it('finds every use of an object', () => {
    const scene = sampleDoc().scenes[0]!;
    const uses = findReferences(scene, 'label');
    expect(uses.map((u) => `${u.kind}:${u.itemId}`)).toEqual(['object:group', 'step:intro_2', 'step:intro_4', 'step:intro_7']);
  });

  it('finds dangling references, empty ones included', () => {
    const scene = sampleDoc().scenes[0]!;
    expect(danglingReferences(scene)).toEqual([]);
    const broken = { ...scene, steps: [...scene.steps!, { id: 'x', do: 'show', target: '' }, { id: 'y', do: 'hide', target: 'ghost' }] };
    expect(danglingReferences(broken).map((u) => u.itemId)).toEqual(['x', 'y']);
  });
});

/**
 * Every field the schema marks as an object reference has to be one refs.ts knows about,
 * or renaming would miss it.
 */
describe('coverage of the schema', () => {
  function refFields(def: JsonSchema): string[] {
    const out: string[] = [];
    for (const [name, prop] of Object.entries(def.properties ?? {})) {
      const variants = [prop, ...(prop.anyOf ?? []), ...(prop.anyOf ?? []).map((v) => v.items ?? {}), prop.items ?? {}];
      if (variants.some((v) => v['x-widget'] === 'object-ref')) out.push(name);
    }
    return out;
  }

  const defs = schema.$defs ?? {};
  const sample: Record<string, unknown> = {};

  it('knows every reference field of every object kind', () => {
    for (const [name, def] of Object.entries(defs)) {
      if (!name.endsWith('Object')) continue;
      const type = (def.properties?.type?.const as string) ?? '';
      for (const field of refFields(def)) {
        const obj: SceneObject = { id: 'o', type, [field]: field === 'members' ? ['ref'] : 'ref' };
        const found = objectRefs(obj).map((r) => r.id);
        expect(found, `${name}.${field}`).toContain('ref');
      }
      sample[type] = true;
    }
    expect(Object.keys(sample).length).toBe(23);
  });

  it('knows every reference field of every step kind, and of placements', () => {
    for (const [name, def] of Object.entries(defs)) {
      if (!name.endsWith('Step')) continue;
      const kind = def.properties?.do?.const as string;
      for (const field of refFields(def)) {
        const step: Step = { do: kind, [field]: 'ref' };
        expect(stepRefs(step).map((r) => r.id), `${name}.${field}`).toContain('ref');
      }
    }
    const placementRefs = refFields(defs.Placement!);
    expect(placementRefs.sort()).toEqual(['next_to', 'on']);
    for (const field of placementRefs) {
      expect(stepRefs({ do: 'move', target: 'a', to: { [field]: 'ref' } }).map((r) => r.id), `move.to.${field}`).toContain('ref');
      expect(objectRefs({ id: 'o', type: 'circle', place: { [field]: 'ref' } }).map((r) => r.id), `place.${field}`).toContain('ref');
    }
  });
});
