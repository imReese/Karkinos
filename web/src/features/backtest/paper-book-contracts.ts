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
    corporate_action_mode: 'reported_distributions_gross';
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
