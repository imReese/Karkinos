import { expect, test } from '@playwright/test';

import type { BacktestReport } from '../src/features/backtest/api-contracts';

// Synthetic API payloads exercise the browser without provider/account access.
const report: BacktestReport = {
  id: 201,
  created_at: '2026-10-03T08:00:00Z',
  config: {
    start_date: '2026-09-01',
    end_date: '2026-09-30',
    strategy: 'dual_ma',
    initial_cash: 100000,
    assets: [{ symbol: '600000', asset_class: 'stock' }],
    cost_assumptions: {
      stock_commission_rate: 0.00025,
      stock_min_commission: 0,
      slippage_bps: 12.5,
    },
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 100010,
    total_return: 0.0001,
    annual_return: 0.001,
    sharpe: 0.5,
    sortino: 0.5,
    max_drawdown: 0.01,
    win_rate: 0.5,
    duration_days: 30,
  },
  equity_curve: [
    { timestamp: '2026-09-01T15:00:00+08:00', equity: 100000 },
    { timestamp: '2026-09-30T15:00:00+08:00', equity: 100010 },
  ],
  fills: [],
  metrics_json: {
    cost_assumptions: {
      schema_version: 'karkinos.backtest_cost_assumptions.v1',
      source: 'research_simulation',
      slippage_model: 'percent_of_reference_price',
      slippage_bps: '12.5',
      stock: {
        commission_rate: '0.00025',
        min_commission: '0',
        transfer_fee_rate: '0.00001',
        sell_stamp_tax_rate: '0.0005',
        other_fee_rate: '0',
        fee_rule_id: 'cn_stock_research_override_v1',
      },
      etf: {
        commission_rate: '0.0003',
        min_commission: '5',
        transfer_fee_rate: '0.00001',
        other_fee_rate: '0',
        fee_rule_id: 'cn_fund_etf_default_v1',
      },
      limitations: ['Synthetic research assumptions; no broker verification.'],
    },
    capacity_review: {
      schema_version: 'karkinos.backtest_capacity.v2',
      status: 'blocked',
      capacity_utilization_pct: '0.25',
      liquidity_utilization_pct: '1.2',
      max_daily_volume_participation: '0.10',
      fill_count: 2,
      observation_count: 2,
      issues: [],
    },
  },
};

for (const width of [390, 1280]) {
  test(`cost inputs and saved evidence survive reload at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    let saved = false;
    let submitted: Record<string, unknown> | undefined;
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      let payload: unknown;
      if (path === '/api/backtest/strategies') {
        payload = [
          {
            strategy_id: 'dual_ma',
            name: 'dual_ma',
            display_name: 'Dual Moving Average',
            params: [],
            parameter_schema: [],
            asset_universe: ['stock'],
            supported_frequencies: ['1d'],
          },
        ];
      } else if (path === '/api/backtest/datasets') {
        payload = {
          tdx_configured: false,
          storage_path: '',
          busy: false,
          datasets: [],
        };
      } else if (path === '/api/backtest/strategy-promotion-readiness') {
        payload = { rows: [], limitations: [] };
      } else if (path === '/api/backtest/results') {
        payload = saved
          ? [
              {
                id: report.id,
                created_at: report.created_at,
                strategy: 'dual_ma',
                total_return: 0.0001,
                sharpe: 0.5,
                max_drawdown: 0.01,
              },
            ]
          : [];
      } else if (path === '/api/backtest/run') {
        submitted = route.request().postDataJSON();
        saved = true;
        payload = report;
      } else if (path === '/api/backtest/results/201') {
        payload = report;
      } else {
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_fixture_not_available' },
        });
        return;
      }
      await route.fulfill({ status: 200, json: payload });
    });
    await page.goto('/backtest');
    await page.getByText('Trading cost assumptions', { exact: true }).click();
    await page
      .getByRole('combobox', { name: 'Cost model', exact: true })
      .selectOption('custom');
    await page
      .getByLabel('Stock commission (bps)', { exact: true })
      .fill('2.5');
    await page
      .getByLabel('Stock minimum commission (CNY)', { exact: true })
      .fill('0');
    await page
      .getByLabel('Slippage per fill (bps)', { exact: true })
      .fill('12.5');
    await page
      .getByRole('button', { name: 'Run backtest', exact: true })
      .click();
    const evidence = page.getByRole('region', {
      name: 'Recorded costs and liquidity',
    });
    await expect(evidence).toBeVisible();
    expect(submitted?.cost_assumptions).toEqual({
      stock_commission_rate: 0.00025,
      stock_min_commission: 0,
      slippage_bps: 12.5,
    });
    await expect(evidence).toContainText('12.5');
    await expect(evidence).toContainText(
      'Limits exceeded or evidence incomplete',
    );
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);

    await page.reload();
    await expect(page.locator('[data-result-id="201"]')).toBeVisible();
    await expect(evidence).toBeVisible();
    await expect(evidence).toContainText('12.5');
    await expect(evidence).toContainText(
      'Synthetic research assumptions; no broker verification.',
    );
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
    await evidence.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`costs-${width}.png`) });
  });
}
