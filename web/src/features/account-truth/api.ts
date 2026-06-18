import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

export type AccountTruthGateStatus = 'pass' | 'degraded' | 'blocked';
export type ReconciliationStatus = 'pass' | 'warning' | 'mismatch' | 'blocked';
export type ReviewStatus =
  | 'accepted'
  | 'ignored'
  | 'known_difference'
  | 'ledger_candidate'
  | 'needs_investigation';

export type AccountTruthScore = {
  schema_version: string;
  status: 'available' | 'missing';
  import_run_id: string | null;
  score: number | null;
  gate_status: AccountTruthGateStatus;
  cash_status: string;
  position_status: string;
  fee_status: string;
  cost_basis_status: string;
  data_freshness_status: string;
  unresolved_mismatch_count: number | null;
  resolved_review_count: number;
  required_actions: string[];
  blocking_reasons: string[];
  limitations: string[];
  source_type?: string;
  source_name?: string;
  created_at?: string;
};

export type ImportRun = {
  import_run_id: string;
  schema_version: string;
  source_type: string;
  source_name: string;
  file_fingerprint: string;
  row_count: number;
  valid_row_count: number;
  invalid_row_count: number;
  row_duplicate_count: number;
  file_duplicate_count: number;
  validation_status: string;
  limitations: string[];
  duplicate_of_import_run_id: string | null;
  created_at: string;
};

export type ReconciliationReportSummary = {
  import_run_id: string;
  schema_version: string;
  status: ReconciliationStatus;
  row_count: number;
  validation_status: string;
  source_type: string;
  source_name: string;
  created_at: string;
  unresolved_count: number;
  cash_difference: string;
  fee_difference: string;
  tax_difference: string;
  suggested_review_actions: string[];
  limitations: string[];
};

export type ReviewDecision = {
  id: number;
  import_run_id: string;
  item_key: string;
  category: string;
  symbol: string;
  review_status: ReviewStatus;
  note: string;
  reviewer: string;
  schema_version: string;
  created_at: string;
  updated_at: string;
  does_not_mutate_production_ledger: boolean;
};

export type ReconciliationItem = {
  item_key: string;
  category: string;
  status: ReconciliationStatus;
  severity: string;
  symbol: string;
  broker_value: string;
  karkinos_value: string;
  difference: string;
  suggested_review_action: string;
  detail: string;
  evidence_references: string[];
  latest_review: ReviewDecision | null;
};

export type ReconciliationReportDetail = ReconciliationReportSummary & {
  items: ReconciliationItem[];
};

export function useAccountTruthScoreQuery() {
  return useQuery({
    queryKey: ['account-truth-score'],
    queryFn: () => apiClient<AccountTruthScore>('/api/account-truth/score'),
    staleTime: 10_000,
  });
}

export function useAccountTruthImportRunsQuery() {
  return useQuery({
    queryKey: ['account-truth-import-runs'],
    queryFn: () =>
      apiClient<ImportRun[]>('/api/account-truth/import-runs?limit=50'),
    staleTime: 10_000,
  });
}

export function useReconciliationReportsQuery(
  status: ReconciliationStatus | 'all',
) {
  const search = status === 'all' ? '' : `?status=${status}`;
  return useQuery({
    queryKey: ['account-truth-reports', status],
    queryFn: () =>
      apiClient<ReconciliationReportSummary[]>(
        `/api/account-truth/reconciliation-reports${search}`,
      ),
    staleTime: 10_000,
  });
}

export function useReconciliationReportDetailQuery(importRunId: string | null) {
  return useQuery({
    queryKey: ['account-truth-report-detail', importRunId],
    queryFn: () =>
      apiClient<ReconciliationReportDetail>(
        `/api/account-truth/reconciliation-reports/${encodeURIComponent(
          importRunId ?? '',
        )}`,
      ),
    enabled: Boolean(importRunId),
    staleTime: 5_000,
  });
}

export function useRecordReviewDecisionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      importRunId: string;
      itemKey: string;
      category: string;
      symbol: string;
      review_status: ReviewStatus;
    }) => {
      const response = await fetch(
        `/api/account-truth/reconciliation-reports/${encodeURIComponent(
          payload.importRunId,
        )}/items/${encodeURIComponent(payload.itemKey)}/review`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            category: payload.category,
            symbol: payload.symbol,
            review_status: payload.review_status,
            note: 'Reviewed from Account Truth center.',
            reviewer: 'local',
          }),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as ReviewDecision;
    },
    onSuccess: async (_decision, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-report-detail', variables.importRunId],
        }),
      ]);
    },
  });
}
