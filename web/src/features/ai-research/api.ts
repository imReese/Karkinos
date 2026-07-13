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
