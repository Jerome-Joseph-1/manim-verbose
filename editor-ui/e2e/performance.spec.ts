/**
 * The ten minute example (11 scenes, 285 steps) stays quick to work with: switching scenes,
 * picking steps, and typing into the properties panel.
 */
import { expect, test } from './fixtures';

test.skip(({ editor }) => editor.real, 'the big fixture is loaded into the mock only');

test('a long video stays responsive', async ({ editor, page, consoleErrors }) => {
  await editor.open('eola');
  const scenes = page.getByTestId('scene-list').getByRole('listitem');
  await expect(scenes).toHaveCount(11);

  // Switching between scenes
  const switchTimes: number[] = [];
  for (let i = 0; i < 11; i += 1) {
    const t0 = Date.now();
    await scenes.nth(i).locator('.row-main').click();
    await expect(scenes.nth(i)).toHaveClass(/selected/);
    await expect(editor.stepCards().first()).toBeVisible();
    switchTimes.push(Date.now() - t0);
  }

  // The scene with the most steps
  const counts = await page.evaluate(() =>
    (window as unknown as { __manimEditor: { document: () => { scenes: { steps?: unknown[] }[] } } }).__manimEditor.document().scenes.map((s) => s.steps?.length ?? 0),
  );
  const biggest = counts.indexOf(Math.max(...counts));
  await scenes.nth(biggest).locator('.row-main').click();
  await expect(editor.stepCards()).toHaveCount(counts[biggest]!);

  // Picking steps one after another
  const pickTimes: number[] = [];
  for (let i = 0; i < 20; i += 1) {
    const card = editor.stepCards().nth(i);
    const t0 = Date.now();
    await card.locator('.step-title').click();
    await expect(card).toHaveClass(/selected/);
    await expect(editor.properties.locator('.props-body')).toHaveAttribute('data-item-id', (await card.getAttribute('data-step-id'))!);
    pickTimes.push(Date.now() - t0);
  }

  // Typing a caption, key by key
  await editor.stepCards().nth(5).locator('.step-title').click();
  const caption = editor.field('caption').locator('textarea');
  await caption.fill('');
  const text = 'Vectors are lists of numbers, and arrows, at once.';
  const t0 = Date.now();
  await caption.pressSequentially(text);
  await expect(editor.stepCards().nth(5)).toContainText(text);
  const typing = Date.now() - t0;

  const median = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)]!;
  test.info().annotations.push({ type: 'timings', description: `scene switch median ${median(switchTimes)} ms, step pick median ${median(pickTimes)} ms, ${text.length} keys typed in ${typing} ms` });
  expect(median(switchTimes)).toBeLessThan(400);
  expect(median(pickTimes)).toBeLessThan(250);
  expect(typing / text.length).toBeLessThan(60);
  await editor.waitSaved();
  expect(consoleErrors).toEqual([]);
});
