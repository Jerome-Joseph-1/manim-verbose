/** What the editor does when the file changes elsewhere, can't be read, or the code is wanted. */
import { expect, test } from './fixtures';

test.describe('against the mock only', () => {
  test.skip(({ editor }) => editor.real, 'needs the mock server to change the file behind the editor');

  test('a change made elsewhere shows a conflict; keeping mine saves over it', async ({ editor, page }) => {
    await editor.open('demo');
    await page.request.post('/__mock/external-edit', { data: { title: 'Changed on disk' }, headers: { 'x-mock-session': editor.session } });
    await page.getByLabel('Video title').fill('My title');
    const banner = page.getByTestId('conflict-banner');
    await expect(banner).toBeVisible();
    await expect(editor.saveStatus).toHaveText(/Conflict/);
    await banner.getByRole('button', { name: 'Keep mine' }).click();
    await editor.waitSaved();
    expect((await editor.serverDocument()).title).toBe('My title');
  });

  test('a conflict can be resolved by loading their version', async ({ editor, page }) => {
    await editor.open('demo');
    await page.request.post('/__mock/external-edit', { data: { title: 'Changed on disk' }, headers: { 'x-mock-session': editor.session } });
    await page.getByLabel('Video title').fill('My title');
    await page.getByTestId('conflict-banner').getByRole('button', { name: 'Load their version' }).click();
    await expect(page.getByLabel('Video title')).toHaveValue('Changed on disk');
    await expect(page.getByTestId('conflict-banner')).toBeHidden();
    await editor.waitSaved();
    // Undo brings back what was mine
    await page.getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByLabel('Video title')).toHaveValue('My title');
  });

  test("a file which can't be read offers to start over", async ({ editor, page }) => {
    await editor.open('broken');
    await expect(page.getByRole('heading', { name: "This file can't be opened as a video" })).toBeVisible();
    await expect(page.getByText("This isn't valid YAML")).toBeVisible();
    await page.getByRole('button', { name: 'Start a new video in this file' }).click();
    await expect(page.locator('.app')).toBeVisible();
    await expect(page.getByTestId('empty-scene')).toBeVisible();
    expect((await editor.serverDocument()).scenes.map((s) => s.id)).toEqual(['scene_1']);
  });

  test('saving goes on after the server was unreachable for a while', async ({ editor, page }) => {
    await editor.open('demo');
    await page.request.post('/__mock/config', { data: { failNext: { path: '/api/document', status: 503 } }, headers: { 'x-mock-session': editor.session } });
    await page.getByLabel('Video title').fill('Written while down');
    await expect(editor.saveStatus).toHaveText(/Offline/);
    await editor.waitSaved(20_000);
    expect((await editor.serverDocument()).title).toBe('Written while down');
  });
});

test('see the Python code, for a scene or the whole video', async ({ editor, page }) => {
  await editor.open('demo');
  await page.getByRole('button', { name: 'Code', exact: true }).click();
  const dialog = page.getByTestId('code-dialog');
  const code = dialog.getByTestId('code-view');
  await expect(code).toContainText('from manimlib import *', { timeout: 30_000 });
  await expect(code).toContainText('class Intro');
  await expect(code).not.toContainText('class Proof');
  await dialog.getByRole('radio', { name: 'Whole video' }).click();
  await expect(code).toContainText('class Proof', { timeout: 30_000 });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await dialog.getByRole('button', { name: 'Copy code' }).click();
  await expect(dialog.getByRole('button', { name: 'Copied' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});
