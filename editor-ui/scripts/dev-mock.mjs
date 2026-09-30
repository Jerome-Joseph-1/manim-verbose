#!/usr/bin/env node
// `npm run dev:mock`: the mock server and Vite together, Vite proxying /api and /files to
// the mock. Ctrl+C stops both. Pass --fixture empty|demo|eola|broken to pick a document.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const port = process.env.MOCK_PORT ?? '8790';
const extra = process.argv.slice(2);

const children = [
  spawn(process.execPath, ['mock/server.mjs', '--port', port, ...extra], { cwd: root, stdio: 'inherit' }),
  spawn(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js')], {
    cwd: root,
    stdio: 'inherit',
    env: { ...process.env, EDITOR_API: `http://127.0.0.1:${port}` },
  }),
];

const stop = () => {
  for (const child of children) child.kill('SIGTERM');
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
for (const child of children) child.on('exit', (code) => code && stop());
