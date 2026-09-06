import { expect, test } from '@playwright/test';
import { correctionFixture } from '../src/shared/ledger-correction-fixture';

test('correction evidence remains readable on desktop and mobile without writes', async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('karkinos.locale', 'zh'));
  await page.route('**/api/**', async (route) => {
    expect(route.request().method()).toBe('GET');
    const url = new URL(route.request().url());
    let body: unknown = {};
    if (url.pathname === '/api/ledger/entries') body = [correctionFixture];
    else if (
      [
        '/api/portfolio/pending-fund-orders',
        '/api/portfolio/positions',
      ].includes(url.pathname)
    )
      body = [];
    await route.fulfill({ status: 200, json: body });
  });
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/activity');
    await expect(
      page.getByText('历史重复记账修正', { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/记录于 2026\/02\/20/)).toBeVisible();
    await expect(page.getByText(/账本生效于 2026\/02\/10/)).toBeVisible();
    await page.getByText('查看修正依据', { exact: true }).click();
    await expect(
      page.getByText('重复原流水 #101', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('保留流水 #102', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('有授权摘要，未核验批准人／批准时间。'),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`correction-${width}.png`),
      fullPage: true,
    });
  }
});
