import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../shared/api/client';
import type {
  BacktestAttributionPreviewRequest,
  BacktestAttributionPreviewResponse,
  BacktestCompareRequest,
  BacktestCompareResponse,
  BacktestPaperShadowPreviewRequest,
  BacktestPaperShadowPreviewResponse,
  BacktestReport,
  BacktestRiskPreviewRequest,
  BacktestRiskPreviewResponse,
  BacktestRunRequest,
  BacktestStrategyInfo,
  BacktestSummary,
  BacktestSweepRequest,
  BacktestSweepResponse,
  StrategyLearningReviewQueue,
  StrategyPromotionReadiness,
  StrategySignalPreviewRequest,
  StrategySignalPreviewResponse,
  StrategyValidationMatrix,
} from './api-contracts';

export function useBacktestResultsQuery() {
  return useQuery({
    queryKey: ['backtest-results'],
    queryFn: () => apiClient<BacktestSummary[]>('/api/backtest/results'),
    staleTime: 10_000,
  });
}

export function useBacktestStrategiesQuery() {
  return useQuery({
    queryKey: ['backtest-strategies'],
    queryFn: () =>
      apiClient<BacktestStrategyInfo[]>('/api/backtest/strategies'),
    staleTime: 60_000,
  });
}

export {
  useAccountStrategyAssignmentQuery,
  useAccountStrategyAssignmentsQuery,
  useAccountStrategyAttributionQuery,
  useAccountStrategyContributionQuery,
  useUpdateAccountStrategyAssignmentMutation,
  useUpdateScopedAccountStrategyAssignmentMutation,
} from './backtest-feature-boundary';

export function useStrategyLearningReviewQuery() {
  return useQuery({
    queryKey: ['strategy-learning-review'],
    queryFn: () =>
      apiClient<StrategyLearningReviewQueue>(
        '/api/strategy-learning/review-queue',
      ),
    staleTime: 10_000,
  });
}

export function useRunBacktestMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestRunRequest) =>
      postJson<BacktestReport>('/api/backtest/run', payload),
    onSuccess: async (report) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['backtest-results'] }),
        queryClient.invalidateQueries({
          queryKey: ['backtest-result', report.id],
        }),
      ]);
    },
  });
}

export function useStrategySignalPreviewMutation() {
  return useMutation({
    mutationFn: (payload: StrategySignalPreviewRequest) =>
      postJson<StrategySignalPreviewResponse>(
        '/api/backtest/signal-preview',
        payload,
      ),
  });
}

export function useBacktestRiskPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestRiskPreviewRequest) =>
      postJson<BacktestRiskPreviewResponse>(
        '/api/backtest/risk-preview',
        payload,
      ),
  });
}

export function useBacktestPaperShadowPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestPaperShadowPreviewRequest) =>
      postJson<BacktestPaperShadowPreviewResponse>(
        '/api/backtest/paper-shadow-preview',
        payload,
      ),
  });
}

export function useBacktestAttributionPreviewMutation() {
  return useMutation({
    mutationFn: (payload: BacktestAttributionPreviewRequest) =>
      postJson<BacktestAttributionPreviewResponse>(
        '/api/backtest/attribution-preview',
        payload,
      ),
  });
}

export function useRunBacktestSweepMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestSweepRequest) =>
      postJson<BacktestSweepResponse>('/api/backtest/sweep', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['backtest-results'] });
    },
  });
}

export function useRunBacktestCompareMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: BacktestCompareRequest) =>
      postJson<BacktestCompareResponse>('/api/backtest/compare', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['backtest-results'] });
    },
  });
}

export function useBacktestResultQuery(resultId: number | null) {
  return useQuery({
    queryKey: ['backtest-result', resultId],
    queryFn: () =>
      apiClient<BacktestReport>(`/api/backtest/results/${resultId}`),
    enabled: resultId !== null,
    staleTime: 10_000,
  });
}

export function useStrategyValidationQuery(enabled = true) {
  return useQuery({
    queryKey: ['backtest-strategy-validation'],
    queryFn: () =>
      apiClient<StrategyValidationMatrix>('/api/backtest/strategy-validation'),
    staleTime: 10_000,
    enabled,
  });
}

export function useStrategyPromotionReadinessQuery() {
  return useQuery({
    queryKey: ['backtest-strategy-promotion-readiness'],
    queryFn: () =>
      apiClient<StrategyPromotionReadiness>(
        '/api/backtest/strategy-promotion-readiness',
      ),
    staleTime: 10_000,
  });
}
