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

  const composition = await page.evaluate(() => {
    const ids = ['product', 'principles', 'workflow'];
    const readingOrder = ids.map((id) =>
      Math.round(document.getElementById(id)?.getBoundingClientRect().top ?? 0),
    );
    const evidenceTop = Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    );
    return { evidenceTop, readingOrder };
  });
  expect(composition.readingOrder[0]).toBeLessThan(900);
  expect(composition.readingOrder[0]).toBeLessThan(
    composition.readingOrder[1] ?? 0,
  );
  expect(composition.readingOrder[1]).toBeLessThan(
    composition.readingOrder[2] ?? 0,
  );
  expect(composition.evidenceTop).toBeLessThan(500);

  await expect(
    page.getByLabel('Public-to-private route').getByText('/overview'),
  ).toBeVisible();
  await expect(page.getByText('Read and review only')).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open surface: Account Truth' }),
  ).toHaveAttribute('href', '/account-truth');

  const documentOverflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(documentOverflow).toBeLessThanOrEqual(0);

  await page
    .getByRole('banner')
    .getByRole('link', { name: 'Open private workbench' })
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
    evidenceTop: Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    ),
  }));
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
  expect(geometry.controls.every((control) => control.height >= 36)).toBe(true);
  expect(geometry.evidenceTop).toBeLessThan(700);
  await expect(page.getByText('仅查看与复核')).toBeVisible();
});
