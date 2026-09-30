#!/usr/bin/env node
// Starts the real editor server for the `real` end to end project on a fresh copy of the
// fixture document and an empty render cache, so the tests never touch a file in the
// repository and never depend on what an earlier run left:
//
//   python -m manim_verbose.editor.cli <tmp>/lesson.yaml --no-browser --port <port>
//
// The fixture is JSON, which is also valid YAML.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '../..');
const port = process.argv[2] ?? '8799';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'manim-editor-e2e-'));
const file = path.join(dir, 'lesson.yaml');
fs.copyFileSync(path.join(here, '../mock/fixtures/demo.json'), file);

const python = process.env.PYTHON ?? 'python3';
const child = spawn(python, ['-m', 'manim_verbose.editor.cli', file, '--no-browser', '--port', port, '--output-dir', path.join(dir, 'out')], {
  cwd: repoRoot,
  stdio: 'inherit',
  // A render cache of its own too, so an export really renders every run rather than
  // finishing at once from scenes an earlier run left behind
  env: { ...process.env, PYTHONPATH: repoRoot, MANIM_VERBOSE_CACHE: path.join(dir, 'cache') },
});

const stop = () => {
  child.kill('SIGTERM');
  fs.rmSync(dir, { recursive: true, force: true });
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
child.on('exit', (code) => {
  fs.rmSync(dir, { recursive: true, force: true });
  process.exit(code ?? 0);
});
