/** Objects carried over from one scene to the next, and the edits that have to follow them. */
import { describe, expect, it } from 'vitest';
import { carriedObjects, carryCandidates, effectiveScene, scenesCarrying, usableObjects, withDependencies } from './carry';
import { planObjectRemoval, removeObject, renameObject } from './ops';
import { onScreenAfter } from './screen';
import { danglingReferences } from './refs';
import { invariantViolations } from './check';
import type { Document } from './types';

function doc(): Document {
  return {
    version: 1,
    title: 'Carry',
    scenes: [
      {
        id: 'one',
        objects: [
          { id: 'plane', type: 'number_plane' },
          { id: 'v', type: 'vector', on: 'plane', tip: [2, 1] },
          { id: 'eq', type: 'tex', tex: 'x' },
          { id: 'brace', type: 'brace', target: 'eq' },
        ],
        steps: [{ id: 'one_1', do: 'show', target: ['plane', 'v', 'eq'] }],
      },
      {
        id: 'two',
        carry: ['plane', 'v'],
        objects: [{ id: 'w', type: 'vector', on: 'plane', tip: [1, 2] }],
        steps: [
          { id: 'two_1', do: 'show', target: 'w' },
          { id: 'two_2', do: 'move', target: 'v', by: [1, 0] },
        ],
      },
      {
        id: 'three',
        carry: ['plane', 'v', 'w'],
        steps: [{ id: 'three_1', do: 'hide', target: 'v' }],
      },
    ],
  };
}

describe('what a scene can use', () => {
  it('is its own objects and those carried in, from however far back', () => {
    expect([...usableObjects(doc(), 'one').keys()]).toEqual(['plane', 'v', 'eq', 'brace']);
    expect([...usableObjects(doc(), 'two').keys()]).toEqual(['plane', 'v', 'w']);
    const three = usableObjects(doc(), 'three');
    expect([...three.keys()]).toEqual(['plane', 'v', 'w']);
    expect(three.get('v')?.from).toBe('one');
    expect(three.get('w')?.from).toBe('two');
    expect(usableObjects(doc(), 'nowhere').size).toBe(0);
  });

  it('lists what is carried in, ignoring names that carry nothing', () => {
    const d = doc();
    d.scenes[1]!.carry = ['plane', 'ghost', 'v'];
    expect(carriedObjects(d, 'two').map((c) => c.object.id)).toEqual(['plane', 'v']);
    expect(carriedObjects(d, 'one')).toEqual([]);
  });

  it('puts carried objects in the scene as its references see it', () => {
    const d = doc();
    const scene = effectiveScene(d, d.scenes[1]!);
    expect(scene.objects!.map((o) => o.id)).toEqual(['plane', 'v', 'w']);
    expect(effectiveScene(d, d.scenes[0]!)).toBe(d.scenes[0]);
    // ...and counts them as known, and as on screen from the start
    expect(danglingReferences(d.scenes[1]!)).toEqual([]);
    expect([...onScreenAfter(d.scenes[1]!, -1)].sort()).toEqual(['plane', 'v']);
  });

  it('offers everything usable in the scene before', () => {
    expect(carryCandidates(doc(), 'two').map((c) => c.object.id)).toEqual(['plane', 'v', 'eq', 'brace']);
    expect(carryCandidates(doc(), 'one')).toEqual([]);
  });

  it('brings along what an object is built on', () => {
    const candidates = carryCandidates(doc(), 'two');
    expect(withDependencies(candidates, ['v'])).toEqual(['v', 'plane']);
    expect(withDependencies(candidates, ['brace'])).toEqual(['brace', 'eq']);
    expect(withDependencies(candidates, ['nothing'])).toEqual([]);
  });

  it('knows which scenes carry an object on, one after another', () => {
    expect(scenesCarrying(doc(), 'one', 'v')).toEqual(['two', 'three']);
    expect(scenesCarrying(doc(), 'one', 'eq')).toEqual([]);
    expect(scenesCarrying(doc(), 'two', 'w')).toEqual(['three']);
  });
});

describe('edits that follow carried objects', () => {
  it('renames a carried object in every scene carrying it, and every use of it there', () => {
    const next = renameObject(doc(), 'one', 'v', 'arrow');
    expect(next.scenes[1]!.carry).toEqual(['plane', 'arrow']);
    expect(next.scenes[1]!.steps![1]).toMatchObject({ target: 'arrow' });
    expect(next.scenes[2]!.carry).toEqual(['plane', 'arrow', 'w']);
    expect(next.scenes[2]!.steps![0]).toMatchObject({ target: 'arrow' });
    expect(invariantViolations(next, { references: true })).toEqual([]);
  });

  it("won't rename to a name a carrying scene already uses", () => {
    expect(() => renameObject(doc(), 'one', 'v', 'w')).toThrow(/Scene 'two' carries 'v' over and already has something called 'w'/);
  });

  it('removes an object from the scenes carrying it, and what uses it there', () => {
    const d = doc();
    const plan = planObjectRemoval(d, 'one', 'v');
    expect(plan.carriedBy).toEqual(['two', 'three']);
    const next = removeObject(d, 'one', 'v', { cascade: true });
    expect(next.scenes[1]!.carry).toEqual(['plane']);
    expect(next.scenes[1]!.steps!.map((s) => s.id)).toEqual(['two_1']);
    expect(next.scenes[2]!.carry).toEqual(['plane', 'w']);
    expect(next.scenes[2]!.steps).toBeUndefined();
    expect(invariantViolations(next, { references: true })).toEqual([]);
  });

  it('leaves carry lists alone when only the object goes', () => {
    const next = removeObject(doc(), 'one', 'eq');
    expect(next.scenes[1]!.carry).toEqual(['plane', 'v']);
  });
});
