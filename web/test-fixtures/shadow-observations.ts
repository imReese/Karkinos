import type {
  ShadowResearchAutomationStatus,
  ShadowResearchCandidate,
} from '../src/features/ai-research/shadow-research-api';
import type { ResearchObservation } from '../src/features/backtest/observation-contracts';

export const normalizedCandidate: ShadowResearchCandidate = {
  candidate_id: 'normalized-candidate',
  run_id: 'normalized-run',
  session_id: 'synthetic-session',
  draft_id: 'synthetic-formula',
  backtest_run_id: 'synthetic-backtest',
  critique_id: null,
  baseline_result_id: 7,
  candidate_result_id: 8,
  status: 'evaluated_research_only',
  recommendation: 'formula_research_candidate',
  promotion_status: 'account_qualification_required',
  created_at: '2026-09-16T08:00:00Z',
  updated_at: '2026-09-16T08:00:00Z',
  comparison: {
    economic_hypothesis: 'Synthetic normalized trend candidate',
    research_capital_mode: 'normalized_notional',
    promotion_gate: {
      status: 'blocked',
      blockers: ['independent_final_missing'],
    },
  },
  automatic_strategy_replacement_enabled: false,
  production_strategy_mutation_enabled: false,
  broker_submission_enabled: false,
  human_paper_shadow_approval_required: true,
};

export function savedObservation(
  id = 'saved-observation',
  sourceResultId = 8,
): ResearchObservation {
  return {
    id,
    source_backtest_result_id: sourceResultId,
    lifecycle: 'paused',
    version: 2,
    started_at: '2026-09-18T08:00:00Z',
    last_blocker: { code: 'observation_health_rule_paused' },
    source: {
      strategy_kind: 'formula',
      start_date: '2026-09-01',
      dataset_id: `sha256:${'a'.repeat(64)}`,
      source_code_verified: false,
      source_historical_pit_verified: false,
    },
    universe: [{ symbol: '600000', instrument_type: 'stock' }],
    policy: {
      horizon_sessions: 1,
      max_symbol_weight: '0.25',
      max_gross_weight: '1',
      health_policy: {
        mode: 'pause_on_breach',
        window_intervals: 1,
        minimum_eligible_intervals: 1,
        minimum_mean_relative_price_response: '-0.02',
      },
    },
    health_decision: {
      policy_id: 'karkinos.research.forward_price_health.v1',
      status: 'threshold_breached',
      action: 'pause_observation',
      evaluated_at: '2026-09-22T08:01:00Z',
      market_as_of: '2026-09-22',
      data_available: true,
      counts: {
        scheduled_matured: 1,
        pending: 0,
        missing_matured: 0,
        zero_exposure: 0,
        corporate_action_excluded: 0,
        unresolved: 0,
        eligible: 1,
      },
      mean_relative_price_response: '-0.03',
      threshold: '-0.02',
      selected_publication_ids: [`${id}-publication`],
      input_fingerprint: 'synthetic-input',
      blockers: [],
      limitations: ['Unadjusted prices exclude dividends and costs.'],
      return_basis: 'unadjusted_price_only',
    },
    publications: [
      {
        id: `${id}-publication`,
        decision_session: '2026-09-18',
        published_at: '2026-09-18T08:01:00Z',
        dataset_id: 'synthetic-publication-dataset',
        payload: {
          forecasts: [
            { symbol: '600000', instrument_type: 'stock', action: 'enter' },
          ],
          previous_target_weights: { '600000': '0' },
          target_weights: { '600000': '0.25' },
          rebalance_weight_deltas: { '600000': '0.25' },
          risk_decision: { status: 'allowed', reasons: [] },
          reference_session: '2026-09-21',
          end_session: '2026-09-22',
          horizon_sessions: 1,
        },
      },
    ],
    outcomes: [
      {
        publication_id: `${id}-publication`,
        horizon: 1,
        measured_at: '2026-09-22T08:01:00Z',
        dataset_id: 'synthetic-outcome-dataset',
        payload: {
          status: 'measured',
          weighted_price_response: '0.01',
          return_basis: 'unadjusted_price_only',
          observations: [
            {
              symbol: '600000',
              target_weight: '0.25',
              price_return: '0.04',
              weighted_price_response: '0.01',
            },
          ],
        },
      },
    ],
  };
}

export function researchStatus(
  qualified = false,
): ShadowResearchAutomationStatus {
  return {
    schema_version: 'karkinos.ai.shadow_research_automation.v1',
    policy: {
      schema_version: 'karkinos.ai.shadow_research_policy.v4',
      policy_id: 'ai_shadow_research',
      enabled: false,
      after_close_time: '15:30',
      timezone: 'Asia/Shanghai',
      provider_call_window_schema: 'karkinos.ai.provider_call_window.v1',
      provider_call_window_policy_id: 'synthetic-policy',
      provider_call_window_policy_fingerprint: 'synthetic-policy-fingerprint',
      max_provider_calls_per_market_date: 10,
      daily_token_budget: null,
      token_budget_mode: 'unbounded_daily',
      max_candidates_per_run: 5,
      baseline_backtest_result_id: null,
      research_capital_mode: 'normalized_notional',
      require_complete_account_evidence: false,
      promotion_requires_complete_account_evidence: true,
      research_question: 'Synthetic local review fixture',
      updated_by: 'human:fixture',
      authorization_recorded: true,
      automatic_strategy_replacement_enabled: false,
      broker_submission_enabled: false,
      production_strategy_mutation_enabled: false,
      human_paper_shadow_approval_required: true,
    },
    kill_switch: { enabled: false, reason: '' },
    usage: {
      market_date: '2026-09-16',
      provider_calls: 0,
      reserved_tokens: 0,
      actual_tokens: 0,
    },
    runs: [
      {
        run_id: 'normalized-run',
        market_date: '2026-09-16',
        status: 'completed',
        candidate_count: 1,
        failure_code: null,
      },
    ],
    candidates: [structuredClone(normalizedCandidate)],
    daily_selections: [],
    daily_backups: [],
    qualification_runs: [
      {
        schema_version: 'karkinos.ai.shadow_research_account_qualification.v1',
        qualification_run_id: 'qualification-run',
        source_run_id: 'normalized-run',
        market_date: '2026-09-16',
        source_selection_id: 'synthetic-selection',
        status: qualified ? 'completed' : 'blocked',
        selection_status: qualified ? 'winner_selected' : 'no_selection',
        winner_qualification_candidate_id: qualified
          ? 'qualification-winner'
          : null,
        blockers: qualified
          ? []
          : ['qualification_valuation_or_ledger_not_complete'],
        failure_code: null,
        created_at: '2026-09-16T09:00:00Z',
        updated_at: '2026-09-16T09:00:00Z',
      },
    ],
    qualification_candidates: qualified
      ? [
          {
            schema_version:
              'karkinos.ai.shadow_research_account_qualification.v1',
            qualification_candidate_id: 'qualification-winner',
            qualification_run_id: 'qualification-run',
            source_candidate_id: 'normalized-candidate',
            source_draft_id: 'synthetic-formula',
            source_formula_fingerprint: 'synthetic-source-formula',
            qualified_formula_fingerprint: 'synthetic-qualified-formula',
            status: 'qualified',
            recommendation: 'paper_shadow_review',
            rank: 1,
            created_at: '2026-09-16T09:00:00Z',
          },
        ]
      : [],
    qualification_approvals: [],
    latest_qualification_attempt: null,
    daily_new_candidate_winner_id: null,
    daily_winner_candidate_id: null,
    daily_research_winner_candidate_id: null,
    research_outcome: {
      status: 'best_available_formula_for_further_research',
      new_candidate_winner_id: null,
      account_qualification_status: qualified ? 'passed' : 'blocked',
      qualification_run_id: 'qualification-run',
      winner_qualification_candidate_id: qualified
        ? 'qualification-winner'
        : null,
      incumbent_strategy_policy:
        'leave_current_human_approved_strategy_unchanged',
      incumbent_strategy_state_changed: false,
      daily_trading_decision_status: 'not_evaluated',
      implies_daily_trading_no_action: false,
    },
    automatic_strategy_replacement_enabled: false,
    production_strategy_mutation_enabled: false,
    broker_submission_enabled: false,
    human_paper_shadow_approval_required: true,
    authority_effect: 'research_only',
  };
}
