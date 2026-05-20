import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

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

export type SettingsResponse = {
  host: string;
  port: number;
  live_auto_start: boolean;
  initial_cash: number;
  start_date: string;
  end_date: string;
  assets: Array<{
    symbol: string;
    asset_class: string;
    display_name?: string;
  }>;
  strategy: string;
  short_period: number;
  long_period: number;
  data_source: string;
  tushare_token: string;
  notification: Record<string, unknown>;
  live_poll_interval: number;
};

export type DataSourceSettingsPayload = {
  data_source: string;
  tushare_token: string;
  live_poll_interval: number;
};

export type DataSourceStatusResponse = {
  data_source: string;
  provider_name: string;
  provider_configured: boolean;
  provider_supports_funds: boolean | null;
  provider_requires_token: boolean;
  requires_restart: boolean;
  next_action: string | null;
  metadata_configured_count: number;
  available_providers: string[];
};

export type NotificationTestResponse = {
  status: 'ok' | 'error';
  message: string;
};

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function useSettingsQuery() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => apiClient<SettingsResponse>('/api/settings'),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function useLiveStatusQuery() {
  return useQuery({
    queryKey: ['settings-live-status'],
    queryFn: () => apiClient<LiveStatusResponse>('/api/settings/live/status'),
    staleTime: 10_000,
    refetchInterval: liveStatusRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useDataSourceStatusQuery() {
  return useQuery({
    queryKey: ['settings-data-source'],
    queryFn: () =>
      apiClient<DataSourceStatusResponse>('/api/settings/data-source'),
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });
}

export function useUpdateDataSourceSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: DataSourceSettingsPayload) =>
      putJson<SettingsResponse>('/api/settings/data-source', payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['settings'] }),
        queryClient.invalidateQueries({ queryKey: ['settings-data-source'] }),
        queryClient.invalidateQueries({ queryKey: ['market-data-health'] }),
        queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-snapshot'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-positions'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
        queryClient.invalidateQueries({
          queryKey: ['portfolio-live-holdings'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-overview'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-equity-curve-series'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-state'] }),
      ]);
    },
  });
}

export function useStartLiveMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => postJson<LiveStatusResponse>('/api/settings/live/start'),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['settings-live-status'],
      });
    },
  });
}

export function useStopLiveMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => postJson<LiveStatusResponse>('/api/settings/live/stop'),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['settings-live-status'],
      });
    },
  });
}

export function useTestNotificationMutation() {
  return useMutation({
    mutationFn: () =>
      postJson<NotificationTestResponse>('/api/settings/notification/test'),
  });
}
