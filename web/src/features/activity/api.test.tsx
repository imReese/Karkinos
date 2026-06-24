import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import { useCreateTradeMutation } from './api';

function wrapper({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('omits auto-filled trade fee so backend configured fee contract is used', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ id: 1 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

  const { result } = renderHook(() => useCreateTradeMutation(), { wrapper });

  result.current.mutate({
    occurred_at: '2026-06-05T14:33:41+08:00',
    symbol: '603659',
    direction: 'buy',
    quantity: 200,
    unit_price: 28.82,
    amount: null,
    fee: 3,
    asset_class: 'stock',
    note: '',
  });

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());

  const [, init] = fetchMock.mock.calls[0];
  const body = JSON.parse(String((init as RequestInit).body)) as Record<
    string,
    unknown
  >;
  expect(body).toEqual(
    expect.objectContaining({
      symbol: '603659',
      quantity: 200,
      price: 28.82,
      asset_class: 'stock',
    }),
  );
  expect(body).not.toHaveProperty('commission');
});

test('keeps explicitly edited trade fee as manual commission evidence', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ id: 1 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

  const { result } = renderHook(() => useCreateTradeMutation(), { wrapper });

  result.current.mutate({
    occurred_at: '2026-06-05T14:33:41+08:00',
    symbol: '603659',
    direction: 'buy',
    quantity: 200,
    unit_price: 28.82,
    amount: null,
    fee: 8.5,
    fee_is_manual: true,
    asset_class: 'stock',
    note: '',
  });

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());

  const [, init] = fetchMock.mock.calls[0];
  const body = JSON.parse(String((init as RequestInit).body)) as Record<
    string,
    unknown
  >;
  expect(body.commission).toBe(8.5);
});
