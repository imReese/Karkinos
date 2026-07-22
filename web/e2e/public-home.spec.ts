import { expect, test } from '@playwright/test';

test('public home presents the brand contract before entering the workbench', async ({
  page,
}) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) {
      apiRequests.push(request.url());
    }
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  await expect(page.locator('h1')).toHaveCount(1);
  await expect(
    page.getByRole('heading', {
      name: 'Every decision should leave evidence.',
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Public navigation' }),
  ).toBeVisible();
  await expect(page.locator('.app-shell-frame')).toHaveCount(0);
  await expect(page.getByRole('contentinfo')).toBeVisible();
  expect(apiRequests).toEqual([]);

  const readingOrder = await page.evaluate(() => {
    const ids = ['product', 'principles', 'workflow'];
    return ids.map((id) =>
      Math.round(document.getElementById(id)?.getBoundingClientRect().top ?? 0),
    );
  });
  expect(readingOrder[0]).toBeLessThan(readingOrder[1] ?? 0);
  expect(readingOrder[1]).toBeLessThan(readingOrder[2] ?? 0);

  const documentOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(0);

  await page
    .getByRole('banner')
    .getByRole('link', { name: 'Enter workbench' })
    .click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.locator('.app-shell-frame')).toBeVisible();
  await expect(page.getByRole('contentinfo')).toHaveCount(0);
});

test('public home remains localized, themeable, and overflow safe on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  await page.getByRole('button', { name: 'Switch to Mocha theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: 'Switch to Chinese' }).click();
  await expect(
    page.getByRole('heading', {
      name: '让每一个投资决定，都有证据可回放。',
    }),
  ).toBeVisible();

  const geometry = await page.evaluate(() => ({
    documentOverflow:
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
    controls: Array.from(
      document.querySelectorAll<HTMLElement>(
        '.app-public-header button, .app-public-header a[href]',
      ),
    )
      .map((element) => ({
        height: element.getBoundingClientRect().height,
        width: element.getBoundingClientRect().width,
      }))
      .filter((control) => control.height > 0 && control.width > 0),
  }));
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.controls.every((control) => control.height >= 36)).toBe(true);
});
