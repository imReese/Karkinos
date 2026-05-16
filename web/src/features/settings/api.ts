import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

const LIVE_STATUS_REFETCH_MS = 10_000;

function liveStatusRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return LIVE_STATUS_REFETCH_MS;
}

export type LiveStatusResponse = {
  running: boolean;
  market_open: boolean;
};

export function useLiveStatusQuery() {
  return useQuery({
    queryKey: ['settings-live-status'],
    queryFn: () => apiClient<LiveStatusResponse>('/api/settings/live/status'),
    staleTime: 10_000,
    refetchInterval: liveStatusRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
