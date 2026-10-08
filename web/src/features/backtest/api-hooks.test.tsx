import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { useHoldingStrategyAttributionQuery } from '../account-strategy/api';
import {
  useUpdateAccountStrategyAssignmentMutation,
  useUpdateScopedAccountStrategyAssignmentMutation,
} from './api-hooks';

afterEach(() => vi.unstubAllGlobals());

test.each([
  ['account', useUpdateAccountStrategyAssignmentMutation],
  ['symbol', useUpdateScopedAccountStrategyAssignmentMutation],
] as const)(
  'refreshes visible holding attribution after %s strategy assignment changes',
  async (scope, useUpdate) => {
    let strategyId = 'dual_ma';
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'PUT')
          strategyId = JSON.parse(String(init.body)).strategy_id;
        return new Response(
          JSON.stringify({ strategy_id: strategyId, symbol: '600519', scope }),
          {
            headers: { 'Content-Type': 'application/json' },
          },
        );
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const { result } = renderHook(
      () => ({
        holding: useHoldingStrategyAttributionQuery('600519'),
        update: useUpdate(),
      }),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={queryClient}>
            {children}
          </QueryClientProvider>
        ),
      },
    );
    await waitFor(() =>
      expect(result.current.holding.data?.strategy_id).toBe('dual_ma'),
    );
    await act(() =>
      result.current.update.mutateAsync({
        strategy_id: 'momentum',
        scope,
        symbol: scope === 'symbol' ? '600519' : null,
      }),
    );
    await waitFor(() =>
      expect(result.current.holding.data?.strategy_id).toBe('momentum'),
    );
  },
);
