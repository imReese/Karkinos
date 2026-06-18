import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../lib/api/client';

export type MarketHealthQuote = {
  symbol: string;
  asset_class: string;
  timestamp: string | null;
  price: number | null;
  quote_status: 'live' | 'stale' | 'missing' | 'error' | 'unknown';
  quote_source: string | null;
  quote_age_seconds: number | null;
  stale_reason: string | null;
  last_refresh_attempt: string | null;
  last_refresh_error: string | null;
  using_persistent_cache?: boolean;
  nav_date?: string | null;
};

export type MarketDataHealthResponse = {
  quotes: MarketHealthQuote[];
  market_open: boolean;
  refresh_policy: string;
  provider_status: string;
  provider_name: string;
  provider_configured: boolean;
  provider_requires_token: boolean;
  provider_supports_funds: boolean | null;
  provider_last_error: string | null;
  provider_timeout_seconds: number | null;
  next_action: string | null;
  metadata_configured_count: number;
  source_health: string;
  cache_age_seconds: number | null;
  latest_quote_timestamp: string | null;
  last_refresh_attempt: string | null;
  last_refresh_error: string | null;
  stale_symbols_count: number;
  stale_symbols_sample: string[];
  real_data_available?: boolean;
  has_persistent_cache?: boolean;
  latest_persistent_quote_timestamp?: string | null;
  persistent_cache_status?: string;
};

export type ResearchBoardItem = {
  symbol: string;
  asset_class: string;
  name: string;
  is_holding: boolean;
  quantity: number | null;
  avg_cost: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  last_snapshot_at: string | null;
  price: number | null;
  volume: number | null;
  research_count: number;
  last_research_at: string | null;
};

export type ResearchBoardResponse = {
  items: ResearchBoardItem[];
  health: MarketDataHealthResponse;
};

export type ResearchNoteResponse = {
  id: number;
  symbol: string;
  asset_class: string;
  entry_kind: string;
  title: string;
  content: string;
  priority: string;
  event_date: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchNoteListResponse = {
  items: ResearchNoteResponse[];
};

export type KlineBar = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type MarketQuoteRefreshResult = {
  symbol: string;
  status: 'refreshed' | 'stale' | 'failed' | 'skipped';
  quote_timestamp: string | null;
  quote_source: string | null;
  quote_age_seconds: number | null;
  error: string | null;
  reason: string | null;
  last_refresh_attempt: string | null;
  last_refresh_error: string | null;
  using_persistent_cache?: boolean;
};

export type MarketQuoteRefreshResponse = {
  requested_symbols: string[];
  refreshed: MarketQuoteRefreshResult[];
  failed: MarketQuoteRefreshResult[];
  skipped: MarketQuoteRefreshResult[];
  refresh_policy: string;
  market_open: boolean;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  quote_status: 'live' | 'stale' | 'partial' | 'error';
  last_refresh_attempt: string | null;
  last_refresh_error: string | null;
  message: string;
  real_data_available?: boolean;
  has_persistent_cache?: boolean;
};

export type QuoteFetchRun = {
  run_id: string;
  trigger: string;
  provider: string | null;
  asset_type: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  symbol_count: number;
  success_count: number;
  failure_count: number;
  cache_hit_count: number;
  error_message: string | null;
  metadata: Record<string, unknown> | null;
};

export type InstrumentMetadataBackfillResponse = {
  provider: string;
  requested_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
};

export type MarketBarsBackfillResponse = {
  provider: string;
  interval: string;
  start: string;
  end: string;
  requested_count: number;
  updated_count: number;
  cached_count: number;
  failed_count: number;
};

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
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

async function deleteJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    method: 'DELETE',
    headers: {
      Accept: 'application/json',
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function useResearchBoardQuery() {
  return useQuery({
    queryKey: ['market-research-board'],
    queryFn: () =>
      apiClient<ResearchBoardResponse>('/api/market/research-board'),
  });
}

export function useMarketDataHealthQuery() {
  return useQuery({
    queryKey: ['market-data-health'],
    queryFn: () =>
      apiClient<MarketDataHealthResponse>('/api/market/data-health'),
    staleTime: 10_000,
    refetchInterval: () => {
      if (
        typeof document !== 'undefined' &&
        document.visibilityState !== 'visible'
      ) {
        return false;
      }
      return 10_000;
    },
    refetchOnWindowFocus: true,
  });
}

export function useRefreshMarketQuotesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload?: { symbols?: string[]; force?: boolean }) =>
      postJson<MarketQuoteRefreshResponse>(
        '/api/market/quotes/refresh',
        payload ?? {},
      ),
    onSuccess: async () => {
      await Promise.all([
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

export function useQuoteFetchRunsQuery() {
  return useQuery({
    queryKey: ['market-quote-fetch-runs'],
    queryFn: () =>
      apiClient<QuoteFetchRun[]>('/api/market/quote-fetch-runs?limit=8'),
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  });
}

export function useInstrumentMetadataBackfillMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<InstrumentMetadataBackfillResponse>(
        '/api/market/instrument-metadata/backfill',
        { force: false },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
        queryClient.invalidateQueries({ queryKey: ['market-data-health'] }),
      ]);
    },
  });
}

export function useMarketBarsBackfillMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      postJson<MarketBarsBackfillResponse>('/api/market/bars/backfill', {
        interval: '1d',
        force: false,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['market-kline'] }),
        queryClient.invalidateQueries({
          queryKey: ['market-quote-fetch-runs'],
        }),
      ]);
    },
  });
}

export function useKlineQuery(symbol: string) {
  return useQuery({
    queryKey: ['market-kline', symbol],
    enabled: symbol.length > 0,
    queryFn: () =>
      apiClient<KlineBar[]>(`/api/market/kline/${encodeURIComponent(symbol)}`),
  });
}

export function useResearchNotesQuery(
  symbol: string,
  filters?: {
    entry_kind?: string;
    priority?: string;
    event_date_from?: string;
    event_date_to?: string;
  },
) {
  return useQuery({
    queryKey: ['market-research-notes', symbol, filters],
    enabled: symbol.length > 0,
    queryFn: () => {
      const params = new URLSearchParams({ symbol });
      if (filters?.entry_kind) params.set('entry_kind', filters.entry_kind);
      if (filters?.priority) params.set('priority', filters.priority);
      if (filters?.event_date_from)
        params.set('event_date_from', filters.event_date_from);
      if (filters?.event_date_to)
        params.set('event_date_to', filters.event_date_to);
      return apiClient<ResearchNoteListResponse>(
        `/api/market/research-notes?${params.toString()}`,
      );
    },
  });
}

export function useAddWatchlistItemMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { symbol: string; asset_class: string }) =>
      postJson('/api/market/watchlist', payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['market-research-board'],
      });
    },
  });
}

export function useCreateResearchNoteMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      symbol: string;
      asset_class: string;
      entry_kind: string;
      title: string;
      content: string;
      priority: string;
      event_date: string | null;
    }) => postJson<ResearchNoteResponse>('/api/market/research-notes', payload),
    onSuccess: async (note) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['market-research-notes', note.symbol],
        }),
        queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
      ]);
    },
  });
}

export function useUpdateResearchNoteMutation(symbol: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      noteId: number;
      entry_kind: string;
      title: string;
      content: string;
      priority: string;
      event_date: string | null;
    }) =>
      putJson<ResearchNoteResponse>(
        `/api/market/research-notes/${payload.noteId}`,
        payload,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['market-research-notes', symbol],
        }),
        queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
      ]);
    },
  });
}

export function useDeleteResearchNoteMutation(symbol: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (noteId: number) =>
      deleteJson<{ status: string }>(`/api/market/research-notes/${noteId}`),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['market-research-notes', symbol],
        }),
        queryClient.invalidateQueries({ queryKey: ['market-research-board'] }),
      ]);
    },
  });
}

export function useRemoveWatchlistItemMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) =>
      deleteJson(`/api/market/watchlist/${encodeURIComponent(symbol)}`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['market-research-board'],
      });
    },
  });
}
