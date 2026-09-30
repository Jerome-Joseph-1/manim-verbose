/** Putting the editor's store into a known state for component tests. */
import type { Document, Problem } from '../doc/types';
import { catalogFromSchema } from '../lib/templates';
import { initialState, loaded, select, useEditor, type Selection } from '../state/store';
import { schema, schemaIndex } from './fixtures';

export function setupEditor(doc: Document, options: { selection?: Selection; problems?: Problem[] } = {}): void {
  useEditor.setState(initialState(), true);
  loaded({
    document: doc,
    revision: 1,
    path: '/videos/test.yaml',
    problems: options.problems ?? [],
    schema,
    catalog: catalogFromSchema(schemaIndex),
  });
  if (options.selection) select(options.selection);
}

export function editorDoc(): Document {
  const doc = useEditor.getState().history?.present;
  if (!doc) throw new Error('no document loaded');
  return doc;
}
