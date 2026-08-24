import { useMutation, useQueryClient } from '@tanstack/react-query';

export type PaperShadowCostSummary = {
  estimated_total_fee?: number | string | null;
  simulated_fee_tax_cost?: number | string | null;
  simulated_slippage_cost?: number | string | null;
  simulated_total_execution_cost?: number | string | null;
  fee_rule_ids?: string[];
  fill_count_with_cost_evidence?: number;
};

export type PaperShadowExpectedStrategyBehavior = {
  source_decision?: string | null;
  expected_order_count?: number | null;
  symbols?: string[];
  side_counts?: Record<string, number>;
  strategy_refs?: string[];
  risk_refs?: string[];
  signal_refs?: string[];
  risk_gate_status_counts?: Record<string, number>;
  manual_confirmation_status_counts?: Record<string, number>;
  submission_status_counts?: Record<string, number>;
};

export type PaperShadowExecutionComparison = {
  matched_order_count?: number | null;
  missing_order_intent_refs?: string[];
  diverged_order_refs?: string[];
  failed_order_refs?: string[];
  simulated_status_counts?: Record<string, number>;
  fill_count_by_order?: Record<string, number>;
  filled_quantity_by_order?: Record<string, number | string>;
  remaining_quantity_by_order?: Record<string, number | string>;
};

export type PaperShadowMarketSymbolContext = {
  symbol?: string | null;
  expected_price?: number | string | null;
  price_basis?: string | null;
  simulated_fill_prices?: Array<number | string>;
  simulated_slippage_cost?: number | string | null;
};

export type PaperShadowRealizedMarketContext = {
  symbol_count?: number | null;
  price_basis_counts?: Record<string, number>;
  symbols?: PaperShadowMarketSymbolContext[];
};

export type PaperShadowDivergenceSummary = {
  status?: string;
  expected_strategy_behavior?: PaperShadowExpectedStrategyBehavior;
  execution_comparison?: PaperShadowExecutionComparison;
  realized_market_context?: PaperShadowRealizedMarketContext;
  cost_summary?: PaperShadowCostSummary;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
  [key: string]: unknown;
};

export type PaperShadowReviewQueueItem = {
  review_id: string;
  order_intent_ref?: string | null;
  order_id?: string | null;
  symbol?: string | null;
  status: string;
  divergence_status: string;
  severity: 'info' | 'warning' | 'danger' | string;
  required_action: string;
  reason: string;
  filled_quantity?: string | number | null;
  remaining_quantity?: string | number | null;
  strategy_refs?: string[];
  risk_refs?: string[];
  signal_refs?: string[];
  evidence_refs?: string[];
  account_truth?: {
    gate_status?: string | null;
    has_evidence?: boolean;
    blocking_reasons?: string[];
  };
  risk_gate_status?: string | null;
  manual_confirmation_status?: string | null;
  submission_status?: string | null;
  cash_status?: string | null;
  constraint_status_counts?: Record<string, number>;
  cost_evidence?: {
    estimated_gross_amount?: string | number | null;
    estimated_total_fee?: string | number | null;
    simulated_fee_tax_cost?: string | number | null;
    simulated_slippage_cost?: string | number | null;
    fee_rule_id?: string | null;
  };
  market_context?: {
    price_basis?: string | null;
    expected_price?: string | number | null;
    simulated_fill_prices?: Array<string | number>;
  };
  terminal_status?: string | null;
  terminal_reason?: string | null;
  terminal_oms_transition_ref?: string | null;
  oms_status_path?: string[];
  oms_transition_refs?: string[];
  oms_transitions?: Array<{
    sequence?: string | number | null;
    from_status?: string | null;
    to_status?: string | null;
    source?: string | null;
    reason?: string | null;
    filled_quantity?: string | number | null;
    does_not_submit_broker_order?: boolean;
    does_not_mutate_production_ledger?: boolean;
  }>;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export type PaperShadowManualHandoff = {
  ready: boolean;
  status: string;
  blockers?: string[];
  required_actions?: string[];
  review_queue_count?: number;
  highest_severity?: string | null;
  review_status?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export type PaperShadowRunResponse = {
  run_id: string;
  status: string;
  input_fingerprint?: string;
  input_snapshot?: Record<string, unknown>;
  order_intent_count: number;
  simulated_order_count: number;
  simulated_fill_count: number;
  divergence_status: string;
  next_manual_review_step: string;
  limitations: string[];
  review_queue?: PaperShadowReviewQueueItem[];
  does_not_submit_broker_order: boolean;
  does_not_mutate_production_ledger: boolean;
};

export type PaperShadowRunReviewResponse = {
  run_id: string;
  status: string;
  divergence_status: string;
  review_status?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  next_manual_review_step: string;
  does_not_submit_broker_order?: boolean;
  does_not_mutate_production_ledger?: boolean;
};

export function useRunPaperShadowMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const response = await fetch('/api/operations/paper-shadow/run', {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as PaperShadowRunResponse;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['operations', 'today'],
      });
    },
  });
}

export function useReviewPaperShadowRunMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ runId }: { runId: string }) => {
      const response = await fetch(
        `/api/operations/paper-shadow/runs/${encodeURIComponent(runId)}/review`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            reviewed_at: new Date().toISOString(),
            review_status: 'accepted_for_manual_confirmation',
            review_notes:
              'Operator accepted simulation evidence from the Trading review panel.',
            reviewer: 'web',
          }),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as PaperShadowRunReviewResponse;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['trading-order-facts'] }),
      ]);
    },
  });
}
