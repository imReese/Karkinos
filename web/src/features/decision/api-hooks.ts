import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';
import type {
  ActionCard,
  BatchPreTradeRiskResult,
  DailyTradingPlanResponse,
  DecisionOutcomeReviewResult,
  DecisionOutcomeReviewTarget,
  DecisionQualityCaptureResult,
  DecisionQualityView,
  DecisionResponse,
  SignalJournalEntry,
} from './api-contracts';

const DECISION_REFETCH_MS = 15_000;

function liveRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return DECISION_REFETCH_MS;
}

function decisionQuery(path: string, key: readonly string[], enabled = true) {
  return useQuery({
    queryKey: key,
    queryFn: () => apiClient<DecisionResponse>(path),
    staleTime: 5_000,
    enabled,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useTodayDecisionQuery(enabled = true) {
  return decisionQuery('/api/decision/today', ['decision', 'today'], enabled);
}

export function useIntradayDecisionQuery(enabled = true) {
  return decisionQuery(
    '/api/decision/intraday',
    ['decision', 'intraday'],
    enabled,
  );
}

export function useDecisionQualityQuery() {
  return useQuery({
    queryKey: ['decision', 'quality'],
    queryFn: () => apiClient<DecisionQualityView>('/api/decision/quality'),
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useCaptureDecisionQualityMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      idempotency_key: string;
      captured_by: string;
      expected_target_fingerprint: string;
    }) =>
      postJson<DecisionQualityCaptureResult>('/api/decision/quality/capture', {
        ...payload,
        confirmation:
          'capture_decision_quality_evidence_without_financial_or_trading_authority',
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['decision', 'quality'],
      });
    },
  });
}

export function useDailyTradingPlanQuery(enabled = true) {
  return useQuery({
    queryKey: ['decision', 'trading-plan'],
    queryFn: () =>
      apiClient<DailyTradingPlanResponse>('/api/decision/trading-plan'),
    staleTime: 5_000,
    enabled,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useBatchPreTradeRiskMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<BatchPreTradeRiskResult>(
        '/api/decision/pre-trade-risk/batch',
        {},
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['decision', 'today'] }),
        queryClient.invalidateQueries({
          queryKey: ['decision', 'trading-plan'],
        }),
        queryClient.invalidateQueries({ queryKey: ['signal-actions'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['trading-manual-orders'] }),
      ]);
    },
  });
}

export function useSignalActionsQuery(enabled = true) {
  return useQuery({
    queryKey: ['signal-actions'],
    queryFn: () => apiClient<ActionCard[]>('/api/signals/actions'),
    enabled,
    staleTime: 5_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useSignalJournalQuery(enabled = true) {
  return useQuery({
    queryKey: ['signal-journal'],
    queryFn: () => apiClient<SignalJournalEntry[]>('/api/signals/journal'),
    enabled,
    staleTime: 10_000,
    refetchInterval: liveRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useDecisionOutcomeReviewPreviewMutation() {
  return useMutation({
    mutationFn: (signalId: number) =>
      postJson<DecisionOutcomeReviewTarget>(
        `/api/signals/journal/${signalId}/review/preview`,
        {},
      ),
  });
}

export function useRecordDecisionOutcomeReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      signalId: number;
      idempotency_key: string;
      reviewed_by: string;
      user_decision: 'acted' | 'ignored' | 'deferred' | 'blocked';
      outcome:
        | 'evidence_supported'
        | 'evidence_not_supported'
        | 'risk_gate_validated'
        | 'not_executed'
        | 'inconclusive';
      note: string;
      expected_target_fingerprint: string;
    }) =>
      postJson<DecisionOutcomeReviewResult>(
        `/api/signals/journal/${payload.signalId}/review`,
        {
          idempotency_key: payload.idempotency_key,
          reviewed_by: payload.reviewed_by,
          user_decision: payload.user_decision,
          outcome: payload.outcome,
          note: payload.note,
          expected_target_fingerprint: payload.expected_target_fingerprint,
          confirmation:
            'record_evidence_bound_decision_review_without_trade_or_capital_authority',
        },
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['signal-journal'] });
    },
  });
}

export function useCreateManualOrderFromActionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      actionId: number;
      quantity: number;
      price?: number | null;
      order_type?: string;
      note?: string;
    }) =>
      postJson(`/api/trading/actions/${payload.actionId}/manual-order`, {
        quantity: payload.quantity,
        price: payload.price ?? null,
        order_type: payload.order_type ?? 'market',
        note: payload.note ?? 'Prepared from Decision action queue.',
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['signal-actions'] }),
        queryClient.invalidateQueries({ queryKey: ['signal-journal'] }),
        queryClient.invalidateQueries({
          queryKey: ['decision', 'trading-plan'],
        }),
        queryClient.invalidateQueries({ queryKey: ['trading-manual-orders'] }),
      ]);
    },
  });
}
