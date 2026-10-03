import { expect, test } from '@playwright/test';

import type {
  BacktestReport,
  BacktestSweepResponse,
} from '../src/features/backtest/api-contracts';

const datasetId = `sha256:${'c'.repeat(64)}`;
const parameters = [
  {
    name: 'short_period',
    type: 'int',
    default: 2,
    required: true,
    description: '',
  },
  {
    name: 'long_period',
    type: 'int',
    default: 3,
    required: true,
    description: '',
  },
];
const sweep: BacktestSweepResponse = {
  strategy: 'dual_ma',
  rank_by: 'total_return',
  tested_count: 1,
  warnings: [],
  results: [
    {
      rank: 1,
      result_id: 301,
      strategy: 'dual_ma',
      params: { short_period: 2, long_period: 3 },
      score: 0.1,
      metrics: {
        initial_cash: 100000,
        final_equity: 110000,
        total_return: 0.1,
        annual_return: 0.2,
        sharpe: 1.2,
        sortino: 1.3,
        max_drawdown: 0.01,
        win_rate: 0.5,
        duration_days: 10,
      },
    },
  ],
  selected_test_result_id: 302,
  chronological_validation: {
    schema_version: 'karkinos.chronological_sweep.v1',
    experiment_id: 'synthetic-experiment',
    source_dataset_id: datasetId,
    test_start_date: '2026-09-15',
    rank_by: 'total_return',
    selection_basis: 'training_only',
    selected_params: { short_period: 2, long_period: 3 },
    selected_training_result_id: 301,
    training_result_ids: [301],
    tested_count: 1,
    exploratory: true,
    independent_final: false,
    fingerprint: 'synthetic-experiment-fingerprint',
    limitations: [],
  },
};
const savedReport: BacktestReport = {
  id: 302,
  created_at: '2026-10-03T08:00:00Z',
  config: {
    strategy: 'dual_ma',
    dataset_id: datasetId,
    start_date: '2026-09-01',
    end_date: '2026-09-30',
    initial_cash: 100000,
    assets: [{ symbol: '600000', asset_class: 'stock' }],
  },
  metrics: {
    ...sweep.results[0].metrics,
    final_equity: 98000,
    total_return: -0.02,
    annual_return: -0.4,
    sharpe: -0.4,
    sortino: -0.6,
    max_drawdown: 0.02,
    win_rate: 0,
    total_commission: 20,
    total_slippage: 0,
    total_trades: 2,
    gross_turnover: 38020,
  },
  equity_curve: [
    { timestamp: '2026-09-15T15:00:00+08:00', equity: 100000 },
    { timestamp: '2026-09-16T15:00:00+08:00', equity: 99990 },
    { timestamp: '2026-09-30T15:00:00+08:00', equity: 98000 },
  ],
  fills: [
    {
      timestamp: '2026-09-16T15:00:00+08:00',
      symbol: '600000',
      side: 'buy',
      fill_price: 100,
      fill_quantity: 200,
      commission: 10,
      slippage: 0,
    },
    {
      timestamp: '2026-09-30T15:00:00+08:00',
      symbol: '600000',
      side: 'sell',
      fill_price: 90.1,
      fill_quantity: 200,
      commission: 10,
      slippage: 0,
    },
  ],
  metrics_json: {
    chronological_validation: {
      ...sweep.chronological_validation!,
      role: 'test',
    },
    execution_window: {
      schema_version: 'karkinos.backtest_execution_window.v1',
      source_dataset_id: datasetId,
      source_snapshot_id: 'synthetic-snapshot',
      source_start_date: '2026-09-01',
      source_end_date: '2026-09-30',
      history_end_date: '2026-09-30',
      evaluation_start_date: '2026-09-15',
      evaluation_end_date: '2026-09-30',
      metric_start_date: '2026-09-15',
      metric_end_date: '2026-09-30',
      warmup_policy: 'strategy_state_only_no_orders_or_book_carry',
      independent_initial_cash: true,
      exploratory: true,
      independent_final: false,
      fingerprint: 'synthetic-window-fingerprint',
    },
  },
};

for (const width of [390, 1280]) {
  test(`chronological selection keeps training and saved test evidence distinct at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
      localStorage.setItem('karkinos.theme', 'light');
    });
    let saved = false;
    let submissions = 0;
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      let payload: unknown;
      if (path === '/api/backtest/strategies')
        payload = [
          {
            strategy_id: 'dual_ma',
            name: 'dual_ma',
            display_name: 'Dual Moving Average',
            description: '',
            params: parameters,
            parameter_schema: parameters,
            asset_universe: ['stock'],
            supported_frequencies: ['1d'],
          },
        ];
      else if (path === '/api/backtest/strategy-promotion-readiness')
        payload = { rows: [], limitations: [] };
      else if (path === '/api/backtest/datasets')
        payload = {
          tdx_configured: false,
          storage_path: '',
          busy: false,
          datasets: [
            {
              dataset_id: datasetId,
              start_date: '2026-09-01',
              end_date: '2026-09-30',
              instruments: [{ symbol: '600000', instrument_type: 'stock' }],
              cross_source_verified: true,
              price_basis: 'unadjusted',
              point_in_time_verified: false,
            },
          ],
        };
      else if (path === '/api/backtest/results')
        payload = saved
          ? [
              {
                id: 302,
                created_at: savedReport.created_at,
                strategy: 'dual_ma',
                total_return: -0.02,
                sharpe: -0.4,
                max_drawdown: 0.02,
              },
            ]
          : [];
      else if (path === '/api/backtest/results/302') payload = savedReport;
      else if (path === '/api/backtest/sweep') {
        const request = route.request().postDataJSON();
        expect(request).toMatchObject({
          strategy: 'dual_ma',
          dataset_id: datasetId,
          test_start_date: '2026-09-15',
          start_date: '2026-09-01',
          end_date: '2026-09-30',
          corporate_action_mode: 'price_only',
        });
        submissions++;
        saved = true;
        payload = sweep;
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
    await page
      .getByText('Research datasets · persistent snapshots', { exact: true })
      .click();
    await page
      .getByRole('combobox', { name: 'Data for this backtest', exact: true })
      .selectOption(datasetId);
    await page.getByTestId('backtest-advanced-tools-disclosure').click();
    const advanced = page.locator('#backtest-advanced-tools');
    await advanced
      .getByLabel('Select on training data, then test chronologically')
      .check();
    const submit = advanced.getByRole('button', {
      name: 'Run training selection and test',
      exact: true,
    });
    await expect(submit).toBeDisabled();
    await advanced
      .getByLabel('Test start date', { exact: true })
      .fill('2026-09-15');
    const rankBounds = await advanced
      .getByRole('combobox', { name: 'Rank by', exact: true })
      .boundingBox();
    const submitBounds = await submit.boundingBox();
    expect(
      rankBounds &&
        submitBounds &&
        (rankBounds.y + rankBounds.height <= submitBounds.y ||
          submitBounds.y + submitBounds.height <= rankBounds.y ||
          rankBounds.x + rankBounds.width <= submitBounds.x ||
          submitBounds.x + submitBounds.width <= rankBounds.x),
    ).toBe(true);
    await advanced
      .getByLabel('Select on training data, then test chronologically')
      .evaluate((element) =>
        element.parentElement!.scrollIntoView({ block: 'start' }),
      );
    await page.screenshot({
      path: testInfo.outputPath(`chronological-form-${width}.png`),
    });
    await submit.click();
    await expect(advanced).toContainText('Training-period rankings');
    await advanced
      .getByRole('heading', { name: 'Training-period rankings', exact: true })
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`chronological-training-${width}.png`),
    });
    const trainingTable = advanced.getByRole('table').first();
    await trainingTable.evaluate((element) => {
      element.parentElement!.scrollLeft = element.parentElement!.scrollWidth;
    });
    await expect(
      trainingTable.getByRole('cell', { name: '10.0%', exact: true }),
    ).toBeInViewport();
    await page.screenshot({
      path: testInfo.outputPath(`chronological-training-scores-${width}.png`),
    });
    const selected = advanced.getByRole('region', {
      name: 'Selected candidate · test result',
      exact: true,
    });
    await expect(selected).toContainText('-2.0%');
    await expect(selected).toContainText('38,020');
    await expect(selected).toContainText('2 fills');
    await expect(selected).toContainText('¥20.00');
    await expect(selected).toContainText(
      'Actual metric dates: 2026-09-15 → 2026-09-30',
    );
    await selected
      .getByRole('heading', {
        name: 'Selected candidate · test result',
        exact: true,
      })
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`chronological-test-${width}.png`),
    });
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
    if (width < 1280)
      await page
        .getByRole('tab', { name: 'Results and evidence', exact: true })
        .click();
    const window = page.getByRole('region', {
      name: 'Recorded performance window',
      exact: true,
    });
    await expect(window).toContainText('Test period');
    await expect(window).toContainText(
      'Actual metric dates: 2026-09-15 → 2026-09-30',
    );
    await window
      .getByText('Chronological evaluation details', { exact: true })
      .click();
    await expect(window).toContainText('2026-09-01 → 2026-09-30');
    await expect(window).toContainText('synthetic-experiment');
    await window
      .getByRole('heading')
      .evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({
      path: testInfo.outputPath(`chronological-saved-${width}.png`),
    });
    await page.getByTestId('backtest-fills-disclosure').click();
    const fills = page.getByTestId('backtest-fills-table');
    await expect(fills.getByRole('row')).toHaveCount(3);
    await expect(fills).toContainText('100.00');
    await expect(fills).toContainText('90.10');
    expect(submissions).toBe(1);
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
  });
}
