import { expect, test } from '@playwright/test';
import {
  installOverviewFixture,
  overviewTradingPlanFixture,
} from './overview-fixture';

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
    await expect(page.getByTestId('overview-today-queue')).toHaveCount(0);
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
      target.locale === 'zh' ? '今日收益' : 'Today PnL',
    );
    await expect(holdings).not.toContainText(
      target.locale === 'zh' ? '已公布净值' : 'Published NAV',
    );
    await page.screenshot({
      path: testInfo.outputPath('02-holdings.png'),
      animations: 'disabled',
    });
    expect(errors).toEqual([]);
  });
}

test('overview surfaces only manually reviewable strategy actions', async ({
  page,
}) => {
  await installOverviewFixture(page);
  await page.unroute('**/api/decision/trading-plan');
  await page.route('**/api/decision/trading-plan', (route) =>
    route.fulfill({
      json: {
        ...overviewTradingPlanFixture,
        manual_ready_count: 1,
        order_intent_count: 1,
        account_action_recommendation: {
          ...overviewTradingPlanFixture.account_action_recommendation,
          status: 'manual_review_required',
          actions: [
            {
              action_id: 'fixture-action',
              symbol: 'fixture-stock',
              display_name: '示例制造',
              asset_class: 'stock',
              side: 'buy',
              target_weight: 0.7,
              estimated_quantity: 100,
              submission_status: 'manual_confirmation_required',
            },
          ],
        },
      },
    }),
  );
  await page.addInitScript(() => {
    localStorage.setItem('karkinos.locale', 'zh');
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/overview');

  const recommendation = page.getByTestId('overview-strategy-recommendation');
  await expect(recommendation).toContainText('待人工复核');
  await expect(recommendation).toContainText('买入');
  await expect(recommendation).toContainText('示例制造');
  await expect(recommendation).toContainText('59.7%');
  await expect(recommendation).toContainText('70.0%');
  await expect(recommendation).toContainText('预计数量');
  await expect(recommendation).toContainText('100 股');
  await expect(
    recommendation.getByRole('link', { name: '复核交易队列' }),
  ).toHaveAttribute('href', '/trading');
});
