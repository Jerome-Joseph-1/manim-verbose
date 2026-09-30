import schemaJson from '../../../manim_verbose/scenefile/schema.json';
import type { Document } from '../doc/types';
import { buildSchemaIndex, type JsonSchema } from '../lib/schema';

export const schema = schemaJson as unknown as JsonSchema;
export const schemaIndex = buildSchemaIndex(schema);

/** A document using every kind of reference there is, in two scenes. */
export function sampleDoc(): Document {
  return {
    version: 1,
    title: 'Pythagoras',
    scenes: [
      {
        id: 'intro',
        title: 'Introduction',
        objects: [
          { id: 'plane', type: 'number_plane' },
          { id: 'eq', type: 'tex', tex: 'a^2 + b^2 = c^2', place: { edge: 'top' } },
          { id: 'label', type: 'text', text: 'The theorem', place: { next_to: 'eq', side: 'down' } },
          { id: 'dot', type: 'dot', point: [1, 2], on: 'plane' },
          { id: 'brace', type: 'brace', target: 'eq', label: 'c' },
          { id: 'group', type: 'group', members: ['eq', 'label'] },
          { id: 'axes', type: 'axes' },
          { id: 'graph', type: 'graph', on: 'axes', function: 'sin(x)' },
        ],
        steps: [
          { id: 'intro_1', do: 'show', target: 'plane' },
          { id: 'intro_2', do: 'show', target: ['eq', 'label'], caption: 'The oldest theorem you know' },
          { id: 'intro_3', do: 'highlight', target: 'eq', part: 'c^2' },
          { id: 'intro_4', do: 'transform', target: 'label', into: 'eq', keep: true },
          { id: 'intro_5', do: 'camera', focus: 'eq', zoom: 2 },
          { id: 'intro_6', do: 'move', target: 'dot', to: { next_to: 'eq', side: 'right' } },
          { id: 'intro_7', do: 'change', target: 'label', set: { color: 'RED', place: { next_to: 'eq' } } },
          {
            id: 'intro_8',
            do: 'together',
            steps: [
              { id: 'intro_9', do: 'show', target: 'brace' },
              { id: 'intro_10', do: 'highlight', target: 'eq' },
            ],
          },
          { id: 'intro_11', do: 'wait', duration: 2 },
          { id: 'intro_12', do: 'clear' },
        ],
      },
      {
        id: 'second',
        objects: [{ id: 'eq', type: 'text', text: 'Another eq in another scene' }],
        steps: [{ id: 'second_1', do: 'show', target: 'eq' }],
      },
    ],
  };
}
