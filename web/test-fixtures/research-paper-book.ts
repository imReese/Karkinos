import type { ResearchPaperBook } from '../src/features/backtest/paper-book-contracts';

// Financial fields copied from test_cash_fill_restart_pause_and_mark_without_shared_account_writes HTTP output.
// Costs explicitly freeze commission rate 0, minimum 5, zero slippage; transfer fee remains 0.25.
export const createdBook: ResearchPaperBook = {
  id: 'ebef6f40-f6ed-52dc-9876-47e8a778ff55',
  observation_id: '138446ff-7d88-5daf-84ac-fc05f9566854',
  scope: 'independent_paper',
  lifecycle: 'active',
  version: 0,
  started_at: '2026-09-18T08:00:00+00:00',
  paused_at: null,
  evaluation_start: '2026-09-21',
  initial_cash: '100000',
  policy: {
    cost_assumptions: {
      bond: {
        commission_rate: '0.00004',
        fee_rule_id: 'cn_bond_exchange_default_v1',
        min_commission: '1',
        other_fee_rate: '0',
      },
      etf: {
        commission_rate: '0.0003',
        fee_rule_id: 'cn_fund_etf_default_v1',
        min_commission: '5',
        other_fee_rate: '0',
        transfer_fee_rate: '0.00001',
      },
      gold: {
        commission_rate: '0.0008',
      },
      limitations: [
        'Research assumptions are not a reviewed broker fee schedule.',
        'Tax and transfer-fee rates use the built-in model, not historical dated schedules.',
        'Fixed proportional slippage does not model market impact or partial fills.',
      ],
      schema_version: 'karkinos.backtest_cost_assumptions.v1',
      slippage_bps: '0.0',
      slippage_model: 'percent_of_reference_price',
      source: 'research_simulation',
      stock: {
        commission_rate: '0.0',
        fee_rule_id: 'cn_stock_research_override_v1',
        min_commission: '5.0',
        other_fee_rate: '0',
        sell_stamp_tax_rate: '0.0005',
        transfer_fee_rate: '0.00001',
      },
    },
    cost_inputs: {
      etf_commission_rate: null,
      etf_min_commission: null,
      slippage_bps: 0.0,
      stock_commission_rate: 0.0,
      stock_min_commission: 5.0,
    },
    corporate_action_mode: 'reported_distributions_gross',
    currency: 'CNY',
  },
  last_settled_session: null,
  state: {
    cash: '100000',
    equity: '100000',
    dividend_receivable: '0',
    dividend_income: '0',
    positions: {},
  },
  steps: [],
  fills: [],
  attempts: [],
  limitations: [
    'Independent simulated cash, positions and fills; no actual account or broker authority.',
    'Daily close fills use the frozen simulation model, not executable venue evidence or liquidity guarantees.',
    'Stock lot, T+1 and 10%/20% price limits are frozen model assumptions; ST and special listing phases are not verified.',
    'Reported corporate actions are modeled gross; source completeness, investor-specific taxes and cash payment rounding remain unverified.',
    'At most 2000 settled sessions and the frozen Dataset row budget are supported; this bounded research book has no rollover or capital authority.',
    'Different corporate-action terms for one symbol and report period are ambiguous and block settlement, including record/ex-date revisions.',
    'Unknown fractional share entitlements and ex-date orders without an official price-limit reference are blocked.',
    'Research assumptions are not a reviewed broker fee schedule.',
    'Tax and transfer-fee rates use the built-in model, not historical dated schedules.',
    'Fixed proportional slippage does not model market impact or partial fills.',
  ],
  account_authority: false,
  automatic: false,
};

export const settledBook: ResearchPaperBook = {
  ...createdBook,
  version: 1,
  last_settled_session: '2026-09-21',
  state: {
    cash: '74994.75',
    equity: '99994.75',
    dividend_receivable: '0',
    dividend_income: '0',
    positions: {
      '600000': {
        available_qty: '0',
        avg_cost: '10.0021',
        commission_paid: '5.25',
        frozen_qty: '2500',
        market_value: '25000',
        quantity: '2500',
        realized_pnl: '0',
        unlisted_qty: '0',
        unrealized_pnl: '-5.25',
      },
    },
  },
  fills: [
    {
      commission: '5.25',
      fee_breakdown: {
        commission: '5',
        fee_rule_id: 'cn_stock_research_override_v1',
        gross_amount: '25000',
        limitations: [
          'transfer_fee_exchange_not_split',
          'broker_regulatory_fees_assumed_absorbed',
        ],
        other_fees: '0',
        stamp_tax: '0',
        total_fee: '5.25',
        transfer_fee: '0.25',
      },
      fee_rule_id: 'cn_stock_research_override_v1',
      fee_rule_version: 'backtest_commission_model',
      fill_id:
        'paper-fill-cc6177f337fc5dfd54ee6ec9b75f4ae806c35c4afc3d1267988ad1bd6bad6dc6',
      fill_price: '10',
      fill_quantity: '2500',
      order_id:
        'paper-order-06b5eb031345bb29052de3af43211d90524c37e8c78779a3e7ed46d8500dc1ba',
      publication_id: 'c041d6df-735a-5e8b-92b6-a333bbaeff66',
      session: '2026-09-21',
      side: 'buy',
      slippage: '0',
      symbol: '600000',
      timestamp: '2026-09-21T15:00:00+08:00',
    },
  ],
  attempts: [
    {
      fill_id:
        'paper-fill-cc6177f337fc5dfd54ee6ec9b75f4ae806c35c4afc3d1267988ad1bd6bad6dc6',
      publication_id: 'c041d6df-735a-5e8b-92b6-a333bbaeff66',
      reason: 'filled',
      session: '2026-09-21',
      status: 'filled',
      symbol: '600000',
    },
  ],
  steps: [
    {
      session: '2026-09-21',
      settled_at: '2026-09-21T08:00:00+00:00',
      dataset_id:
        'sha256:8062efa7ecd1d7fd6260b9b031987a9fb3dc2353a4e9e3b6e418cd62fb604deb',
      projection: {
        attempts: [
          {
            fill_id:
              'paper-fill-cc6177f337fc5dfd54ee6ec9b75f4ae806c35c4afc3d1267988ad1bd6bad6dc6',
            publication_id: 'c041d6df-735a-5e8b-92b6-a333bbaeff66',
            reason: 'filled',
            session: '2026-09-21',
            status: 'filled',
            symbol: '600000',
          },
        ],
        cash: '74994.75',
        corporate_actions: [],
        dividend_income: '0',
        dividend_receivable: '0',
        equity: '99994.75',
        fills: [
          {
            commission: '5.25',
            fee_breakdown: {
              commission: '5',
              fee_rule_id: 'cn_stock_research_override_v1',
              gross_amount: '25000',
              limitations: [
                'transfer_fee_exchange_not_split',
                'broker_regulatory_fees_assumed_absorbed',
              ],
              other_fees: '0',
              stamp_tax: '0',
              total_fee: '5.25',
              transfer_fee: '0.25',
            },
            fee_rule_id: 'cn_stock_research_override_v1',
            fee_rule_version: 'backtest_commission_model',
            fill_id:
              'paper-fill-cc6177f337fc5dfd54ee6ec9b75f4ae806c35c4afc3d1267988ad1bd6bad6dc6',
            fill_price: '10',
            fill_quantity: '2500',
            order_id:
              'paper-order-06b5eb031345bb29052de3af43211d90524c37e8c78779a3e7ed46d8500dc1ba',
            publication_id: 'c041d6df-735a-5e8b-92b6-a333bbaeff66',
            session: '2026-09-21',
            side: 'buy',
            slippage: '0',
            symbol: '600000',
            timestamp: '2026-09-21T15:00:00+08:00',
          },
        ],
        positions: {
          '600000': {
            available_qty: '0',
            avg_cost: '10.0021',
            commission_paid: '5.25',
            frozen_qty: '2500',
            market_value: '25000',
            quantity: '2500',
            realized_pnl: '0',
            unlisted_qty: '0',
            unrealized_pnl: '-5.25',
          },
        },
        session: '2026-09-21',
      },
    },
  ],
};

export const pausedBook: ResearchPaperBook = {
  ...settledBook,
  lifecycle: 'paused',
  version: 2,
  paused_at: '2026-09-21T08:00:00+00:00',
};

export const markedBook: ResearchPaperBook = {
  ...pausedBook,
  version: 3,
  last_settled_session: '2026-09-22',
  state: {
    cash: '74994.75',
    equity: '102494.75',
    dividend_receivable: '0',
    dividend_income: '0',
    positions: {
      '600000': {
        available_qty: '2500',
        avg_cost: '10.0021',
        commission_paid: '5.25',
        frozen_qty: '0',
        market_value: '27500',
        quantity: '2500',
        realized_pnl: '0',
        unlisted_qty: '0',
        unrealized_pnl: '2494.75',
      },
    },
  },
  steps: [
    ...settledBook.steps,
    {
      session: '2026-09-22',
      settled_at: '2026-09-22T08:00:00+00:00',
      dataset_id:
        'sha256:52e312b9ceedffc0f364090a4f6c5f142eab4d99239334470f602310c4cb1e3c',
      projection: {
        attempts: [],
        cash: '74994.75',
        corporate_actions: [],
        dividend_income: '0',
        dividend_receivable: '0',
        equity: '102494.75',
        fills: [],
        positions: {
          '600000': {
            available_qty: '2500',
            avg_cost: '10.0021',
            commission_paid: '5.25',
            frozen_qty: '0',
            market_value: '27500',
            quantity: '2500',
            realized_pnl: '0',
            unlisted_qty: '0',
            unrealized_pnl: '2494.75',
          },
        },
        session: '2026-09-22',
      },
    },
  ],
};
