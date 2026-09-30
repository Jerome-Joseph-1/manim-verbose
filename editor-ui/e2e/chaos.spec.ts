/**
 * A minute of random clicks, keys, typing and drags. Afterwards: no console errors or page
 * errors, ids still unique and valid, and the server has accepted the document the editor
 * holds (the editor never made one the server couldn't read).
 *
 * The run is seeded (CHAOS_SEED, printed), so a failure can be replayed.
 */
import type { Locator, Page } from '@playwright/test';
import { expect, test } from './fixtures';

const DURATION_MS = Number(process.env.CHAOS_MS ?? 60_000);

function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const KEYS = [
  'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Shift+ArrowUp', 'Delete', 'Backspace', 'Escape', 'Enter', 'Tab', 'Shift+Tab',
  'Control+z', 'Control+Shift+z', 'Control+y', 'Control+d', '[', ']', 'Alt+ArrowDown', 'Alt+ArrowUp', ' ', 'Home', 'End',
];
const WORDS = ['x', 'hello', 'a^2', '\\frac{1}{2}', 'blue', 'RED', '#58C4DD', '12', '-3', '0', '', 'eq', 'note', 'new_name', '1bad', 'c^2', '$x$', 'é ü', '{', '}'];

async function visible(locator: Locator): Promise<Locator[]> {
  const all = await locator.all();
  const out: Locator[] = [];
  for (const item of all.slice(0, 200)) {
    if (await item.isVisible().catch(() => false)) out.push(item);
  }
  return out;
}

async function randomAction(page: Page, rand: () => number): Promise<string> {
  const pick = <T,>(xs: T[]): T | undefined => xs[Math.floor(rand() * xs.length)];
  const r = rand();
  if (r < 0.42) {
    const targets = await visible(page.locator('button:not([disabled]), [role="menuitem"], [role="radio"], input[type="checkbox"], input[type="radio"], .row-main, .step-title'));
    const target = pick(targets);
    if (!target) return 'nothing to click';
    const name = (await target.textContent().catch(() => ''))?.trim().slice(0, 30) ?? '';
    // Leave the page alone: never start the file over
    if (/Start a new video/.test(name)) return 'skipped';
    await target.click({ timeout: 1000, trial: false }).catch(() => undefined);
    return `click ${name}`;
  }
  if (r < 0.55) {
    const inputs = await visible(page.locator('input[type="text"]:not([disabled]), input[type="number"], input:not([type]), textarea'));
    const input = pick(inputs);
    if (!input) return 'nothing to type into';
    const word = pick(WORDS)!;
    await input.fill(word, { timeout: 1000 }).catch(() => undefined);
    if (rand() < 0.5) await input.press(rand() < 0.5 ? 'Enter' : 'Tab').catch(() => undefined);
    return `type ${word}`;
  }
  if (r < 0.62) {
    const selects = await visible(page.locator('select:not([disabled])'));
    const select = pick(selects);
    if (!select) return 'no select';
    const options = await select.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
    const value = pick(options);
    if (value !== undefined) await select.selectOption(value, { timeout: 1000 }).catch(() => undefined);
    return `select ${value}`;
  }
  if (r < 0.82) {
    const key = pick(KEYS)!;
    await page.keyboard.press(key);
    return `key ${key}`;
  }
  const canvas = await page.getByTestId('canvas').boundingBox();
  if (!canvas) return 'no canvas';
  const x = canvas.x + rand() * canvas.width;
  const y = canvas.y + rand() * canvas.height;
  if (r < 0.9) {
    await page.mouse.click(x, y);
    return 'canvas click';
  }
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (rand() - 0.5) * 300, y + (rand() - 0.5) * 200, { steps: 5 });
  await page.mouse.up();
  return 'canvas drag';
}

test('a minute of random input leaves a valid, saved document and no errors', async ({ editor, page, consoleErrors }) => {
  test.skip(editor.real, 'chaos runs against the mock');
  test.setTimeout(DURATION_MS + 120_000);
  const seed = Number(process.env.CHAOS_SEED ?? Date.now() % 1_000_000);
  test.info().annotations.push({ type: 'seed', description: String(seed) });
  console.log(`chaos seed ${seed}`);
  const rand = prng(seed);
  await editor.open('demo', { latency: 30, exportMs: 1500 });
  page.on('dialog', (dialog) => void dialog.dismiss());
  page.on('popup', (popup) => void popup.close());

  const log: string[] = [];
  const end = Date.now() + DURATION_MS;
  while (Date.now() < end) {
    log.push(await randomAction(page, rand));
    if (page.url().startsWith('about:') || !(await page.locator('#root').isVisible())) throw new Error(`The editor went away after: ${log.slice(-10).join(' / ')}`);
    expect(consoleErrors, `after: ${log.slice(-10).join(' / ')}`).toEqual([]);
  }

  // Close whatever is open and let saving settle
  for (let i = 0; i < 4; i += 1) await page.keyboard.press('Escape');
  await page.keyboard.press('Control+s');
  await expect
    .poll(async () => page.evaluate(() => (window as unknown as { __manimEditor: { state: () => { saveState: string } } }).__manimEditor.state().saveState), { timeout: 20_000 })
    .toBe('saved');

  expect(await editor.invariantViolations()).toEqual([]);
  const mine = await editor.document();
  const theirs = await editor.serverDocument();
  expect(theirs).toEqual(mine);
  expect(consoleErrors).toEqual([]);
  test.info().annotations.push({ type: 'actions', description: `${log.length} actions` });
});
