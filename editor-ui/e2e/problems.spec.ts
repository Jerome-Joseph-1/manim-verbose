/** Mistakes are explained beside the field they are about, and nothing else stops working. */
import { expect, test } from './fixtures';

test('bad LaTeX: an error on the field and in the Problems panel, and the rest keeps working', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  test.skip(!(await editor.renderingWorks()), 'LaTeX is only checked when drawing, and this server cannot draw yet');
  await editor.waitStill();
  await editor.objectRow('eq').click();
  await editor.field('tex').locator('textarea').fill('c^2 = \\frac{a}{b');

  const canvasError = page.getByTestId('canvas-error');
  await expect(canvasError).toContainText("couldn't be typeset", { timeout: 60_000 });
  await expect(editor.field('tex')).toContainText("couldn't be typeset");
  await expect(editor.field('tex')).toHaveClass(/has-error/);
  // The last good picture stays
  await expect(editor.still).toBeVisible();

  await canvasError.getByRole('button', { name: 'Show problems' }).click();
  const item = page.getByTestId('problem-item').filter({ hasText: "couldn't be typeset" });
  await expect(item).toBeVisible();
  await expect(item).toContainText('eq');

  // Saving goes on, other objects can be edited, other scenes drawn
  await editor.waitSaved();
  await editor.objectRow('note').click();
  await editor.field('text').locator('textarea').fill('Only for right triangles');
  await editor.waitSaved();
  await page.getByTestId('scene-list').getByRole('button', { name: 'A proof' }).click();
  await editor.waitStill();
  await expect(canvasError).toBeHidden();
  await expect(editor.objectBox('square')).toHaveCount(1);

  // Fixing it clears the problem
  await page.getByTestId('scene-list').getByRole('button', { name: 'The theorem' }).click();
  await item.click();
  await expect(editor.field('tex').locator('textarea')).toBeFocused();
  await editor.field('tex').locator('textarea').fill('a^2 + b^2 = c^2');
  await expect(canvasError).toBeHidden({ timeout: 60_000 });
  await expect(page.getByTestId('problem-item')).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test('a field the server finds wrong: shown beside it and listed; the list leads back to it', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  // The highlight step picks out part of the equation; ask for a part it doesn't have
  await editor.stepCards().nth(3).locator('.step-title').click();
  await editor.field('part').locator('input').fill('d^2');
  await editor.waitSaved();
  await expect(editor.field('part')).toContainText("'d^2' doesn't appear in 'eq'");
  await expect(editor.stepCards().nth(3).locator('.problem-dot.error')).toBeVisible();

  const panel = page.getByTestId('problems-panel');
  await expect(panel.getByRole('button', { name: /Problems/ })).toContainText('1 error');
  await panel.getByRole('button', { name: /Problems/ }).click();
  await editor.objectRow('title').click();
  await page.getByTestId('problem-item').filter({ hasText: "'d^2' doesn't appear" }).click();
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('Highlight step');
  await expect(editor.field('part').locator('input')).toBeFocused();

  // The rest of the document is still saved as it is edited
  await editor.objectRow('title').click();
  await editor.field('text').locator('input').fill('Pythagoras again');
  await editor.waitSaved();
  expect((await editor.serverDocument()).scenes[0]!.objects![0]!.text).toBe('Pythagoras again');

  await editor.stepCards().nth(3).locator('.step-title').click();
  await editor.field('part').locator('input').fill('c^2');
  await editor.waitSaved();
  await expect(editor.field('part')).not.toContainText("doesn't appear");
  await expect(panel.getByRole('button', { name: /Problems/ })).toContainText('None');
  expect(consoleErrors).toEqual([]);
});

test('an out of range number is refused at once, beside the field', async ({ editor }) => {
  await editor.open('demo');
  await editor.objectRow('note').click();
  const size = editor.field('font_size').locator('input');
  await size.fill('0');
  await expect(editor.field('font_size')).toContainText('Has to be more than 0');
  await editor.waitSaved();
  expect((await editor.serverDocument()).scenes[0]!.objects!.find((o) => o.id === 'note')!.font_size).toBe(32);
  await size.fill('24');
  await editor.waitSaved();
  expect((await editor.serverDocument()).scenes[0]!.objects!.find((o) => o.id === 'note')!.font_size).toBe(24);
});
