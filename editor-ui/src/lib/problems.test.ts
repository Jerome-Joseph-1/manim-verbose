import { describe, expect, it } from 'vitest';
import {
  dedupeProblems, isRequestProblem, locateProblem, problemsForField, problemsForItem, sameItem, sortProblems, worstSeverity,
} from './problems';
import type { Problem } from '../doc/types';
import { moveStep } from '../doc/ops';
import { sampleDoc } from '../test/fixtures';

function problem(loc: (string | number)[], extra: Partial<Problem> = {}): Problem {
  return { message: 'm', severity: 'error', loc, path: '', scene_id: null, item_id: null, ...extra };
}

describe('locating a problem', () => {
  it('finds the object and the field', () => {
    const p = problem(['scenes', 0, 'objects', 2, 'place', 'next_to'], { scene_id: 'intro', item_id: 'label' });
    expect(locateProblem(p)).toEqual({ kind: 'object', sceneId: 'intro', itemId: 'label', field: ['place', 'next_to'] });
  });

  it('finds a step, even one nested in together', () => {
    expect(locateProblem(problem(['scenes', 0, 'steps', 3, 'target'], { scene_id: 'intro', item_id: 'intro_4' }))).toEqual({
      kind: 'step', sceneId: 'intro', itemId: 'intro_4', field: ['target'],
    });
    expect(locateProblem(problem(['scenes', 0, 'steps', 7, 'steps', 1, 'target', 0], { scene_id: 'intro', item_id: 'intro_10' }))).toEqual({
      kind: 'step', sceneId: 'intro', itemId: 'intro_10', field: ['target', 0],
    });
  });

  it('keeps a problem about the steps of a together on the together', () => {
    const p = problem(['scenes', 0, 'steps', 7, 'steps'], { scene_id: 'intro', item_id: 'intro_8' });
    expect(locateProblem(p)).toMatchObject({ kind: 'step', itemId: 'intro_8', field: ['steps'] });
  });

  it('finds a change step property', () => {
    const p = problem(['scenes', 0, 'steps', 6, 'set', 'colour'], { scene_id: 'intro', item_id: 'intro_7' });
    expect(locateProblem(p)).toMatchObject({ kind: 'step', field: ['set', 'colour'] });
  });

  it('finds scenes and the document', () => {
    expect(locateProblem(problem(['scenes', 1, 'id'], { scene_id: 'second' }))).toEqual({ kind: 'scene', sceneId: 'second', itemId: null, field: ['id'] });
    expect(locateProblem(problem(['scenes', 1]), sampleDoc())).toMatchObject({ kind: 'scene', sceneId: 'second', field: [] });
    expect(locateProblem(problem(['settings', 'fps']))).toEqual({ kind: 'document', sceneId: null, itemId: null, field: ['settings', 'fps'] });
    expect(locateProblem(problem([]))).toMatchObject({ kind: 'document', field: [] });
  });

  it('fills in ids from the document when the problem has none', () => {
    const p = problem(['scenes', 0, 'objects', 1, 'tex']);
    expect(locateProblem(p, sampleDoc())).toEqual({ kind: 'object', sceneId: 'intro', itemId: 'eq', field: ['tex'] });
  });

  it('prefers ids, which survive steps moving, over positions', () => {
    // The problem was found when intro_4 was the fourth step; it has since moved first
    const doc = moveStep(sampleDoc(), 'intro', 3, 0);
    const p = problem(['scenes', 0, 'steps', 3, 'into'], { scene_id: 'intro', item_id: 'intro_4' });
    expect(locateProblem(p, doc)).toMatchObject({ itemId: 'intro_4', field: ['into'] });
  });

  it('knows problems about the request rather than the document', () => {
    expect(isRequestProblem(problem(['step_index']))).toBe(true);
    expect(isRequestProblem(problem(['width']))).toBe(true);
    expect(isRequestProblem(problem(['scenes', 0]))).toBe(false);
    expect(isRequestProblem(problem(['title']))).toBe(false);
  });
});

describe('matching problems to fields', () => {
  const problems = [
    problem(['scenes', 0, 'objects', 1, 'tex'], { scene_id: 'intro', item_id: 'eq', message: 'bad tex' }),
    problem(['scenes', 0, 'objects', 1, 'place', 'next_to'], { scene_id: 'intro', item_id: 'eq', message: 'no such object' }),
    problem(['scenes', 0, 'objects', 1], { scene_id: 'intro', item_id: 'eq', message: 'about eq', severity: 'warning' }),
    problem(['scenes', 1, 'objects', 0, 'tex'], { scene_id: 'second', item_id: 'eq', message: 'other scene' }),
    problem(['scenes', 0, 'steps', 2, 'part'], { scene_id: 'intro', item_id: 'intro_3', message: 'part' }),
  ];
  const eq = { kind: 'object' as const, sceneId: 'intro', itemId: 'eq' };

  it('puts each under its field, and only its own item', () => {
    expect(problemsForField(problems, eq, ['tex']).map((p) => p.message)).toEqual(['bad tex']);
    expect(problemsForField(problems, eq, ['place']).map((p) => p.message)).toEqual(['no such object']);
    expect(problemsForField(problems, eq, ['place'], { exact: true })).toEqual([]);
    expect(problemsForField(problems, eq, [], { exact: true }).map((p) => p.message)).toEqual(['about eq']);
    expect(problemsForField(problems, { kind: 'object', sceneId: 'second', itemId: 'eq' }, ['tex']).map((p) => p.message)).toEqual(['other scene']);
    expect(problemsForField(problems, { kind: 'step', sceneId: 'intro', itemId: 'intro_3' }, ['part'])).toHaveLength(1);
  });

  it('collects everything about an item', () => {
    expect(problemsForItem(problems, eq)).toHaveLength(3);
    expect(worstSeverity(problemsForItem(problems, eq))).toBe('error');
    expect(worstSeverity([problems[2]!])).toBe('warning');
    expect(worstSeverity([])).toBeNull();
  });

  it('compares items', () => {
    const target = locateProblem(problems[0]!);
    expect(sameItem(target, eq)).toBe(true);
    expect(sameItem(target, { kind: 'step', sceneId: 'intro', itemId: 'eq' })).toBe(false);
    expect(sameItem({ kind: 'document', sceneId: null, itemId: null, field: [] }, { kind: 'document' })).toBe(true);
  });

  it('drops duplicates and sorts errors first, in document order', () => {
    const twice = [...problems, { ...problems[0]! }];
    expect(dedupeProblems(twice)).toHaveLength(problems.length);
    const sorted = sortProblems(problems);
    expect(sorted.at(-1)!.severity).toBe('warning');
    expect(sorted[0]!.loc).toEqual(['scenes', 0, 'objects', 1, 'place', 'next_to']);
  });
});
