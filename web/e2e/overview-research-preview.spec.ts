import { expect, test } from '@playwright/test';
import {
  installOverviewFixture,
  overviewFixture,
  overviewTradingPlanFixture,
} from './overview-fixture';
import { researchSimulationFixture } from './research-simulation-fixture';

for (const width of [1440, 390]) {
  for (const state of ['available', 'blocked'] as const) {
    test(`closed Overview keeps an explicit ${state} research preview at ${width}px`, async ({
      page,
    }, testInfo) => {
      const errors: string[] = [];
      const decisionReads: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => {
        if (request.url().includes('/api/decision/'))
          decisionReads.push(
            `${request.method()} ${new URL(request.url()).pathname}`,
          );
      });
      await page.addInitScript(() => {
        localStorage.setItem('karkinos.locale', 'zh');
        localStorage.setItem('karkinos.theme', 'light');
      });
      await installOverviewFixture(page);
      const account = overviewFixture();
      await page.route('**/api/portfolio/state', (route) =>
        route.fulfill({
          json: {
            ...account,
            overview: {
              ...account.overview,
              market_session: {
                ...account.overview.market_session,
                status: 'non_trading_day',
                market_date: '2026-09-12',
                next_trading_date: '2026-09-14',
              },
            },
          },
        }),
      );
      const preview = researchSimulationFixture();
      if (state === 'blocked') {
        preview.status = 'blocked';
        preview.blockers = ['research_latest_cross_source_dataset_unavailable'];
        preview.as_of_market_date = null;
      }
      await page.route('**/api/decision/trading-plan', (route) =>
        route.fulfill({
          json: {
            ...overviewTradingPlanFixture,
            research_simulation_preview: preview,
            account_action_recommendation: {
              ...overviewTradingPlanFixture.account_action_recommendation,
              status: 'manual_review_required',
              actions: [
                {
                  action_id: 'formal-only',
                  symbol: 'formal-only',
                  side: 'buy',
                  display_name: '不可展示的正式动作',
                },
              ],
            },
          },
        }),
      );
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('/overview');
      const card = page.getByTestId('overview-research-simulation-preview');
      if (state === 'available') {
        await expect(card).toContainText('合成制造');
        await expect(card).toContainText('待人工确认');
      } else {
        await expect(card).toContainText('证据待补齐');
        await expect(card).toContainText('最新交易窗口的双源行情尚未核验完整');
        await expect(
          card.getByTestId('overview-research-simulation-action'),
        ).toHaveCount(0);
        await expect(card).not.toContainText('合成制造');
      }
      await expect(card).toContainText('未核验当前账户费率');
      await expect(
        page.getByTestId('overview-recommendation-market-closed'),
      ).toBeVisible();
      await expect(page.getByText('不可展示的正式动作')).toHaveCount(0);
      await expect(card.getByRole('button')).toHaveCount(0);
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: testInfo.outputPath('research-preview-closed.png'),
        animations: 'disabled',
      });
      await card
        .getByText('研究来源、费用假设与风险证据', { exact: true })
        .click();
      await expect(
        card.getByRole('link', { name: '保存的真实回测 #201' }),
      ).toHaveAttribute('href', '/backtest?id=201');
      await expect(card).toContainText('尚未评估是否通过全部历史门禁');
      await expect(card).toContainText('保存报告的研究门禁：受阻');
      expect(
        await page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      ).toBe(0);
      await page.screenshot({
        path: testInfo.outputPath('research-preview-evidence.png'),
        animations: 'disabled',
      });
      expect(decisionReads).toContain('GET /api/decision/trading-plan');
      expect(
        decisionReads.some(
          (read) =>
            read.includes('/api/decision/today') || !read.startsWith('GET '),
        ),
      ).toBe(false);
      expect(errors).toEqual([]);
    });
  }
}
