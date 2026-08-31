import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../api/client';
import { visiblePersistedProjectionRefetchInterval } from '../api/query-policy';
import type { CurrentHoldingMarketEvidenceReview, Position } from './contracts';

export function usePositionsQuery(enabled = true) {
  return useQuery({
    queryKey: ['portfolio-positions'],
    queryFn: () => apiClient<Position[]>('/api/portfolio/positions'),
    staleTime: 10_000,
    enabled,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useCurrentHoldingMarketEvidenceReviewQuery(enabled = true) {
  return useQuery({
    queryKey: ['current-holding-market-evidence-review'],
    queryFn: () =>
      apiClient<CurrentHoldingMarketEvidenceReview>(
        '/api/portfolio/market-evidence-review',
      ),
    staleTime: 10_000,
    enabled,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
