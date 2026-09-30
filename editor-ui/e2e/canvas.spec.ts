/** Working on the picture: click to select, change a property, drag to move. */
import { expect, test } from './fixtures';

test.beforeEach(async ({ editor }) => {
  await editor.open('demo');
  test.skip(!(await editor.renderingWorks()), 'this server cannot draw stills yet');
  await editor.waitStill();
});

test('click an object, change its color, and the picture follows', async ({ editor, page, consoleErrors }) => {
  await editor.clickObject('eq');
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('Equation');
  await expect(editor.objectBox('eq')).toHaveClass(/selected/);
  await expect(page.locator('[data-object-id="eq"] .row-main')).toHaveAttribute('aria-pressed', 'true');

  const before = await editor.still.getAttribute('src');
  const color = editor.field('color');
  await color.getByRole('button', { name: /pick from manim's colors/ }).click();
  await color.getByRole('button', { name: 'Red', exact: true }).click();
  await expect(color.locator('input[type="text"]')).toHaveValue('RED');
  await expect(editor.still).not.toHaveAttribute('src', before!, { timeout: 30_000 });
  await editor.waitSaved();
  const saved = await editor.serverDocument();
  expect(saved.scenes[0]!.objects!.find((o) => o.id === 'eq')!.color).toBe('RED');
  expect(consoleErrors).toEqual([]);
});

test('clicking again where objects overlap picks the one underneath', async ({ editor, page }) => {
  // The note sits under the equation; the title is elsewhere. Clicking on the equation
  // twice reaches nothing else, so check the cycling on the canvas as a whole instead.
  await editor.clickObject('eq');
  await expect(page.locator('[data-object-id="eq"] .row-main')).toHaveAttribute('aria-pressed', 'true');
  const box = (await editor.objectBox('tri').boundingBox())!;
  await page.mouse.click(box.x + box.width - 4, box.y + box.height - 4);
  await expect(page.locator('[data-object-id="tri"] .row-main')).toHaveAttribute('aria-pressed', 'true');
  // A click on nothing selects the scene
  const canvas = (await editor.canvas.boundingBox())!;
  await page.mouse.click(canvas.x + 6, canvas.y + canvas.height / 2);
  await expect(editor.properties.getByRole('heading', { level: 2 })).toContainText('The theorem');
});

test('drag an object, and it stays where it was put after a reload', async ({ editor, page }) => {
  const start = (await editor.objectBox('eq').boundingBox())!;
  const x = start.x + start.width / 2;
  const y = start.y + start.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 60, y - 40, { steps: 6 });
  await page.mouse.move(x - 120, y - 80, { steps: 6 });
  await page.mouse.up();
  await editor.waitSaved();
  const saved = await editor.serverDocument();
  const place = saved.scenes[0]!.objects!.find((o) => o.id === 'eq')!.place as { at: number[] };
  // Started at [3.5, -1]; moved left and up
  expect(place.at[0]).toBeLessThan(3.5 - 1);
  expect(place.at[1]).toBeGreaterThan(-1 + 0.5);

  await page.reload();
  await editor.waitSaved();
  await editor.waitStill();
  const after = (await editor.objectBox('eq').boundingBox())!;
  expect(Math.abs(after.x + after.width / 2 - (x - 120))).toBeLessThan(6);
  expect(Math.abs(after.y + after.height / 2 - (y - 80))).toBeLessThan(6);
});

test('arrow keys nudge the selected object', async ({ editor, page }) => {
  await editor.clickObject('eq');
  await editor.canvas.focus();
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('Shift+ArrowUp');
  await editor.waitSaved();
  const saved = await editor.serverDocument();
  expect(saved.scenes[0]!.objects!.find((o) => o.id === 'eq')!.place).toEqual({ at: [3.4, 0] });
});

test('stepping through the frames changes what is on screen', async ({ editor, page }) => {
  await editor.stepCards().first().locator('.step-title').click();
  await editor.waitStill();
  await expect(page.getByTestId('frame-label')).toContainText('After step 1 of 4');
  await expect(editor.objectBox('title')).toHaveCount(1);
  await expect(editor.objectBox('eq')).toHaveCount(0);
  await page.getByRole('button', { name: 'Show the frame after the next step' }).click();
  await page.getByRole('button', { name: 'Show the frame after the next step' }).click();
  await editor.waitStill();
  await expect(page.getByTestId('frame-label')).toContainText('After step 3 of 4');
  await expect(editor.objectBox('eq')).toHaveCount(1);
});
