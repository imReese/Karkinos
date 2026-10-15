import type {
  PublicationPolicyBinding,
  PublicationPolicyStatus,
} from '../src/features/ai-research/publication-policy-api';

export const publicationPolicyBinding: PublicationPolicyBinding = {
  allocation_scope: 'account-stock-sleeve',
  strategy_family: 'formula',
  max_initial_cash: '100000',
  account_scope_fingerprint: 'sha256:account',
  deployment_scope_fingerprint: 'sha256:deployment',
  statistical_policy_fingerprint: 'sha256:statistics',
  entry_board_policy: {
    allowed_boards: ['main'],
    excluded_boards: {
      star: 'unsupported_trade_unit',
      chinext: 'permission_disabled_or_unknown',
      beijing: 'permission_disabled_or_unknown',
    },
    permission_evidence_fingerprint: null,
    reviewed_at: null,
    evidence_fingerprint: 'sha256:entry-boards',
  },
  risk_limits: {
    max_drawdown: '0.1',
    max_gross_weight: '1',
    max_symbol_weight: '0.30',
    max_positions: 4,
  },
  max_publications: 1,
  max_final_tests: 1,
  total_error_budget: '0.05',
  statistical_policy: {
    method: 'paired_moving_block_bootstrap.v1',
    minimum_observations: 60,
    block_length: 5,
    minimum_effective_blocks: 12,
    bootstrap_samples: 100000,
    significance_level: '0.05',
    minimum_net_excess: '0.01',
    decision_checkpoint: '2027-06-30',
  },
  min_net_improvement: '0.01',
  cooldown_days: 20,
  incumbent_strategy_id: null,
  expires_at: '2027-07-01T16:00:00+08:00',
};
export const disabledPublicationPolicyStatus: PublicationPolicyStatus = {
  policy: { enabled: false, generation: null },
  status: 'disabled',
  blockers: [],
  preview_blockers: [],
  proposed_binding: publicationPolicyBinding,
  latest_decision: null,
  usable_current_sources: [],
};
