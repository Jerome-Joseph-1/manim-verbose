/** axe-core over the editor in its main states: no serious or critical violations. */
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

async function seriousViolations(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  return results.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id} (${v.impact}): ${v.help} at ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
}

for (const theme of ['dark', 'light'] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ editor, page }) => {
      await page.addInitScript((t) => localStorage.setItem('manim-editor-theme', t), theme);
      await editor.open('demo');
    });

    test('the editor with nothing selected', async ({ page }) => {
      expect(await seriousViolations(page)).toEqual([]);
    });

    test('an object selected, its properties showing', async ({ editor, page }) => {
      await editor.objectRow('note').click();
      await expect(editor.field('text')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test('a step selected, with a problem showing', async ({ editor, page }) => {
      await editor.stepCards().nth(3).locator('.step-title').click();
      await editor.field('part').locator('input').fill('zz');
      await editor.waitSaved();
      await page.getByTestId('problems-panel').getByRole('button', { name: /Problems/ }).click();
      await expect(page.getByTestId('problem-item')).toHaveCount(1);
      expect(await seriousViolations(page)).toEqual([]);
    });

    test('the dialogs', async ({ editor, page }) => {
      await page.getByRole('button', { name: 'Export', exact: true }).click();
      await expect(page.getByTestId('export-dialog')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: 'Code', exact: true }).click();
      await expect(page.getByTestId('code-view')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press('Escape');
      await editor.objectRow('eq').click();
      await page.keyboard.press('Delete');
      await expect(page.getByTestId('confirm-dialog')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test('menus and the palette open', async ({ editor, page }) => {
      await page.getByTestId('add-object').click();
      await expect(page.getByRole('menu')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
      await page.keyboard.press('Escape');
      await editor.objectRow('eq').click();
      await editor.field('color').getByRole('button', { name: /pick from manim's colors/ }).click();
      expect(await seriousViolations(page)).toEqual([]);
    });

    test('an empty scene', async ({ page }) => {
      await page.getByTestId('add-scene').click();
      await expect(page.getByTestId('empty-scene')).toBeVisible();
      expect(await seriousViolations(page)).toEqual([]);
    });
  });
}
