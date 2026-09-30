/**
 * The scene file as data, as the server sends it (see manim_verbose/scenefile/model.py).
 *
 * Types are deliberately loose: every object and step kind carries its own fields, which
 * the editor learns from the json schema at run time rather than from these types. What
 * is spelled out here is only what the document operations rely on.
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export type Edge =
  | 'center' | 'top' | 'bottom' | 'left' | 'right'
  | 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';
export type Side = 'up' | 'down' | 'left' | 'right';

export interface Placement {
  at?: number[] | null;
  /** A coordinate system `at` is given in; frame units when left out. */
  on?: string | null;
  edge?: Edge | null;
  next_to?: string | null;
  side?: Side;
  buff?: number;
  shift?: number[] | null;
}

export interface SceneObject {
  id: string;
  type: string;
  [field: string]: Json | undefined;
}

export interface Step {
  do: string;
  id?: string | null;
  caption?: string | null;
  [field: string]: Json | undefined;
}

export interface Scene {
  id: string;
  title?: string | null;
  background?: string | null;
  objects?: SceneObject[];
  steps?: Step[];
}

export interface Document {
  version?: number;
  title?: string;
  settings?: JsonObject;
  scenes: Scene[];
}

/** Any field of a scene or document by name, for the generic form code. */
export function fieldOf(item: Scene | Document, name: string): Json | undefined {
  return (item as unknown as Record<string, Json | undefined>)[name];
}

/** A path into the document as data, as in a problem's `loc`. */
export type Loc = (string | number)[];

export interface Problem {
  message: string;
  severity: 'error' | 'warning';
  loc: Loc;
  path?: string;
  scene_id: string | null;
  item_id: string | null;
}

export const ID_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const ID_MAX_LENGTH = 64;
