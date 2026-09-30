// Templates for the mock server: every JSON document in mock/templates/, named by its file
// name, with a thumbnail drawn the way the mock draws stills (the last frame of its first
// scene). The real server reads manim_verbose/templates/*.yaml with PNG thumbnails.
import fs from 'node:fs';
import path from 'node:path';
import { renderStill } from './layout.mjs';

export function loadTemplates(folder) {
  if (!fs.existsSync(folder)) return [];
  return fs
    .readdirSync(folder)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((file) => {
      const name = file.replace(/\.json$/, '');
      const document = JSON.parse(fs.readFileSync(path.join(folder, file), 'utf8'));
      const scene = document.scenes[0];
      const thumbnailSvg = renderStill(document, scene, (scene.steps ?? []).length - 1, 384).svg;
      return {
        name,
        title: document.title ?? name,
        description: document.description ?? null,
        thumbnail_url: `/api/templates/${name}/thumbnail.svg`,
        document,
        thumbnailSvg,
      };
    });
}
