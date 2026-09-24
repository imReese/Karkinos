import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import {
  DailyDecisionReportPanel,
  type DailyDecisionReport,
} from './daily-decision-report-panel';

const missing: DailyDecisionReport = {
  schema_version: 'karkinos.decision.daily_report.v1',
  report_date: '2026-09-23',
  status: 'missing_run',
  calendar_evidence_ref: 'market_calendar:SSE:2026:fixture',
  preparations: [],
  attempts: [],
  daily_evidence_runs: [],
  scans: [
    {
      run_id: 'scan:orphan',
      status: 'completed',
      integrity_valid: true,
      market_date: '2026-09-22',
      selected_signal_count: 1,
      raw_signal_count: 1,
      normal_no_signal: false,
      account_blocked_buys: [],
      reason_codes: [],
    },
  ],
  candidates: [
    {
      kind: 'formal_signal',
      decision_date: '2026-09-23',
      frozen_market_date: '2026-09-22',
      symbol: '600869',
      direction: 'buy',
      scan_run_id: 'scan:orphan',
      signal_id: 41,
      action_id: 91,
      source_ref: 'scan:orphan:signal:41',
      frozen_price: 22.03,
      report_authoritative: false,
    },
  ],
  blocked_signals: [],
  blocked_signal_count: 0,
  research_previews: [
    {
      run_id: 'research:one',
      selection_id: 'selection:one',
      status: 'no_selection',
      operations: [
        {
          kind: 'research_preview',
          market_date: '2026-09-23',
          target_market_date: null,
          signal_date: '2026-09-23',
          symbol: '301251',
          operation: 'buy_candidate',
          source_ref: 'selection:one:operation:0',
          dataset_snapshot_id: 'dataset:one',
          formula_fingerprint: 'formula:one',
          frozen_price: null,
          research_only: true,
          report_authoritative: false,
        },
      ],
      research_only: true,
    },
  ],
  research_history_status: 'complete',
  authoritative_candidate_count: 0,
  reason_codes: ['promoted_scan_without_daily_attempt'],
  read_only: true,
  authorizes_execution: false,
};

const failed: DailyDecisionReport = {
  ...missing,
  report_date: '2026-09-24',
  status: 'failed',
  attempts: [
    {
      run_id: 'attempt:failed',
      status: 'failed_closed',
      failure_stage: 'portfolio_snapshot',
      failure_code: 'market_revision_conflict',
      error_type: 'PortfolioReadSnapshotRejected',
      evidence_refs: [],
    },
  ],
  scans: [],
  candidates: [],
  research_previews: [],
  reason_codes: ['market_revision_conflict'],
};

afterEach(() => vi.unstubAllGlobals());

test('shows failed and orphan days without promoting research previews', async () => {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL) =>
      new Response(
        JSON.stringify(
          String(input).endsWith('/2026-09-23')
            ? {
                ...missing,
                candidate_outcomes: {
                  schema_version: 'karkinos.decision.candidate_outcomes.v1',
                  items: [
                    {
                      source_ref: 'scan:orphan:signal:41',
                      anchor_status: 'verified',
                      anchor: {
                        receipt_fingerprint: `sha256:${'a'.repeat(64)}`,
                      },
                      horizons: {
                        'T+1': { status: 'observed', price_move_pct: -4.57 },
                        'T+5': { status: 'pending' },
                        'T+20': { status: 'pending' },
                      },
                    },
                    {
                      source_ref: 'selection:one:operation:0',
                      anchor_status: 'unavailable',
                      anchor: null,
                      reason_code: 'research_snapshot_source_unbound',
                      horizons: {
                        'T+1': {
                          status: 'unavailable',
                          reason_code: 'research_snapshot_source_unbound',
                        },
                        'T+5': {
                          status: 'unavailable',
                          reason_code: 'research_snapshot_source_unbound',
                        },
                        'T+20': {
                          status: 'unavailable',
                          reason_code: 'research_snapshot_source_unbound',
                        },
                      },
                    },
                  ],
                  formal_authoritative_directional_hits: {
                    'T+1': {
                      observed_count: 0,
                      directional_hit_count: 0,
                      directional_hit_rate: null,
                    },
                  },
                },
              }
            : String(input).endsWith('/2026-09-24')
              ? failed
              : {
                  schema_version: 'karkinos.decision.daily_report_index.v1',
                  status: 'complete',
                  reports: [failed, missing],
                  has_more: false,
                  blockers: [],
                },
        ),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <DailyDecisionReportPanel locale="zh" />
    </QueryClientProvider>,
  );

  const panel = await screen.findByTestId('daily-decision-report-panel');
  expect(await within(panel).findByText('生成失败')).toBeTruthy();
  expect(within(panel).getByText('未形成当日报告')).toBeTruthy();
  fireEvent.click(within(panel).getByText('2026-09-24'));
  expect(within(panel).getByText(/portfolio_snapshot/)).toBeTruthy();
  fireEvent.click(within(panel).getByText('2026-09-23'));
  expect(within(panel).getByText(/600869 · buy/)).toBeTruthy();
  expect(within(panel).getByText(/信号未绑定当日最终报告/)).toBeTruthy();
  expect(within(panel).getByText(/301251 · buy_candidate/)).toBeTruthy();
  expect(within(panel).getByText(/研究预览 · 不构成账户买入建议/)).toBeTruthy();
  expect(await within(panel).findByText(/-4.57%/)).toBeTruthy();
  expect(within(panel).getByText(/收据已核验/)).toBeTruthy();
  expect(within(panel).queryByText(/正式信号方向命中/)).toBeNull();
  expect(
    within(
      within(panel).getByText(/301251 · buy_candidate/).parentElement!,
    ).getAllByText(/历史研究快照未绑定行情来源/).length,
  ).toBeGreaterThan(0);
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/decision/daily-reports?limit=20&offset=0',
    expect.anything(),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/decision/daily-reports/2026-09-23',
    expect.anything(),
  );
});

test('shows observed denominator beside all formal candidates and explains legacy receipts', async () => {
  const formal: DailyDecisionReport = {
    ...missing,
    report_date: '2026-09-22',
    status: 'formal_candidate',
    candidates: [
      {
        ...missing.candidates[0],
        source_ref: 'scan:one:signal:41',
        report_authoritative: true,
      },
      {
        ...missing.candidates[0],
        symbol: '600667',
        source_ref: 'scan:one:signal:42',
        report_authoritative: true,
      },
    ],
    research_previews: [],
    authoritative_candidate_count: 2,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (input: RequestInfo | URL) =>
        new Response(
          JSON.stringify(
            String(input).endsWith('/2026-09-22')
              ? {
                  ...formal,
                  candidate_outcomes: {
                    schema_version: 'karkinos.decision.candidate_outcomes.v1',
                    items: [
                      {
                        source_ref: 'scan:one:signal:41',
                        anchor_status: 'verified',
                        anchor: {
                          receipt_fingerprint: `sha256:${'a'.repeat(64)}`,
                        },
                        horizons: {
                          'T+1': { status: 'observed', price_move_pct: 2 },
                          'T+5': { status: 'pending' },
                          'T+20': { status: 'pending' },
                        },
                      },
                      {
                        source_ref: 'scan:one:signal:42',
                        anchor_status: 'unavailable',
                        anchor: null,
                        reason_code: 'historical_price_basis_unverified',
                        horizons: {
                          'T+1': {
                            status: 'unavailable',
                            reason_code: 'historical_price_basis_unverified',
                          },
                          'T+5': {
                            status: 'unavailable',
                            reason_code: 'historical_price_basis_unverified',
                          },
                          'T+20': {
                            status: 'unavailable',
                            reason_code: 'historical_price_basis_unverified',
                          },
                        },
                      },
                    ],
                    formal_authoritative_directional_hits: {
                      'T+1': {
                        observed_count: 1,
                        directional_hit_count: 1,
                        directional_hit_rate: 1,
                      },
                      'T+5': {
                        observed_count: 0,
                        directional_hit_count: 0,
                        directional_hit_rate: null,
                      },
                      'T+20': {
                        observed_count: 0,
                        directional_hit_count: 0,
                        directional_hit_rate: null,
                      },
                    },
                  },
                }
              : {
                  schema_version: 'karkinos.decision.daily_report_index.v1',
                  status: 'complete',
                  reports: [formal],
                  has_more: false,
                  blockers: [],
                },
          ),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    ),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <DailyDecisionReportPanel locale="zh" />
    </QueryClientProvider>,
  );

  fireEvent.click(await screen.findByText('2026-09-22'));

  expect(await screen.findByText(/正式候选 2 · 已评估 1/)).toBeTruthy();
  expect(screen.getByText(/正式信号方向命中 T\+1: 1\/1/)).toBeTruthy();
  expect(
    screen.getAllByText(/旧版行情收据缺少价格基准证明/).length,
  ).toBeGreaterThan(0);
});
