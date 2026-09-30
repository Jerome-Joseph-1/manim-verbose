/**
 * The editor as it looks, compared with pictures kept in e2e/__screenshots__, at two sizes in
 * both themes. After a deliberate change of look: npm run e2e:update, and check the new ones.
 */
import { expect, test } from './fixtures';

const SIZES = [
  { width: 1280, height: 800 },
  { width: 1920, height: 1080 },
];

for (const theme of ['dark', 'light'] as const) {
  for (const size of SIZES) {
    test(`editor ${size.width}x${size.height} ${theme}`, async ({ editor, page }) => {
      await page.setViewportSize(size);
      await page.addInitScript((t) => localStorage.setItem('manim-editor-theme', t), theme);
      await editor.open('demo');
      await editor.waitStill();
      await editor.clickObject('eq');
      await expect(editor.field('tex')).toBeVisible();
      await editor.waitStill();
      await page.mouse.move(0, 0);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await expect(page).toHaveScreenshot(`editor-${size.width}x${size.height}-${theme}.png`);
    });
  }
}

test('empty video, first run', async ({ editor, page }) => {
  await editor.open('empty');
  await editor.waitStill();
  await expect(page).toHaveScreenshot('first-run-1280x800-dark.png');
});
