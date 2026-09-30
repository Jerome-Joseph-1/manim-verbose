/**
 * Random sequences of edits: whatever order they come in, ids stay unique and valid,
 * references keep naming objects which exist (when removals cascade), and undoing every
 * edit gives back exactly the document started from.
 */
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  DocOpError, addObject, addScene, addStep, duplicateObject, duplicateScene, duplicateStep, moveObject, moveScene,
  moveStep, removeObject, removeScene, removeStep, renameObject, renameScene, renameStep, setItemField,
} from './ops';
import { invariantViolations } from './check';
import { commit, createHistory, redo, undo } from './history';
import type { Document, Scene } from './types';
import { sampleDoc } from '../test/fixtures';

const NAMES = ['a', 'b', 'eq', 'plane', 'label', 'intro', 'intro_3', 'second', 'x_1', 'bad name', '9lives', ''];
const OBJECT_TYPES = ['text', 'tex', 'circle', 'dot', 'number_plane', 'axes', 'square'];

type Op =
  | { op: 'addScene' }
  | { op: 'removeScene'; s: number }
  | { op: 'duplicateScene'; s: number }
  | { op: 'renameScene'; s: number; name: string }
  | { op: 'moveScene'; s: number; to: number }
  | { op: 'addObject'; s: number; type: string }
  | { op: 'addRefObject'; s: number; kind: 'brace' | 'next_to' | 'group' | 'graph'; o: number; o2: number }
  | { op: 'duplicateObject'; s: number; o: number }
  | { op: 'removeObject'; s: number; o: number; cascade: boolean }
  | { op: 'renameObject'; s: number; o: number; name: string }
  | { op: 'moveObject'; s: number; o: number; to: number }
  | { op: 'addStep'; s: number; kind: 'show' | 'hide' | 'wait' | 'transform' | 'together' | 'camera' | 'change'; o: number; o2: number }
  | { op: 'duplicateStep'; s: number; t: number }
  | { op: 'removeStep'; s: number; t: number }
  | { op: 'renameStep'; s: number; t: number; name: string }
  | { op: 'moveStep'; s: number; t: number; to: number }
  | { op: 'caption'; s: number; t: number; text: string };

const idx = fc.nat({ max: 20 });

function opArbitrary(allowDangling: boolean): fc.Arbitrary<Op> {
  const ops: fc.Arbitrary<Op>[] = [
    fc.constant({ op: 'addScene' as const }),
    fc.record({ op: fc.constant('removeScene' as const), s: idx }),
    fc.record({ op: fc.constant('duplicateScene' as const), s: idx }),
    fc.record({ op: fc.constant('renameScene' as const), s: idx, name: fc.constantFrom(...NAMES) }),
    fc.record({ op: fc.constant('moveScene' as const), s: idx, to: idx }),
    fc.record({ op: fc.constant('addObject' as const), s: idx, type: fc.constantFrom(...OBJECT_TYPES) }),
    fc.record({
      op: fc.constant('addRefObject' as const), s: idx, kind: fc.constantFrom('brace' as const, 'next_to' as const, 'group' as const, 'graph' as const), o: idx, o2: idx,
    }),
    fc.record({ op: fc.constant('duplicateObject' as const), s: idx, o: idx }),
    fc.record({ op: fc.constant('removeObject' as const), s: idx, o: idx, cascade: allowDangling ? fc.boolean() : fc.constant(true) }),
    fc.record({ op: fc.constant('renameObject' as const), s: idx, o: idx, name: fc.constantFrom(...NAMES) }),
    fc.record({ op: fc.constant('moveObject' as const), s: idx, o: idx, to: idx }),
    fc.record({
      op: fc.constant('addStep' as const), s: idx,
      kind: fc.constantFrom('show' as const, 'hide' as const, 'wait' as const, 'transform' as const, 'together' as const, 'camera' as const, 'change' as const),
      o: idx, o2: idx,
    }),
    fc.record({ op: fc.constant('duplicateStep' as const), s: idx, t: idx }),
    fc.record({ op: fc.constant('removeStep' as const), s: idx, t: idx }),
    fc.record({ op: fc.constant('renameStep' as const), s: idx, t: idx, name: fc.constantFrom(...NAMES, 'intro_1', 'second_1') }),
    fc.record({ op: fc.constant('moveStep' as const), s: idx, t: idx, to: idx }),
    fc.record({ op: fc.constant('caption' as const), s: idx, t: idx, text: fc.string({ maxLength: 12 }) }),
  ];
  return fc.oneof(...ops);
}

function pick<T>(list: T[] | undefined, i: number): T | undefined {
  if (!list || list.length === 0) return undefined;
  return list[i % list.length];
}

/** Apply one op; ops which refuse (DocOpError) leave the document as it was. */
function run(doc: Document, op: Op): Document {
  const scene: Scene | undefined = 's' in op ? pick(doc.scenes, op.s) : undefined;
  const objects = scene?.objects ?? [];
  const steps = scene?.steps ?? [];
  const obj = 'o' in op ? pick(objects, op.o) : undefined;
  const obj2 = 'o2' in op ? pick(objects, op.o2) : undefined;
  const step = 't' in op ? pick(steps, op.t) : undefined;
  try {
    switch (op.op) {
      case 'addScene':
        return addScene(doc).doc;
      case 'removeScene':
        return scene ? removeScene(doc, scene.id) : doc;
      case 'duplicateScene':
        return scene ? duplicateScene(doc, scene.id).doc : doc;
      case 'renameScene':
        return scene ? renameScene(doc, scene.id, op.name) : doc;
      case 'moveScene':
        return moveScene(doc, op.s % doc.scenes.length, op.to % doc.scenes.length);
      case 'addObject':
        return scene ? addObject(doc, scene.id, { type: op.type }).doc : doc;
      case 'addRefObject': {
        if (!scene || !obj) return doc;
        if (op.kind === 'brace') return addObject(doc, scene.id, { type: 'brace', target: obj.id }).doc;
        if (op.kind === 'next_to') return addObject(doc, scene.id, { type: 'text', text: 't', place: { next_to: obj.id } }).doc;
        if (op.kind === 'group') return addObject(doc, scene.id, { type: 'group', members: [obj.id, ...(obj2 && obj2.id !== obj.id ? [obj2.id] : [])] }).doc;
        return addObject(doc, scene.id, { type: 'graph', on: obj.id, function: 'x' }).doc;
      }
      case 'duplicateObject':
        return scene && obj ? duplicateObject(doc, scene.id, obj.id).doc : doc;
      case 'removeObject':
        return scene && obj ? removeObject(doc, scene.id, obj.id, { cascade: op.cascade }) : doc;
      case 'renameObject':
        return scene && obj ? renameObject(doc, scene.id, obj.id, op.name) : doc;
      case 'moveObject':
        return scene && objects.length ? moveObject(doc, scene.id, op.o % objects.length, op.to % objects.length) : doc;
      case 'addStep': {
        if (!scene) return doc;
        if (op.kind === 'wait') return addStep(doc, scene.id, { do: 'wait', duration: 1 }).doc;
        if (!obj) return doc;
        if (op.kind === 'transform') return addStep(doc, scene.id, { do: 'transform', target: obj.id, into: (obj2 ?? obj).id }).doc;
        if (op.kind === 'camera') return addStep(doc, scene.id, { do: 'camera', focus: obj.id }).doc;
        if (op.kind === 'change') return addStep(doc, scene.id, { do: 'change', target: obj.id, set: { color: 'RED', place: { next_to: (obj2 ?? obj).id } } }).doc;
        if (op.kind === 'together') {
          return addStep(doc, scene.id, { do: 'together', steps: [{ do: 'show', target: obj.id }, { do: 'hide', target: [(obj2 ?? obj).id] }] }).doc;
        }
        return addStep(doc, scene.id, { do: op.kind, target: obj2 && obj2.id !== obj.id ? [obj.id, obj2.id] : obj.id }).doc;
      }
      case 'duplicateStep':
        return scene && step?.id ? duplicateStep(doc, scene.id, step.id).doc : doc;
      case 'removeStep':
        return scene && step?.id ? removeStep(doc, scene.id, step.id) : doc;
      case 'renameStep':
        return scene && step?.id ? renameStep(doc, scene.id, step.id, op.name) : doc;
      case 'moveStep':
        return scene && steps.length ? moveStep(doc, scene.id, op.t % steps.length, op.to % steps.length) : doc;
      case 'caption':
        return scene && step?.id ? setItemField(doc, { kind: 'step', sceneId: scene.id, id: step.id }, ['caption'], op.text) : doc;
    }
  } catch (error) {
    if (error instanceof DocOpError) return doc;
    throw error;
  }
}

const RUNS = 300;

describe('random edit sequences', () => {
  it('keep ids unique and valid', () => {
    fc.assert(
      fc.property(fc.array(opArbitrary(true), { maxLength: 40 }), (ops) => {
        let doc = sampleDoc();
        for (const op of ops) {
          doc = run(doc, op);
          expect(invariantViolations(doc)).toEqual([]);
        }
      }),
      { numRuns: RUNS },
    );
  });

  it('keep every reference valid when removals cascade', () => {
    fc.assert(
      fc.property(fc.array(opArbitrary(false), { maxLength: 40 }), (ops) => {
        let doc = sampleDoc();
        for (const op of ops) {
          doc = run(doc, op);
          expect(invariantViolations(doc, { references: true })).toEqual([]);
        }
      }),
      { numRuns: RUNS },
    );
  });

  it('undo back to the start gives exactly the original, and redo gives the end again', () => {
    fc.assert(
      fc.property(fc.array(opArbitrary(true), { maxLength: 40 }), fc.boolean(), (ops, withKeys) => {
        const original = sampleDoc();
        const snapshot = JSON.stringify(original);
        let history = createHistory(original);
        let t = 0;
        for (const op of ops) {
          // Some edits carry coalescing keys; merged runs undo together, which must still work
          history = commit(history, run(history.present, op), withKeys ? { key: op.op, now: (t += 400) } : { now: (t += 5000) });
        }
        const end = history.present;
        const endJson = JSON.stringify(end);
        while (history.past.length) history = undo(history);
        expect(history.present).toBe(original);
        expect(JSON.stringify(history.present)).toBe(snapshot);
        while (history.future.length) history = redo(history);
        expect(history.present).toBe(end);
        expect(JSON.stringify(history.present)).toBe(endJson);
      }),
      { numRuns: RUNS },
    );
  });

  it('never leave a document which differs from its JSON round trip', () => {
    fc.assert(
      fc.property(fc.array(opArbitrary(true), { maxLength: 25 }), (ops) => {
        let doc = sampleDoc();
        for (const op of ops) doc = run(doc, op);
        expect(JSON.parse(JSON.stringify(doc))).toEqual(doc);
      }),
      { numRuns: 100 },
    );
  });
});
