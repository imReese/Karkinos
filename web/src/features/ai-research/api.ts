import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson, putJson } from '../../lib/api/client';

export type ResearchEvidenceType =
  | 'portfolio'
  | 'account_state'
  | 'operations'
  | 'research_evidence'
  | 'account_truth'
  | 'strategy_contribution';

export type ResearchTaskEvidence = {
  evidence_reference_id: string;
  tool_name: string;
  status: string;
  authoritative: boolean;
  as_of: string;
  record_fingerprint: string;
};

export type HumanResearchTask = {
  schema_version: string;
  task_id: string;
  capture_id: string;
  context_snapshot_id: string;
  context_fingerprint: string;
  account_alias: string;
  valuation_snapshot_id: string;
  ledger_cutoff_id: number;
  ledger_fingerprint: string;
  created_by: string;
  title: string;
  research_question: string;
  evidence: ResearchTaskEvidence[];
  all_evidence_authoritative: boolean;
  blockers: string[];
  status:
    | 'awaiting_human_review'
    | 'blocked_by_evidence'
    | 'context_accepted'
    | 'context_revision_requested'
    | 'closed_without_analysis';
  created_at: string;
  updated_at: string;
  persisted_facts_only: true;
  provider_fetch_used: false;
  model_execution_enabled: false;
  model_invocation_count: 0;
  workflow_started: false;
  authority_effect: 'none';
  does_not_mutate_financial_state: true;
  reused?: boolean;
};

type HumanResearchTaskList = {
  schema_version: string;
  tasks: HumanResearchTask[];
  model_execution_enabled: false;
  workflow_started: false;
  authority_effect: 'none';
};

type ContextCaptureResponse = {
  capture_id: string;
  capture_status: 'completed';
  context: {
    snapshot_id: string;
    valuation_snapshot_id: string;
    ledger_cutoff_id: number;
    ledger_fingerprint: string;
  };
  model_invocation_count: 0;
  workflow_started: false;
  authority_effect: 'none';
};

export type CreateHumanResearchTaskInput = {
  capture_idempotency_key: string;
  task_idempotency_key: string;
  operator: string;
  account_alias: string;
  title: string;
  research_question: string;
  evidence_types: ResearchEvidenceType[];
  backtest_result_id: number | null;
  strategy_id: string | null;
};

export type ReviewResearchTaskInput = {
  task_id: string;
  idempotency_key: string;
  reviewed_by: string;
  decision:
    | 'context_accepted'
    | 'context_revision_requested'
    | 'closed_without_analysis';
  note: string;
};

export type FixtureAnalysisArtifact = {
  artifact_id: string;
  stage_id: string;
  role_id: string;
  kind: 'claim' | 'debate' | 'report' | 'memory';
  content: Record<string, unknown>;
  evidence_reference_ids: string[];
  fingerprint: string;
  created_at: string;
  authority_effect: 'none';
};

export type ResearchTaskFixtureAnalysis = {
  schema_version: string;
  analysis_id: string;
  task_id: string;
  workflow_id: string;
  workflow_status:
    'pending' | 'running' | 'partial' | 'failed' | 'blocked' | 'completed';
  workflow_failure_code: string | null;
  partial_result: boolean;
  context_snapshot_id: string;
  context_fingerprint: string;
  binding_validity: 'valid' | 'evidence_drift';
  binding_errors: string[];
  memory_validity:
    | 'not_created'
    | 'human_review_required_exact_context_only'
    | 'invalidated_by_evidence_drift';
  artifacts: FixtureAnalysisArtifact[];
  tool_calls: Array<{
    call_id: string;
    run_id: string;
    stage_id: string;
    role_id: string;
    tool_name: string;
    status: string;
    evidence_reference_id: string | null;
    denial_reason: string | null;
  }>;
  audit_replay: {
    valid: boolean;
    event_count: number;
    last_event_hash: string | null;
    errors: string[];
  };
  requested_by: string;
  created_at: string;
  reused: boolean;
  provider_id: string;
  model_id: string;
  fixture_only: true;
  fixture_stage_run_count: number;
  network_io_used: false;
  external_model_invocation_count: 0;
  real_provider_registered: false;
  background_execution_used: false;
  persisted_facts_only: true;
  research_output_is_account_fact: false;
  authority_effect: 'none';
  does_not_mutate_financial_state: true;
};

type ResearchTaskFixtureAnalysisList = {
  schema_version: string;
  analyses: ResearchTaskFixtureAnalysis[];
  fixture_only: true;
  network_io_used: false;
  external_model_invocation_count: 0;
  authority_effect: 'none';
};

export type StartFixtureAnalysisInput = {
  task_id: string;
  idempotency_key: string;
  requested_by: string;
};

export function useResearchTasksQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['ai-research-tasks'],
    queryFn: () =>
      apiClient<HumanResearchTaskList>('/api/ai/research-tasks?limit=20'),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  });
}

export function useCreateHumanResearchTaskMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      input: CreateHumanResearchTaskInput,
    ): Promise<HumanResearchTask> => {
      const capture = await postJson<ContextCaptureResponse>(
        '/api/ai/research-contexts/capture',
        {
          idempotency_key: input.capture_idempotency_key,
          requested_by: input.operator,
          research_question: input.research_question,
          account_alias: input.account_alias,
          evidence_types: input.evidence_types,
          confirmation: 'capture_read_only_research_context',
          backtest_result_id: input.evidence_types.includes('research_evidence')
            ? input.backtest_result_id
            : null,
          strategy_id: input.evidence_types.includes('strategy_contribution')
            ? input.strategy_id
            : null,
        },
      );
      if (capture.capture_status !== 'completed') {
        throw new Error('Context capture did not complete');
      }
      return postJson<HumanResearchTask>('/api/ai/research-tasks', {
        idempotency_key: input.task_idempotency_key,
        capture_id: capture.capture_id,
        created_by: input.operator,
        title: input.title,
        research_question: input.research_question,
        confirmation: 'record_human_research_task_without_model_execution',
      });
    },
    onSuccess: (task) => {
      queryClient.setQueryData<HumanResearchTaskList>(
        ['ai-research-tasks'],
        (current) => ({
          schema_version:
            current?.schema_version ??
            'karkinos.ai.human_research_task_list.v1',
          tasks: [
            task,
            ...(current?.tasks ?? []).filter(
              (currentTask) => currentTask.task_id !== task.task_id,
            ),
          ],
          model_execution_enabled: false,
          workflow_started: false,
          authority_effect: 'none',
        }),
      );
    },
  });
}

export function useReviewResearchTaskMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: ReviewResearchTaskInput) => {
      const result = await postJson<{ task: HumanResearchTask }>(
        `/api/ai/research-tasks/${encodeURIComponent(input.task_id)}/reviews`,
        {
          idempotency_key: input.idempotency_key,
          reviewed_by: input.reviewed_by,
          decision: input.decision,
          note: input.note,
          confirmation: 'record_human_research_review_without_model_execution',
        },
      );
      return result.task;
    },
    onSuccess: (task) => {
      queryClient.setQueryData<HumanResearchTaskList>(
        ['ai-research-tasks'],
        (current) =>
          current
            ? {
                ...current,
                tasks: current.tasks.map((item) =>
                  item.task_id === task.task_id ? task : item,
                ),
              }
            : current,
      );
    },
  });
}

export function useResearchTaskFixtureAnalysesQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['ai-research-task-fixture-analyses'],
    queryFn: () =>
      apiClient<ResearchTaskFixtureAnalysisList>(
        '/api/ai/research-task-analyses?limit=20',
      ),
    enabled,
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  });
}

export function useStartFixtureAnalysisMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: StartFixtureAnalysisInput) =>
      postJson<ResearchTaskFixtureAnalysis>(
        `/api/ai/research-tasks/${encodeURIComponent(input.task_id)}/fixture-analyses`,
        {
          idempotency_key: input.idempotency_key,
          requested_by: input.requested_by,
          confirmation:
            'run_deterministic_fixture_analysis_without_external_model',
        },
      ),
    onSuccess: (analysis) => {
      queryClient.setQueryData<ResearchTaskFixtureAnalysisList>(
        ['ai-research-task-fixture-analyses'],
        (current) => ({
          schema_version:
            current?.schema_version ??
            'karkinos.ai.task_fixture_analysis_list.v1',
          analyses: [
            analysis,
            ...(current?.analyses ?? []).filter(
              (item) => item.analysis_id !== analysis.analysis_id,
            ),
          ],
          fixture_only: true,
          network_io_used: false,
          external_model_invocation_count: 0,
          authority_effect: 'none',
        }),
      );
    },
  });
}

export type AnalysisReviewDecision =
  'accept_as_reviewed_memory' | 'request_revision' | 'reject';

export type ResearchTaskAnalysisReview = {
  schema_version: string;
  review_id: string;
  analysis_id: string;
  task_id: string;
  workflow_id: string;
  decision: AnalysisReviewDecision;
  effective_status:
    | 'reviewed_memory'
    | 'revision_requested'
    | 'rejected'
    | 'invalidated_by_evidence_drift';
  note: string;
  reviewed_by: string;
  created_at: string;
  memory_artifact_id: string | null;
  stored_analysis_target_fingerprint: string;
  current_analysis_target_fingerprint: string;
  analysis_target_binding_valid: boolean;
  analysis_acceptance_eligible: boolean;
  memory_recall_eligible: boolean;
  invalidation_reasons: string[];
  audit_replay: {
    valid: boolean;
    event_count: number;
    last_event_hash: string | null;
    errors: string[];
  };
  reused: boolean;
  fixture_only: true;
  research_memory_only: true;
  persisted_facts_only: true;
  network_io_used: false;
  external_model_invocation_count: 0;
  research_output_is_account_fact: false;
  decision_handoff_enabled: false;
  trade_plan_created: false;
  authority_effect: 'none';
  does_not_mutate_financial_state: true;
};

type ResearchTaskAnalysisReviewList = {
  schema_version: string;
  reviews: ResearchTaskAnalysisReview[];
  fixture_only: true;
  research_memory_only: true;
  network_io_used: false;
  external_model_invocation_count: 0;
  decision_handoff_enabled: false;
  authority_effect: 'none';
};

export type ReviewFixtureAnalysisInput = {
  analysis_id: string;
  idempotency_key: string;
  reviewed_by: string;
  decision: AnalysisReviewDecision;
  note: string;
};

export function useResearchTaskAnalysisReviewsQuery(analysisId: string) {
  return useQuery({
    queryKey: ['ai-research-task-analysis-reviews', analysisId],
    queryFn: () =>
      apiClient<ResearchTaskAnalysisReviewList>(
        `/api/ai/research-task-analysis-reviews?analysis_id=${encodeURIComponent(analysisId)}&limit=20`,
      ),
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  });
}

export function useReviewFixtureAnalysisMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ReviewFixtureAnalysisInput) =>
      postJson<ResearchTaskAnalysisReview>(
        `/api/ai/research-task-analyses/${encodeURIComponent(input.analysis_id)}/reviews`,
        {
          idempotency_key: input.idempotency_key,
          reviewed_by: input.reviewed_by,
          decision: input.decision,
          note: input.note,
          confirmation:
            'record_fixture_analysis_review_without_decision_or_execution_authority',
        },
      ),
    onSuccess: (review) => {
      queryClient.setQueryData<ResearchTaskAnalysisReviewList>(
        ['ai-research-task-analysis-reviews', review.analysis_id],
        (current) => ({
          schema_version:
            current?.schema_version ??
            'karkinos.ai.fixture_analysis_review_list.v1',
          reviews: [
            review,
            ...(current?.reviews ?? []).filter(
              (item) => item.review_id !== review.review_id,
            ),
          ],
          fixture_only: true,
          research_memory_only: true,
          network_io_used: false,
          external_model_invocation_count: 0,
          decision_handoff_enabled: false,
          authority_effect: 'none',
        }),
      );
    },
  });
}

export type StrategyFormulaAst = {
  schema_version: 'karkinos.ai.formula_ast.v1';
  entry: Record<string, unknown>;
  exit: Record<string, unknown>;
  position_size: Record<string, unknown>;
};

export type StrategyHypothesisDraft = {
  schema_version: 'karkinos.ai.strategy_hypothesis_draft.v1';
  draft_id: string;
  workflow_id: string;
  session_id: string;
  context_snapshot_id: string;
  context_fingerprint: string;
  evidence_reference_id: string;
  provider_id: string;
  model_id: string;
  prompt_version: string;
  provider_provenance?: Record<string, unknown>;
  research_question: string;
  economic_hypothesis: string;
  selected_universe: string[];
  universe_fingerprint: string;
  dataset_snapshot_id: string;
  test_window: { start_date: string; end_date: string };
  frequency: string;
  formula_ast: StrategyFormulaAst;
  formula_fingerprint: string | null;
  parameter_values: Record<string, unknown>;
  parameter_ranges: Record<string, unknown>;
  entry_conditions: string;
  exit_conditions: string;
  position_sizing_hypothesis: string;
  portfolio_constraints: Record<string, unknown>;
  cost_model_reference: string;
  required_evidence: string[];
  anti_lookahead_assumptions: string[];
  proposed_deterministic_tests: string[];
  sample_split_plan: string;
  failure_conditions: string[];
  limitations: string[];
  risk_impact: string;
  citations: string[];
  validation: { status: 'valid' | 'blocked'; errors: string[] };
  executable: false;
  requires_human_review: true;
  decision_input_created: false;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type StrategyResearchSession = {
  schema_version: string;
  session_id: string;
  status:
    'pending' | 'running' | 'partial' | 'failed' | 'blocked' | 'completed';
  failure_code: string | null;
  research_question: string;
  selection: {
    saved_backtest_result_id: number;
    universe: string[];
    asset_classes: string[];
    dataset_snapshot_id: string;
    start_date: string;
    end_date: string;
    frequency: string;
    initial_cash: number;
    cost_model_reference: string;
    account_fact_binding: string;
  };
  selection_fingerprint: string;
  context_snapshot_id: string | null;
  context_fingerprint: string | null;
  evidence_reference_id: string | null;
  provider_id: string | null;
  model_id: string | null;
  prompt_version: string;
  binding_validity: 'not_established' | 'valid' | 'invalidated_by_drift';
  binding_errors: string[];
  drafts: StrategyHypothesisDraft[];
  reviews: Array<Record<string, unknown>>;
  reused: boolean;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type StrategyFormulaBacktest = {
  schema_version: string;
  backtest_run_id: string;
  status: 'running' | 'failed' | 'completed';
  failure_code: string | null;
  session_id: string;
  draft_id: string;
  formula_fingerprint: string;
  dataset_snapshot_id: string;
  cost_model_reference: string;
  canonical_backtest: null | {
    result_id: number;
    initial_cash: number;
    final_equity: number;
    total_return: number;
    sharpe: number;
    max_drawdown: number;
    duration_days: number;
    cost_summary: {
      total_commission?: number;
      total_slippage?: number;
      total_trades?: number;
      gross_turnover?: number;
    };
    oos_validation: Record<string, unknown>;
    research_evidence_bundle: Record<string, unknown>;
    dataset_snapshot: Record<string, unknown>;
    formula_binding: Record<string, unknown>;
  };
  reused: boolean;
  research_only: true;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  authority_effect: 'none';
};

export type StrategyBacktestCritique = {
  schema_version: string;
  critique_id: string;
  session_id: string;
  draft_id: string;
  backtest_run_id: string;
  status:
    'pending' | 'running' | 'partial' | 'failed' | 'blocked' | 'completed';
  failure_code: string | null;
  provider_id: string | null;
  model_id: string | null;
  prompt_version: string;
  artifact: null | {
    schema_version: string;
    supported_claims: string[];
    contradicted_claims: string[];
    evidence_gaps: string[];
    cost_turnover_sensitivity: string;
    concentration_risk: string;
    sample_dependence: string;
    possible_overfitting: string;
    recommended_ablations: string[];
    recommended_walk_forward_stress_tests: string[];
    explicit_failure_conditions: string[];
    uncertainty: string;
    citations: string[];
    provider_provenance?: Record<string, unknown>;
    trade_plan_created: false;
    authority_effect: 'none';
  };
  reused: boolean;
  non_authoritative: true;
  non_executable: true;
  requires_human_review: true;
  trade_plan_created: false;
  authority_effect: 'none';
};

export type GenerateStrategyHypothesesInput = {
  idempotency_key: string;
  requested_by: string;
  account_alias: string;
  research_question: string;
  selection: {
    saved_backtest_result_id: number;
    universe: string[];
    asset_classes: string[];
    dataset_snapshot_id: string;
    start_date: string;
    end_date: string;
    frequency: '1d';
    initial_cash: number;
    cost_model_reference: string;
    valuation_snapshot_id: string;
    ledger_cutoff_id: number;
  };
};

export function useGenerateStrategyHypothesesMutation() {
  return useMutation({
    mutationFn: (input: GenerateStrategyHypothesesInput) =>
      postJson<StrategyResearchSession>(
        '/api/ai/strategy-research/hypotheses',
        {
          ...input,
          confirmation:
            'send_selected_sanitized_strategy_research_evidence_to_configured_external_model_without_trade_authority',
        },
      ),
  });
}

export function useRunStrategyFormulaBacktestMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      requested_by: string;
      session_id: string;
      draft_id: string;
    }) =>
      postJson<StrategyFormulaBacktest>('/api/ai/strategy-research/backtests', {
        ...input,
        confirmation:
          'run_selected_validated_formula_with_canonical_backtest_without_trade_authority',
      }),
  });
}

export function useCritiqueStrategyBacktestMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      requested_by: string;
      session_id: string;
      draft_id: string;
      backtest_run_id: string;
    }) =>
      postJson<StrategyBacktestCritique>(
        '/api/ai/strategy-research/critiques',
        {
          ...input,
          confirmation:
            'send_selected_formula_and_canonical_backtest_evidence_to_configured_external_model_without_trade_authority',
        },
      ),
  });
}

export function useReviewStrategyResearchMutation() {
  return useMutation({
    mutationFn: (input: {
      idempotency_key: string;
      session_id: string;
      critique_id: string;
      reviewer: string;
      disposition: 'accepted_for_more_research' | 'rejected' | 'needs_revision';
      notes: string;
    }) =>
      postJson<Record<string, unknown>>(
        `/api/ai/strategy-research/sessions/${encodeURIComponent(input.session_id)}/reviews`,
        {
          idempotency_key: input.idempotency_key,
          reviewer: input.reviewer,
          disposition: input.disposition,
          notes: input.notes,
          confirmation:
            'record_human_strategy_research_review_without_trade_authority',
        },
      ),
  });
}

export type ShadowResearchMetricView = {
  result_id: number;
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  total_cost: number;
  total_commission: number;
  total_slippage: number;
  total_trades: number;
  gross_turnover: number;
  oos_fold_count: number;
  mean_oos_return: number;
  worst_oos_return: number;
  oos_validation_status: string;
  evidence_gate_status: string;
  dataset_snapshot_id: string | null;
};

export type ShadowResearchCandidate = {
  candidate_id: string;
  run_id: string;
  session_id: string;
  draft_id: string;
  backtest_run_id: string | null;
  critique_id: string | null;
  baseline_result_id: number;
  candidate_result_id: number | null;
  status: 'awaiting_human_approval' | 'research_blocked' | 'failed_closed';
  recommendation: 'paper_shadow_review' | 'keep_researching' | 'reject';
  promotion_status:
    | 'awaiting_human_approval'
    | 'blocked_by_evidence'
    | 'paper_shadow_approval_recorded'
    | 'paper_shadow_approved';
  created_at: string;
  updated_at: string;
  comparison: {
    economic_hypothesis?: string;
    risk_impact?: string;
    failure_conditions?: string[];
    limitations?: string[];
    baseline?: ShadowResearchMetricView;
    candidate?: ShadowResearchMetricView;
    deltas?: Record<string, number>;
    deepseek_critique?: {
      supported_claims?: string[];
      contradicted_claims?: string[];
      evidence_gaps?: string[];
      uncertainty?: string;
    };
    iteration_lineage?: {
      iteration_number: number;
      total_iterations: number;
      formula_fingerprint: string;
      parent_candidate_id: string | null;
      parent_draft_id: string | null;
      parent_formula_fingerprint: string | null;
      iteration_context_fingerprint: string;
      sequential_feedback_bound: boolean;
    };
    recommendation?: string;
    promotion_gate: { status: string; blockers: string[] };
  };
  automatic_strategy_replacement_enabled: false;
  production_strategy_mutation_enabled: false;
  broker_submission_enabled: false;
  human_paper_shadow_approval_required: true;
};

export type StrategyPromotionState = {
  strategy_id: string;
  stage: string;
  gate_status: string;
  live_like_enabled: boolean;
};

export type ShadowResearchDailySelection = {
  schema_version: 'karkinos.ai.daily_strategy_selection.v1';
  selection_id: string;
  run_id: string;
  market_date: string;
  status: 'winner_selected' | 'no_selection';
  winner_candidate_id: string | null;
  expected_candidate_count: number;
  observed_candidate_count: number;
  eligible_candidate_count: number;
  blockers: string[];
  selection_scope: 'new_candidate_research_only';
  incumbent_strategy_policy: 'leave_current_human_approved_strategy_unchanged';
  incumbent_strategy_state_changed: false;
  daily_trading_decision_status: 'not_evaluated';
  implies_daily_trading_no_action: false;
  integrity_status: 'verified' | 'fingerprint_mismatch';
};

export type ShadowResearchDailyBackup = {
  schema_version: 'karkinos.ai.daily_strategy_backup_receipt.v1';
  backup_id: string;
  run_id: string;
  market_date: string;
  relative_path: string;
  artifact_fingerprint: string;
  byte_count: number;
  verification_status: string;
  contains_private_account_identifiers: false;
  contains_broker_export_rows: false;
};

export type ShadowResearchAutomationStatus = {
  schema_version: string;
  policy: {
    enabled: boolean;
    after_close_time: string;
    timezone: 'Asia/Shanghai';
    max_provider_calls_per_market_date: number;
    daily_token_budget: number | null;
    token_budget_mode: 'unbounded_daily' | 'legacy_bounded_daily';
    max_candidates_per_run: number;
    baseline_backtest_result_id: number | null;
    require_complete_account_evidence: boolean;
    research_question: string;
    updated_by: string;
    authorization_recorded: boolean;
    automatic_strategy_replacement_enabled: false;
    broker_submission_enabled: false;
    production_strategy_mutation_enabled: false;
    human_paper_shadow_approval_required: true;
  };
  kill_switch: { enabled: boolean; reason: string };
  usage: {
    market_date: string | null;
    provider_calls: number;
    reserved_tokens: number;
    actual_tokens: number;
  };
  runs: Array<{
    run_id: string;
    market_date: string;
    status: string;
    candidate_count: number;
    failure_code: string | null;
  }>;
  candidates: ShadowResearchCandidate[];
  daily_selections: ShadowResearchDailySelection[];
  daily_backups: ShadowResearchDailyBackup[];
  daily_new_candidate_winner_id: string | null;
  /** Compatibility alias; this is a research winner, not a trading decision. */
  daily_winner_candidate_id: string | null;
  research_outcome: {
    status:
      | 'new_candidate_available_for_human_review'
      | 'no_new_candidate_current_strategy_unchanged';
    new_candidate_winner_id: string | null;
    incumbent_strategy_policy: 'leave_current_human_approved_strategy_unchanged';
    incumbent_strategy_state_changed: false;
    daily_trading_decision_status: 'not_evaluated';
    implies_daily_trading_no_action: false;
  };
  automatic_strategy_replacement_enabled: false;
  production_strategy_mutation_enabled: false;
  broker_submission_enabled: false;
  human_paper_shadow_approval_required: true;
  authority_effect: 'research_only';
};

export type ShadowResearchPolicyInput = {
  enabled: boolean;
  after_close_time: string;
  max_provider_calls_per_market_date: number;
  daily_token_budget: null;
  token_budget_mode: 'unbounded_daily';
  max_candidates_per_run: number;
  baseline_backtest_result_id: number | null;
  require_complete_account_evidence: boolean;
  research_question: string;
  updated_by: string;
};

export function useShadowResearchAutomationQuery() {
  return useQuery({
    queryKey: ['ai-shadow-research-automation'],
    queryFn: () =>
      apiClient<ShadowResearchAutomationStatus>(
        '/api/ai/strategy-research/shadow-automation',
      ),
    refetchOnWindowFocus: false,
    refetchInterval: 60_000,
    staleTime: 10_000,
  });
}

export function useStrategyPromotionStatesQuery() {
  return useQuery({
    queryKey: ['strategy-promotion-states'],
    queryFn: () =>
      apiClient<StrategyPromotionState[]>('/api/strategy-promotion/states'),
    refetchOnWindowFocus: false,
    staleTime: 10_000,
  });
}

export function useUpdateShadowResearchPolicyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ShadowResearchPolicyInput) =>
      putJson<ShadowResearchAutomationStatus['policy']>(
        '/api/ai/strategy-research/shadow-automation/policy',
        {
          ...input,
          confirmation: input.enabled
            ? 'authorize_five_sequential_after_close_deepseek_strategy_research_without_daily_token_budget_or_strategy_or_trade_authority'
            : 'pause_after_close_ai_strategy_research_without_changing_trading_authority',
        },
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['ai-shadow-research-automation'],
      }),
  });
}

export function useRunShadowResearchMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<ShadowResearchAutomationStatus>(
        '/api/ai/strategy-research/shadow-automation/run',
        {},
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['ai-shadow-research-automation'],
      }),
  });
}

export function useApproveShadowResearchCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      candidate_id: string;
      approved_by: string;
      notes: string;
    }) =>
      postJson<Record<string, unknown>>(
        `/api/ai/strategy-research/shadow-candidates/${encodeURIComponent(input.candidate_id)}/paper-shadow-approvals`,
        {
          approved_by: input.approved_by,
          notes: input.notes,
          confirmation:
            'approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority',
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['ai-shadow-research-automation'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['strategy-promotion-states'],
        }),
      ]);
    },
  });
}

export function usePauseShadowResearchCandidateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      candidate_id: string;
      actor: string;
      reason: string;
    }) =>
      postJson<StrategyPromotionState>(
        `/api/strategy-promotion/${encodeURIComponent(`ai_formula_shadow:${input.candidate_id}`)}/lifecycle`,
        {
          target_stage: 'paused',
          reason: input.reason,
          actor: input.actor,
          confirmation:
            'pause_or_retire_strategy_without_execution_or_capital_authority',
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['ai-shadow-research-automation'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['strategy-promotion-states'],
        }),
      ]);
    },
  });
}
