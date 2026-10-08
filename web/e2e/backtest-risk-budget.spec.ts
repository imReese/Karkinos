import { expect, test } from '@playwright/test';

import { candidateSourceReport } from '../test-fixtures/shadow-observations';

// UI transport only; the Python Dataset journey separately runs the optimizer.
const dataset = {
  dataset_id: `sha256:${'9'.repeat(64)}`,
  start_date: '2026-01-05',
  end_date: '2026-04-30',
  cutoff: '2026-05-01T08:00:00Z',
  instruments: [
    { symbol: '510300', instrument_type: 'etf' },
    { symbol: '511010', instrument_type: 'etf' },
  ],
  partition_count: 80,
  price_basis: 'unadjusted',
  point_in_time_verified: false,
};

for (const width of [390, 1280]) {
  test(`risk budgets remain typed and invalid inputs cannot submit at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(() => {
      localStorage.setItem('karkinos.locale', 'en');
    });
    const requests: Record<string, unknown>[] = [];
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/backtest/strategies') {
        await route.fulfill({
          json: [
            {
              strategy_id: 'risk_parity_macro',
              name: 'risk_parity_macro',
              display_name: 'Bounded Macro Risk Budgeting',
              asset_universe: ['stock', 'etf'],
              supported_frequencies: ['1d'],
              params: [],
              parameter_schema: [
                {
                  name: 'risk_budgets',
                  type: 'dict',
                  default: null,
                  required: false,
                },
                {
                  name: 'trend_filter',
                  type: 'bool',
                  default: true,
                  required: false,
                },
              ],
            },
          ],
        });
      } else if (path === '/api/backtest/datasets') {
        await route.fulfill({
          json: {
            datasets: [dataset],
            busy: false,
            tdx_configured: false,
            storage_path: '',
          },
        });
      } else if (path === '/api/backtest/results') {
        await route.fulfill({ json: [] });
      } else if (path === '/api/backtest/strategy-promotion-readiness') {
        await route.fulfill({ json: { rows: [], limitations: [] } });
      } else if (path === '/api/backtest/run') {
        const body = route.request().postDataJSON();
        requests.push(body);
        await route.fulfill({
          json: {
            ...candidateSourceReport,
            config: { ...candidateSourceReport.config, ...body },
          },
        });
      } else {
        await route.fulfill({
          status: 503,
          json: { detail: 'synthetic_fixture_only' },
        });
      }
    });
    await page.goto('/backtest?strategy=risk_parity_macro');
    await page
      .getByText('Research datasets · persistent snapshots', { exact: true })
      .click();
    await page
      .getByRole('combobox', { name: 'Data for this backtest', exact: true })
      .selectOption(dataset.dataset_id);
    const budgets = page.getByLabel('Risk Budgets', { exact: true });
    const trend = page.getByLabel('Trend Filter', { exact: true });
    const run = page.getByRole('button', { name: 'Run backtest', exact: true });
    for (const invalid of ['{', '[1,2]', 'null']) {
      await budgets.fill(invalid);
      await run.click();
      await expect(page.getByRole('alert')).toContainText('valid JSON object');
    }
    await budgets.fill('{"510300":2,"511010":1}');
    await trend.fill('maybe');
    await run.click();
    await expect(page.getByRole('alert')).toContainText('true or false');
    expect(requests).toHaveLength(0);
    await trend.fill('false');
    await expect(run).toBeEnabled();
    await run.click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).toMatchObject({
      strategy: 'risk_parity_macro',
      dataset_id: dataset.dataset_id,
      assets: [
        { symbol: '510300', asset_class: 'etf' },
        { symbol: '511010', asset_class: 'etf' },
      ],
      params: {
        risk_budgets: { '510300': 2, '511010': 1 },
        trend_filter: false,
      },
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
  });
}
