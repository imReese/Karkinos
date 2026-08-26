import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren } from 'react';
import { afterEach, expect, test, vi } from 'vitest';

import {
  createLedgerMutationIdentity,
  createTradeMutationIdentity,
  useCreateCashFlowMutation,
  useCreateTradeMutation,
  useTradePreviewMutation,
} from './api';

function wrapper({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function retryWrapper({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: 1, retryDelay: 0 },
    },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('creates distinct identities for separate user submissions', () => {
  const firstTrade = createTradeMutationIdentity();
  const secondTrade = createTradeMutationIdentity();
  const firstLedger = createLedgerMutationIdentity();
  const secondLedger = createLedgerMutationIdentity();

  expect(secondTrade.command_id).not.toBe(firstTrade.command_id);
  expect(secondLedger.request_id).not.toBe(firstLedger.request_id);
});

test('omits auto-filled trade fee so backend configured fee contract is used', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ id: 1 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );

  const { result } = renderHook(() => useCreateTradeMutation(), { wrapper });
  const identity = createTradeMutationIdentity();

  result.current.mutate({
    ...identity,
    occurred_at: '2026-01-12T14:33:41+08:00',
    symbol: '600002',
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
      command_id: identity.command_id,
      operator_id: identity.operator_id,
      symbol: '600002',
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
  const identity = createTradeMutationIdentity();

  result.current.mutate({
    ...identity,
    occurred_at: '2026-01-12T14:33:41+08:00',
    symbol: '600002',
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
  expect(body.command_id).toBe(identity.command_id);
  expect(body.operator_id).toBe(identity.operator_id);
});

test('reuses caller-provided command identity across automatic trade retries', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockRejectedValueOnce(new TypeError('network response lost'))
    .mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  const identity = createTradeMutationIdentity();
  const { result } = renderHook(() => useCreateTradeMutation(), {
    wrapper: retryWrapper,
  });

  result.current.mutate({
    ...identity,
    occurred_at: '2026-01-12T14:33:41+08:00',
    symbol: '600002',
    direction: 'buy',
    quantity: 200,
    unit_price: 28.82,
    amount: null,
    fee: 3,
    asset_class: 'stock',
    note: '',
  });

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  const requestBodies = fetchMock.mock.calls.map(([, init]) =>
    JSON.parse(String((init as RequestInit).body)),
  );
  expect(requestBodies.map((body) => body.command_id)).toEqual([
    identity.command_id,
    identity.command_id,
  ]);
  expect(requestBodies.map((body) => body.operator_id)).toEqual([
    identity.operator_id,
    identity.operator_id,
  ]);
});

test('reuses caller-provided request identity across automatic ledger retries', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockRejectedValueOnce(new TypeError('network response lost'))
    .mockResolvedValue(
      new Response(JSON.stringify({ id: 1 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  const identity = createLedgerMutationIdentity();
  const { result } = renderHook(() => useCreateCashFlowMutation(), {
    wrapper: retryWrapper,
  });

  result.current.mutate({
    ...identity,
    occurred_at: '2026-01-12T14:33:41+08:00',
    amount: 100,
    flow_type: 'deposit',
    note: '',
  });

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  const requestBodies = fetchMock.mock.calls.map(([, init]) =>
    JSON.parse(String((init as RequestInit).body)),
  );
  expect(requestBodies.map((body) => body.request_id)).toEqual([
    identity.request_id,
    identity.request_id,
  ]);
  expect(requestBodies.map((body) => body.operator_id)).toEqual([
    identity.operator_id,
    identity.operator_id,
  ]);
});

test('requests manual trade preview with the same commission override contract', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        gross_amount: 5764,
        commission: 8.5,
        total_fee: 8.5,
        net_cash_impact: -5772.5,
        fee_breakdown: { total_fee: '8.5' },
      }),
      {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      },
    ),
  );

  const { result } = renderHook(() => useTradePreviewMutation(), { wrapper });

  result.current.mutate({
    occurred_at: '2026-01-12T14:33:41+08:00',
    symbol: '600002',
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

  const [url, init] = fetchMock.mock.calls[0];
  const body = JSON.parse(String((init as RequestInit).body)) as Record<
    string,
    unknown
  >;
  expect(url).toBe('/api/portfolio/trade/preview');
  expect(body).toEqual(
    expect.objectContaining({
      symbol: '600002',
      quantity: 200,
      price: 28.82,
      asset_class: 'stock',
      commission: 8.5,
    }),
  );
  expect(body).not.toHaveProperty('command_id');
  expect(body).not.toHaveProperty('operator_id');
  expect(body).not.toHaveProperty('request_id');
});
