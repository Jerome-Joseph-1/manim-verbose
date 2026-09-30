/**
 * End to end tests, in two projects:
 *
 *   mock  against mock/server.mjs serving the built editor (fast, deterministic; the
 *         screenshots and the chaos run live here)
 *   real  against the real server, `python -m manim_verbose.editor.cli`, on a copy of a
 *         fixture file. Skipped when manim_verbose.editor can't be imported.
 *
 *   npx playwright test --project=mock
 *   npx playwright test --project=real
 *
 * Chromium comes from `npx playwright install chromium` (CI) or PLAYWRIGHT_BROWSERS_PATH;
 * set PW_CHROMIUM to use another build of it.
 */
import { defineConfig, devices } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const MOCK_PORT = Number(process.env.E2E_MOCK_PORT ?? 8797);
const REAL_PORT = Number(process.env.E2E_REAL_PORT ?? 8799);
const python = process.env.PYTHON ?? 'python3';
const CI = Boolean(process.env.CI);

/** Projects asked for on the command line (all when none are). */
function requestedProjects(): string[] {
  const out: string[] = [];
  process.argv.forEach((a, i) => {
    if (a === '--project' && process.argv[i + 1]) out.push(process.argv[i + 1]!);
    else if (a.startsWith('--project=')) out.push(a.slice('--project='.length));
  });
  return out;
}

const projects = requestedProjects();
const wantsReal = projects.length === 0 || projects.includes('real');
const wantsMock = projects.length === 0 || projects.includes('mock');

const realImportable =
  wantsReal &&
  spawnSync(python, ['-c', 'import manim_verbose.editor.cli, manim_verbose.editor.server'], {
    cwd: repoRoot,
    env: { ...process.env, PYTHONPATH: repoRoot },
    stdio: 'ignore',
  }).status === 0;
process.env.E2E_REAL_AVAILABLE = realImportable ? '1' : '0';

const launch = process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {};

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 8_000, toHaveScreenshot: { maxDiffPixelRatio: 0.01, animations: 'disabled', caret: 'hide' } },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  // The real server edits one file, so its tests take turns
  workers: wantsReal ? 1 : 2,
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}{ext}',
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: launch,
  },
  projects: [
    {
      name: 'mock',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 }, baseURL: `http://127.0.0.1:${MOCK_PORT}` },
    },
    {
      name: 'real',
      testIgnore: /(screenshots|chaos)\.spec\.ts/,
      timeout: 120_000,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 }, baseURL: `http://127.0.0.1:${REAL_PORT}` },
    },
  ],
  webServer: [
    ...(wantsMock
      ? [
          {
            command: `npm run build && node mock/server.mjs --port ${MOCK_PORT} --static ../manim_verbose/editor/static --quiet`,
            url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
            reuseExistingServer: !CI,
            timeout: 180_000,
            env: { MOCK_EXPORT_MS: '2500' },
          },
        ]
      : []),
    ...(realImportable
      ? [
          {
            command: `${wantsMock ? '' : 'npm run build && '}node e2e/start-real.mjs ${REAL_PORT}`,
            url: `http://127.0.0.1:${REAL_PORT}/api/health`,
            reuseExistingServer: !CI,
            timeout: 180_000,
            env: { PYTHONPATH: repoRoot, PYTHON: python },
          },
        ]
      : []),
  ],
});
