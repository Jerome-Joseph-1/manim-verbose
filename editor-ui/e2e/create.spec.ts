/** A new user builds a scene from nothing: two objects, steps to show them, a caption, a preview. */
import { expect, test } from './fixtures';

test('create a scene from scratch and preview it', async ({ editor, page, consoleErrors }) => {
  await editor.open('empty');
  await expect(page.getByTestId('empty-scene')).toBeVisible();
  await expect(page.getByText('Nothing selected')).toBeVisible();

  // A text, with our own words
  await editor.addObject('Text');
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('Text');
  const text = editor.field('text').locator('textarea');
  await text.fill('Hello, triangles');
  await expect(page.getByTestId('empty-scene')).toBeHidden();

  // An equation
  await editor.addObject('Equation');
  await editor.field('tex').locator('textarea').fill('a^2 + b^2 = c^2');

  // Neither is shown by any step yet, and the editor says so
  await expect(page.getByTestId('never-shown')).toContainText("aren't shown by any step yet");

  // Steps to show them, one after the other
  await editor.objectRow('text').click();
  await editor.addStep('Show');
  await expect(editor.stepCards()).toHaveCount(1);
  await expect(editor.stepCards().first()).toContainText('text');
  await editor.objectRow('equation').click();
  await editor.addStep('Show');
  await expect(editor.stepCards()).toHaveCount(2);
  await expect(editor.stepCards().nth(1)).toContainText('equation');
  await expect(page.getByTestId('never-shown')).toBeHidden();

  // A caption on the first step
  await editor.stepCards().first().locator('.step-title').click();
  await editor.field('caption').locator('textarea').fill('Every right triangle');
  await expect(editor.stepCards().first()).toContainText('Every right triangle');

  await editor.waitSaved();
  const saved = await editor.serverDocument();
  const scene = saved.scenes[0]!;
  expect(scene.objects!.map((o) => [o.id, o.type])).toEqual([['text', 'text'], ['equation', 'tex']]);
  expect(scene.objects![0]!.text).toBe('Hello, triangles');
  expect(scene.steps!.map((s) => [s.do, s.target, s.caption ?? null])).toEqual([
    ['show', 'text', 'Every right triangle'],
    ['show', 'equation', null],
  ]);

  // The canvas shows both after the second step
  if (await editor.renderingWorks()) {
    await editor.stepCards().nth(1).locator('.step-title').click();
    await editor.waitStill();
    await expect(editor.objectBox('text')).toHaveCount(1);
    await expect(editor.objectBox('equation')).toHaveCount(1);

    // Preview the scene
    await page.getByRole('button', { name: 'Scene', exact: false }).first().isVisible();
    await page.getByTestId('scene-list').getByRole('button', { name: 'scene_1' }).click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    const dialog = page.getByTestId('preview-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('steps 1 to 2');
    await expect(dialog.getByTestId('preview-video').or(dialog.getByText("can't play the preview"))).toBeVisible({ timeout: 90_000 });
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
  }
  expect(consoleErrors).toEqual([]);
});

test("won't add a step with nothing to act on, and says why", async ({ editor, page }) => {
  await editor.open('empty');
  await editor.addStep('Show');
  await expect(page.getByRole('alert').filter({ hasText: 'add an object to this scene first' })).toBeVisible();
  await expect(editor.stepCards()).toHaveCount(0);
  await expect(editor.saveStatus).toHaveText(/Saved/);
});
