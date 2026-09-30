import { createContext, useContext } from 'react';
import type { SchemaIndex } from '../../lib/schema';
import type { ItemAddress } from '../../lib/problems';
import type { Document, Loc, Problem, Scene } from '../../doc/types';

export interface CommitOptions {
  /** Merge with the previous edit of this field into one undo step (typing). */
  coalesce?: boolean;
}

export interface FormCtx {
  schema: SchemaIndex;
  doc: Document;
  scene: Scene | null;
  /** The object, step, scene or document being edited, for matching problems. */
  item: ItemAddress;
  problems: Problem[];
  /** Write a value at a path inside the item; `undefined` removes it. */
  commit: (path: Loc, value: unknown, options?: CommitOptions) => void;
  /** Rename the item (for its id field); returns an error message or null. */
  rename?: (newId: string) => string | null;
  /** Prefix making input ids unique on the page. */
  idPrefix: string;
}

export const FormContext = createContext<FormCtx | null>(null);

export function useForm(): FormCtx {
  const ctx = useContext(FormContext);
  if (!ctx) throw new Error('Form fields need a FormContext');
  return ctx;
}
