import { expect, test, type Page } from '@playwright/test';

import type {
  BacktestReport,
  CorporateActionEvidence,
} from '../src/features/backtest/api-contracts';
import type { PublishedDataset } from '../src/features/backtest/dataset-api';

// Every API response in this journey is synthetic; no request reaches a provider.
const sourceDataset: PublishedDataset = {
  dataset_id: `sha256:${'a'.repeat(64)}`,
  start_date: '2026-06-01',
  end_date: '2026-06-12',
  cutoff: '2026-06-15T08:00:00Z',
  instruments: [{ symbol: '600000', instrument_type: 'stock' }],
  partition_count: 10,
  price_basis: 'unadjusted',
  point_in_time_verified: false,
};

const evidence: CorporateActionEvidence = {
  schema_version: 'karkinos.corporate_action_evidence.v1',
  status: 'observed',
  observation_ids: ['synthetic-observation-1'],
  provider: 'tushare',
  available_at: '2026-10-02T08:00:00Z',
  availability_basis: 'capture_completed_at',
  historical_availability_verified: false,
  covered_action_types: ['cash_dividend', 'bonus_share_distribution'],
  coverage_status: 'provider_reported_only',
  total_record_count: 3,
  matched_event_count: 1,
  undated_event_count: 0,
  events: [
    {
      symbol: '600000',
      instrument_type: 'stock',
      div_proc: '预案',
      end_date: '2025-12-31',
      ann_date: '2026-03-20',
      imp_ann_date: null,
      record_date: '2026-06-05',
      ex_date: '2026-06-08',
      pay_date: null,
      div_listdate: '2026-06-10',
      cash_div_tax: '0.125',
      cash_div: null,
      stk_div: '0.3',
      stk_bo_rate: '0.1',
      stk_co_rate: '0.2',
      available_at: '2026-10-02T08:00:00Z',
      captured_at: '2026-10-02T08:00:00Z',
      source_revision_id: 'synthetic-revision-1',
      observation_id: 'synthetic-observation-1',
    },
  ],
  returns_modeled: false,
  limitations: [
    'Synthetic observation; corporate-action returns are not modeled.',
  ],
};

const enrichedDataset: PublishedDataset = {
  ...sourceDataset,
  dataset_id: `sha256:${'b'.repeat(64)}`,
  cutoff: evidence.available_at,
  corporate_action_evidence: evidence,
};

const report: BacktestReport = {
  id: 101,
  created_at: '2026-10-02T08:01:00Z',
  config: {
    dataset_id: enrichedDataset.dataset_id,
    start_date: sourceDataset.start_date,
    end_date: sourceDataset.end_date,
    initial_cash: 100000,
    strategy: 'dual_ma',
    assets: [{ symbol: '600000', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 101000,
    total_return: 0.01,
    annual_return: 0.1,
    sharpe: 0.8,
    sortino: 1.0,
    max_drawdown: 0.02,
    win_rate: 0.5,
    duration_days: 12,
  },
  metrics_json: {
    dataset_snapshot: {
      immutable_dataset_id: enrichedDataset.dataset_id,
      available_as_of: enrichedDataset.cutoff,
      snapshot_id: 'sha256:synthetic-backtest-snapshot',
      price_basis: 'unadjusted',
      adjustment_mode: 'none',
      point_in_time_verified: false,
      research_use: 'exploratory_backtest',
      provider: { configured_source: 'synthetic' },
      cache: { store_available: false, metadata_available: false },
      date_range: {
        start: sourceDataset.start_date,
        end: sourceDataset.end_date,
      },
      row_count: 10,
      data_quality: { status: 'ok', issues: [] },
      symbol_universe: [
        {
          symbol: '600000',
          asset_class: 'stock',
          frequency: '1d',
          row_count: 10,
        },
      ],
      corporate_action_evidence: evidence,
    },
  },
  fills: [],
  equity_curve: [
    { timestamp: '2026-06-01T15:00:00+08:00', equity: 100000 },
    { timestamp: '2026-06-12T15:00:00+08:00', equity: 101000 },
  ],
};

async function expectNoDocumentOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
}

for (const width of [390, 1280]) {
  test(`explicit corporate-action collection binds the next run at ${width}px`, async ({
    page,
  }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem('karkinos.locale', 'zh');
      window.localStorage.setItem('karkinos.theme', 'light');
    });
    let collected = false;
    let releaseCollection!: () => void;
    const collectionGate = new Promise<void>((resolve) => {
      releaseCollection = resolve;
    });
    const postRequests: Array<{ path: string; body: Record<string, unknown> }> =
      [];
    await page.route('**/api/**', async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST') {
        postRequests.push({ path, body: request.postDataJSON() });
      }
      let payload: unknown;
      if (path.endsWith('/corporate-actions') && request.method() === 'POST') {
        await collectionGate;
        collected = true;
        payload = enrichedDataset;
      } else if (path === '/api/backtest/datasets') {
        payload = {
          tdx_configured: true,
          storage_path: '',
          busy: false,
          datasets: collected
            ? [enrichedDataset, sourceDataset]
            : [sourceDataset],
        };
      } else if (path === '/api/backtest/strategies') {
        payload = [
          {
            strategy_id: 'dual_ma',
            name: 'dual_ma',
            display_name: 'Dual Moving Average',
            description: 'Synthetic strategy fixture.',
            params: [],
            parameter_schema: [],
            asset_universe: ['stock'],
            supported_frequencies: ['1d'],
          },
        ];
      } else if (path === '/api/backtest/results') {
        payload = [];
      } else if (path === '/api/backtest/strategy-promotion-readiness') {
        payload = { rows: [], limitations: [] };
      } else if (
        path === '/api/backtest/run' ||
        path === '/api/backtest/results/101'
      ) {
        payload = report;
      } else if (path === '/api/backtest/signal-preview') {
        payload = {
          schema_version: 'synthetic.preview',
          strategy_id: 'dual_ma',
          symbol: '600000',
          params: {},
          run_id: 'synthetic-preview',
          record_count: 0,
          outputs: [],
          limitations: ['Synthetic preview only.'],
          does_not_enable_execution: true,
        };
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
    await expect(
      page.getByRole('heading', { name: '策略回放', exact: true }),
    ).toBeVisible();
    await page
      .getByText('研究 Dataset · 持久保存与离线回测', { exact: true })
      .click();
    const selector = page.getByLabel('本次回测的数据输入');
    await expect(selector.locator('option')).toHaveCount(2);
    await selector.selectOption(sourceDataset.dataset_id);
    await expect(page.getByTestId('selected-dataset-id')).toContainText(
      sourceDataset.dataset_id,
    );
    expect(postRequests).toEqual([]);
    await expectNoDocumentOverflow(page);

    await page
      .getByRole('button', { name: '采集分红送转证据', exact: true })
      .click();
    await expect(
      page.getByRole('button', { name: '正在采集分红送转证据…', exact: true }),
    ).toBeDisabled();
    await expect(
      page.getByRole('button', { name: '运行回测', exact: true }),
    ).toBeDisabled();
    await expect.poll(() => postRequests.length).toBe(1);
    expect(postRequests).toEqual([
      {
        path: `/api/backtest/datasets/${encodeURIComponent(sourceDataset.dataset_id)}/corporate-actions`,
        body: { refresh: false },
      },
    ]);
    releaseCollection();
    await expect(
      page.getByText(/分红送转证据已采集，已选中新数据集/),
    ).toBeVisible();
    await expect(selector).toHaveValue(enrichedDataset.dataset_id);
    await expect(selector.locator('option')).toHaveCount(3);
    await expectNoDocumentOverflow(page);
    expect(postRequests).toHaveLength(1);

    await page.getByRole('button', { name: '运行回测', exact: true }).click();
    const result = page.locator('#backtest-dataset-evidence');
    await expect(
      result.getByText('已采集 · 覆盖未核实', { exact: true }),
    ).toBeVisible();
    expect(
      postRequests.find((item) => item.path === '/api/backtest/run')?.body
        .dataset_id,
    ).toBe(enrichedDataset.dataset_id);
    await expect(result.getByText(/尚未证明区间事件完整/)).toBeVisible();
    await expect(
      result.getByText(/尚未计入现金派息、送转持仓或总收益/),
    ).toBeVisible();
    await expect(
      result.getByText(/本次采集不补足历史时点可用性/),
    ).toBeVisible();
    await result.getByText('查看记录明细（1）', { exact: true }).click();
    const table = result.getByRole('table', { name: '分红送转记录明细' });
    await expect(
      table.getByRole('cell', { name: '预案', exact: true }),
    ).toBeVisible();
    await expect(
      table.getByRole('cell', { name: '未知', exact: true }),
    ).toHaveCount(2);
    await expect(
      table.getByRole('cell', { name: '0.125', exact: true }),
    ).toBeVisible();
    await expectNoDocumentOverflow(page);
    const scroll = result.getByTestId('corporate-action-events-scroll');
    expect(
      await scroll.evaluate(
        (element) => element.scrollWidth > element.clientWidth,
      ),
    ).toBe(true);
    await scroll.evaluate((element) => {
      element.scrollLeft = element.scrollWidth;
    });
    await expectNoDocumentOverflow(page);
    await scroll.evaluate((element) => {
      element.scrollLeft = 0;
    });
    await result.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: testInfo.outputPath(`corporate-actions-${width}.png`),
      fullPage: true,
    });
  });
}
