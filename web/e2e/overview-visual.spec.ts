import { expect, test } from '@playwright/test';
import { installOverviewFixture } from './overview-fixture';

for (const target of [
  { width: 1440, height: 1000, theme: 'light', locale: 'en' },
  { width: 1440, height: 1000, theme: 'dark', locale: 'zh' },
  { width: 390, height: 844, theme: 'light', locale: 'zh' },
  { width: 390, height: 844, theme: 'dark', locale: 'en' },
] as const) {
  test(`overview financial canvas ${target.width} ${target.theme} ${target.locale}`, async ({
    page,
  }, testInfo) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(({ locale, theme }) => {
      localStorage.setItem('karkinos.locale', locale);
      localStorage.setItem('karkinos.theme', theme);
    }, target);
    await installOverviewFixture(page);
    await page.setViewportSize(target);
    await page.goto('/overview');
    await expect(page.getByTestId('overview-total-value')).toContainText(
      '100,500.00',
    );
    await expect(page.getByTestId('overview-cumulative-pnl')).toContainText(
      '5,500.00',
    );
    await expect(page.getByTestId('overview-session-pnl')).toContainText(
      '-¥450.00',
    );
    await expect(page.getByTestId('overview-data-status')).toHaveCount(0);
    await expect(page.getByTestId('overview-data-trust')).toHaveCount(0);
    await expect(page.getByTestId('overview-today-queue')).toContainText('0');
    await expect(
      page.getByTestId('equity-chart-frame').locator('.recharts-line-curve'),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    ).toBe(0);
    await page.screenshot({
      path: testInfo.outputPath('01-overview.png'),
      animations: 'disabled',
    });
    const holdings = page.getByTestId('overview-holdings-section');
    await holdings.scrollIntoViewIfNeeded();
    await expect(holdings).toContainText(
      target.locale === 'zh' ? '已公布净值' : 'Published NAV',
    );
    await page.screenshot({
      path: testInfo.outputPath('02-holdings.png'),
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
  });
}
