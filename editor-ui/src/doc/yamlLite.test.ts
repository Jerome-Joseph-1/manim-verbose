import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { fromYaml, toYaml, YamlError } from './yamlLite';
import type { Json } from './types';

// The canonical YAML the Python server writes for the starter document (captured from
// manim_verbose/scenefile/files.dump_text). Opening a file made by the desktop editor has to
// work, so the reader is held to this exact shape: flow maps, flow sequences, block maps and
// compact block mappings inside sequences (`- id: hint` continued on the next lines).
const STARTER_YAML = `version: 1
title: My first video
scenes:
- id: hello
  title: Hello
  objects:
  - {id: greeting, type: text, text: Hello!, font_size: 72, color: BLUE}
  - id: hint
    type: text
    text: Click anything in the picture to change it
    font_size: 30
    place: {next_to: greeting, buff: 0.5}
  steps:
  - id: hello_1
    do: show
    target: greeting
    caption: A video is made of scenes, and a scene of steps
  - {id: hello_2, do: show, target: hint, style: fade_up}
  - {id: hello_3, do: highlight, target: greeting, style: wiggle}
  - {id: hello_4, do: wait}
  - {id: hello_5, do: clear}
- id: shapes
  title: Shapes that move
  objects:
  - {id: circle, type: circle, radius: 1.2, fill: BLUE, color: BLUE, place: [-3, 0]}
  - {id: square, type: square, fill: YELLOW, color: YELLOW, place: [3, 0]}
  - {id: arrow, type: line, start: [-1.5, 0], end: [1.5, 0], arrow: true}
  steps:
  - id: shapes_1
    do: show
    target: circle
    caption: Objects wait off screen until a step shows them
  - {id: shapes_2, do: show, target: arrow}
  - id: shapes_3
    do: transform
    target: circle
    into: square
    keep: true
    caption: One thing can turn into another
  - {id: shapes_4, do: move, target: square, to: top}
  - id: shapes_5
    do: change
    target: square
    set: {fill: GREEN, color: GREEN}
    caption: Or change color
  - {id: shapes_6, do: wait, duration: 2}
`;

describe('fromYaml on the server\'s canonical output', () => {
  it('reads the starter document exactly', () => {
    const doc = fromYaml(STARTER_YAML) as Record<string, Json>;
    expect(doc.version).toBe(1);
    expect(doc.title).toBe('My first video');
    const scenes = doc.scenes as Record<string, Json>[];
    expect(scenes).toHaveLength(2);
    expect(scenes[0]!.id).toBe('hello');

    const objects = scenes[0]!.objects as Record<string, Json>[];
    // A flow mapping
    expect(objects[0]).toEqual({ id: 'greeting', type: 'text', text: 'Hello!', font_size: 72, color: 'BLUE' });
    // A compact block mapping in a sequence, with a nested flow map
    expect(objects[1]).toEqual({
      id: 'hint', type: 'text', text: 'Click anything in the picture to change it',
      font_size: 30, place: { next_to: 'greeting', buff: 0.5 },
    });

    const steps = scenes[0]!.steps as Record<string, Json>[];
    expect(steps[0]).toEqual({
      id: 'hello_1', do: 'show', target: 'greeting',
      caption: 'A video is made of scenes, and a scene of steps',
    });
    expect(steps[3]).toEqual({ id: 'hello_4', do: 'wait' });

    // Flow sequences of numbers, and a boolean
    const arrow = (scenes[1]!.objects as Record<string, Json>[])[2];
    expect(arrow).toEqual({ id: 'arrow', type: 'line', start: [-1.5, 0], end: [1.5, 0], arrow: true });

    // A nested flow map inside a compact block mapping
    const change = (scenes[1]!.steps as Record<string, Json>[])[4]!;
    expect(change.set).toEqual({ fill: 'GREEN', color: 'GREEN' });
  });
});

describe('scalars', () => {
  it('reads the YAML scalar types the format uses', () => {
    const doc = fromYaml([
      'a: 1',
      'b: -2.5',
      'c: true',
      'd: false',
      'e: null',
      'f: ~',
      'g: hello world',
      "h: 'quoted: value'",
      'i: "with \\"quotes\\" and \\n newline"',
      'j: BLUE',
      'k: 1e3',
    ].join('\n')) as Record<string, Json>;
    expect(doc).toEqual({
      a: 1, b: -2.5, c: true, d: false, e: null, f: null,
      g: 'hello world', h: 'quoted: value', i: 'with "quotes" and \n newline',
      j: 'BLUE', k: 1000,
    });
  });

  it('does not treat yes/no/on/off as booleans (scene files are YAML 1.2 here)', () => {
    const doc = fromYaml('a: yes\nb: no\nc: on\nd: off') as Record<string, Json>;
    expect(doc).toEqual({ a: 'yes', b: 'no', c: 'on', d: 'off' });
  });
});

describe('block scalars', () => {
  it('reads a literal | block', () => {
    const doc = fromYaml(['text: |', '  line one', '  line two', 'after: 1'].join('\n')) as Record<string, Json>;
    expect(doc.text).toBe('line one\nline two');
    expect(doc.after).toBe(1);
  });
});

describe('errors', () => {
  it('reports tabs, not a mystery', () => {
    expect(() => fromYaml('a:\n\tb: 1')).toThrow(YamlError);
  });
  it('reports an unterminated flow', () => {
    expect(() => fromYaml('a: [1, 2')).toThrow(YamlError);
  });
});

describe('round trip', () => {
  const jsonValue: fc.Arbitrary<Json> = fc.letrec<{ node: Json }>((tie) => ({
    node: fc.oneof(
      { depthSize: 'small', withCrossShrink: true },
      fc.constant(null),
      fc.boolean(),
      fc.integer({ min: -1000, max: 1000 }),
      fc.double({ min: -1000, max: 1000, noNaN: true, noDefaultInfinity: true }).map((n) => Math.round(n * 100) / 100 + 0),
      // Strings without control characters (and without tabs, which YAML indentation forbids);
      // the format's text is ordinary
      fc.string().filter((s) => ![...s].some((c) => c.charCodeAt(0) < 0x20)),
      fc.array(tie('node'), { maxLength: 4 }),
      fc.dictionary(
        fc.stringMatching(/^[A-Za-z_][A-Za-z0-9_]*$/),
        tie('node'),
        { maxKeys: 5 },
      ),
    ),
  })).node;

  it('reads back whatever it writes', () => {
    fc.assert(
      fc.property(jsonValue, (value) => {
        const text = toYaml(value);
        const back = fromYaml(text);
        expect(back).toEqual(value);
      }),
      { numRuns: 400 },
    );
  });
});

describe('a whole document round-trips through toYaml/fromYaml', () => {
  it('keeps every field', () => {
    const original = fromYaml(STARTER_YAML);
    const text = toYaml(original);
    expect(fromYaml(text)).toEqual(original);
  });
});
