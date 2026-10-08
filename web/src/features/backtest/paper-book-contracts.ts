import type {
  BacktestCostAssumptions,
  BacktestEffectiveCosts,
} from './cost-contracts';

export type PaperPosition = {
  quantity: string;
  frozen_qty: string;
  unlisted_qty: string;
  available_qty: string;
  avg_cost: string;
  realized_pnl: string;
  unrealized_pnl: string;
  commission_paid: string;
  market_value: string;
};

export type PaperState = {
  cash: string;
  equity: string;
  dividend_receivable: string;
  dividend_income: string;
  positions: Record<string, PaperPosition>;
};

export type PaperFill = {
  fill_id: string;
  order_id?: string;
  publication_id: string;
  session: string;
  symbol: string;
  side: string;
  fill_price: string;
  fill_quantity: string;
  commission: string;
  slippage: string;
  timestamp?: string;
  fee_breakdown?: Record<string, unknown> | null;
  fee_rule_id?: string | null;
  fee_rule_version?: string | null;
};

export type PaperAttempt = {
  publication_id: string;
  symbol: string;
  session: string;
  status: string;
  reason: string | null;
  fill_id?: string | null;
};

export type PaperHealthPolicy = {
  mode: 'report_only' | 'pause_on_breach';
  minimum_settled_sessions: number;
  maximum_drawdown: string;
  minimum_net_excess_return: string;
};

export type PaperPerformance = {
  input_version: number;
  outcome_fingerprint: string;
  evaluation_start: string;
  through_session: string | null;
  status: 'waiting' | 'measured';
  settled_sessions: number;
  sessions_since_first_accepted_target: number;
  benchmark_start_session?: string | null;
  waiting_sessions_before_first_target?: number;
  net_return: string;
  max_drawdown: string;
  benchmark_net_return: string | null;
  modeled_net_excess_return: string | null;
  fees_paid: string;
  slippage_cost: string;
  cash_weight: string | null;
  pnl_reconciliation_residual: string;
  return_basis: string;
  position_contributions: {
    symbol: string;
    net_pnl: string;
    return_contribution: string;
    distribution_income: string;
  }[];
  equity_series: {
    session: string | null;
    net_return: string;
    benchmark_net_return: string | null;
  }[];
};

export type PaperHealth = {
  status:
    | 'not_configured'
    | 'unavailable'
    | 'insufficient_evidence'
    | 'threshold_breached'
    | 'within_rule';
  action: string;
  breaches: string[];
  policy?: PaperHealthPolicy;
};

export type ResearchPaperBook = {
  id: string;
  observation_id: string;
  scope: 'independent_paper';
  lifecycle: 'active' | 'paused';
  version: number;
  started_at: string;
  paused_at: string | null;
  evaluation_start: string;
  initial_cash: string;
  policy: {
    cost_assumptions: BacktestEffectiveCosts;
    cost_inputs: Partial<Record<keyof BacktestCostAssumptions, number | null>>;
    corporate_action_mode: 'reported_distributions_gross' | 'price_only';
    health_policy?: PaperHealthPolicy | null;
    currency: 'CNY';
  };
  last_settled_session: string | null;
  state: PaperState;
  steps: {
    session: string;
    settled_at: string;
    dataset_id: string;
    projection: PaperState & {
      session?: string;
      fills: PaperFill[];
      attempts: PaperAttempt[];
      corporate_actions: {
        action_id: string;
        symbol: string;
        eligible_quantity: string;
        accrued: boolean;
        gross_amount: string;
        paid: boolean;
        share_quantity: string;
        shares_listed: boolean;
      }[];
    };
  }[];
  fills: PaperFill[];
  attempts: PaperAttempt[];
  performance?: PaperPerformance;
  health?: PaperHealth;
  limitations: string[];
  account_authority: false;
  automatic: false;
};

export type PaperBookCommand = {
  observationId: string;
} & (
  | {
      kind: 'create';
      payload: {
        request_id: string;
        initial_cash: string;
        cost_assumptions?: BacktestCostAssumptions;
        health_policy?: PaperHealthPolicy;
      };
    }
  | {
      kind: 'settle';
      payload: {
        request_id: string;
        expected_version: number;
        dataset_id: string;
      };
    }
  | {
      kind: 'pause';
      payload: { request_id: string; expected_version: number };
    }
);
