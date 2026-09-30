/** Twenty edits of all sorts, undone one by one back to the start, then redone. */
import { expect, test } from './fixtures';

test('20 edits, then undo all and redo all', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  const original = await editor.document();
  const undoButton = page.getByRole('button', { name: 'Undo' });
  const redoButton = page.getByRole('button', { name: 'Redo' });
  await expect(undoButton).toBeDisabled();

  const pickColor = async (name: string) => {
    await editor.field('color').getByRole('button', { name: /pick from manim's colors/ }).click();
    await editor.field('color').getByRole('button', { name, exact: true }).click();
  };

  // Each of these is one edit (selecting something first, where needed, isn't one)
  const edits: [string, () => Promise<void>][] = [
    ['add a circle', () => editor.addObject('Circle')],
    ['add a square', () => editor.addObject('Square')],
    ['add a text', () => editor.addObject('Text')],
    ['add a show step', () => editor.addStep('Show')],
    ['add a wait', () => editor.addStep('Wait')],
    ['color eq', async () => {
      await editor.objectRow('eq').click();
      await pickColor('Green');
    }],
    ['duplicate eq', () => page.keyboard.press('Control+d')],
    ['add a highlight', () => editor.addStep('Highlight')],
    ['make note italic', async () => {
      await editor.objectRow('note').click();
      await editor.field('italic').getByRole('checkbox').check();
    }],
    ['make note bold', () => editor.field('bold').getByRole('checkbox').check()],
    ['align note left', () => editor.field('align').getByRole('radio', { name: 'Left' }).click()],
    ['put note against an edge', () => editor.field('place').getByRole('radio', { name: 'Edge' }).click()],
    ['in the top right corner', () => editor.field('place').getByRole('button', { name: 'Top right' }).click()],
    ['color note', () => pickColor('Teal')],
    ['add a dot', () => editor.addObject('Dot')],
    ['clear the screen', () => editor.addStep('Clear screen')],
    ['add a scene', () => page.getByTestId('add-scene').click()],
    ['add axes to it', () => editor.addObject('Axes')],
    ['show them', () => editor.addStep('Show')],
    ['zoom the camera', () => editor.addStep('Camera')],
  ];
  expect(edits).toHaveLength(20);
  for (const [what, edit] of edits) {
    const before = JSON.stringify(await editor.document());
    await edit();
    await expect.poll(async () => JSON.stringify(await editor.document()), { message: what }).not.toBe(before);
  }
  const end = await editor.document();

  for (let i = 0; i < 20; i += 1) await page.keyboard.press('Control+z');
  await expect(undoButton).toBeDisabled();
  expect(await editor.document()).toEqual(original);

  for (let i = 0; i < 20; i += 1) await redoButton.click();
  await expect(redoButton).toBeDisabled();
  expect(await editor.document()).toEqual(end);

  await editor.waitSaved();
  expect(await editor.invariantViolations()).toEqual([]);
  const saved = await editor.serverDocument();
  expect(saved.scenes.map((s) => s.id)).toEqual(end.scenes.map((s) => s.id));
  expect(saved.scenes[0]!.objects!.map((o) => o.id)).toEqual(end.scenes[0]!.objects!.map((o) => o.id));
  expect(consoleErrors).toEqual([]);
});
