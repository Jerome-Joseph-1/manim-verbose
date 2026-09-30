/** Exporting the finished video: progress, a download, and cancelling. */
import { expect, test } from './fixtures';

test('export shows progress and ends with a download link', async ({ editor, page, consoleErrors }) => {
  await editor.open('demo');
  test.skip(!(await editor.renderingWorks()), 'this server cannot render yet');
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByTestId('export-dialog');
  await dialog.getByLabel(/Draft/).check();
  await dialog.getByRole('button', { name: 'Start export' }).click();
  const bar = dialog.getByRole('progressbar', { name: 'Export progress' });
  await expect(bar).toBeVisible();
  // It moves on, and the top bar says how far while the dialog is hidden
  await expect.poll(async () => Number(await bar.getAttribute('aria-valuenow')), { timeout: 60_000 }).toBeGreaterThan(0);
  await dialog.getByRole('button', { name: 'Hide' }).click();
  await expect(page.getByRole('button', { name: /Exporting \d+%/ })).toBeVisible();
  await page.getByRole('button', { name: /Exporting|Export/ }).click();
  const link = page.getByTestId('download-link');
  await expect(link).toBeVisible({ timeout: 10 * 60_000 });
  await expect(bar).toHaveAttribute('aria-valuenow', '100');
  expect(await link.getAttribute('href')).toMatch(/^\/files\/exports\/.+\.mp4$/);
  const download = page.waitForEvent('download');
  await link.click();
  expect((await download).suggestedFilename()).toMatch(/\.mp4$/);
  expect(consoleErrors).toEqual([]);
});

test('an export can be cancelled', async ({ editor, page }) => {
  await editor.open('demo', { exportMs: 20_000 });
  test.skip(!(await editor.renderingWorks()), 'this server cannot render yet');
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByTestId('export-dialog');
  await dialog.getByRole('button', { name: 'Start export' }).click();
  await expect(dialog.getByRole('progressbar')).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel export' }).click();
  await expect(dialog.getByTestId('export-status')).toContainText('Export cancelled');
  await expect(dialog.getByRole('button', { name: 'Export again' })).toBeEnabled();
});

test("an export which can't start says why", async ({ editor, page }) => {
  await editor.open('demo');
  await editor.stepCards().nth(3).locator('.step-title').click();
  await editor.field('part').locator('input').fill('zz');
  await editor.waitSaved();
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const dialog = page.getByTestId('export-dialog');
  await dialog.getByRole('button', { name: 'Start export' }).click();
  await expect(dialog.getByRole('alert').first()).toContainText("'zz' doesn't appear in 'eq'");
});
