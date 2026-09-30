// Documents the mock server can start from, each a JSON file in fixtures/ (the end to end
// tests load the same files into the real server):
//   demo    a small lesson in two scenes (the default)
//   empty   what a brand new file looks like
//   eola    the ten minute example video (examples/eola_vectors/vectors.yaml, converted by
//           scripts/convert_fixture.py), for checking the editor stays quick with a big one
//   geometry  a number plane with plotted objects on it and around it, for dragging
//   broken  a file which can't be read at all (GET /api/document gives document: null)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const load = (name) => () => JSON.parse(fs.readFileSync(path.join(here, 'fixtures', `${name}.json`), 'utf8'));

export const FIXTURES = {
  empty: () => ({ version: 1, title: 'Untitled', scenes: [{ id: 'scene_1' }] }),
  demo: load('demo'),
  eola: load('eola_vectors'),
  geometry: load('geometry'),
};

export const DEFAULT_FIXTURE = 'demo';
