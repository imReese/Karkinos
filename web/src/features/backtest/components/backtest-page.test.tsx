import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
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

const signalPreviewResponse = {
  schema_version: 'karkinos.strategy_signal_preview.v1',
  strategy_id: 'dual_ma',
  symbol: '600002',
  params: { short_period: 3, long_period: 9 },
  run_id: 'preview-run-001',
  dataset_snapshot_id: 'sha256:preview-dataset',
  record_count: 1,
  does_not_enable_execution: true,
  limitations: [
    'Strategy signal preview is research evidence only.',
    'Candidate actions require data, account-truth, risk, paper/shadow, and manual-review gates before any live-like workflow.',
  ],
  outputs: [
    {
      schema_version: 'karkinos.strategy_runtime_output.v1',
      output_id: 'preview-run-001:0001:buy_candidate',
      strategy_id: 'dual_ma',
      run_id: 'preview-run-001',
      hook: 'on_bar',
      output_type: 'buy_candidate',
      record_kind: 'candidate_action',
      action: 'buy',
      reason: 'Strategy emitted a buy candidate from the supplied market bars.',
      source_event_id: '600002:2026-06-18T15:00:00+08:00',
      symbol: '600002',
      confidence: null,
      target_weight: '1.0',
      quantity: null,
      price: '29.17',
      evidence: {
        bar_count: 120,
        dataset_snapshot_id: 'sha256:preview-dataset',
        data_quality_status: 'ok',
        research_only: true,
        does_not_enable_execution: true,
        signal_timestamp: '2026-06-18T15:00:00+08:00',
        reference_price: '29.17',
      },
      review_gates: [
        {
          key: 'data',
          status: 'pass',
          severity: 'info',
          summary: 'Dataset snapshot is available for the preview bars.',
          required_action: null,
          evidence_ref: 'sha256:preview-dataset',
        },
        {
          key: 'account_truth',
          status: 'not_evaluated',
          severity: 'warning',
          summary:
            'Account-truth evidence must be checked before this candidate can enter any live-like workflow.',
          required_action: 'review_account_truth_evidence',
          evidence_ref: null,
        },
        {
          key: 'risk',
          status: 'not_evaluated',
          severity: 'warning',
          summary:
            'Pre-trade risk requires a sized order intent and current account context.',
          required_action: 'size_order_and_run_pre_trade_risk_gate',
          evidence_ref: null,
        },
        {
          key: 'paper_shadow',
          status: 'waiting',
          severity: 'warning',
          summary:
            'Paper/shadow preview waits for data, account-truth, and risk gates.',
          required_action: 'run_paper_shadow_preview_after_gates',
          evidence_ref: null,
        },
        {
          key: 'manual_review',
          status: 'required',
          severity: 'warning',
          summary: 'Manual review is required before any live-like workflow.',
          required_action: 'manual_confirm_or_reject_candidate',
          evidence_ref: null,
        },
      ],
      requires_risk_gate: true,
      requires_account_truth_gate: true,
      requires_paper_shadow_review: true,
      requires_manual_review: true,
      does_not_enable_execution: true,
    },
  ],
};

const riskPreviewResponse = {
  schema_version: 'karkinos.pre_trade_risk_preview.v1',
  passed: false,
  status: 'blocked',
  severity: 'warning',
  reasons: ['kill switch is enabled: buy orders are blocked'],
  manual_confirmation_required: true,
  does_not_create_order: true,
  does_not_persist_decision: true,
  metadata: {
    quantity: '100',
    reference_price: '29.17',
    target_weight: '1.0',
    cash: '100000',
    total_equity: '100000',
    order_value: '2917.00',
    projected_cash: '97083.00',
    current_position_value: '0',
    projected_position_value: '2917.00',
    projected_position_weight: '0.02917',
    policy: {
      execution_mode: 'manual',
      max_order_notional: null,
      min_cash_reserve: '0',
      max_position_weight: null,
    },
  },
};

const passedRiskPreviewResponse = {
  ...riskPreviewResponse,
  passed: true,
  status: 'passed',
  severity: 'info',
  reasons: ['approved'],
};

const paperShadowPreviewResponse = {
  schema_version: 'karkinos.paper_shadow_preview.v1',
  status: 'simulated',
  execution_mode: 'paper_shadow_preview',
  manual_confirmation_required: true,
  does_not_create_order: true,
  does_not_create_fill: true,
  does_not_mutate_ledger: true,
  risk_reasons: ['approved'],
  order: {
    order_id: 'paper-shadow-preview:dual_ma:600002:buy:100:29.17',
    symbol: '600002',
    side: 'buy',
    order_type: 'market',
    quantity: '100',
    price: '29.17',
    asset_class: 'stock',
    status: 'filled',
    filled_quantity: '100',
    remaining_quantity: '0',
    context: {
      strategy_id: 'dual_ma',
      signal_id: 'preview-run-001:0001:buy_candidate',
      dataset_id: 'sha256:preview-dataset',
    },
    execution_mode: 'paper_shadow_preview',
    source: 'backtest_paper_shadow_preview',
    does_not_mutate_production_ledger: true,
  },
  fill: {
    fill_id: 'paper-shadow-preview:dual_ma:600002:buy:100:29.17:fill:1',
    order_id: 'paper-shadow-preview:dual_ma:600002:buy:100:29.17',
    symbol: '600002',
    side: 'buy',
    fill_price: '29.17',
    fill_quantity: '100',
    commission: '5.0291700',
    slippage: '0',
    asset_class: 'stock',
    execution_mode: 'paper_shadow_preview',
    source: 'backtest_paper_shadow_preview',
    does_not_mutate_production_ledger: true,
    fee_breakdown: {
      gross_amount: '2917.00',
      commission: '5',
      stamp_tax: '0',
      transfer_fee: '0.0291700',
      other_fees: '0.00',
      total_fee: '5.0291700',
      fee_rule_id: 'cn_stock_a_default_v1',
      limitations: ['transfer_fee_exchange_not_split'],
    },
  },
  shadow_review: {
    schema_version: 'karkinos.shadow_review.v1',
    does_not_mutate_account_facts: true,
    candidate_count: 1,
    supported_match_count: 0,
    unsupported_real_movement_count: 0,
    items: [],
    limitations: ['This report does not mutate account facts.'],
  },
  limitations: [
    'Paper/shadow preview is simulation evidence, not investment advice.',
    'This preview does not mutate ledger entries or submit broker orders.',
  ],
};

const attributionPreviewResponse = {
  schema_version: 'karkinos.strategy_attribution_preview.v1',
  status: 'ready_for_review_linkage',
  strategy_id: 'dual_ma',
  symbol: '600002',
  asset_class: 'stock',
  attribution_status: 'preview_only_pnl_not_attributed',
  can_attribute_pnl: false,
  does_not_create_order: true,
  does_not_create_fill: true,
  does_not_mutate_ledger: true,
  evidence_counts: {
    signal_preview: 1,
    risk_preview: 1,
    paper_shadow_order: 1,
    paper_shadow_fill: 1,
    production_order: 0,
    production_fill: 0,
  },
  evidence_refs: [
    'signal_preview:preview-run-001:0001:buy_candidate',
    'dataset_snapshot:sha256:preview-dataset',
    'risk_preview:approved',
    'paper_shadow_order:paper-shadow-preview:dual_ma:600002:buy:100:29.17',
    'paper_shadow_fill:paper-shadow-preview:dual_ma:600002:buy:100:29.17:fill:1',
  ],
  required_next_actions: [
    'link_signal_review_order_and_fill_before_strategy_pnl_attribution',
  ],
  review_linkage_candidate: {
    candidate_id:
      'review-linkage:dual_ma:600002:preview-run-001:0001:buy_candidate',
    strategy_id: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    signal_ref: 'signal_preview:preview-run-001:0001:buy_candidate',
    dataset_snapshot_ref: 'dataset_snapshot:sha256:preview-dataset',
    risk_preview_ref: 'risk_preview:approved',
    paper_shadow_order_ref:
      'paper_shadow_order:paper-shadow-preview:dual_ma:600002:buy:100:29.17',
    paper_shadow_fill_ref:
      'paper_shadow_fill:paper-shadow-preview:dual_ma:600002:buy:100:29.17:fill:1',
    recommended_review_action: 'review_and_link_evidence_manually',
    manual_confirmation_required: true,
    does_not_create_order: true,
    does_not_create_fill: true,
    does_not_mutate_ledger: true,
    can_link_to_strategy_pnl: false,
  },
  limitations: [
    'Preview evidence is not production attribution evidence.',
    'Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.',
  ],
};

const holdingStrategyAttributionResponse = {
  strategy_id: 'dual_ma',
  symbol: '600002',
  assignment_scope: 'account',
  assignment_applies_to_symbol: true,
  attribution_status: 'holding_evidence_linked_review_required',
  signal_count: 1,
  action_count: 1,
  risk_decision_count: 1,
  order_count: 1,
  fill_count: 1,
  evidence_refs: [
    'signal:1',
    'action:101',
    'risk:RISK-HOLDING-1',
    'order:ORD-HOLDING-1',
    'fill:FILL-HOLDING-1',
  ],
  review_prerequisites: [
    { key: 'strategy_signal', passed: true, evidence_count: 1 },
    { key: 'candidate_action', passed: true, evidence_count: 1 },
    { key: 'risk_gate', passed: true, evidence_count: 1 },
    { key: 'manual_review', passed: false, evidence_count: 0 },
    { key: 'order_evidence', passed: true, evidence_count: 1 },
    { key: 'fill_evidence', passed: true, evidence_count: 1 },
  ],
  limitations: [
    'Holding-level strategy attribution is evidence-only until the linked fills are reviewed against the production ledger and valuation history.',
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
    source_type: 'builtin',
    is_extension: false,
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
  source_type: 'extension',
  is_extension: true,
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
  datasets = [],
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
      'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    ],
  },
  accountStrategyAssignments = [],
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
    schema_version: 'karkinos.account_strategy_contribution.v2',
    strategy_id: 'dual_ma',
    contribution_status: 'evidence_bound_from_posted_fills',
    evidence_binding_status: 'bound',
    next_manual_action: 'review_evidence_bound_strategy_contribution',
    blockers: [],
    strategy_health_status: 'healthy',
    strategy_health_reasons: ['posted_fill_and_valuation_evidence_bound'],
    linked_fill_count: 1,
    ledger_posted_fill_count: 1,
    unposted_linked_fill_count: 0,
    unattributed_fill_count: 0,
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
    valuation_snapshot_id: 'valuation-backtest-fixture',
    valuation_status: 'complete',
    valuation_scope_status: 'complete',
    ledger_cutoff_id: 12,
    contribution_fingerprint: 'contribution-backtest-fixture',
    evidence_refs: [
      'fill:FILL-ATTR-1',
      'ledger_entry:12',
      'valuation_snapshot:valuation-backtest-fixture',
    ],
    persisted_facts_only: true,
    provider_contacted: false,
    database_writes_performed: false,
    authorizes_execution: false,
    limitations: [
      'Only strategy-linked fills posted to the production ledger are eligible for contribution.',
    ],
  },
  strategyPromotionReadinessResponse = strategyPromotionReadiness,
  signalPreview = signalPreviewResponse,
  riskPreview = riskPreviewResponse,
  paperShadowPreview = paperShadowPreviewResponse,
  attributionPreview = attributionPreviewResponse,
  holdingStrategyAttribution = holdingStrategyAttributionResponse,
  savedBacktestReport = savedReport,
  portfolio = portfolioSnapshot,
}: {
  runFails?: boolean;
  sweepFails?: boolean;
  compareFails?: boolean;
  datasets?: unknown[];
  results?: unknown[];
  strategies?: unknown[];
  accountStrategy?: unknown;
  accountStrategyAssignments?: unknown[];
  accountStrategyAttribution?: unknown;
  accountStrategyContribution?: unknown;
  strategyPromotionReadinessResponse?: unknown;
  signalPreview?: unknown;
  riskPreview?: unknown;
  paperShadowPreview?: unknown;
  attributionPreview?: unknown;
  holdingStrategyAttribution?: unknown;
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
      if (url.includes('/api/backtest/datasets')) {
        return jsonResponse({
          tdx_configured: true,
          storage_path: '/workspace/data/research',
          busy: false,
          datasets,
        });
      }
      if (url.includes('/api/backtest/strategy-validation')) {
        return jsonResponse(strategyValidation);
      }
      if (url.includes('/api/backtest/strategy-promotion-readiness')) {
        return jsonResponse(strategyPromotionReadinessResponse);
      }
      if (url.includes('/api/account-strategy/holdings/')) {
        return jsonResponse(holdingStrategyAttribution);
      }
      if (url.includes('/api/account-strategy/attribution')) {
        return jsonResponse(accountStrategyAttribution);
      }
      if (url.includes('/api/account-strategy/contribution')) {
        return jsonResponse(accountStrategyContribution);
      }
      if (url.includes('/api/strategy-learning/review-queue')) {
        return jsonResponse({
          schema_version: 'karkinos.strategy_learning_review.v1',
          status: 'not_configured',
          reviewed_signal_count: 0,
          action_item_count: 0,
          critical_item_count: 0,
          outcome_counts: {},
          strategy_summaries: [],
          items: [],
          limitations: [],
          queue_fingerprint: 'strategy-learning-empty-fixture',
          generated_at: '2026-07-18T12:00:00+00:00',
          persisted_facts_only: true,
          provider_contacted: false,
          database_writes_performed: false,
          financial_recalculation_performed: false,
          ai_invoked: false,
          memory_created: false,
          strategy_changed: false,
          authorizes_execution: false,
          capital_authority_changed: false,
        });
      }
      if (url.includes('/api/account-strategy/assignments')) {
        if (init?.method === 'PUT') {
          const payload = JSON.parse(String(init.body ?? '{}'));
          return jsonResponse({
            strategy_id: payload.strategy_id,
            strategy_name: payload.strategy_id,
            status: payload.status ?? 'research_only',
            scope: payload.scope ?? 'symbol',
            asset_class: payload.asset_class ?? null,
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
              'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
            ],
          });
        }
        return jsonResponse(accountStrategyAssignments);
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
              'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
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
      if (url.includes('/api/backtest/signal-preview')) {
        return jsonResponse(signalPreview);
      }
      if (url.includes('/api/backtest/risk-preview')) {
        return jsonResponse(riskPreview);
      }
      if (url.includes('/api/backtest/paper-shadow-preview')) {
        return jsonResponse(paperShadowPreview);
      }
      if (url.includes('/api/backtest/attribution-preview')) {
        return jsonResponse(attributionPreview);
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

function openBacktestDisclosure(testId: string) {
  const disclosure = screen.getByTestId(testId);
  if (disclosure.getAttribute('aria-expanded') !== 'true') {
    fireEvent.click(disclosure);
  }
}

async function clickEnabledButton(name: string) {
  const button = (await screen.findByRole('button', {
    name,
  })) as HTMLButtonElement;
  await waitFor(() => {
    expect(button.disabled).toBe(false);
  });
  fireEvent.click(button);
}

async function selectCatalogStrategy(value: string, label: string) {
  await screen.findByRole('option', { name: label });
  const strategySelect = await screen.findByRole('combobox', {
    name: 'Available strategies',
  });
  fireEvent.change(strategySelect, { target: { value } });
  await waitFor(() => {
    expect((strategySelect as HTMLSelectElement).value).toBe(value);
  });
}

afterEach(() => {
  window.history.pushState({}, '', '/');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the backtest workspace and saved report history', async () => {
  renderBacktestPage();

  expect(await screen.findByText('Strategy replay')).toBeTruthy();
  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
  const evidenceGateTitle = await screen.findByText(
    'Strategy validation and review status',
  );
  expect(evidenceGateTitle).toBeTruthy();
  const evidenceGate = evidenceGateTitle.closest('section');
  expect(evidenceGate).toBeTruthy();
  expect(
    await within(evidenceGate!).findByText('Dual Moving Average'),
  ).toBeTruthy();
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
  expect(await screen.findByText('Run registry')).toBeTruthy();
  expect(screen.getByTestId('backtest-run-registry')).toBeTruthy();
  const persistedEvidence = screen.getByTestId('backtest-persisted-evidence');
  const equityChart = await within(persistedEvidence).findByRole('heading', {
    name: 'Equity and drawdown',
  });
  for (const testId of [
    'backtest-validation-disclosure',
    'backtest-dataset-disclosure',
    'backtest-strategy-evidence-disclosure',
    'backtest-fills-disclosure',
  ]) {
    const disclosure = within(persistedEvidence).getByTestId(testId);
    expect(disclosure.tagName).toBe('DETAILS');
    expect(disclosure.hasAttribute('open')).toBe(false);
  }
  const metrics = persistedEvidence.querySelector(
    '[data-backtest-report-section="metrics"]',
  );
  expect(metrics).toBeTruthy();
  const validationEvidence = within(persistedEvidence).getByRole('heading', {
    name: 'Validation evidence',
  });
  const datasetSnapshot = within(persistedEvidence).getByRole('heading', {
    name: 'Dataset snapshot',
  });
  const strategySnapshot = within(persistedEvidence).getByRole('heading', {
    name: 'Strategy snapshot',
  });
  expect(
    equityChart.compareDocumentPosition(metrics!) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    equityChart.compareDocumentPosition(validationEvidence) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    validationEvidence.compareDocumentPosition(datasetSnapshot) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    datasetSnapshot.compareDocumentPosition(strategySnapshot) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  const tabs = screen.getByTestId('backtest-mobile-workspace-tabs');
  await waitFor(() => {
    expect(tabs.getAttribute('data-workspace-view')).toBe('results');
  });
  expect(
    within(tabs).getByRole('tab', { name: 'Results and evidence' }),
  ).toBeTruthy();
  expect(screen.getByTestId('backtest-result-panel').className).not.toContain(
    'hidden xl:block',
  );
});

test('keeps the saved report context separate from the next run configuration', async () => {
  renderBacktestPage({
    results: [{ ...savedSummary, strategy: 'bollinger' }],
    savedBacktestReport: {
      ...savedReport,
      config: { ...savedReport.config, strategy: 'bollinger' },
    },
  });

  const reportContext = await screen.findByTestId(
    'backtest-selected-report-context',
  );
  expect(await within(reportContext).findByText('600519')).toBeTruthy();
  expect(within(reportContext).getByText('Selected report #1')).toBeTruthy();
  expect(
    within(reportContext).getByText('Bollinger Mean Reversion'),
  ).toBeTruthy();
  const draftContext = screen.getByRole('region', {
    name: 'Next run configuration',
  });
  expect(within(draftContext).getByText('Dual Moving Average')).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Symbol'), {
    target: { value: '600000' },
  });
  expect(within(draftContext).getByText('600000')).toBeTruthy();
  expect(within(reportContext).getByText('600519')).toBeTruthy();
  expect(within(reportContext).queryByText('600000')).toBeNull();
});

test('keeps setup and current results in one primary workspace with mobile tabs', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  const primary = await screen.findByTestId('backtest-primary-workbench');
  const setup = screen.getByTestId(
    'backtest-run-setup-disclosure',
  ) as HTMLDetailsElement;
  const results = screen.getByTestId('backtest-result-panel');
  const tabs = screen.getByTestId('backtest-mobile-workspace-tabs');
  const contextMetrics = screen
    .getAllByLabelText('Next run configuration')
    .find((element) => element.tagName === 'DL');

  expect(setup).toBeTruthy();
  expect(contextMetrics?.className).toContain('app-backtest-evidence-strip');
  expect(contextMetrics?.className).toContain('app-backtest-context-strip');
  expect(contextMetrics?.className).toContain('app-horizontal-scroll-cue');
  expect(primary.contains(setup)).toBe(true);
  expect(primary.contains(results)).toBe(true);
  expect(setup.open).toBe(true);
  expect(
    (
      screen.getByTestId(
        'backtest-strategy-detail-disclosure',
      ) as HTMLDetailsElement
    ).open,
  ).toBe(false);
  expect(tabs.getAttribute('role')).toBe('tablist');
  expect(tabs.getAttribute('data-workspace-view')).toBe('setup');
  expect(
    results.compareDocumentPosition(setup) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();

  for (const testId of [
    'backtest-advanced-tools-disclosure',
    'backtest-research-governance-disclosure',
    'backtest-promotion-evidence-disclosure',
    'backtest-research-archive-disclosure',
  ]) {
    expect(screen.getByTestId(testId).getAttribute('aria-expanded')).toBe(
      'false',
    );
  }

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes('/api/backtest/strategy-promotion-readiness'),
      ),
    ).toBe(true);
  });
  for (const deferredPath of [
    '/api/account-strategy',
    '/api/portfolio',
    '/api/strategy-learning/review-queue',
    '/api/backtest/strategy-validation',
  ]) {
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes(deferredPath)),
      deferredPath,
    ).toBe(false);
  }

  fireEvent.click(
    screen.getByTestId('backtest-research-governance-disclosure'),
  );
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes('/api/strategy-learning/review-queue'),
      ),
    ).toBe(true);
  });
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('/api/account-strategy'),
    ),
  ).toBe(true);
  expect(
    fetchMock.mock.calls.some(([url]) =>
      String(url).includes('/api/portfolio'),
    ),
  ).toBe(true);

  fireEvent.click(screen.getByTestId('backtest-promotion-evidence-disclosure'));
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes('/api/backtest/strategy-validation'),
      ),
    ).toBe(true);
  });

  fireEvent.click(screen.getByTestId('backtest-advanced-tools-disclosure'));
  expect(
    screen
      .getByTestId('backtest-advanced-tools-disclosure')
      .getAttribute('aria-expanded'),
  ).toBe('true');
  expect(
    document.getElementById('backtest-advanced-tools')!.className,
  ).not.toContain('hidden');

  fireEvent.click(
    within(tabs).getByRole('tab', { name: 'Results and evidence' }),
  );
  expect(results.className).not.toContain('hidden xl:block');
  expect(setup!.className).toContain('hidden xl:block');
});

test('prefills single-instrument research context from decision handoff query', async () => {
  window.history.pushState(
    {},
    '',
    '/backtest?symbol=600519&assetClass=stock&strategy=dual_ma',
  );

  renderBacktestPage({ results: [] });

  expect(
    ((await screen.findByLabelText('Symbol')) as HTMLInputElement).value,
  ).toBe('600519');
  expect(
    (screen.getByLabelText('Asset class') as HTMLSelectElement).value,
  ).toBe('stock');
  expect(
    (screen.getByLabelText('Available strategies') as HTMLSelectElement).value,
  ).toBe('dual_ma');
  const handoff = await screen.findByTestId('backtest-handoff-context');
  expect(handoff.textContent).toContain('Decision handoff context');
  expect(handoff.textContent).toContain('600519');
  expect(handoff.textContent).toContain('Dual Moving Average');
  expect(handoff.textContent).toContain('Research only');
});

test('labels portfolio handoff context as holding research instead of decision handoff', async () => {
  window.history.pushState(
    {},
    '',
    '/backtest?symbol=600519&assetClass=stock&strategy=dual_ma&source=portfolio',
  );

  renderBacktestPage({ results: [] });

  const handoff = await screen.findByTestId('backtest-handoff-context');
  expect(handoff.textContent).toContain('Holding research handoff');
  expect(handoff.textContent).toContain('Holding research context');
  expect(handoff.textContent).not.toContain('Decision handoff');
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
        'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
      ],
    },
  });

  openBacktestDisclosure('backtest-research-governance-disclosure');
  expect(await screen.findByText('Current account strategy')).toBeTruthy();
  expect(
    (await screen.findAllByText('Dual Moving Average')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(await screen.findByText('Research only')).toBeTruthy();
  expect(await screen.findByText('Auto trading off')).toBeTruthy();
  expect(await screen.findByText('Attribution not started')).toBeTruthy();
  expect(
    await screen.findByText(
      'This assignment only sets research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
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

  openBacktestDisclosure('backtest-research-governance-disclosure');
  expect(await screen.findByText('当前账户策略')).toBeTruthy();
  expect(
    await screen.findByText(
      '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain(
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.',
  );
  expect(document.body.textContent).not.toContain('paper/shadow');
});

test('shows account strategy attribution evidence without claiming pnl', async () => {
  renderBacktestPage({ results: [] });

  openBacktestDisclosure('backtest-research-governance-disclosure');
  expect(await screen.findByText('Attribution evidence')).toBeTruthy();
  expect(await screen.findByText('Signal / action / risk')).toBeTruthy();
  expect(await screen.findByText('1 / 1 / 1')).toBeTruthy();
  expect(await screen.findByText('Orders / fills')).toBeTruthy();
  expect((await screen.findAllByText('1 / 1')).length).toBeGreaterThanOrEqual(
    2,
  );
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

test('shows ledger and valuation bound account strategy contribution', async () => {
  renderBacktestPage({ results: [] });

  openBacktestDisclosure('backtest-research-governance-disclosure');
  expect(await screen.findByText('Contribution report')).toBeTruthy();
  expect(await screen.findByText('Gross realized P/L')).toBeTruthy();
  expect(await screen.findByText(/8\.00/)).toBeTruthy();
  expect(await screen.findByText('Gross unrealized P/L')).toBeTruthy();
  expect(await screen.findByText(/23\.00/)).toBeTruthy();
  expect(await screen.findByText('Commission / slippage')).toBeTruthy();
  expect(await screen.findByText(/5\.00 \/ .*1\.50/)).toBeTruthy();
  expect(await screen.findByText('Tax')).toBeTruthy();
  expect(await screen.findByText(/0\.50/)).toBeTruthy();
  expect(await screen.findByText('Valuation snapshot')).toBeTruthy();
  expect(await screen.findByText('valuation-backtest-fixture')).toBeTruthy();
  expect(await screen.findByText('Ledger cutoff')).toBeTruthy();
  expect(await screen.findByText('12')).toBeTruthy();
  expect(await screen.findByText('Posted / linked fills')).toBeTruthy();
  expect((await screen.findAllByText('1 / 1')).length).toBeGreaterThanOrEqual(
    2,
  );
  expect(await screen.findByText('Net contribution')).toBeTruthy();
  expect(await screen.findByText(/24\.00/)).toBeTruthy();
  expect(
    await screen.findByText(
      'Only strategy-linked fills posted to the production ledger are eligible for contribution.',
    ),
  ).toBeTruthy();
});

test('keeps known strategy ids secondary when registry metadata is missing', async () => {
  renderBacktestPage({
    results: [],
    strategies: [strategyCatalog[1]],
  });

  openBacktestDisclosure('backtest-research-governance-disclosure');
  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
  expect(await screen.findByText('Research only')).toBeTruthy();
  const currentStrategy = (
    await screen.findByText('Current account strategy')
  ).closest('section');
  expect(currentStrategy).toBeTruthy();
  expect(
    within(currentStrategy!).getByText('Dual Moving Average'),
  ).toBeTruthy();
  expect(within(currentStrategy!).queryByText(/^dual_ma$/u)).toBeNull();

  const evidenceGate = (
    await screen.findByText('Strategy validation and review status')
  ).closest('section');
  expect(evidenceGate).toBeTruthy();
  expect(within(evidenceGate!).getByText('Dual Moving Average')).toBeTruthy();
  expect(within(evidenceGate!).getByText('dual_ma')).toBeTruthy();
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

  openBacktestDisclosure('backtest-research-governance-disclosure');
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
  const catalogStrategySelect = await screen.findByRole('combobox', {
    name: 'Available strategies',
  });
  fireEvent.change(catalogStrategySelect, { target: { value: 'bollinger' } });

  expect(
    await screen.findByLabelText('Bollinger lookback window'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText('Standard-deviation multiplier'),
  ).toBeTruthy();
  expect(screen.queryByLabelText('Short moving-average window')).toBeNull();
});

test('shows user-readable strategy source badges in the catalog', async () => {
  renderBacktestPage({
    results: [],
    strategies: [...strategyCatalog, extensionStrategy],
  });

  expect(
    (await screen.findAllByText('Dual Moving Average')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('Built-in strategy')).length,
  ).toBeGreaterThanOrEqual(1);

  await selectCatalogStrategy('custom_momentum', 'Custom Momentum Extension');

  expect(
    (await screen.findAllByText('Custom Momentum Extension')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(
    (await screen.findAllByText('Local extension')).length,
  ).toBeGreaterThanOrEqual(1);
  expect(document.body.textContent).not.toContain('source_type');
  expect(document.body.textContent).not.toContain('is_extension');
});

test('shows a pre-run single-instrument evidence summary before submission', async () => {
  renderBacktestPage({
    results: [],
    strategies: [...strategyCatalog, extensionStrategy],
  });

  await selectCatalogStrategy('custom_momentum', 'Custom Momentum Extension');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
  });

  const summary = within(
    await screen.findByTestId('backtest-run-readiness-summary'),
  );
  expect(summary.getByText('Run readiness summary')).toBeTruthy();
  expect(summary.getByText('Custom Momentum Extension')).toBeTruthy();
  expect(summary.getByText('Local extension')).toBeTruthy();
  expect(summary.getByText('600002')).toBeTruthy();
  expect(summary.getByText('Stock')).toBeTruthy();
  expect(summary.getByText('1 configured parameter')).toBeTruthy();
  expect(
    summary.getByText(
      'Dataset snapshot will be frozen when this backtest runs.',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain('source_type');
  expect(document.body.textContent).not.toContain('is_extension');
});

test('assigns the selected strategy as research-only account context', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await selectCatalogStrategy('bollinger', 'Bollinger Mean Reversion');
  openBacktestDisclosure('backtest-research-governance-disclosure');
  await clickEnabledButton('Set as account research strategy');

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

test('assigns the selected strategy as current-symbol research context', async () => {
  window.history.pushState(
    {},
    '',
    '/backtest?symbol=600002&assetClass=stock&strategy=dual_ma',
  );
  const { fetchMock } = renderBacktestPage({ results: [] });

  await selectCatalogStrategy('bollinger', 'Bollinger Mean Reversion');
  openBacktestDisclosure('backtest-research-governance-disclosure');
  await clickEnabledButton('Set for current symbol');

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([url, init]) => {
        if (!String(url).includes('/api/account-strategy/assignments')) {
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
          payload.scope === 'symbol' &&
          payload.symbol === '600002' &&
          payload.asset_class === 'stock'
        );
      }),
    ).toBe(true);
  });
});

test('shows account-truth gate status in strategy review status', async () => {
  renderBacktestPage({ results: [] });

  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
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

  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
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

  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
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
  await selectCatalogStrategy('bollinger', 'Bollinger Mean Reversion');

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
  await selectCatalogStrategy('custom_momentum', 'Custom Momentum Extension');

  openBacktestDisclosure('backtest-advanced-tools-disclosure');
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
    target: { value: '600002' },
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
  expect(payload.assets).toEqual([{ symbol: '600002', asset_class: 'stock' }]);
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
  openBacktestDisclosure('backtest-promotion-evidence-disclosure');
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
    target: { value: '600002' },
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

  const symbolInput = (await screen.findByLabelText(
    '标的代码',
  )) as HTMLInputElement;
  const assetClassSelect = (await screen.findByLabelText(
    '资产类别',
  )) as HTMLSelectElement;
  const optionLabels = Array.from(assetClassSelect.options).map(
    (option) => option.textContent,
  );

  expect(optionLabels).toEqual(['股票', 'ETF', '基金', '黄金', '债券']);
  expect(optionLabels).not.toContain('stock');
  expect(optionLabels).not.toContain('fund');
  expect(symbolInput.className).toContain('w-full');
  expect(symbolInput.className).toContain('min-w-0');
  expect(symbolInput.closest('label')?.className).toContain('min-w-0');
  expect(assetClassSelect.className).toContain('w-full');
  expect(assetClassSelect.className).toContain('min-w-0');

  fireEvent.change(symbolInput, { target: { value: '019999' } });
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
  expect(payload.assets).toEqual([{ symbol: '019999', asset_class: 'fund' }]);
});

test('uses user-readable chinese copy for the backtest configuration contract', async () => {
  renderBacktestPage({ results: [], locale: 'zh' });

  await screen.findByText('回测配置');
  const pageText = document.body.textContent ?? '';
  expect(pageText).toContain('留空时使用已保存的研究资产池');
  expect(pageText).not.toContain('contract');
  expect(pageText).not.toContain('后端');
});

test('uses user-readable english copy for the backtest configuration interface', async () => {
  renderBacktestPage({ results: [], locale: 'en' });

  await screen.findByText('Backtest configuration');
  const pageText = document.body.textContent ?? '';
  expect(pageText).toContain(
    'leave it blank to use the saved research universe',
  );
  expect(pageText).not.toContain('backend backtest contract');
  expect(pageText).not.toContain('interface boundary');
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
    target: { value: '600002' },
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
  expect(payload.assets).toEqual([{ symbol: '600002', asset_class: 'stock' }]);
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

test('keeps portfolio handoff context visible beside the run evidence chain', async () => {
  window.history.pushState(
    {},
    '',
    '/backtest?symbol=600519&assetClass=stock&strategy=dual_ma&source=portfolio',
  );
  renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);

  const runContext = await screen.findByTestId('backtest-run-context-summary');
  const equityChart = screen.getByRole('heading', {
    name: 'Equity and drawdown',
  });
  expect(
    equityChart.compareDocumentPosition(runContext) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(runContext.textContent).toContain('Run context');
  expect(runContext.textContent).toContain('From holding detail');
  expect(runContext.textContent).toContain('600519');
  expect(runContext.textContent).toContain('Stock');
  expect(runContext.textContent).toContain('Dual Moving Average');
  expect(runContext.textContent).toContain(
    'Research only; no broker order is created.',
  );
  const holdingLink = within(runContext).getByRole('link', {
    name: 'Review holding detail',
  });
  expect(holdingLink.getAttribute('href')).toBe('/portfolio/600519');
});

test('previews research-only strategy signal after a single-symbol backtest', async () => {
  const { fetchMock } = renderBacktestPage({ results: [] });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
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

  expect(await screen.findByText('Strategy signal preview')).toBeTruthy();
  expect(await screen.findByText('Buy candidate')).toBeTruthy();
  expect((await screen.findAllByText('Research only')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText(/sha256:preview-dataset/)).toBeTruthy();
  expect(await screen.findByText('Data quality: OK')).toBeTruthy();
  expect(await screen.findByText('Signal data basis')).toBeTruthy();
  expect(
    await screen.findByText('Dataset snapshot · preview-dataset'),
  ).toBeTruthy();
  expect(await screen.findByText('Reference price ¥29.17')).toBeTruthy();
  expect(await screen.findByText('Review gates')).toBeTruthy();
  expect(await screen.findByText('Data ready')).toBeTruthy();
  expect(await screen.findByText('Risk gate required')).toBeTruthy();
  expect(await screen.findByText('Simulation review waiting')).toBeTruthy();
  expect(await screen.findByText('Next review step')).toBeTruthy();
  expect(
    await screen.findByText('Run the risk preview before simulation review.'),
  ).toBeTruthy();
  fireEvent.change(await screen.findByLabelText('Risk quantity'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Preview risk' }));
  expect(await screen.findByText('Risk preview')).toBeTruthy();
  expect(await screen.findByText('Blocked by risk')).toBeTruthy();
  expect(await screen.findByText('Kill switch enabled')).toBeTruthy();
  expect(await screen.findByText('No order created')).toBeTruthy();
  expect(
    await screen.findByText(
      'Requires risk, account-truth, simulation review, and manual review before any live-like workflow.',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain('buy_candidate');
  expect(document.body.textContent).not.toContain('requires_risk_gate');
  expect(document.body.textContent).not.toContain('account_truth_gate');

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/signal-preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const previewCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/signal-preview'),
  );
  const payload = JSON.parse(String(previewCall?.[1]?.body));
  expect(payload).toMatchObject({
    strategy: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    start_date: '2025-01-02',
    end_date: expect.any(String),
    params: { short_period: 3, long_period: 9 },
  });
  expect(payload.bars).toBeUndefined();
  expect(payload.dataset_snapshot).toBeUndefined();
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/risk-preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const riskCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/risk-preview'),
  );
  const riskPayload = JSON.parse(String(riskCall?.[1]?.body));
  expect(riskPayload).toMatchObject({
    strategy: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    action: 'buy',
    quantity: 100,
    reference_price: 29.17,
    target_weight: '1.0',
    data_quality_status: 'ok',
  });
  expect(riskPayload.order_type).toBeUndefined();
  expect(riskPayload.execution_mode).toBeUndefined();
});

test('previews paper shadow simulation after a passed risk preview', async () => {
  const { fetchMock } = renderBacktestPage({
    results: [],
    riskPreview: passedRiskPreviewResponse,
  });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
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
  fireEvent.submit(
    screen
      .getByRole('button', { name: 'Run backtest' })
      .closest('form') as HTMLFormElement,
  );

  fireEvent.change(await screen.findByLabelText('Risk quantity'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Preview risk' }));
  expect(await screen.findByText('Risk passed')).toBeTruthy();
  expect(await screen.findByText('Approved for manual review')).toBeTruthy();
  expect(await screen.findByText('Simulation review next step')).toBeTruthy();
  expect(
    await screen.findByText(
      'Risk preview passed. Run the simulation review before any manual step.',
    ),
  ).toBeTruthy();

  fireEvent.click(
    screen.getByRole('button', { name: 'Preview simulation review' }),
  );
  expect(await screen.findByText('Simulation review preview')).toBeTruthy();
  expect(await screen.findByText('Simulated fill')).toBeTruthy();
  expect(await screen.findByText('Filled 100 @ ¥29.17')).toBeTruthy();
  expect(await screen.findByText('Estimated fee ¥5.03')).toBeTruthy();
  expect(await screen.findByText('No ledger mutation')).toBeTruthy();

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/paper-shadow-preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const paperShadowCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/paper-shadow-preview'),
  );
  const paperShadowPayload = JSON.parse(String(paperShadowCall?.[1]?.body));
  expect(paperShadowPayload).toMatchObject({
    strategy: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    action: 'buy',
    quantity: 100,
    reference_price: 29.17,
    target_weight: '1.0',
    signal_id: 'preview-run-001:0001:buy_candidate',
    dataset_snapshot_id: 'sha256:preview-dataset',
    risk_preview_passed: true,
    risk_reasons: ['approved'],
  });
  expect(paperShadowPayload.execution_mode).toBeUndefined();
  expect(paperShadowPayload.order_type).toBeUndefined();
});

test('uses Chinese simulation-review wording instead of paper-shadow jargon', async () => {
  renderBacktestPage({
    results: [],
    riskPreview: passedRiskPreviewResponse,
    locale: 'zh',
  });

  await screen.findByText('策略回放');
  fireEvent.change(await screen.findByLabelText('标的代码'), {
    target: { value: '600002' },
  });
  fireEvent.change(await screen.findByLabelText('短期均线周期'), {
    target: { value: '3' },
  });
  fireEvent.change(await screen.findByLabelText('长期均线周期'), {
    target: { value: '9' },
  });
  fireEvent.submit(
    screen
      .getByRole('button', { name: '运行回测' })
      .closest('form') as HTMLFormElement,
  );

  fireEvent.change(await screen.findByLabelText('风控预检数量'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: '预检风控' }));
  expect(await screen.findByText('风控通过')).toBeTruthy();
  expect(await screen.findByText('模拟复核下一步')).toBeTruthy();
  expect(
    await screen.findByText(
      '风控预检已通过。先运行模拟复核，再进入任何人工步骤。',
    ),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: '预览模拟复核' }));
  expect(await screen.findByText('模拟复核预览')).toBeTruthy();
  expect(await screen.findByText('模拟成交')).toBeTruthy();
  expect(await screen.findByText('模拟复核订单')).toBeTruthy();
  expect(await screen.findByText('模拟复核成交')).toBeTruthy();
  expect(await screen.findByText('模拟复核已就绪')).toBeTruthy();
  expect(document.body.textContent).not.toContain('paper/shadow');
});

test('summarizes attribution preview evidence without claiming strategy pnl', async () => {
  const { fetchMock } = renderBacktestPage({
    results: [],
    riskPreview: passedRiskPreviewResponse,
  });

  await screen.findByText('Strategy replay');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
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
  fireEvent.submit(
    screen
      .getByRole('button', { name: 'Run backtest' })
      .closest('form') as HTMLFormElement,
  );

  fireEvent.change(await screen.findByLabelText('Risk quantity'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Preview risk' }));
  expect(await screen.findByText('Risk passed')).toBeTruthy();

  fireEvent.click(
    screen.getByRole('button', { name: 'Preview simulation review' }),
  );
  expect(await screen.findByText('Simulated fill')).toBeTruthy();
  expect(await screen.findByText('Attribution evidence preview')).toBeTruthy();
  expect(await screen.findByText('Ready for review linkage')).toBeTruthy();
  expect(
    await screen.findByText('Preview only, P/L not attributed'),
  ).toBeTruthy();
  expect(
    await screen.findByText('Preview evidence 4 / Production facts 0'),
  ).toBeTruthy();
  expect(await screen.findByText('Review linkage candidate')).toBeTruthy();
  const evidenceChain = within(
    await screen.findByTestId('backtest-attribution-evidence-chain'),
  );
  expect(evidenceChain.getByText('Evidence chain')).toBeTruthy();
  expect(evidenceChain.getByText('Strategy signal')).toBeTruthy();
  expect(evidenceChain.getByText('Dataset snapshot')).toBeTruthy();
  expect(evidenceChain.getByText('Risk gate preview')).toBeTruthy();
  expect(evidenceChain.getByText('Simulation review order')).toBeTruthy();
  expect(evidenceChain.getByText('Simulation review fill')).toBeTruthy();
  expect(await screen.findByText('Holding attribution readiness')).toBeTruthy();
  expect(await screen.findByText('Evidence still incomplete')).toBeTruthy();
  expect(await screen.findByText('Manual review missing')).toBeTruthy();
  expect(
    await screen.findByText(
      'Review the strategy candidate in Decision before this holding can enter attribution review.',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain('manual_review');
  expect(await screen.findAllByText('Manual review required')).not.toHaveLength(
    0,
  );
  expect(await screen.findByText('No order or ledger write')).toBeTruthy();
  expect(
    await screen.findByText('Single-instrument loop readiness'),
  ).toBeTruthy();
  expect(await screen.findByText('Ready for manual review')).toBeTruthy();
  expect(await screen.findByText('Dataset snapshot ready')).toBeTruthy();
  expect(await screen.findByText('Strategy registry ready')).toBeTruthy();
  expect(await screen.findByText('After-cost backtest ready')).toBeTruthy();
  expect(await screen.findByText('Signal preview ready')).toBeTruthy();
  expect(await screen.findByText('Risk gate passed')).toBeTruthy();
  expect(await screen.findByText('Simulation review ready')).toBeTruthy();
  expect(await screen.findByText('Attribution boundary ready')).toBeTruthy();
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review holding attribution',
      })
    ).getAttribute('href'),
  ).toBe('/portfolio/600002#holding-strategy-attribution-boundary');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review dataset snapshot evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-dataset-evidence');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review strategy registry evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-strategy-catalog');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review after-cost backtest evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-after-cost-evidence');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review signal preview evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-signal-review-evidence');
  expect(
    (
      await screen.findByRole('link', { name: 'Review risk gate evidence' })
    ).getAttribute('href'),
  ).toBe('#backtest-signal-review-evidence');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review simulation evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-signal-review-evidence');
  expect(
    (
      await screen.findByRole('link', {
        name: 'Review attribution boundary evidence',
      })
    ).getAttribute('href'),
  ).toBe('#backtest-signal-review-evidence');
  expect(
    await screen.findByText(
      'Signal, risk, and simulation review evidence can be reviewed and linked manually.',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('No linked production fills')).toBeTruthy();
  expect(
    await screen.findByText(
      'Strategy P/L is unavailable until signal, review, order, and fill evidence are linked.',
    ),
  ).toBeTruthy();
  expect(document.body.textContent).not.toContain('signal_preview:');
  expect(document.body.textContent).not.toContain('dataset_snapshot:');
  expect(document.body.textContent).not.toContain('risk_preview:approved');
  expect(document.body.textContent).not.toContain('ready_for_review_linkage');
  expect(document.body.textContent).not.toContain('paper_shadow_order');

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/attribution-preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const attributionCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/attribution-preview'),
  );
  const attributionPayload = JSON.parse(String(attributionCall?.[1]?.body));
  expect(attributionPayload).toMatchObject({
    strategy: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    signal_id: 'preview-run-001:0001:buy_candidate',
    dataset_snapshot_id: 'sha256:preview-dataset',
    risk_preview_passed: true,
    risk_reasons: ['approved'],
    paper_shadow_status: 'simulated',
  });
  expect(attributionPayload.paper_shadow_order.order_id).toBe(
    'paper-shadow-preview:dual_ma:600002:buy:100:29.17',
  );
  expect(attributionPayload.paper_shadow_fill.fill_id).toBe(
    'paper-shadow-preview:dual_ma:600002:buy:100:29.17:fill:1',
  );
  expect(attributionPayload.execution_mode).toBeUndefined();
});

test('renders dataset snapshot metadata for saved reports', async () => {
  renderBacktestPage();

  expect(
    await screen.findByRole('heading', {
      level: 3,
      name: 'Dataset snapshot',
    }),
  ).toBeTruthy();
  const snapshotId = await screen.findByText('sha256:fixture-dataset-snapshot');
  expect(snapshotId.className).toContain('break-all');
  expect(snapshotId.className).not.toContain('truncate');
  const source = await screen.findByText('fixture');
  expect(source.className).toContain('[overflow-wrap:anywhere]');
  expect(source.className).not.toContain('truncate');
  const dateRange = await screen.findByText('2025-01-02 -> 2026-05-15');
  expect(dateRange.className).toContain('[overflow-wrap:anywhere]');
  expect(dateRange.className).not.toContain('truncate');
  expect(
    await within(screen.getByTestId('backtest-dataset-disclosure')).findByText(
      '600519',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('260 rows')).toBeTruthy();
  expect(await screen.findByText('qfq')).toBeTruthy();
});

test('restores gross dividend income, paid cash and receivables from a saved report', async () => {
  const { fetchMock } = renderBacktestPage({
    savedBacktestReport: {
      ...savedReport,
      config: {
        ...savedReport.config,
        corporate_action_mode: 'cash_dividends_gross',
      },
      metrics_json: {
        ...savedReport.metrics_json,
        dataset_snapshot: {
          ...savedReport.metrics_json.dataset_snapshot,
          price_basis: 'unadjusted',
          adjustment_mode: 'none',
        },
        cash_dividend_accounting: {
          schema_version: 'karkinos.backtest_cash_dividends.v1',
          mode: 'cash_dividends_gross',
          gross_income: '150.25',
          cash_paid: '125.00',
          receivable: '25.25',
          taxes_modeled: false,
          coverage_verified: false,
          historical_availability_verified: false,
          ex_date_execution_blocked_count: 2,
          distributions: [],
          limitations: [],
        },
      },
    },
  });
  const accounting = await screen.findByTestId('cash-dividend-accounting');
  expect(
    within(accounting).getByText('Recognized gross dividend income')
      .nextElementSibling?.textContent,
  ).toBe('¥ 150.25');
  expect(
    within(accounting).getByText('Paid into available cash').nextElementSibling
      ?.textContent,
  ).toBe('¥ 125.00');
  expect(
    within(accounting).getByText('Unpaid dividend receivable')
      .nextElementSibling?.textContent,
  ).toBe('¥ 25.25');
  expect(
    within(accounting).getByText(
      /Receivables are included in equity but cannot fund purchases/,
    ),
  ).toBeTruthy();
  expect(
    within(accounting).getByText(
      /Investor tax, payment rounding and bonus shares are omitted/,
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(/Simulated equity includes gross cash dividends/),
  ).toBeTruthy();
  expect(
    screen.queryByText(/Simulated equity return; excludes dividends/),
  ).toBeNull();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
    false,
  );
});

test('separates bound Dataset quality from research admission', async () => {
  renderBacktestPage({
    savedBacktestReport: {
      ...savedReport,
      metrics_json: {
        ...savedReport.metrics_json,
        dataset_snapshot: {
          ...savedReport.metrics_json.dataset_snapshot,
          immutable_dataset_id: 'sha256:bound-dataset',
          available_as_of: '2026-09-17T08:05:00+00:00',
          cross_source_verified: true,
          price_basis: 'unadjusted',
          point_in_time_verified: false,
          research_use: 'exploratory_backtest',
          research_limitations: [
            { code: 'historical_availability_unverified' },
            { code: 'unadjusted_corporate_actions_unmodeled' },
          ],
        },
      },
    },
  });

  expect(
    await screen.findByText('Cross-source verification: passed'),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Exploratory backtest only; not strategy advancement evidence',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      'Unadjusted prices · historical PIT unverified · corporate-action returns excluded',
    ),
  ).toBeTruthy();
});

test('binds AI strategy research to the selected saved canonical report', async () => {
  renderBacktestPage();
  await screen.findByText('sha256:fixture-dataset-snapshot');

  fireEvent.click(
    screen.getByRole('button', { name: 'Open AI strategy research' }),
  );

  const panel = screen
    .getByRole('heading', { name: 'Evidence-bound hypothesis lab' })
    .closest('section');
  expect(panel).toBeTruthy();
  expect(within(panel!).getByText('#1')).toBeTruthy();
  expect(
    within(panel!).getByText('sha256:fixture-dataset-snapshot'),
  ).toBeTruthy();
  expect(within(panel!).getByText('600519')).toBeTruthy();
  expect(
    within(panel!).queryByText('Run and save a backtest first.'),
  ).toBeNull();
});

test('localizes dataset snapshot asset classes in chinese reports', async () => {
  renderBacktestPage({ locale: 'zh' });

  const title = await screen.findByRole('heading', {
    level: 3,
    name: '数据快照',
  });
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

  const strategyDisclosure = await screen.findByTestId(
    'backtest-strategy-evidence-disclosure',
  );
  fireEvent.click(strategyDisclosure.querySelector('summary')!);
  expect(strategyDisclosure.hasAttribute('open')).toBe(true);
  expect(
    within(strategyDisclosure).getByRole('heading', {
      name: 'Strategy snapshot',
    }),
  ).toBeTruthy();
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

  const strategyDisclosure = await screen.findByTestId(
    'backtest-strategy-evidence-disclosure',
  );
  fireEvent.click(strategyDisclosure.querySelector('summary')!);
  expect(strategyDisclosure.hasAttribute('open')).toBe(true);
  expect(
    within(strategyDisclosure).getByRole('heading', { name: '策略快照' }),
  ).toBeTruthy();
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

  const validationDisclosure = await screen.findByTestId(
    'backtest-validation-disclosure',
  );
  fireEvent.click(validationDisclosure.querySelector('summary')!);
  expect(validationDisclosure.hasAttribute('open')).toBe(true);
  expect(
    within(validationDisclosure).getByRole('heading', {
      name: 'Validation evidence',
    }),
  ).toBeTruthy();
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
  openBacktestDisclosure('backtest-advanced-tools-disclosure');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
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
  expect(payload.assets).toEqual([{ symbol: '600002', asset_class: 'stock' }]);
  expect(payload).not.toHaveProperty('dataset_id');
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
  openBacktestDisclosure('backtest-advanced-tools-disclosure');
  fireEvent.change(await screen.findByLabelText('Symbol'), {
    target: { value: '600002' },
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
  expect(payload.assets).toEqual([{ symbol: '600002', asset_class: 'stock' }]);
  expect(payload).not.toHaveProperty('dataset_id');
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

test('keeps sweep and comparison available with one selected Dataset', async () => {
  const datasetId = `sha256:${'c'.repeat(64)}`;
  const { fetchMock } = renderBacktestPage({
    results: [],
    datasets: [
      {
        dataset_id: datasetId,
        start_date: '2025-01-02',
        end_date: '2026-09-18',
        cutoff: '2026-09-19T08:00:00Z',
        instruments: [{ symbol: '600002', instrument_type: 'stock' }],
        partition_count: 2,
        price_basis: 'unadjusted',
        point_in_time_verified: false,
      },
    ],
  });

  await screen.findByText('Strategy replay');
  const datasetDisclosure = screen
    .getByText('Research datasets · persistent snapshots')
    .closest('details') as HTMLDetailsElement;
  datasetDisclosure.open = true;
  fireEvent(datasetDisclosure, new Event('toggle'));
  await screen.findByRole('option', { name: /600002.*2025-01-02/ });
  fireEvent.change(screen.getByLabelText('Data for this backtest'), {
    target: { value: datasetId },
  });
  expect(
    (await screen.findByTestId('selected-dataset-id')).textContent,
  ).toContain(datasetId);
  openBacktestDisclosure('backtest-advanced-tools-disclosure');

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

  for (const path of ['/api/backtest/sweep', '/api/backtest/compare']) {
    const call = fetchMock.mock.calls.find(([url]) =>
      String(url).includes(path),
    );
    const payload = JSON.parse(String(call?.[1]?.body));
    expect(payload.dataset_id).toBe(datasetId);
    expect(payload.assets).toEqual([
      { symbol: '600002', asset_class: 'stock' },
    ]);
    expect(payload.start_date).toBe('2025-01-02');
    expect(payload.end_date).toBe('2026-09-18');
  }

  const runButton = screen.getByRole('button', { name: 'Run backtest' });
  fireEvent.submit(runButton.closest('form') as HTMLFormElement);
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/backtest/signal-preview',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  const previewCall = fetchMock.mock.calls.find(([url]) =>
    String(url).includes('/api/backtest/signal-preview'),
  );
  const previewPayload = JSON.parse(String(previewCall?.[1]?.body));
  expect(previewPayload).toMatchObject({
    dataset_id: datasetId,
    strategy: 'dual_ma',
    symbol: '600002',
    asset_class: 'stock',
    start_date: '2025-01-02',
    end_date: '2026-09-18',
  });
  expect(previewPayload.bars).toBeUndefined();
  expect(previewPayload.dataset_snapshot).toBeUndefined();
});

test.each(['price_only', 'cash_dividends_gross'] as const)(
  'collects corporate-action evidence and runs the newly selected Dataset in %s mode',
  async (mode) => {
    const original = {
      dataset_id: `sha256:${'a'.repeat(64)}`,
      start_date: '2025-01-02',
      end_date: '2026-09-18',
      cutoff: '2026-09-19T08:00:00Z',
      instruments: [{ symbol: '600002', instrument_type: 'stock' }],
      partition_count: 2,
      price_basis: 'unadjusted',
      point_in_time_verified: false,
    };
    const evidence = {
      schema_version: 'karkinos.corporate_action_evidence.v1',
      status: 'observed',
      observation_ids: ['observation-1'],
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
          symbol: '600002',
          instrument_type: 'stock',
          div_proc: '实施',
          end_date: '2025-12-31',
          ann_date: '2026-03-20',
          imp_ann_date: '2026-09-01',
          record_date: '2026-09-14',
          ex_date: '2026-09-15',
          pay_date: '2026-09-21',
          div_listdate: null,
          cash_div_tax: '0.125',
          cash_div: null,
          stk_div: '0',
          stk_bo_rate: '0',
          stk_co_rate: '0',
          available_at: '2026-10-02T08:00:00Z',
          captured_at: '2026-10-02T08:00:00Z',
          source_revision_id: 'cash-revision',
          observation_id: 'observation-1',
        },
      ],
      returns_modeled: false,
      limitations: [],
    };
    const next = {
      ...original,
      dataset_id: `sha256:${'b'.repeat(64)}`,
      cutoff: evidence.available_at,
      corporate_action_evidence: evidence,
    };
    const datasets = [original];
    const { fetchMock } = renderBacktestPage({
      results: [],
      datasets,
      locale: 'zh',
    });
    const defaultFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (input, init) => {
      if (
        String(input).endsWith('/corporate-actions') &&
        init?.method === 'POST'
      ) {
        datasets.push(next);
        return jsonResponse(next);
      }
      if (String(input) === '/api/backtest/run') {
        return jsonResponse({
          ...runReport,
          metrics_json: {
            ...runReport.metrics_json,
            ...(mode === 'cash_dividends_gross'
              ? {
                  cash_dividend_accounting: {
                    schema_version: 'karkinos.backtest_cash_dividends.v1',
                    mode,
                    gross_income: '1250.00',
                    cash_paid: '0',
                    receivable: '1250.00',
                    taxes_modeled: false,
                    coverage_verified: false,
                    historical_availability_verified: false,
                    ex_date_execution_blocked_count: 1,
                    distributions: [
                      {
                        action_id: 'cash-action',
                        symbol: '600002',
                        record_date: '2026-09-14',
                        ex_date: '2026-09-15',
                        pay_date: '2026-09-21',
                        cash_per_share: '0.125',
                        eligible_quantity: '10000',
                        gross_amount: '1250.00',
                        paid: false,
                      },
                    ],
                    limitations: [],
                  },
                }
              : {}),
            dataset_snapshot: {
              ...runReport.metrics_json.dataset_snapshot,
              immutable_dataset_id: next.dataset_id,
              price_basis: 'unadjusted',
              corporate_action_evidence: evidence,
            },
          },
        });
      }
      return defaultFetch(input, init);
    });
    await screen.findByText('策略回放');
    const disclosure = screen
      .getByText('研究 Dataset · 持久保存与离线回测')
      .closest('details')!;
    disclosure.open = true;
    fireEvent(disclosure, new Event('toggle'));
    await screen.findByRole('option', { name: /600002.*2025-01-02/ });
    fireEvent.change(screen.getByLabelText('本次回测的数据输入'), {
      target: { value: original.dataset_id },
    });
    const modeSelector = screen.getByLabelText(
      '公司行动收益处理',
    ) as HTMLSelectElement;
    expect(modeSelector.disabled).toBe(true);
    expect(modeSelector.value).toBe('price_only');
    expect(
      fetchMock.mock.calls.some(([, init]) => init?.method === 'POST'),
    ).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '采集分红送转证据' }));
    await screen.findByText(/分红送转证据已采集，已选中新数据集/);
    expect(
      (screen.getByLabelText('本次回测的数据输入') as HTMLSelectElement).value,
    ).toBe(next.dataset_id);
    expect(screen.getByTestId('selected-dataset-id').textContent).toContain(
      next.dataset_id,
    );
    expect(datasets[0]).toEqual(original);
    expect(modeSelector.disabled).toBe(false);
    expect(modeSelector.value).toBe('price_only');
    fireEvent.change(modeSelector, { target: { value: mode } });
    if (mode === 'cash_dividends_gross') {
      openBacktestDisclosure('backtest-advanced-tools-disclosure');
      for (const name of ['运行参数扫描', '运行对比']) {
        const button = screen.getByRole('button', {
          name,
        }) as HTMLButtonElement;
        expect(button.disabled).toBe(true);
        fireEvent.submit(button.closest('form')!);
      }
      expect(
        fetchMock.mock.calls.some(([url]) =>
          /\/api\/backtest\/(sweep|compare)$/.test(String(url)),
        ),
      ).toBe(false);
      expect(
        screen.getAllByText(/参数扫描与策略对比目前仅支持价格模式/).length,
      ).toBe(2);
    }
    expect(
      fetchMock.mock.calls.some(([url]) => String(url) === '/api/backtest/run'),
    ).toBe(false);

    const runButton = screen.getByRole('button', { name: '运行回测' });
    fireEvent.submit(runButton.closest('form') as HTMLFormElement);
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/backtest/run',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    const runCall = fetchMock.mock.calls.find(
      ([url]) => String(url) === '/api/backtest/run',
    );
    expect(JSON.parse(String(runCall?.[1]?.body)).dataset_id).toBe(
      next.dataset_id,
    );
    expect(JSON.parse(String(runCall?.[1]?.body)).corporate_action_mode).toBe(
      mode,
    );
    await waitFor(() => {
      const panel = document.getElementById('backtest-dataset-evidence')!;
      expect(within(panel).getByText('已采集 · 覆盖未核实')).toBeTruthy();
      if (mode === 'price_only') {
        expect(
          within(panel).getByText(/尚未计入现金派息、送转持仓或总收益/),
        ).toBeTruthy();
      } else {
        expect(
          within(panel).queryByText(/尚未计入现金派息、送转持仓或总收益/),
        ).toBeNull();
        expect(
          within(panel).getAllByText(/已计入税前现金分红/).length,
        ).toBeGreaterThan(0);
      }
    });
    if (mode === 'cash_dividends_gross') {
      const accounting = screen.getByTestId('cash-dividend-accounting');
      expect(
        within(accounting).getByText('已确认税前分红收入').nextElementSibling
          ?.textContent,
      ).toBe('¥ 1250.00');
      expect(
        within(accounting).getByText('已转为可用现金').nextElementSibling
          ?.textContent,
      ).toBe('¥ 0');
      expect(
        within(accounting).getByText('尚未支付的应收分红').nextElementSibling
          ?.textContent,
      ).toBe('¥ 1250.00');
      expect(
        within(accounting).getByText(/应收分红已计入权益，但尚不能用于买入/),
      ).toBeTruthy();
      expect(within(accounting).getByText(/相关交易已阻止 1 次/)).toBeTruthy();
      expect(
        screen.queryByText(
          '模拟权益收益；未计入分红等公司行动，不代表完整经济收益。',
        ),
      ).toBeNull();
      const successfulFetch = fetchMock.getMockImplementation()!;
      fetchMock.mockImplementation(async (input, init) =>
        String(input) === '/api/backtest/run'
          ? jsonResponse(
              { detail: 'cash_dividend_event_dates_incomplete' },
              { status: 422 },
            )
          : successfulFetch(input, init),
      );
      fireEvent.submit(runButton.closest('form')!);
      expect(
        await screen.findByText(
          '分红记录缺少登记日、除息日或派息日，无法核算。',
        ),
      ).toBeTruthy();
      expect(
        screen.queryByText('cash_dividend_event_dates_incomplete'),
      ).toBeNull();
      expect(screen.getByTestId('cash-dividend-accounting')).toBe(accounting);
      fireEvent.change(screen.getByLabelText('本次回测的数据输入'), {
        target: { value: original.dataset_id },
      });
      expect(modeSelector.value).toBe('price_only');
      expect(modeSelector.disabled).toBe(true);
    }
  },
);

test('accepts localized comparison parameter names while submitting API keys', async () => {
  const { fetchMock } = renderBacktestPage({ results: [], locale: 'zh' });

  openBacktestDisclosure('backtest-advanced-tools-disclosure');
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
    target: { value: '600002' },
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
