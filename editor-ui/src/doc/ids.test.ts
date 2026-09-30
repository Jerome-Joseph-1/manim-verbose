import { describe, expect, it } from 'vitest';
import { isValidId, iterSteps, newObjectId, newSceneId, newStepId, objectBaseName, sanitizeId, stepIds, uniqueId } from './ids';
import { sampleDoc } from '../test/fixtures';

describe('ids', () => {
  it('knows a valid id', () => {
    expect(isValidId('eq')).toBe(true);
    expect(isValidId('_x1')).toBe(true);
    expect(isValidId('1x')).toBe(false);
    expect(isValidId('my eq')).toBe(false);
    expect(isValidId('')).toBe(false);
    expect(isValidId('a'.repeat(65))).toBe(false);
  });

  it('turns what someone typed into a valid id', () => {
    expect(sanitizeId('My circle!')).toBe('My_circle');
    expect(sanitizeId('2nd')).toBe('_2nd');
    expect(sanitizeId('   ')).toBe('item');
    expect(sanitizeId('a__b')).toBe('a__b');
    expect(sanitizeId('_private')).toBe('_private');
    expect(sanitizeId('é')).toBe('item');
    expect(sanitizeId('x'.repeat(100)).length).toBe(64);
  });

  it('makes unique ids', () => {
    expect(uniqueId('circle', new Set())).toBe('circle');
    expect(uniqueId('circle', new Set(['circle']))).toBe('circle_2');
    expect(uniqueId('circle', new Set(['circle', 'circle_2']))).toBe('circle_3');
    expect(uniqueId('circle_2', new Set(['circle_2']))).toBe('circle_3');
    expect(uniqueId('circle', new Set(), { bare: false })).toBe('circle_2');
    expect(uniqueId('scene', new Set(), { bare: false, start: 1 })).toBe('scene_1');
    const long = 'y'.repeat(64);
    const id = uniqueId(long, new Set([long]));
    expect(isValidId(id)).toBe(true);
    expect(id).not.toBe(long);
  });

  it('numbers steps the way the server does', () => {
    const doc = sampleDoc();
    expect(newStepId('intro', stepIds(doc))).toBe('intro_13');
    expect(newStepId('fresh', stepIds(doc))).toBe('fresh_1');
  });

  it('names objects after their kind', () => {
    const scene = sampleDoc().scenes[0]!;
    expect(objectBaseName('tex')).toBe('equation');
    expect(newObjectId(scene, 'circle')).toBe('circle');
    expect(newObjectId(scene, 'number_plane')).toBe('plane_2');
    expect(newSceneId(sampleDoc())).toBe('scene_1');
  });

  it('walks nested steps depth first', () => {
    const ids = [...iterSteps(sampleDoc().scenes[0]!.steps)].map((s) => s.id);
    expect(ids).toEqual(['intro_1', 'intro_2', 'intro_3', 'intro_4', 'intro_5', 'intro_6', 'intro_7', 'intro_8', 'intro_9', 'intro_10', 'intro_11', 'intro_12']);
  });
});
