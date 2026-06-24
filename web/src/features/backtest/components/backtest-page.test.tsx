import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { BacktestPage } from './backtest-page';

const savedSummary = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  strategy: 'dual_ma',
  total_return: 0.082,
  sharpe: 1.27,
  max_drawdown: 0.044,
};

const portfolioSnapshot = {
  cash: 0,
  total_equity: 0,
  total_deposits: 0,
  positions: [],
  allocation: [],
  allocation_grouped: [],
};

const savedReport = {
  id: 1,
  created_at: '2026-05-15T10:00:00+08:00',
  config: {
    start_date: '2025-01-02',
    end_date: '2026-05-15',
    initial_cash: 100000,
    strategy: 'dual_ma',
    short_period: 5,
    long_period: 20,
    assets: [{ symbol: '600519', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100000,
    final_equity: 108200,
    total_return: 0.082,
    annual_return: 0.11,
    sharpe: 1.27,
    sortino: 1.56,
    max_drawdown: 0.044,
    calmar: 2.5,
    volatility: 0.14,
    win_rate: 0.58,
    duration_days: 260,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  metrics_json: {
    calmar: 2.5,
    volatility: 0.14,
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
    strategy_metadata: {
      schema_version: 'karkinos.strategy_metadata.v1',
      strategy_id: 'dual_ma',
      name: 'dual_ma',
      display_name: 'Dual Moving Average',
      description: 'Dual moving-average crossover baseline.',
      asset_universe: ['etf'],
      supported_frequencies: ['1d'],
      benchmark_role: 'etf_rotation_trend_following',
      benchmark_universe: ['etf'],
      requires_out_of_sample_validation: true,
      requires_after_cost_report: true,
      validation_notes: [
        'Requires after-cost, out-of-sample ETF trend-following validation before promotion.',
      ],
      parameter_schema: [
        {
          name: 'short_period',
          type: 'int',
          default: 5,
          required: false,
          min: 1,
          max: 250,
          allowed_values: null,
          description: 'Short moving-average window in trading bars.',
        },
        {
          name: 'long_period',
          type: 'int',
          default: 20,
          required: false,
          min: 2,
          max: 500,
          allowed_values: null,
          description: 'Long moving-average window in trading bars.',
        },
      ],
      params: {
        short_period: 5,
        long_period: 20,
      },
    },
    evidence_bundle: {
      net_pnl: 8200,
      total_cost: 10.5,
      gross_pnl_before_costs: 8210.5,
      net_return: 0.082,
      gross_return_before_costs: 0.082105,
      cost_to_initial_cash: 0.000105,
      fill_count: 2,
      gross_turnover: 21800,
      assumptions: [
        'Backtest results are calculated after simulated commissions and slippage.',
      ],
      cost_assumptions: [
        'Commission assumptions use the configured simulated backtest fee schedule.',
      ],
      slippage_assumptions: [
        'Slippage assumptions use the configured simulated execution drift model.',
      ],
      limitations: ['Backtest evidence is not a profitability claim.'],
    },
    oos_validation: {
      strategy_id: 'dual_ma',
      benchmark_role: 'etf_rotation_trend_following',
      split_timestamp: '2025-09-01T00:00:00',
      in_sample: {
        start_timestamp: '2025-01-02T00:00:00',
        end_timestamp: '2025-08-29T00:00:00',
        initial_equity: 100000,
        final_equity: 104000,
        net_pnl: 4000,
        net_return: 0.04,
        total_cost: 4.5,
        gross_pnl_before_costs: 4004.5,
        gross_return_before_costs: 0.040045,
        fill_count: 1,
      },
      out_of_sample: {
        start_timestamp: '2025-09-01T00:00:00',
        end_timestamp: '2026-05-15T00:00:00',
        initial_equity: 104000,
        final_equity: 108200,
        net_pnl: 4200,
        net_return: 0.040384615,
        total_cost: 6,
        gross_pnl_before_costs: 4206,
        gross_return_before_costs: 0.040442307,
        fill_count: 1,
      },
      benchmark_return: 0.02,
      excess_return: 0.020384615,
      passed_benchmark: true,
      validation_status: 'benchmark_passed',
      assumptions: [
        'Out-of-sample validation is computed from a completed deterministic backtest result.',
      ],
      limitations: [
        'Validation evidence is not investment advice or a profitability guarantee.',
      ],
    },
    dataset_snapshot: {
      schema_version: 'karkinos.dataset_snapshot.v1',
      snapshot_id: 'sha256:fixture-dataset-snapshot',
      provider: {
        configured_source: 'fixture',
        available_sources: ['fixture', 'akshare'],
      },
      cache: {
        store_available: true,
        metadata_available: true,
      },
      date_range: {
        start: '2025-01-02',
        end: '2026-05-15',
      },
      row_count: 260,
      adjustment_mode: 'qfq',
      data_quality: {
        status: 'ok',
        issues: [],
      },
      symbol_universe: [
        {
          symbol: '600519',
          asset_class: 'stock',
          frequency: '1d',
          row_count: 260,
          first_timestamp: '2025-01-02T00:00:00',
          last_timestamp: '2026-05-15T00:00:00',
          provider_name: 'fixture_provider',
          data_source: 'fixture',
          adjustment_mode: 'qfq',
          source_dataset_id: 'cache-dataset-600519',
          data_quality: {
            status: 'ok',
            issues: [],
          },
        },
      ],
    },
  },
  cost_summary_json: {
    total_commission: 8.4,
    total_slippage: 2.1,
    total_trades: 2,
    gross_turnover: 21800,
  },
  evidence_json: {
    net_pnl: 8200,
    total_cost: 10.5,
    gross_pnl_before_costs: 8210.5,
    net_return: 0.082,
    gross_return_before_costs: 0.082105,
    cost_to_initial_cash: 0.000105,
    fill_count: 2,
    gross_turnover: 21800,
    assumptions: [
      'Backtest results are calculated after simulated commissions and slippage.',
    ],
    cost_assumptions: [
      'Commission assumptions use the configured simulated backtest fee schedule.',
    ],
    slippage_assumptions: [
      'Slippage assumptions use the configured simulated execution drift model.',
    ],
    limitations: ['Backtest evidence is not a profitability claim.'],
  },
  fills: [],
  equity_curve: [],
};

const runReport = {
  ...savedReport,
  id: 2,
  created_at: '',
  metrics: {
    ...savedReport.metrics,
    final_equity: 112000,
    total_return: 0.12,
    max_drawdown: 0.06,
  },
  metrics_json: {
    ...savedReport.metrics_json,
    calmar: 3.1,
    total_trades: 3,
  },
  cost_summary_json: {
    total_commission: 12.5,
    total_slippage: 3.5,
    total_trades: 3,
    gross_turnover: 24000,
  },
  fills: [],
  equity_curve: [],
};

const sweepResponse = {
  strategy: 'dual_ma',
  rank_by: 'total_return',
  tested_count: 2,
  warnings: [
    'Parameter sweep rankings are research evidence, not investment advice.',
    'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.',
  ],
  results: [
    {
      rank: 1,
      result_id: 12,
      strategy: 'dual_ma',
      params: { short_period: 5, long_period: 9 },
      score: 0.14,
      metrics: {
        initial_cash: 100000,
        final_equity: 114000,
        total_return: 0.14,
        annual_return: 0.18,
        sharpe: 1.41,
        sortino: 1.7,
        max_drawdown: 0.04,
        calmar: 4.5,
        volatility: 0.12,
        win_rate: 0.62,
        duration_days: 260,
        total_commission: 9,
        total_slippage: 3,
        total_trades: 4,
        gross_turnover: 31000,
      },
    },
    {
      rank: 2,
      result_id: 11,
      strategy: 'dual_ma',
      params: { short_period: 3, long_period: 9 },
      score: 0.09,
      metrics: {
        initial_cash: 100000,
        final_equity: 109000,
        total_return: 0.09,
        annual_return: 0.12,
        sharpe: 1.08,
        sortino: 1.2,
        max_drawdown: 0.05,
        calmar: 2.4,
        volatility: 0.15,
        win_rate: 0.56,
        duration_days: 260,
        total_commission: 8,
        total_slippage: 2,
        total_trades: 3,
        gross_turnover: 26000,
      },
    },
  ],
};

const compareResponse = {
  compared_count: 2,
  dataset_snapshot_id: 'snapshot-shared',
  dataset_snapshot: {
    schema_version: 'karkinos.dataset_snapshot.v1',
    snapshot_id: 'snapshot-shared',
    row_count: 10,
  },
  warnings: [
    'Strategy comparison results are research evidence, not investment advice.',
    'Comparison is valid only when every run uses the same frozen dataset snapshot.',
  ],
  results: [
    {
      strategy: 'dual_ma',
      description: 'Dual moving-average crossover baseline.',
      result_id: 1201,
      params: { short_period: 3, long_period: 9 },
      dataset_snapshot_id: 'snapshot-shared',
      dataset_snapshot: {
        schema_version: 'karkinos.dataset_snapshot.v1',
        snapshot_id: 'snapshot-shared',
        row_count: 10,
      },
      metrics: {
        initial_cash: 100000,
        final_equity: 103000,
        total_return: 0.03,
        annual_return: 0.03,
        sharpe: 1.03,
        sortino: 1.2,
        max_drawdown: 0.02,
        calmar: 1.5,
        volatility: 0.1,
        win_rate: 0.51,
        duration_days: 10,
        total_commission: 3,
        total_slippage: 1,
        total_trades: 2,
        gross_turnover: 9000,
      },
      equity_curve: [],
    },
    {
      strategy: 'dual_ma',
      description: 'Dual moving-average crossover baseline.',
      result_id: 1202,
      params: { short_period: 5, long_period: 9 },
      dataset_snapshot_id: 'snapshot-shared',
      dataset_snapshot: {
        schema_version: 'karkinos.dataset_snapshot.v1',
        snapshot_id: 'snapshot-shared',
        row_count: 10,
      },
      metrics: {
        initial_cash: 100000,
        final_equity: 105000,
        total_return: 0.05,
        annual_return: 0.05,
        sharpe: 1.25,
        sortino: 1.3,
        max_drawdown: 0.025,
        calmar: 2,
        volatility: 0.11,
        win_rate: 0.54,
        duration_days: 10,
        total_commission: 4,
        total_slippage: 1,
        total_trades: 3,
        gross_turnover: 12000,
      },
      equity_curve: [],
    },
  ],
};

const strategyCatalog = [
  {
    strategy_id: 'dual_ma',
    name: 'dual_ma',
    display_name: 'Dual Moving Average',
    description: 'Dual moving-average crossover baseline.',
    params: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
    parameter_schema: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
    benchmark_role: 'etf_rotation_trend_following',
    benchmark_universe: ['etf'],
    requires_out_of_sample_validation: true,
    requires_after_cost_report: true,
    validation_notes: [
      'Requires after-cost, out-of-sample ETF trend-following validation before promotion.',
    ],
  },
  {
    strategy_id: 'bollinger',
    name: 'bollinger',
    display_name: 'Bollinger Mean Reversion',
    description: 'Bollinger band mean-reversion baseline.',
    params: [
      {
        name: 'bb_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Bollinger lookback window in trading bars.',
      },
      {
        name: 'num_std',
        type: 'float',
        default: 2,
        required: false,
        min: 0.1,
        max: 10,
        allowed_values: null,
        description: 'Number of standard deviations used for bands.',
      },
    ],
    parameter_schema: [
      {
        name: 'bb_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Bollinger lookback window in trading bars.',
      },
      {
        name: 'num_std',
        type: 'float',
        default: 2,
        required: false,
        min: 0.1,
        max: 10,
        allowed_values: null,
        description: 'Number of standard deviations used for bands.',
      },
    ],
    benchmark_role: 'a_share_or_etf_mean_reversion',
    benchmark_universe: ['stock', 'etf'],
    requires_out_of_sample_validation: true,
    requires_after_cost_report: true,
    validation_notes: [],
  },
];

const extensionStrategy = {
  strategy_id: 'custom_momentum',
  name: 'custom_momentum',
  display_name: 'Custom Momentum Extension',
  description: 'Private local extension strategy loaded from a manifest.',
  params: [
    {
      name: 'lookback_window',
      type: 'int',
      default: 15,
      required: false,
      min: 2,
      max: 120,
      allowed_values: null,
      description: 'Local extension lookback window in trading bars.',
    },
  ],
  parameter_schema: [
    {
      name: 'lookback_window',
      type: 'int',
      default: 15,
      required: false,
      min: 2,
      max: 120,
      allowed_values: null,
      description: 'Local extension lookback window in trading bars.',
    },
  ],
  asset_universe: ['stock', 'etf'],
  supported_frequencies: ['1d'],
  benchmark_role: 'custom_momentum_research',
  benchmark_universe: ['stock'],
  requires_out_of_sample_validation: true,
  requires_after_cost_report: true,
  validation_notes: ['Requires paper/shadow review before promotion.'],
};

const strategyValidation = {
  required_strategy_count: 2,
  ready_strategy_count: 1,
  is_complete: false,
  limitations: ['Research evidence is not a profitability guarantee.'],
  rows: [
    {
      strategy_id: 'dual_ma',
      benchmark_role: 'etf_rotation_trend_following',
      requires_out_of_sample_validation: true,
      requires_after_cost_report: true,
      has_out_of_sample_validation: true,
      has_after_cost_report: true,
      validation_status: 'benchmark_passed',
      backtest_result_id: 1,
      missing_requirements: [],
      is_ready: true,
    },
    {
      strategy_id: 'bollinger',
      benchmark_role: 'a_share_or_etf_mean_reversion',
      requires_out_of_sample_validation: true,
      requires_after_cost_report: true,
      has_out_of_sample_validation: false,
      has_after_cost_report: false,
      validation_status: null,
      backtest_result_id: null,
      missing_requirements: ['after_cost_report', 'out_of_sample_validation'],
      is_ready: false,
    },
  ],
};

const strategyPromotionReadiness = {
  required_strategy_count: 2,
  promotable_strategy_count: 1,
  is_complete: false,
  limitations: ['Review status is an audit signal only.'],
  rows: [
    {
      strategy_id: 'dual_ma',
      benchmark_role: 'etf_rotation_trend_following',
      backtest_result_id: 1,
      has_after_cost_and_oos_evidence: true,
      has_risk_block_evidence: true,
      has_paper_shadow_evidence: true,
      has_paper_shadow_divergence_review: true,
      has_account_truth_evidence: true,
      account_truth_gate_status: 'pass',
      account_truth_score: 98,
      has_strategy_attribution_evidence: false,
      strategy_attribution_status: 'evidence_linked_pnl_pending',
      missing_requirements: [],
      promotion_status: 'ready',
      is_promotable: true,
    },
    {
      strategy_id: 'bollinger',
      benchmark_role: 'a_share_or_etf_mean_reversion',
      backtest_result_id: null,
      has_after_cost_and_oos_evidence: false,
      has_risk_block_evidence: false,
      has_paper_shadow_evidence: false,
      has_paper_shadow_divergence_review: false,
      has_account_truth_evidence: false,
      account_truth_gate_status: 'unknown',
      account_truth_score: null,
      has_strategy_attribution_evidence: true,
      strategy_attribution_status: 'not_evaluated',
      missing_requirements: [
        'paper_shadow_evidence',
        'account_truth_gate_pass',
      ],
      promotion_status: 'blocked',
      is_promotable: false,
    },
  ],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installBacktestFetchMock({
  runFails = false,
  sweepFails = false,
  compareFails = false,
  results = [savedSummary],
  strategies = strategyCatalog,
  accountStrategy = {
    strategy_id: 'dual_ma',
    strategy_name: 'dual_ma',
    status: 'research_only',
    scope: 'account',
    symbol: null,
    effective_from: null,
    auto_trade_enabled: false,
    attribution_status: 'not_started',
    attributed_pnl: null,
    realized_pnl: null,
    unrealized_pnl: null,
    total_fees: null,
    notes: '',
    updated_at: '2026-06-18T10:00:00+08:00',
    limitations: [
      'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
    ],
  },
  accountStrategyAttribution = {
    strategy_id: 'dual_ma',
    attribution_status: 'evidence_linked_pnl_pending',
    signal_count: 1,
    action_count: 1,
    risk_decision_count: 1,
    order_count: 1,
    fill_count: 1,
    unattributed_fill_count: 0,
    total_fees: 6.5,
    attributed_pnl: null,
    realized_pnl: null,
    unrealized_pnl: null,
    evidence_refs: ['signal:1', 'order:ORD-ATTR-1', 'fill:FILL-ATTR-1'],
    limitations: [
      'P/L contribution is not calculated until fills are reconciled with position and valuation history.',
    ],
  },
  accountStrategyContribution = {
    strategy_id: 'dual_ma',
    contribution_status: 'estimated_from_linked_fills',
    linked_fill_count: 1,
    gross_realized_pnl: 8,
    gross_unrealized_pnl: 23,
    total_commission: 5,
    total_slippage: 1.5,
    total_tax: 0.5,
    net_contribution: 24,
    unattributed_account_pnl: 4,
    manual_unattributed_pnl: 12,
    cash_flow_pnl: 3,
    missing_valuation_symbols: [],
    evidence_refs: ['fill:FILL-ATTR-1'],
    limitations: [
      'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
    ],
  },
  strategyPromotionReadinessResponse = strategyPromotionReadiness,
  savedBacktestReport = savedReport,
  portfolio = portfolioSnapshot,
}: {
  runFails?: boolean;
  sweepFails?: boolean;
  compareFails?: boolean;
  results?: unknown[];
  strategies?: unknown[];
  accountStrategy?: unknown;
  accountStrategyAttribution?: unknown;
  accountStrategyContribution?: unknown;
  strategyPromotionReadinessResponse?: unknown;
  savedBacktestReport?: unknown;
  portfolio?: unknown;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/backtest/strategies')) {
        return jsonResponse(strategies);
      }
      if (url.includes('/api/backtest/strategy-validation')) {
        return jsonResponse(strategyValidation);
      }
      if (url.includes('/api/backtest/strategy-promotion-readiness')) {
        return jsonResponse(strategyPromotionReadinessResponse);
      }
      if (url.includes('/api/account-strategy/attribution')) {
        return jsonResponse(accountStrategyAttribution);
      }
      if (url.includes('/api/account-strategy/contribution')) {
        return jsonResponse(accountStrategyContribution);
      }
      if (url.includes('/api/account-strategy')) {
        if (init?.method === 'PUT') {
          const payload = JSON.parse(String(init.body ?? '{}'));
          return jsonResponse({
            strategy_id: payload.strategy_id,
            strategy_name: payload.strategy_id,
            status: payload.status ?? 'research_only',
            scope: payload.scope ?? 'account',
            symbol: payload.symbol ?? null,
            effective_from: payload.effective_from ?? null,
            auto_trade_enabled: false,
            attribution_status: 'assignment_only',
            attributed_pnl: null,
            realized_pnl: null,
            unrealized_pnl: null,
            total_fees: null,
            notes: payload.notes ?? '',
            updated_at: '2026-06-18T11:00:00+08:00',
            limitations: [
              'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
            ],
          });
        }
        return jsonResponse(accountStrategy);
      }
      if (url.includes('/api/backtest/run')) {
        return runFails
          ? jsonResponse({ detail: 'backtest unavailable' }, { status: 503 })
          : jsonResponse(runReport);
      }
      if (url.includes('/api/backtest/sweep')) {
        return sweepFails
          ? jsonResponse({ detail: 'sweep unavailable' }, { status: 503 })
          : jsonResponse(sweepResponse);
      }
      if (url.includes('/api/backtest/compare')) {
        return compareFails
          ? jsonResponse({ detail: 'compare unavailable' }, { status: 409 })
          : jsonResponse(compareResponse);
      }
      if (url.includes('/api/backtest/results/1')) {
        return jsonResponse(savedBacktestReport);
      }
      if (url.includes('/api/backtest/results')) {
        return jsonResponse(results);
      }
      if (url.includes('/api/portfolio')) {
        return jsonResponse(portfolio);
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderBacktestPage(
  options?: Parameters<typeof installBacktestFetchMock>[0] & {
    locale?: 'en' | 'zh';
    navigatorLanguage?: string;
  },
) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  Object.defineProperty(window.navigator, 'language', {
    value: options?.navigatorLanguage ?? 'en-US',
    configurable: true,
  });
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installBacktestFetchMock(options);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <BacktestPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the backtest workspace and saved report history', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Strategy replay')).toBeTruthy();
  const evidenceGateTitle = await screen.findByText(
    'Strategy validation and review status',
  );
  expect(evidenceGateTitle).toBeTruthy();
  const evidenceGate = evidenceGateTitle.closest('section');
  expect(evidenceGate).toBeTruthy();
  expect(within(evidenceGate!).getByText('Dual Moving Average')).toBeTruthy();
  expect(within(evidenceGate!).getByText('dual_ma')).toBeTruthy();
  expect(
    within(evidenceGate!).getByText('Bollinger Mean Reversion'),
  ).toBeTruthy();
  expect(within(evidenceGate!).getByText('bollinger')).toBeTruthy();
  expect(await screen.findAllByText('1/2')).toHaveLength(2);
  expect(await screen.findByText('Backtest configuration')).toBeTruthy();
  expect(await screen.findByDisplayValue('Dual Moving Average')).toBeTruthy();
  expect(
    await screen.findByLabelText('Short moving-average window'),
  ).toBeTruthy();
  expect(await screen.findByText('Report selection')).toBeTruthy();
  expect(await screen.findByText('Equity and drawdown')).toBeTruthy();
});

test('shows current account strategy without claiming live attribution', async () => {
  renderBacktestPage({
    accountStrategy: {
      strategy_id: 'dual_ma',
      strategy_name: 'dual_ma',
      status: 'research_only',
      scope: 'account',
      symbol: null,
      effective_from: null,
      auto_trade_enabled: false,
      attribution_status: 'not_started',
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      total_fees: null,
      notes: '',
      updated_at: '2026-06-18T10:00:00+08:00',
      limitations: [
        'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
      ],
    },
  });

  expect(await screen.findByText('Current account strategy')).toBeTruthy();
  expect(
    (await screen.findAllByText('Dual Moving Average')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText('Research only')).toBeTruthy();
  expect(await screen.findByText('Auto trading off')).toBeTruthy();
  expect(await screen.findByText('Attribution not started')).toBeTruthy();
  expect(
    await screen.findByText(
      'This assignment only sets research context; contribution is shown only after signals, reviews, orders, and fills are linked.',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(
      'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
    ),
  ).toBeNull();
});

test('localizes account strategy assignment limitations in Chinese', async () => {
  renderBacktestPage({ results: [], locale: 'zh' });

  expect(await screen.findByText('当前账户策略')).toBeTruthy();
  expect(
    await screen.findByText(
      '当前只是把策略绑定到研究上下文；只有信号、复核、订单和成交都串起来后，才会计算它带来的收益。',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain(
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
  );
  expect(document.body.textContent).not.toContain('paper/shadow');
});

test('shows account strategy attribution evidence without claiming pnl', async () => {
  renderBacktestPage({ results: [] });

  expect(await screen.findByText('Attribution evidence')).toBeTruthy();
  expect(await screen.findByText('Signal / action / risk')).toBeTruthy();
  expect(await screen.findByText('1 / 1 / 1')).toBeTruthy();
  expect(await screen.findByText('Orders / fills')).toBeTruthy();
  expect(await screen.findByText('1 / 1')).toBeTruthy();
  expect(
    (await screen.findAllByText('Evidence linked, P/L pending')).length,
  ).toBeGreaterThan(0);
  expect((await screen.findAllByText(/6\.50/)).length).toBeGreaterThan(0);
  expect(
    await screen.findByText(
      'P/L contribution is waiting for fills to be reconciled with position and valuation history.',
    ),
  ).toBeTruthy();
});

test('shows account strategy contribution estimates with explicit exclusions', async () => {
  renderBacktestPage({ results: [] });

  expect(await screen.findByText('Contribution report')).toBeTruthy();
  expect(await screen.findByText('Gross realized P/L')).toBeTruthy();
  expect(await screen.findByText(/8\.00/)).toBeTruthy();
  expect(await screen.findByText('Gross unrealized P/L')).toBeTruthy();
  expect(await screen.findByText(/23\.00/)).toBeTruthy();
  expect(await screen.findByText('Commission / slippage')).toBeTruthy();
  expect(await screen.findByText(/5\.00 \/ .*1\.50/)).toBeTruthy();
  expect(await screen.findByText('Tax')).toBeTruthy();
  expect((await screen.findAllByText(/0\.50/)).length).toBeGreaterThanOrEqual(
    2,
  );
  expect(await screen.findByText('Manual / cash-flow movement')).toBeTruthy();
  expect(await screen.findByText(/12\.00 \/ .*3\.00/)).toBeTruthy();
  expect(await screen.findByText('Tax / excluded movement')).toBeTruthy();
  expect(await screen.findByText(/0\.50 \/ .*4\.00/)).toBeTruthy();
  expect(await screen.findByText('Net contribution')).toBeTruthy();
  expect(await screen.findByText(/24\.00/)).toBeTruthy();
  expect(
    await screen.findByText(
      'Contribution is estimated from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
    ),
  ).toBeTruthy();
});

test('explains account strategy pnl attribution tier and source statuses', async () => {
  renderBacktestPage({
    results: [],
    accountStrategyAttribution: {
      strategy_id: 'dual_ma',
      attribution_status: 'blocked',
      signal_count: 1,
      action_count: 1,
      risk_decision_count: 1,
      order_count: 1,
      fill_count: 0,
      unattributed_fill_count: 0,
      total_fees: 0,
      attributed_pnl: null,
      realized_pnl: null,
      unrealized_pnl: null,
      evidence_refs: ['signal:1', 'order:ORD-PENDING'],
      limitations: ['Order evidence is present, but fills are blocked.'],
    },
    accountStrategyContribution: {
      strategy_id: 'dual_ma',
      contribution_status: 'valuation_missing',
      linked_fill_count: 0,
      gross_realized_pnl: 0,
      gross_unrealized_pnl: 0,
      total_commission: 0,
      total_slippage: 0,
      total_tax: 0,
      net_contribution: 0,
      unattributed_account_pnl: null,
      manual_unattributed_pnl: null,
      cash_flow_pnl: null,
      missing_valuation_symbols: ['600519'],
      evidence_refs: [],
      limitations: ['Local valuation is missing for linked evidence.'],
    },
    portfolio: {
      ...portfolioSnapshot,
      positions: [
        {
          symbol: '600519',
          display_name: '贵州茅台',
          asset_class: 'stock',
          quantity: 100,
          available_qty: 100,
          frozen_qty: 0,
          avg_cost: 1720.25,
          market_value: 172025,
          unrealized_pnl: 0,
          realized_pnl: 0,
          commission_paid: 0,
        },
      ],
    },
  });

  expect(await screen.findByText('P/L attribution status')).toBeTruthy();
  expect(await screen.findByText('Blocked attribution')).toBeTruthy();
  expect(
    (await screen.findAllByText('Attribution blocked')).length,
  ).toBeGreaterThan(0);
  expect(await screen.findByText('Valuation stale / missing')).toBeTruthy();
  expect(
    await screen.findByText('Source status: Attribution blocked'),
  ).toBeTruthy();
  expect(
    await screen.findByText('Contribution status: Valuation missing'),
  ).toBeTruthy();
  expect(
    await screen.findByText('Missing local valuation for: 贵州茅台 600519.'),
  ).toBeTruthy();
  expect(screen.queryByText('Missing local valuation for: 600519.')).toBeNull();
});

test('selects a strategy from the visible strategy catalog', async () => {
  renderBacktestPage({ results: [] });

  expect(await screen.findByText('Available strategies')).toBeTruthy();
  const selectBollinger = await screen.findByRole('button', {
    name: 'Select Bollinger Mean Reversion',
  });
  fireEvent.click(selectBollinger);

  expect(
    await screen.findByLabelText('Bollinger lookback window'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Standard-deviation multiplier'),
  ).toBeTruthy();
  expect(screen.queryByLabelText('Short moving-average window')).toBeNull();
});

test('assigns the selected strategy as research-only account context', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Select Bollinger Mean Reversion',
    }),
  );
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Set as account research strategy',
    }),
  );

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url, init]) => {
        if (!String(url).includes('/api/account-strategy')) {
          return false;
        }
        const method = (init as RequestInit | undefined)?.method;
        if (method !== 'PUT') {
          return false;
        }
        const payload = JSON.parse(
          String((init as RequestInit | undefined)?.body ?? '{}'),
        );
        return (
          payload.strategy_id === 'bollinger' &&
          payload.status === 'research_only' &&
          payload.scope === 'account'
        );
      }),
    ).toBe(true);
  });
  expect(await screen.findByText('Assignment only')).toBeTruthy();
  expect(screen.getByText('Auto trading off')).toBeTruthy();
});

test('shows account-truth gate status in strategy review status', async () => {
  renderBacktestPage({ results: [] });

  expect(
    await screen.findByText('Strategy validation and review status'),
  ).toBeTruthy();
  expect(await screen.findByText('Account truth gate')).toBeTruthy();
  expect(await screen.findByText('Pass · 98')).toBeTruthy();
  expect(await screen.findByText('Unknown · --')).toBeTruthy();
  expect(await screen.findByText(/Account truth gate must pass/)).toBeTruthy();
  expect(screen.queryByText(/account_truth_gate_pass/)).toBeNull();
});

test('shows strategy attribution gate status in strategy review status', async () => {
  renderBacktestPage({ results: [] });

  expect(await screen.findByText('Strategy attribution gate')).toBeTruthy();
  expect(
    (await screen.findAllByText('Evidence linked, P/L pending')).length,
  ).toBeGreaterThan(0);
  expect(screen.queryByText('evidence_linked_pnl_pending')).toBeNull();
  expect(await screen.findByText('Attribution pending')).toBeTruthy();
});

test('keeps readiness-only strategies visible with display names before ids', async () => {
  renderBacktestPage({
    results: [],
    strategies: [...strategyCatalog, extensionStrategy],
    strategyPromotionReadinessResponse: {
      ...strategyPromotionReadiness,
      required_strategy_count: 3,
      rows: [
        ...strategyPromotionReadiness.rows,
        {
          strategy_id: 'custom_momentum',
          benchmark_role: 'custom_momentum_research',
          backtest_result_id: null,
          has_after_cost_and_oos_evidence: false,
          has_risk_block_evidence: false,
          has_paper_shadow_evidence: false,
          has_paper_shadow_divergence_review: false,
          has_account_truth_evidence: true,
          account_truth_gate_status: 'degraded',
          account_truth_score: 72,
          has_strategy_attribution_evidence: false,
          strategy_attribution_status: 'not_started',
          missing_requirements: [
            'risk_block_evidence',
            'paper_shadow_evidence',
          ],
          promotion_status: 'review_required',
          is_promotable: false,
        },
      ],
    },
  });

  const evidenceGate = (
    await screen.findByText('Strategy validation and review status')
  ).closest('section');
  expect(evidenceGate).toBeTruthy();
  expect(
    await within(evidenceGate!).findByText('Custom Momentum Extension'),
  ).toBeTruthy();
  expect(within(evidenceGate!).getByText('custom_momentum')).toBeTruthy();
  expect(within(evidenceGate!).getByText('Review required')).toBeTruthy();
  expect(within(evidenceGate!).getByText('Degraded · 72')).toBeTruthy();
  expect(within(evidenceGate!).getByText(/Risk block evidence/)).toBeTruthy();
  expect(
    within(evidenceGate!).queryByText(/custom_momentum_research/),
  ).toBeNull();
});

test('defaults strategy parameters to chinese for chinese browser locales', async () => {
  renderBacktestPage({ results: [], navigatorLanguage: 'zh-CN' });

  expect(await screen.findByText('策略回放')).toBeTruthy();
  expect(await screen.findByLabelText('短期均线周期')).toBeTruthy();
  expect(
    await screen.findByText(
      '用于计算短期移动平均线的 K 线/交易周期数，例如 5 表示最近 5 根日线或分钟线。',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText('Short moving-average window in trading bars.'),
  ).toBeNull();
});

test('switches strategy schema controls from the registry', async () => {
  renderBacktestPage({ results: [] });

  expect(
    (await screen.findAllByText('Bollinger Mean Reversion')).length,
  ).toBeGreaterThanOrEqual(1);
  const strategySelect = screen.getByLabelText('Strategy');
  fireEvent.change(strategySelect, { target: { value: 'bollinger' } });

  expect(
    await screen.findByLabelText('Bollinger lookback window'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Standard-deviation multiplier'),
  ).toBeTruthy();
  expect(screen.queryByLabelText('Short moving-average window')).toBeNull();
});

test('renders extension strategy metadata and submits its typed params', async () => {
  const { fetchMock } = renderBacktestPage({
    results: [],
    strategies: [...strategyCatalog, extensionStrategy],
  });

  expect(
    (await screen.findAllByText('Custom Momentum Extension')).length,
  ).toBeGreaterThanOrEqual(1);
  const strategySelect = screen.getByLabelText('Strategy');
  fireEvent.change(strategySelect, { target: { value: 'custom_momentum' } });

  expect(await screen.findByLabelText('Lookback Window')).toBeTruthy();
  expect(await screen.findByText('Strategy metadata')).toBeTruthy();
  expect(await screen.findByText('stock, etf')).toBeTruthy();
  expect((await screen.findAllByText('1d')).length).toBeGreaterThanOrEqual(1);
  expect(
    await screen.findByText('Custom momentum research benchmark'),
  ).toBeTruthy();
  expect(screen.queryByText('custom_momentum_research')).toBeNull();
  expect(
    (await screen.findAllByText('OOS required')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('After-cost required')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    await screen.findByLabelText('Lookback Window candidates'),
  ).toBeTruthy();
  expect(screen.queryByText('lookback_window candidates')).toBeNull();
  expect(
    await screen.findByText('Requires simulation review before manual review.'),
  ).toBeTruthy();

  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '603659' },
  });
  fireEvent.change(await screen.findByLabelText('Lookback Window'), {
    target: { value: '21' },
  });
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.strategy).toBe('custom_momentum');
  expect(payload.params).toEqual({ lookback_window: 21 });
  expect(payload.assets).toEqual([{ symbol: '603659', asset_class: 'stock' }]);
});

test('accepts ordinary whole-number initial cash values in browser validation', async () => {
  renderBacktestPage({ results: [] });

  const initialCashInput = (await screen.findByLabelText(
    'Initial cash',
  )) as HTMLInputElement;
  fireEvent.change(initialCashInput, { target: { value: '10000' } });

  expect(initialCashInput.validity.valid).toBe(true);
});

test('localizes built-in strategy names without changing strategy ids', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  expect(await screen.findByText('策略回放')).toBeTruthy();
  expect(await screen.findByText('策略验证与复核状态')).toBeTruthy();
  expect(screen.getAllByText('复核状态').length).toBeGreaterThan(0);
  expect(await screen.findByDisplayValue('双均线策略')).toBeTruthy();
  expect(
    (await screen.findAllByText('布林带均值回归')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    await screen.findByText(
      '进入复核前需要完成扣除成本后与样本外 ETF 趋势跟踪验证。',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(
      'Requires after-cost, out-of-sample ETF trend-following validation before promotion.',
    ),
  ).toBeNull();

  fireEvent.change(await screen.findByLabelText('标的代码'), {
    target: { value: '603659' },
  });
  const runButton = screen.getByRole('button', { name: '运行回测' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.strategy).toBe('dual_ma');
});

test('localizes backtest asset class options without changing payload enum values', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  const assetClassSelect = (await screen.findByLabelText(
    '资产类别',
  )) as HTMLSelectElement;
  const optionLabels = Array.from(assetClassSelect.options).map(
    (option) => option.textContent,
  );

  expect(optionLabels).toEqual(['股票', 'ETF', '基金', '黄金', '债券']);
  expect(optionLabels).not.toContain('stock');
  expect(optionLabels).not.toContain('fund');

  fireEvent.change(await screen.findByLabelText('标的代码'), {
    target: { value: '018125' },
  });
  fireEvent.change(assetClassSelect, { target: { value: 'fund' } });
  const runButton = screen.getByRole('button', { name: '运行回测' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.assets).toEqual([{ symbol: '018125', asset_class: 'fund' }]);
});

test('uses user-readable chinese copy for the backtest configuration contract', async () => {
  renderBacktestPage({ results: [], locale: 'zh' });

  await screen.findByText('回测配置');
  const pageText = document.body.textContent ?? '';
  expect(pageText).toContain('使用后端回测接口约定');
  expect(pageText).not.toContain('contract');
});

test('uses user-readable english copy for the backtest configuration interface', async () => {
  renderBacktestPage({ results: [], locale: 'en' });

  await screen.findByText('Backtest configuration');
  const pageText = document.body.textContent ?? '';
  expect(pageText).toContain('Uses the backtest interface boundary.');
  expect(pageText).not.toContain('backend backtest contract');
});

test('localizes built-in parameter labels and descriptions without changing payload keys', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  expect(await screen.findByLabelText('短期均线周期')).toBeTruthy();
  expect(await screen.findByLabelText('长期均线周期')).toBeTruthy();
  expect(
    await screen.findByText(
      '用于计算短期移动平均线的 K 线/交易周期数，例如 5 表示最近 5 根日线或分钟线。',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText('Short moving-average window in trading bars.'),
  ).toBeNull();

  fireEvent.change(await screen.findByLabelText('短期均线周期'), {
    target: { value: '3' },
  });
  fireEvent.change(await screen.findByLabelText('长期均线周期'), {
    target: { value: '9' },
  });
  const runButton = screen.getByRole('button', { name: '运行回测' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.params).toEqual({ short_period: 3, long_period: 9 });
});

test('runs a backtest and displays metrics_json and cost_summary_json fields', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '603659' },
  });
  fireEvent.change(
    await screen.findByLabelText('Short moving-average window'),
    {
      target: { value: '3' },
    },
  );
  fireEvent.change(await screen.findByLabelText('Long moving-average window'), {
    target: { value: '9' },
  });
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/run',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const runCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/run'),
  );
  const payload = JSON.parse(String(runCall?.[1]?.body));
  expect(payload.strategy).toBe('dual_ma');
  expect(payload.params).toEqual({ short_period: 3, long_period: 9 });
  expect(payload.assets).toEqual([{ symbol: '603659', asset_class: 'stock' }]);
  expect(await screen.findByText('Run output')).toBeTruthy();
  expect(await screen.findByText('Calmar 3.10')).toBeTruthy();
  expect(await screen.findByText('3 fills')).toBeTruthy();
  expect(
    await screen.findByText(
      'No equity curve is available for this backtest result.',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'No fill details are available for this saved result. New runs expose per-fill cost records when the backtest engine returns them.',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('NaN')).toBeNull();
});

test('renders dataset snapshot metadata for saved reports', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Dataset snapshot')).toBeTruthy();
  expect(
    await screen.findByText('sha256:fixture-dataset-snapshot'),
  ).toBeTruthy();
  expect(await screen.findByText('fixture')).toBeTruthy();
  expect(await screen.findByText('2025-01-02 -> 2026-05-15')).toBeTruthy();
  expect(await screen.findByText('600519')).toBeTruthy();
  expect(await screen.findByText('260 rows')).toBeTruthy();
  expect(await screen.findByText('qfq')).toBeTruthy();
});

test('localizes dataset snapshot asset classes in chinese reports', async () => {
  renderBacktestPage({ locale: 'zh' });

  const title = await screen.findByText('数据快照');
  const panel = title.closest('section');
  expect(panel).toBeTruthy();
  expect(within(panel!).getByText('股票')).toBeTruthy();
  expect(within(panel!).queryByText('stock')).toBeNull();
});

test('marks unconfirmed dataset rows in saved backtest reports', async () => {
  renderBacktestPage({
    savedBacktestReport: {
      ...savedReport,
      metrics_json: {
        ...savedReport.metrics_json,
        dataset_snapshot: {
          ...savedReport.metrics_json.dataset_snapshot,
          symbol_universe:
            savedReport.metrics_json.dataset_snapshot.symbol_universe.map(
              (row) => ({
                ...row,
                data_quality: {
                  status: 'estimated',
                  issues: [
                    {
                      code: 'estimated_quote',
                      message:
                        'Latest local quote is an estimate and needs confirmation.',
                      symbol: row.symbol,
                    },
                  ],
                },
              }),
            ),
        },
      },
    },
  });

  expect(await screen.findByText('Data status')).toBeTruthy();
  expect((await screen.findAllByText('Estimated')).length).toBeGreaterThan(0);
  expect(
    await screen.findByText(
      'Dataset contains unconfirmed market data. Treat after-cost metrics as research evidence until data is refreshed or replayed from confirmed bars.',
    ),
  ).toBeTruthy();
});

test('renders persisted strategy metadata for saved reports', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Strategy snapshot')).toBeTruthy();
  expect(
    (await screen.findAllByText('Dual Moving Average')).length,
  ).toBeGreaterThanOrEqual(2);
  expect((await screen.findAllByText('dual_ma')).length).toBeGreaterThanOrEqual(
    1,
  );
  expect(
    (await screen.findAllByText('ETF trend-following benchmark')).length,
  ).toBeGreaterThanOrEqual(1);
  expect((await screen.findAllByText('etf')).length).toBeGreaterThanOrEqual(1);
  expect((await screen.findAllByText('1d')).length).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('OOS required')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('After-cost required')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText('Short moving-average window=5')).toBeTruthy();
  expect(await screen.findByText('Long moving-average window=20')).toBeTruthy();
  expect(
    (await screen.findAllByText('API field: short_period')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('Short moving-average window')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('default 5')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (
      await screen.findAllByText(
        'Requires after-cost, out-of-sample ETF trend-following validation before promotion.',
      )
    ).length,
  ).toBeGreaterThanOrEqual(1);
});

test('localizes persisted strategy metadata for chinese reports', async () => {
  renderBacktestPage({ locale: 'zh' });

  expect(await screen.findByText('策略快照')).toBeTruthy();
  expect(
    (await screen.findAllByText('双均线策略')).length,
  ).toBeGreaterThanOrEqual(2);
  expect(await screen.findByText('短期均线周期=5')).toBeTruthy();
  expect(await screen.findByText('长期均线周期=20')).toBeTruthy();
  expect(
    (await screen.findAllByText('参数键：short_period')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('默认值 5')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (
      await screen.findAllByText(
        '用于计算短期移动平均线的 K 线/交易周期数，例如 5 表示最近 5 根日线或分钟线。',
      )
    ).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (
      await screen.findAllByText(
        '进入复核前需要完成扣除成本后与样本外 ETF 趋势跟踪验证。',
      )
    ).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    screen.queryByText('Short moving-average window in trading bars.'),
  ).toBeNull();
});

test('renders after-cost and out-of-sample evidence for saved reports', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Validation evidence')).toBeTruthy();
  expect(await screen.findByText('After-cost evidence')).toBeTruthy();
  expect(await screen.findByText('Out-of-sample split')).toBeTruthy();
  expect(
    (await screen.findAllByText('ETF trend-following benchmark')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText('Benchmark passed')).toBeTruthy();
  expect(await screen.findByText('2025-09-01 00:00')).toBeTruthy();
  expect(
    await screen.findByText('Backtest evidence is not a profitability claim.'),
  ).toBeTruthy();
  expect(await screen.findByText('Cost assumptions')).toBeTruthy();
  expect(await screen.findByText('Slippage assumptions')).toBeTruthy();
  expect(
    await screen.findByText(
      'Commission assumptions use the configured simulated backtest fee schedule.',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Slippage assumptions use the configured simulated execution drift model.',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Validation evidence is not investment advice or a profitability guarantee.',
    ),
  ).toBeTruthy();
});

test('shows a clear error when the run endpoint fails', async () => {
  renderBacktestPage({ runFails: true, results: [] });

  await screen.findByText('Strategy replay');
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  expect((await screen.findByRole('alert')).textContent).toContain(
    'backtest unavailable',
  );
  expect(screen.queryByText(/real-time/i)).toBeNull();
});

test('runs a parameter sweep and renders ranked research warnings', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '603659' },
  });
  fireEvent.change(
    await screen.findByLabelText('Short moving-average window candidates'),
    {
      target: { value: '3, 5' },
    },
  );
  fireEvent.change(
    await screen.findByLabelText('Long moving-average window candidates'),
    {
      target: { value: '9' },
    },
  );
  const sweepButton = screen.getByRole('button', {
    name: 'Run parameter sweep',
  });
  fireEvent.submit(sweepButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/sweep',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const sweepCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/sweep'),
  );
  const payload = JSON.parse(String(sweepCall?.[1]?.body));
  expect(payload.param_grid).toEqual({
    short_period: [3, 5],
    long_period: [9],
  });
  expect(payload.assets).toEqual([{ symbol: '603659', asset_class: 'stock' }]);
  expect(await screen.findByText('Sweep rankings')).toBeTruthy();
  expect(await screen.findByText('2 tested')).toBeTruthy();
  expect(await screen.findByText('Result #12')).toBeTruthy();
  expect(
    await screen.findByText(
      'Short moving-average window=5, Long moving-average window=9',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('short_period=5, long_period=9')).toBeNull();
  expect(await screen.findByText('14.0%')).toBeTruthy();
  expect(
    await screen.findByText(
      'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.',
    ),
  ).toBeTruthy();
});

test('runs a same-dataset parameter comparison and renders saved result ids', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '603659' },
  });
  fireEvent.change(await screen.findByLabelText('Comparison parameter sets'), {
    target: {
      value: 'short_period=3, long_period=9\nshort_period=5, long_period=9',
    },
  });
  const compareButton = screen.getByRole('button', {
    name: 'Run comparison',
  });
  fireEvent.submit(compareButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/compare',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const compareCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/compare'),
  );
  const payload = JSON.parse(String(compareCall?.[1]?.body));
  expect(payload.assets).toEqual([{ symbol: '603659', asset_class: 'stock' }]);
  expect(payload.runs).toEqual([
    {
      strategy: 'dual_ma',
      params: { short_period: 3, long_period: 9 },
    },
    {
      strategy: 'dual_ma',
      params: { short_period: 5, long_period: 9 },
    },
  ]);
  expect(await screen.findByText('Comparison results')).toBeTruthy();
  expect(await screen.findByText('2 compared')).toBeTruthy();
  expect(await screen.findByText('snapshot-shared')).toBeTruthy();
  expect(await screen.findByText('Result #1202')).toBeTruthy();
  expect(
    await screen.findByText(
      'Short moving-average window=5, Long moving-average window=9',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('5.0%')).toBeTruthy();
  expect(
    await screen.findByText(
      'Comparison is valid only when every run uses the same frozen dataset snapshot.',
    ),
  ).toBeTruthy();
});

test('accepts localized comparison parameter names while submitting API keys', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  const parameterSets = (await screen.findByLabelText(
    '对比参数集',
  )) as HTMLTextAreaElement;
  expect(parameterSets.value).toContain('短期均线周期=5');
  expect(parameterSets.value).toContain('长期均线周期=20');
  expect(parameterSets.value).not.toContain('short_period=');
  expect(
    await screen.findByText(
      '已解析 2 组参数；每行一组，例如 短期均线周期=3, 长期均线周期=9。',
    ),
  ).toBeTruthy();

  fireEvent.change(await screen.findByLabelText('标的代码'), {
    target: { value: '603659' },
  });
  fireEvent.change(parameterSets, {
    target: {
      value: '短期均线周期=3, 长期均线周期=9\n短期均线周期=5, 长期均线周期=9',
    },
  });
  const compareButton = screen.getByRole('button', {
    name: '运行对比',
  });
  fireEvent.submit(compareButton.closest('form') as HTMLFormElement);

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/compare',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const compareCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/compare'),
  );
  const payload = JSON.parse(String(compareCall?.[1]?.body));
  expect(payload.runs).toEqual([
    {
      strategy: 'dual_ma',
      params: { short_period: 3, long_period: 9 },
    },
    {
      strategy: 'dual_ma',
      params: { short_period: 5, long_period: 9 },
    },
  ]);
  expect(await screen.findByText('对比结果')).toBeTruthy();
  expect(
    await screen.findByText('短期均线周期=5, 长期均线周期=9'),
  ).toBeTruthy();
});
