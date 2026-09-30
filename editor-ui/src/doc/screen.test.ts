import { describe, expect, it } from 'vitest';
import { neverShown, onScreenAfter } from './screen';
import type { Scene } from './types';
import { sampleDoc } from '../test/fixtures';

describe('what is on screen', () => {
  it('follows show, hide, transform and clear', () => {
    const scene = sampleDoc().scenes[0]!;
    expect([...onScreenAfter(scene, -1)]).toEqual([]);
    expect([...onScreenAfter(scene, 0)]).toEqual(['plane']);
    // showing eq and label shows their group too
    expect([...onScreenAfter(scene, 1)].sort()).toEqual(['eq', 'group', 'label', 'plane']);
    expect(onScreenAfter(scene, 7).has('brace')).toBe(true);
    expect([...onScreenAfter(scene, 11)]).toEqual([]);
  });

  it('starts with objects marked shown', () => {
    const scene: Scene = { id: 's', objects: [{ id: 'a', type: 'text', text: 'a', shown: true }] };
    expect([...onScreenAfter(scene, -1)]).toEqual(['a']);
  });

  it('takes a group on and off screen with its members', () => {
    const scene: Scene = {
      id: 's',
      objects: [
        { id: 'a', type: 'text', text: 'a' },
        { id: 'b', type: 'text', text: 'b' },
        { id: 'g', type: 'group', members: ['a', 'b'] },
      ],
      steps: [
        { id: 's_1', do: 'show', target: 'g' },
        { id: 's_2', do: 'hide', target: 'a' },
      ],
    };
    expect([...onScreenAfter(scene, 0)].sort()).toEqual(['a', 'b', 'g']);
    expect([...onScreenAfter(scene, 1)].sort()).toEqual(['b']);
  });

  it('keeps the original of a transform with keep', () => {
    const scene: Scene = {
      id: 's',
      objects: [{ id: 'a', type: 'text', text: 'a' }, { id: 'b', type: 'text', text: 'b' }],
      steps: [
        { id: 's_1', do: 'show', target: 'a' },
        { id: 's_2', do: 'transform', target: 'a', into: 'b', keep: true },
        { id: 's_3', do: 'transform', target: 'b', into: 'a' },
      ],
    };
    expect([...onScreenAfter(scene, 1)].sort()).toEqual(['a', 'b']);
    expect([...onScreenAfter(scene, 2)].sort()).toEqual(['a']);
  });

  it('finds objects no step ever shows', () => {
    const scene: Scene = {
      id: 's',
      objects: [{ id: 'a', type: 'text', text: 'a' }, { id: 'b', type: 'text', text: 'b' }],
      steps: [{ id: 's_1', do: 'add', target: ['a'] }],
    };
    expect(neverShown(scene)).toEqual(['b']);
    // The sample moves the dot and draws axes and a graph, but no step shows them
    expect(neverShown(sampleDoc().scenes[0]!)).toEqual(['dot', 'axes', 'graph']);
  });
});
