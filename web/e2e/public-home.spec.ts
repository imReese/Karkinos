import { expect, test } from '@playwright/test';

const publicHomeViewports = [
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
  { width: 1280, height: 800 },
  { width: 1024, height: 768 },
  { width: 834, height: 1112 },
  { width: 768, height: 1024 },
  { width: 390, height: 844 },
] as const;

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
    const evidenceTop = Math.round(
      document
        .querySelector('.app-public-evidence-frame')
        ?.getBoundingClientRect().top ?? 0,
    );
    return {
      evidenceTop,
      verticalOverflow:
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    };
  });
  expect(composition.evidenceTop).toBeLessThan(500);
  expect(composition.verticalOverflow).toBeLessThanOrEqual(0);

  await expect(
    page.getByLabel('Public-to-private route').getByText('/overview'),
  ).toBeVisible();
  await expect(page.getByLabel('Workbench structure')).toBeVisible();
  await expect(
    page.getByRole('heading', {
      name: 'Resolve the highest blocker first.',
    }),
  ).toBeVisible();
  await expect(page.getByText('Read and review only')).toBeVisible();
  const publicNavigation = page.getByRole('navigation', {
    name: 'Public navigation',
  });
  await publicNavigation.getByRole('link', { name: 'Product' }).click();
  await expect(page.locator('#product')).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'Open surface: Account Truth' }),
  ).toHaveAttribute('href', '/account-truth');
  await publicNavigation.getByRole('link', { name: 'Trust' }).click();
  await expect(page.locator('#principles')).toBeVisible();
  await publicNavigation.getByRole('link', { name: 'Workflow' }).click();
  await expect(page.locator('#workflow')).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    ),
  ).toBeLessThanOrEqual(0);

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
  await expect(
    page.getByRole('banner').getByText('工作台', { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator('.app-public-evidence-boundary')
      .getByText('仅查看与复核', { exact: true }),
  ).toBeVisible();
});

test('public home preserves its composition across the six visual acceptance viewports', async ({
  page,
}) => {
  for (const viewport of publicHomeViewports) {
    await page.setViewportSize(viewport);
    await page.goto('/');

    const latteGeometry = await page.evaluate(() => ({
      documentOverflow:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      evidenceTop: Math.round(
        document
          .querySelector('.app-public-evidence-frame')
          ?.getBoundingClientRect().top ?? 0,
      ),
      localOverflow: Array.from(
        document.querySelectorAll<HTMLElement>(
          '.app-public-header, .app-public-hero, .app-public-evidence-frame, .app-public-proof-grid, .app-public-workflow, .app-public-footer',
        ),
      )
        .map((element) => ({
          className: element.className,
          overflow: element.scrollWidth - element.clientWidth,
        }))
        .filter(({ overflow }) => overflow > 0),
      verticalOverflow:
        document.documentElement.scrollHeight -
        document.documentElement.clientHeight,
    }));
    expect(latteGeometry.documentOverflow, JSON.stringify(viewport)).toBe(0);
    expect(latteGeometry.localOverflow, JSON.stringify(viewport)).toEqual([]);
    expect(latteGeometry.evidenceTop, JSON.stringify(viewport)).toBeLessThan(
      700,
    );
    if (viewport.width >= 1024 && viewport.width > viewport.height) {
      expect(
        latteGeometry.verticalOverflow,
        JSON.stringify(viewport),
      ).toBeLessThanOrEqual(0);
    }
    await expect(
      page
        .getByRole('banner')
        .getByRole('link', { name: 'Open private workbench' }),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Switch to Mocha theme' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
      JSON.stringify(viewport),
    ).toBe(0);
    await page.getByRole('button', { name: 'Switch to Latte theme' }).click();
  }
});
