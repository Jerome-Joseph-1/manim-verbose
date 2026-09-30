/**
 * What every end to end test starts from: an `editor` driver on a fresh document.
 *
 * Against the mock, each test gets its own session (a cookie), so tests run in parallel
 * without seeing each other's edits. Against the real server, which edits one file, the
 * document is put back to the fixture through the API before each test.
 */
import { test as base, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Doc = {
  title?: string;
  scenes: {
    id: string;
    title?: string;
    objects?: { id: string; type: string; [k: string]: Json }[];
    steps?: { id: string; do: string; [k: string]: Json }[];
  }[];
  [k: string]: unknown;
};

export type FixtureName = 'demo' | 'empty' | 'eola' | 'broken';

export function fixtureDocument(name: FixtureName): Doc | null {
  if (name === 'broken') return null;
  if (name === 'empty') return { version: 1, title: 'Untitled', scenes: [{ id: 'scene_1' }] } as unknown as Doc;
  const file = name === 'eola' ? 'eola_vectors.json' : 'demo.json';
  return JSON.parse(fs.readFileSync(path.join(here, '../mock/fixtures', file), 'utf8')) as Doc;
}

export class EditorDriver {
  constructor(
    readonly page: Page,
    readonly real: boolean,
    readonly session: string,
  ) {}

  /** Start the server's document from a fixture and open the editor on it. */
  async open(fixture: FixtureName = 'demo', options: { latency?: number; exportMs?: number } = {}): Promise<void> {
    if (this.real) {
      const doc = fixtureDocument(fixture);
      if (!doc) throw new Error(`The real server can't be given the '${fixture}' fixture`);
      await this.putServerDocument(doc);
    } else {
      const response = await this.page.request.post('/__mock/reset', {
        data: { fixture, ...options },
        headers: { 'x-mock-session': this.session },
      });
      expect(response.ok()).toBeTruthy();
    }
    await this.page.goto('/');
    if (fixture !== 'broken') {
      await expect(this.page.locator('.app')).toBeVisible();
      await this.waitSaved();
    }
  }

  private headers(): Record<string, string> {
    return this.real ? {} : { 'x-mock-session': this.session };
  }

  async putServerDocument(doc: Doc): Promise<void> {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const current = await (await this.page.request.get('/api/document', { headers: this.headers() })).json();
      const response = await this.page.request.put('/api/document', {
        data: { document: doc, base_revision: current.revision },
        headers: this.headers(),
      });
      if (response.ok()) return;
    }
    throw new Error('Could not reset the server document');
  }

  /** The document as the server has it saved. */
  async serverDocument(): Promise<Doc> {
    const response = await this.page.request.get('/api/document', { headers: this.headers() });
    return (await response.json()).document as Doc;
  }

  /** The document as the editor holds it. */
  async document(): Promise<Doc> {
    return (await this.page.evaluate(() => (window as unknown as { __manimEditor: { document: () => unknown } }).__manimEditor.document())) as Doc;
  }

  async invariantViolations(): Promise<string[]> {
    return (await this.page.evaluate(() => (window as unknown as { __manimEditor: { check: () => string[] } }).__manimEditor.check())) as string[];
  }

  get saveStatus(): Locator {
    return this.page.getByTestId('save-status');
  }

  async waitSaved(timeout = 15_000): Promise<void> {
    await expect(this.saveStatus).toHaveText(/Saved/, { timeout });
  }

  get properties(): Locator {
    return this.page.getByRole('complementary', { name: 'Properties' });
  }

  field(name: string): Locator {
    return this.properties.locator(`.field[data-name="${name}"]`).first();
  }

  get canvas(): Locator {
    return this.page.getByTestId('canvas');
  }

  get still(): Locator {
    return this.page.getByTestId('still');
  }

  objectBox(id: string): Locator {
    return this.page.locator(`[data-testid="object-box"][data-object-id="${id}"]`);
  }

  stepCards(): Locator {
    return this.page.getByTestId('step-card');
  }

  objectRow(id: string): Locator {
    return this.page.locator(`[data-object-id="${id}"]`).locator('.row-main');
  }

  /** Wait for the canvas to have drawn the latest picture. */
  async waitStill(): Promise<void> {
    await expect(this.still).toBeVisible({ timeout: 20_000 });
    await expect(this.page.getByTestId('canvas-loading')).toHaveAttribute('data-loading', 'false', { timeout: 20_000 });
  }

  async addObject(label: string): Promise<void> {
    await this.page.getByTestId('add-object').click();
    await this.page.getByRole('menuitem', { name: new RegExp(`^${label}\\b`) }).click();
  }

  async addStep(label: string): Promise<void> {
    await this.page.getByTestId('add-step').click();
    await this.page.getByRole('menuitem', { name: new RegExp(`^${label}\\b`) }).click();
  }

  /** Click the middle of an object's box on the canvas. */
  async clickObject(id: string): Promise<void> {
    const box = await this.objectBox(id).boundingBox();
    if (!box) throw new Error(`${id} isn't on the canvas`);
    await this.page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  }

  /** Whether this server can make the Python code (the real one can't until codegen lands). */
  async codeWorks(): Promise<boolean> {
    if (!this.real) return true;
    const response = await this.page.request.post('/api/code', { data: { document: await this.serverDocument() }, timeout: 60_000 });
    return response.ok();
  }

  /** Whether this server can draw stills (the real one can't until rendering lands). */
  async renderingWorks(): Promise<boolean> {
    if (!this.real) return true;
    const doc = await this.serverDocument();
    const response = await this.page.request.post('/api/still', {
      data: { document: doc, scene_id: doc.scenes[0]!.id, step_index: 0, width: 320 },
      timeout: 90_000,
    });
    return response.ok();
  }
}

/** Console messages which are the browser's, not the editor's: expected HTTP statuses. */
export function isExpectedConsoleNoise(text: string, serverCantRender = false): boolean {
  if (serverCantRender && /status of 50\d/.test(text)) return true;
  return /Failed to load resource: the server responded with a status of (409|422|404|429)/.test(text);
}

let realRendering: Promise<boolean> | null = null;

/**
 * Whether the real server can draw stills yet. Until the rendering work lands it answers
 * still, clip, code and timeline requests with 500s, which the editor shows but which aren't
 * the editor's errors.
 */
function realServerRenders(request: APIRequestContext): Promise<boolean> {
  realRendering ??= request
    .post('/api/still', { data: { document: fixtureDocument('demo'), scene_id: 'intro', step_index: 0, width: 320 }, timeout: 90_000 })
    .then((r) => r.ok())
    .catch(() => false);
  return realRendering;
}

export const test = base.extend<{ editor: EditorDriver; consoleErrors: string[] }>({
  consoleErrors: async ({ page, request }, use, testInfo) => {
    const errors: string[] = [];
    const cantRender = testInfo.project.name === 'real' && process.env.E2E_REAL_AVAILABLE === '1' && !(await realServerRenders(request));
    page.on('console', (message) => {
      if (message.type() === 'error' && !isExpectedConsoleNoise(message.text(), cantRender)) errors.push(message.text());
    });
    page.on('pageerror', (error) => errors.push(`page error: ${error.message}`));
    await use(errors);
  },
  editor: async ({ page, context, baseURL }, use, testInfo) => {
    const real = testInfo.project.name === 'real';
    test.skip(real && process.env.E2E_REAL_AVAILABLE !== '1', 'manim_verbose.editor is not importable, so there is no real server to test');
    const session = `t${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
    if (!real) await context.addCookies([{ name: 'mock_session', value: session, url: baseURL! }]);
    await use(new EditorDriver(page, real, session));
  },
});

export { expect };
