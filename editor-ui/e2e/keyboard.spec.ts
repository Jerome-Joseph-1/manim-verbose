/** The main things a user does, with the keyboard alone: no mouse in this file. */
import type { Locator, Page } from '@playwright/test';
import { expect, test } from './fixtures';

/** Press Tab until the element has focus, as a keyboard user would. */
async function tabTo(page: Page, target: Locator, max = 120): Promise<void> {
  for (let i = 0; i < max; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error(`Couldn't reach ${target} with Tab`);
}

test('build and edit a scene with the keyboard only', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  await page.locator('body').focus();

  // Add an equation from the Object menu
  await tabTo(page, page.getByTestId('add-object'));
  await page.keyboard.press('Enter');
  const menu = page.getByRole('menu', { name: 'Add an object' });
  await expect(menu).toBeVisible();
  for (let i = 0; i < 10; i += 1) {
    if ((await page.evaluate(() => document.activeElement?.textContent ?? '')).startsWith('Equation')) break;
    await page.keyboard.press('ArrowDown');
  }
  await page.keyboard.press('Enter');
  await expect(menu).toBeHidden();
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('Equation');

  // Write its formula
  await tabTo(page, editor.field('tex').locator('textarea'));
  await page.keyboard.press('Control+a');
  await page.keyboard.type('x^2 + y^2 = r^2');
  await page.keyboard.press('Tab');
  expect((await editor.document()).scenes[0]!.objects!.find((o) => o.id === 'equation')!.tex).toBe('x^2 + y^2 = r^2');

  // Add a step showing it (the first entry of the Step menu is Show)
  await tabTo(page, page.getByTestId('add-step'));
  await page.keyboard.press('Enter');
  await expect(page.getByRole('menu', { name: 'Add a step' })).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(editor.stepCards()).toHaveCount(5);
  await expect(editor.stepCards().nth(4)).toContainText('equation');

  // Give it a caption, then think better of it
  await tabTo(page, editor.field('caption').locator('textarea'));
  await page.keyboard.type('A circle, as an equation');
  await expect(editor.stepCards().nth(4)).toContainText('A circle, as an equation');
  await page.keyboard.press('Control+z');
  await expect(editor.stepCards().nth(4)).not.toContainText('A circle');

  // Pick an object from the list and nudge it
  await tabTo(page, editor.objectRow('eq'));
  await page.keyboard.press('Enter');
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('Equation');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect.poll(async () => (await editor.document()).scenes[0]!.objects!.find((o) => o.id === 'eq')!.place).toEqual({ at: [3.7, -1] });

  // Reorder a step
  await tabTo(page, editor.stepCards().nth(0).locator('.step-title'));
  await page.keyboard.press('Alt+ArrowDown');
  await expect(editor.stepCards().nth(1)).toContainText('title');

  // Delete an object, confirming in the dialog
  await tabTo(page, editor.objectRow('tri'));
  await page.keyboard.press('Enter');
  await page.keyboard.press('Delete');
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Delete it and what uses it' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-object-id="tri"]')).toHaveCount(0);

  // Open the export dialog and close it again
  await tabTo(page, page.getByRole('button', { name: 'Export', exact: true }));
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('export-dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('export-dialog')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Export', exact: true })).toBeFocused();

  // Change a color from the palette
  await tabTo(page, editor.objectRow('eq'));
  await page.keyboard.press('Enter');
  await tabTo(page, editor.field('color').getByRole('button', { name: /pick from manim's colors/ }));
  await page.keyboard.press('Enter');
  await tabTo(page, editor.field('color').getByRole('button', { name: 'Yellow', exact: true }));
  await page.keyboard.press('Enter');
  await expect(editor.field('color').locator('input[type="text"]')).toHaveValue('YELLOW');

  await editor.waitSaved();
  expect(await editor.invariantViolations()).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('the shortcuts list opens with ? and closes with Escape', async ({ editor, page }) => {
  await editor.open('demo');
  await page.locator('body').focus();
  await page.keyboard.press('?');
  await expect(page.getByTestId('shortcuts-dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('shortcuts-dialog')).toBeHidden();
});
