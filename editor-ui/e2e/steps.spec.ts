/** Reordering steps by dragging, and renaming an object everywhere it is used. */
import { expect, test } from './fixtures';

test('reorder steps by dragging', async ({ editor, page }) => {
  await editor.open('demo');
  const cards = editor.stepCards();
  await expect(cards).toHaveCount(4);
  const from = (await cards.nth(2).boundingBox())!;
  const to = (await cards.nth(0).boundingBox())!;
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2 - 10, { steps: 4 });
  await page.mouse.move(to.x + to.width / 2, to.y + 4, { steps: 12 });
  await page.mouse.up();
  await expect(cards.nth(0)).toContainText('eq, note');
  await expect(cards.nth(1)).toContainText('title');
  await editor.waitSaved();
  const saved = await editor.serverDocument();
  expect(saved.scenes[0]!.steps!.map((s) => s.id)).toEqual(['intro_3', 'intro_1', 'intro_2', 'intro_4']);
});

test('reorder steps with the keyboard', async ({ editor, page }) => {
  await editor.open('demo');
  await editor.stepCards().nth(0).locator('.step-title').focus();
  await page.keyboard.press('Alt+ArrowDown');
  await page.keyboard.press('Alt+ArrowDown');
  await expect(editor.stepCards().nth(2)).toContainText('title');
  await expect(editor.stepCards().nth(2).locator('.step-title')).toBeFocused();
  await editor.waitSaved();
  expect((await editor.serverDocument()).scenes[0]!.steps!.map((s) => s.id)).toEqual(['intro_2', 'intro_3', 'intro_1', 'intro_4']);
});

test('rename an object and every reference follows', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  await editor.objectRow('eq').click();
  const name = editor.field('id').locator('input');
  await name.fill('formula');
  await name.press('Enter');
  await expect(page.locator('[data-object-id="formula"]')).toBeVisible();
  await expect(editor.stepCards().nth(2)).toContainText('formula, note');
  await expect(editor.stepCards().nth(3)).toContainText('formula');
  await editor.objectRow('note').click();
  await expect(editor.field('place').getByRole('combobox', { name: /beside which object/ })).toHaveValue('formula');

  await editor.waitSaved();
  const scene = (await editor.serverDocument()).scenes[0]!;
  expect(scene.objects!.find((o) => o.id === 'note')!.place).toMatchObject({ next_to: 'formula' });
  expect(scene.steps!.map((s) => s.target)).toEqual(['title', 'tri', ['formula', 'note'], 'formula']);

  // A name already taken is refused, with the reason
  await editor.objectRow('formula').click();
  await editor.field('id').locator('input').fill('note');
  await editor.field('id').locator('input').press('Enter');
  await expect(editor.field('id')).toContainText("There's already an object called 'note'");
  expect(consoleErrors).toEqual([]);
});

test('delete an object in use: asked first, and what used it goes too', async ({ editor, page }) => {
  await editor.open('demo');
  await editor.objectRow('eq').click();
  await page.keyboard.press('Delete');
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toContainText("'eq' is used elsewhere");
  await expect(dialog).toContainText('Step 4, which only acts on it, will be deleted; step 3 will stop using it');
  await dialog.getByRole('button', { name: 'Delete it and what uses it' }).click();
  await expect(page.locator('[data-object-id="eq"]')).toHaveCount(0);
  await expect(editor.stepCards()).toHaveCount(3);
  await editor.waitSaved();
  const scene = (await editor.serverDocument()).scenes[0]!;
  expect(scene.steps!.map((s) => s.target)).toEqual(['title', 'tri', ['note']]);
  expect(scene.objects!.find((o) => o.id === 'note')!.place).toBeUndefined();
  // and it all comes back with undo
  await page.keyboard.press('Control+z');
  await expect(editor.stepCards()).toHaveCount(4);
});

test('scenes: add, rename, duplicate, reorder and delete', async ({ editor, page }) => {
  await editor.open('demo');
  await page.getByTestId('add-scene').click();
  await expect(page.getByTestId('scene-list').getByRole('listitem')).toHaveCount(3);
  await editor.field('title').locator('input').fill('Epilogue');
  await expect(page.getByTestId('scene-list')).toContainText('Epilogue');
  const row = page.locator('[data-scene-id="proof"]');
  await row.hover();
  await row.getByRole('button', { name: 'Duplicate scene A proof' }).click();
  await expect(page.getByTestId('scene-list').getByRole('listitem')).toHaveCount(4);
  // [intro, proof, proof_2, scene_1]: move scene_1 up two places
  await page.locator('[data-scene-id="scene_1"] .row-main').focus();
  await page.keyboard.press('Alt+ArrowUp');
  await expect(page.locator('[data-scene-id="scene_1"] .row-main')).toBeFocused();
  await page.keyboard.press('Alt+ArrowUp');
  const deleteRow = page.locator('[data-scene-id="proof_2"]');
  await deleteRow.hover();
  await deleteRow.getByRole('button', { name: /Delete scene/ }).click();
  await page.getByTestId('confirm-dialog').getByRole('button', { name: 'Delete scene' }).click();
  await editor.waitSaved();
  expect((await editor.serverDocument()).scenes.map((s) => [s.id, s.title ?? null])).toEqual([
    ['intro', 'The theorem'],
    ['scene_1', 'Epilogue'],
    ['proof', 'A proof'],
  ]);
});
