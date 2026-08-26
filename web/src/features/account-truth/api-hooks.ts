import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../shared/api/client';
import type {
  ReconciliationStatus,
  ReviewStatus,
  AccountTruthScore,
  AccountTruthEvidenceReadiness,
  EvidenceScopeReviewCommand,
  ImportRun,
  ReconciliationReportSummary,
  ReviewDecision,
  ReconciliationReportDetail,
  BrokerStatementPreview,
  BrokerStatementImportResult,
  CiticHistoryXlsPreview,
  CiticSourceReviewStatus,
  CiticSourceQueryWindowReviewCommand,
  CiticSourceScopeReviewCommand,
  CiticSourceIntake,
  CiticHistoryXlsDirectoryStatus,
  CiticHistoryXlsDirectoryScan,
  BrokerStatementCollectorStatus,
} from './api-contracts';
import { postAccountTruthJson } from './api-request';

export {
  useReviewedFeeScheduleApprovalMutation,
  useReviewedFeeSchedulePreviewMutation,
  useReviewedFeeScheduleReviewQuery,
  useReviewedFeeScheduleRevocationMutation,
} from './fee-schedule-api-hooks';

export function useAccountTruthScoreQuery() {
  return useQuery({
    queryKey: ['account-truth-score'],
    queryFn: () => apiClient<AccountTruthScore>('/api/account-truth/score'),
    staleTime: 10_000,
  });
}

export function useAccountTruthEvidenceReadinessQuery() {
  return useQuery({
    queryKey: ['account-truth-evidence-readiness'],
    queryFn: () =>
      apiClient<AccountTruthEvidenceReadiness>(
        '/api/account-truth/evidence-readiness',
      ),
    staleTime: 10_000,
  });
}

export function useRecordEvidenceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      importRunId: string;
      expectedObservedScopeFingerprint: string;
      provider: string;
      accountAlias: string;
      accountReferenceHash: string;
      coverageStartDate: string;
      coverageEndDate: string;
      assetClasses: string[];
      fullAccountScopeAttested: boolean;
    }) => {
      if (!payload.fullAccountScopeAttested) {
        throw new Error('Account Truth scope attestation is required.');
      }
      return postEvidenceScopeReview(
        '/api/account-truth/evidence-scope/reviews',
        {
          import_run_id: payload.importRunId,
          expected_observed_scope_fingerprint:
            payload.expectedObservedScopeFingerprint,
          provider: payload.provider.trim().toLowerCase(),
          account_alias: payload.accountAlias.trim(),
          account_reference_hash: payload.accountReferenceHash,
          coverage_start_date: payload.coverageStartDate,
          coverage_end_date: payload.coverageEndDate,
          asset_classes: payload.assetClasses,
          full_account_scope_attested: true,
          reviewer: 'local_owner',
        },
      );
    },
    onSuccess: async (response) => {
      queryClient.setQueryData(
        ['account-truth-evidence-readiness'],
        response.readiness,
      );
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-evidence-readiness'],
      });
    },
  });
}

export function useRevokeEvidenceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      importRunId: string;
      expectedObservedScopeFingerprint: string;
    }) =>
      postEvidenceScopeReview(
        '/api/account-truth/evidence-scope/reviews/revoke',
        {
          import_run_id: payload.importRunId,
          expected_observed_scope_fingerprint:
            payload.expectedObservedScopeFingerprint,
          reviewer: 'local_owner',
        },
      ),
    onSuccess: async (response) => {
      queryClient.setQueryData(
        ['account-truth-evidence-readiness'],
        response.readiness,
      );
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-evidence-readiness'],
      });
    },
  });
}

export async function hashAccountTruthAccountReference(
  provider: string,
  accountIdentifier: string,
): Promise<string> {
  const normalizedProvider = provider.trim().toLowerCase();
  const normalizedIdentifier = accountIdentifier.trim();
  if (!normalizedProvider || !normalizedIdentifier) {
    throw new Error('Provider and local account identifier are required.');
  }
  const encoded = new TextEncoder().encode(
    JSON.stringify({
      schema_version: 'karkinos.account_truth.account_reference.v1',
      provider: normalizedProvider,
      account_identifier: normalizedIdentifier,
    }),
  );
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoded);
  const hex = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, '0'),
  ).join('');
  return `sha256:${hex}`;
}

async function postEvidenceScopeReview(
  path: string,
  payload: Record<string, unknown>,
): Promise<EvidenceScopeReviewCommand> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as EvidenceScopeReviewCommand;
}

export function useBrokerStatementCollectorStatusQuery() {
  return useQuery({
    queryKey: ['broker-statement-collector-status'],
    queryFn: () =>
      apiClient<BrokerStatementCollectorStatus>(
        '/api/account-truth/broker-statement/collector',
      ),
    staleTime: 1_000,
    refetchInterval: 5_000,
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
  enabled = true,
) {
  const search = status === 'all' ? '' : `?status=${status}`;
  return useQuery({
    queryKey: ['account-truth-reports', status],
    queryFn: () =>
      apiClient<ReconciliationReportSummary[]>(
        `/api/account-truth/reconciliation-reports${search}`,
      ),
    enabled,
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
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-report-detail', variables.importRunId],
        }),
      ]);
    },
  });
}

export function useBrokerStatementPreviewMutation() {
  return useMutation({
    mutationFn: (payload: { content: string; source_name: string }) =>
      postAccountTruthJson<BrokerStatementPreview>(
        '/api/account-truth/broker-statement/preview',
        payload,
      ),
  });
}

export function useCiticHistoryXlsPreviewMutation() {
  return useMutation({
    mutationFn: async (payload: { content_base64: string }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/preview',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticHistoryXlsPreview;
    },
  });
}

export function useCiticHistoryXlsIntakesQuery() {
  return useQuery({
    queryKey: ['citic-history-xls-intakes'],
    queryFn: () =>
      apiClient<CiticSourceIntake[]>(
        '/api/account-truth/citic-history-xls/intakes?limit=50',
      ),
    staleTime: 10_000,
  });
}

export function useCiticHistoryXlsDirectoryStatusQuery() {
  return useQuery({
    queryKey: ['citic-history-xls-directory-status'],
    queryFn: () =>
      apiClient<CiticHistoryXlsDirectoryStatus>(
        '/api/account-truth/citic-history-xls/directory',
      ),
    staleTime: 60_000,
  });
}

export function useCiticHistoryXlsDirectoryScanMutation() {
  return useMutation({
    mutationFn: async () => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/directory/scan',
        {
          method: 'POST',
          headers: { Accept: 'application/json' },
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticHistoryXlsDirectoryScan;
    },
  });
}

export function useCiticHistoryXlsDirectoryIntakeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      expected_file_fingerprint: string;
      review_status: CiticSourceReviewStatus;
    }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/directory/intakes',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticSourceIntake;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['citic-history-xls-intakes'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
      ]);
    },
  });
}

export function useCiticHistoryXlsIntakeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      content_base64: string;
      expected_file_fingerprint: string;
      review_status: CiticSourceReviewStatus;
    }) => {
      const response = await fetch(
        '/api/account-truth/citic-history-xls/intakes',
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || `Request failed: ${response.status}`);
      }
      return (await response.json()) as CiticSourceIntake;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['citic-history-xls-intakes'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
      ]);
    },
  });
}

type CiticSourceQueryWindowReviewPayload = {
  expected_file_fingerprint: string;
  expected_source_preview_fingerprint: string;
  query_start_date: string;
  query_end_date: string;
  query_window_attested: true;
};

async function invalidateCiticSourceReviewQueries(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: ['citic-history-xls-intakes'],
    }),
    queryClient.invalidateQueries({
      queryKey: ['account-truth-evidence-readiness'],
    }),
    queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
  ]);
}

export function useCiticHistoryXlsQueryWindowReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: CiticSourceQueryWindowReviewPayload & {
        content_base64: string;
      },
    ) =>
      postAccountTruthJson<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/query-window-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsDirectoryQueryWindowReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CiticSourceQueryWindowReviewPayload) =>
      postAccountTruthJson<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/directory/query-window-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsQueryWindowReviewRevokeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      intake_id: string;
      expected_active_review_id: string;
      expected_active_review_fingerprint: string;
    }) =>
      postAccountTruthJson<CiticSourceQueryWindowReviewCommand>(
        '/api/account-truth/citic-history-xls/query-window-reviews/revoke',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

type CiticSourceScopeReviewPayload = {
  intake_id: string;
  expected_file_fingerprint: string;
  expected_source_preview_fingerprint: string;
  expected_query_window_review_id: string;
  expected_query_window_review_fingerprint: string;
  account_alias: string;
  account_reference_hash: string;
  account_type: string;
  market_scopes: string[];
  asset_classes: string[];
  account_value_band: string;
  business_types: string[];
  no_other_filters_attested: true;
  complete_returned_results_attested: true;
  source_scope_attested: true;
};

export function useCiticHistoryXlsSourceScopeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CiticSourceScopeReviewPayload) =>
      postAccountTruthJson<CiticSourceScopeReviewCommand>(
        '/api/account-truth/citic-history-xls/source-scope-reviews',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useCiticHistoryXlsSourceScopeReviewRevokeMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      intake_id: string;
      expected_active_review_id: string;
      expected_active_review_fingerprint: string;
    }) =>
      postAccountTruthJson<CiticSourceScopeReviewCommand>(
        '/api/account-truth/citic-history-xls/source-scope-reviews/revoke',
        payload,
      ),
    onSuccess: () => invalidateCiticSourceReviewQueries(queryClient),
  });
}

export function useBrokerStatementImportMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { content: string; source_name: string }) =>
      postAccountTruthJson<BrokerStatementImportResult>(
        '/api/account-truth/broker-statement/import',
        payload,
      ),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-evidence-readiness'],
        }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-import-runs'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({
          queryKey: [
            'account-truth-report-detail',
            result.import_run.import_run_id,
          ],
        }),
      ]);
    },
  });
}
