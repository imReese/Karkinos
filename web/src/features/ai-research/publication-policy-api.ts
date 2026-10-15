import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, postJson, putJson } from '../../shared/api/client';

export type PublicationPolicyBounds = {
  allocation_scope: string;
  strategy_family: 'formula';
  max_initial_cash: string;
  risk_limits: {
    max_drawdown: string;
    max_gross_weight: string;
    max_symbol_weight: string;
    max_positions: number;
  };
  max_publications: number;
  max_final_tests: number;
  total_error_budget: string;
  statistical_policy: {
    method: 'paired_moving_block_bootstrap.v1';
    minimum_observations: number;
    block_length: number;
    minimum_effective_blocks: number;
    bootstrap_samples: number;
    significance_level: string;
    minimum_net_excess: string;
    decision_checkpoint: string;
    checkpoint_interval_days?: number;
  };
  min_net_improvement: string;
  cooldown_days: number;
  incumbent_strategy_id: string | null;
  expires_at: string;
};
export type PublicationPolicyBinding = PublicationPolicyBounds & {
  account_scope_fingerprint: string;
  deployment_scope_fingerprint: string;
  statistical_policy_fingerprint: string;
  entry_board_policy?: {
    allowed_boards: string[];
    excluded_boards: Record<string, string>;
    permission_evidence_fingerprint: string | null;
    reviewed_at: string | null;
    evidence_fingerprint: string;
  };
};
export type PublicationPolicyPreview = {
  proposed_binding: PublicationPolicyBinding | null;
  preview_blockers: string[];
  binding_source?: {
    valuation_snapshot_id?: string;
    [key: string]: unknown;
  } | null;
};
export type PublicationPolicyStatus = PublicationPolicyPreview & {
  policy:
    | (PublicationPolicyBinding & {
        policy_id: string;
        generation: string | null;
        enabled: boolean;
        updated_by?: string;
      })
    | { enabled: false; generation: string | null };
  status: 'disabled' | 'active' | 'expired' | 'invalid';
  blockers: string[];
  latest_decision: {
    status?: string;
    decision_source?: string;
    strategy_id?: string;
    [key: string]: unknown;
  } | null;
  usable_current_sources: Array<{
    strategy_id: string;
    decision_source?: string;
    [key: string]: unknown;
  }>;
};
const path = '/api/ai/strategy-research/automatic-publication-policy';
const key = ['automatic-publication-policy'];
export function usePublicationPolicy() {
  return useQuery({
    queryKey: key,
    queryFn: () => apiClient<PublicationPolicyStatus>(path),
    retry: false,
    refetchInterval: 60_000,
  });
}
export function usePreviewPublicationPolicy() {
  return useMutation({
    mutationFn: (input: PublicationPolicyBounds) =>
      postJson<PublicationPolicyPreview>(`${path}/preview`, {
        allocation_scope: input.allocation_scope,
        strategy_family: input.strategy_family,
        max_initial_cash: input.max_initial_cash,
        risk_limits: input.risk_limits,
        max_publications: input.max_publications,
        max_final_tests: input.max_final_tests,
        total_error_budget: input.total_error_budget,
        statistical_policy: input.statistical_policy,
        min_net_improvement: input.min_net_improvement,
        cooldown_days: input.cooldown_days,
        incumbent_strategy_id: input.incumbent_strategy_id,
        expires_at: input.expires_at,
      }),
    retry: false,
  });
}
export function useWritePublicationPolicy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (
      input: {
        enabled: boolean;
        expected_generation: string | null;
        updated_by: string;
        confirmation: string;
      } & Partial<PublicationPolicyBinding>,
    ) => putJson<PublicationPolicyStatus>(path, input),
    retry: false,
    onSuccess: async (status) => {
      client.setQueryData(key, status);
      await Promise.all([
        client.invalidateQueries({ queryKey: key }),
        client.invalidateQueries({
          queryKey: ['ai-shadow-research-automation'],
        }),
        client.invalidateQueries({ queryKey: ['strategy-promotion-states'] }),
      ]);
    },
  });
}
