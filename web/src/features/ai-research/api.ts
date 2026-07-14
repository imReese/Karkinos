import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

export type ResearchEvidenceType =
  | 'portfolio'
  | 'account_state'
  | 'operations'
  | 'research_evidence'
  | 'account_truth';

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

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try {
      const payload = JSON.parse(raw) as { detail?: string };
      detail = payload.detail ?? raw;
    } catch {
      // Preserve the plain-text response.
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

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
