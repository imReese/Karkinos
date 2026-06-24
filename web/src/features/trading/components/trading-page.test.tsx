import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { TradingPage } from './trading-page';

const pendingOrder = {
  id: 1,
  order_id: 'ORD-PENDING',
  timestamp: '2026-05-16T10:00:00+08:00',
  symbol: '600519',
  side: 'buy',
  order_type: 'limit',
  quantity: 100,
  price: 1720.25,
  intent_id: 'INT-1',
  risk_decision_id: 'RISK-1',
  execution_mode: 'manual',
  status: 'pending_confirm',
  payload_json: '{"intent_id":"INT-1","risk_decision_id":"RISK-1"}',
  note: null,
  created_at: '2026-05-16T10:00:00+08:00',
  updated_at: '2026-05-16T10:00:00+08:00',
};

const confirmedOrder = {
  ...pendingOrder,
  id: 2,
  order_id: 'ORD-CONFIRMED',
  symbol: '019999',
  side: 'sell',
  status: 'confirmed',
  note: 'confirmed by operator',
  updated_at: '2026-05-16T10:30:00+08:00',
};

const orderFact = {
  order_id: 'ORD-FACT-1',
  timestamp: '2026-05-16T10:45:00+08:00',
  symbol: '600519',
  side: 'buy',
  order_type: 'limit',
  quantity: 100,
  price: 1720.25,
  asset_class: 'stock',
  execution_mode: 'manual',
  status: 'confirmed',
};

const fillFact = {
  fill_id: 'FILL-1',
  order_id: 'ORD-FACT-1',
  timestamp: '2026-05-16T10:46:00+08:00',
  symbol: '600519',
  side: 'buy',
  fill_price: 1720.25,
  fill_quantity: 100,
  commission: 5,
  slippage: 0,
};

const positionRows = [
  {
    symbol: '600519',
    name: '贵州茅台',
    display_name: '贵州茅台',
    asset_class: 'stock',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 1720.25,
    latest_price: 1721,
    market_value: 172100,
    unrealized_pnl: 75,
    realized_pnl: 0,
    commission_paid: 5,
  },
  {
    symbol: '019999',
    name: '示例成长混合C',
    display_name: '示例成长混合C',
    asset_class: 'fund',
    quantity: 100,
    available_qty: 100,
    frozen_qty: 0,
    avg_cost: 1.1,
    latest_price: 1.12,
    market_value: 112,
    unrealized_pnl: 2,
    realized_pnl: 0,
    commission_paid: 0,
  },
];

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function installTradingFetchMock({
  orders = [pendingOrder, confirmedOrder],
  orderFacts = [orderFact],
  fillFacts = [fillFact],
  positions = positionRows,
  rejectFails = false,
  ordersFail = false,
}: {
  orders?: unknown[];
  orderFacts?: unknown[];
  fillFacts?: unknown[];
  positions?: unknown[];
  rejectFails?: boolean;
  ordersFail?: boolean;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/trading/kill-switch')) {
        if (init?.method === 'PUT') {
          return jsonResponse({
            kill_switch_enabled: false,
            reason: '',
            updated_at: '2026-05-16T10:00:00+08:00',
          });
        }
        return jsonResponse({
          kill_switch_enabled: false,
          reason: '',
          updated_at: '2026-05-16T10:00:00+08:00',
        });
      }
      if (url.includes('/api/portfolio/positions')) {
        return jsonResponse(positions);
      }
      if (url.includes('/api/trading/order-facts')) {
        return jsonResponse(orderFacts);
      }
      if (url.includes('/api/trading/fills')) {
        return jsonResponse(fillFacts);
      }
      if (url.includes('/api/trading/shadow-runs/daily')) {
        return jsonResponse({
          run_id: 'shadow-2026-05-16',
          run_date: '2026-05-16',
          processed_count: 1,
          reused_count: 0,
          skipped_count: 0,
          orders: [orderFact],
          reused_orders: [],
          skipped: [],
        });
      }
      if (url.includes('/api/trading/orders/ORD-PENDING/confirm')) {
        return jsonResponse({ ...pendingOrder, status: 'confirmed' });
      }
      if (url.includes('/api/trading/orders/ORD-PENDING/reject')) {
        return rejectFails
          ? jsonResponse({ detail: 'manual order not found' }, { status: 404 })
          : jsonResponse({ ...pendingOrder, status: 'rejected' });
      }
      if (url.includes('/api/trading/orders')) {
        if (ordersFail) {
          return jsonResponse(
            { detail: 'orders unavailable' },
            { status: 503 },
          );
        }
        if (url.includes('status=pending_confirm')) {
          return jsonResponse(
            orders.filter(
              (order) =>
                typeof order === 'object' &&
                order !== null &&
                'status' in order &&
                order.status === 'pending_confirm',
            ),
          );
        }
        return jsonResponse(orders);
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderTradingPage(
  options?: Parameters<typeof installTradingFetchMock>[0] & {
    locale?: 'en' | 'zh';
  },
) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const { locale: _locale, ...fetchOptions } = options ?? {};
  const fetchMock = installTradingFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <TradingPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders the trading approvals workspace', async () => {
  renderTradingPage();

  expect(await screen.findByText('Trading approvals')).toBeTruthy();
  expect(await screen.findByText('Global kill switch')).toBeTruthy();
  expect(await screen.findByText('Execution audit')).toBeTruthy();
  expect(
    await screen.findByText('Order facts, fills, and simulation review'),
  ).toBeTruthy();
  expect(await screen.findByText('Order facts')).toBeTruthy();
  expect(await screen.findByText('Fill facts')).toBeTruthy();
  expect(await screen.findByText('Order queue')).toBeTruthy();
  expect(await screen.findByText('贵州茅台 600519')).toBeTruthy();
  expect(await screen.findByText('示例成长混合C 019999')).toBeTruthy();
  expect(
    screen.queryByText('Order facts, fills, and shadow review'),
  ).toBeNull();
  expect(screen.queryByText(/real-time/i)).toBeNull();
});

test('localizes generated manual-order notes without exposing action ids', async () => {
  renderTradingPage({
    orders: [
      {
        ...pendingOrder,
        note: 'Prepared from signal action 42.',
      },
      {
        ...confirmedOrder,
        note: 'Prepared from signal action 42.',
      },
    ],
  });

  expect(
    await screen.findAllByText('Prepared from Decision action queue.'),
  ).toHaveLength(2);
  expect(screen.queryByText('Prepared from signal action 42.')).toBeNull();
});

test('hides dotted backend operational note codes in trading rows', async () => {
  renderTradingPage({
    orders: [
      {
        ...pendingOrder,
        note: 'backend.order.review',
      },
    ],
  });

  expect(await screen.findByText('Review note')).toBeTruthy();
  expect(screen.queryByText('backend.order.review')).toBeNull();
});

test('uses a public audit-note placeholder instead of raw order ids', async () => {
  renderTradingPage({
    orders: [
      {
        ...confirmedOrder,
        note: null,
      },
    ],
  });

  expect(await screen.findByText('No public note recorded.')).toBeTruthy();
  expect(screen.queryByText('ORD-CONFIRMED')).toBeNull();
});

test('runs daily simulation review from the execution audit panel', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderTradingPage();

  await screen.findByText('Execution audit');
  await user.click(
    screen.getByRole('button', { name: 'Run daily simulation review' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/shadow-runs/daily',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  expect(
    await screen.findByText(/Simulation review prepared 1 orders/),
  ).toBeTruthy();
});

test('uses execution fact display names when the instrument is not in current holdings', async () => {
  renderTradingPage({
    locale: 'zh',
    positions: [],
    orderFacts: [
      {
        ...orderFact,
        order_id: 'ORD-FACT-NAME',
        symbol: '000001',
        display_name: '平安银行',
        status: 'confirmed',
      },
    ],
    fillFacts: [
      {
        ...fillFact,
        fill_id: 'FILL-NAME',
        symbol: '000001',
        display_name: '平安银行',
      },
    ],
  });

  expect(await screen.findByText('买入 平安银行 000001')).toBeTruthy();
  expect(
    await screen.findByText(
      /金额\s+(?:CN)?¥172,025\.00 · 份额\/数量 100 · 价格\s+(?:CN)?¥1,720\.25 · 状态 已确认/u,
    ),
  ).toBeTruthy();
  expect(await screen.findByText('平安银行 000001 · 买入')).toBeTruthy();
  expect(screen.queryByText('000001 · confirmed')).toBeNull();
  expect(screen.queryByText('000001 · buy')).toBeNull();
});

test('shows order facts with shared ledger action and detail formatting', async () => {
  renderTradingPage({
    orderFacts: [
      {
        ...orderFact,
        status: 'confirmed',
      },
    ],
  });

  expect(await screen.findByText('Buy 贵州茅台 600519')).toBeTruthy();
  expect(
    await screen.findByText(
      /Amount CN¥172,025\.00 · Quantity 100 · Price CN¥1,720\.25 · Status Confirmed/,
    ),
  ).toBeTruthy();
  expect(screen.queryByText('贵州茅台 600519 · Confirmed')).toBeNull();
  expect(screen.queryByText('Buy 100 @ CN¥1,720.25')).toBeNull();
});

test('shows structured fill cash impact and fee breakdown in execution audit', async () => {
  renderTradingPage({
    fillFacts: [
      {
        ...fillFact,
        asset_class: 'stock',
        metadata_json: JSON.stringify({
          gross_amount: 172025,
          net_cash_impact: -172030.2,
          fee_breakdown: {
            commission: '5.00',
            stamp_tax: '0.00',
            transfer_fee: '0.20',
            other_fees: '0.00',
            total_fee: '5.20',
          },
          fee_rule_id: 'manual_configured_commission',
          fee_rule_version: 'account_commission_rate',
        }),
      },
    ],
  });

  expect(await screen.findByText(/Gross amount CN¥172,025\.00/)).toBeTruthy();
  expect(
    await screen.findByText(/Net cash impact -CN¥172,030\.20/),
  ).toBeTruthy();
  expect(await screen.findByText(/Commission CN¥5\.00/)).toBeTruthy();
  expect(await screen.findByText(/Stamp tax CN¥0\.00/)).toBeTruthy();
  expect(await screen.findByText(/Transfer fee CN¥0\.20/)).toBeTruthy();
  expect(screen.queryByText(/manual_configured_commission/)).toBeNull();
  expect(screen.queryByText(/fee_breakdown/)).toBeNull();
});

test('confirms a pending manual order and refreshes the queue', async () => {
  const { fetchMock } = renderTradingPage();

  await screen.findByText('贵州茅台 600519');
  fireEvent.click(
    screen.getByRole('button', { name: 'Confirm: 贵州茅台 600519' }),
  );

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/orders/ORD-PENDING/confirm',
      expect.objectContaining({ method: 'POST' }),
    );
  });
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).includes('/api/trading/orders?status=pending_confirm'),
      ).length,
    ).toBeGreaterThan(1);
  });
});

test('shows reject errors without changing local order state', async () => {
  const user = userEvent.setup();
  renderTradingPage({ rejectFails: true });

  await screen.findByText('贵州茅台 600519');
  await user.type(
    screen.getByLabelText('Reject reason: 贵州茅台 600519'),
    'risk note changed',
  );
  const rejectButton = screen.getByRole('button', {
    name: 'Reject: 贵州茅台 600519',
  });
  await user.click(rejectButton);
  await user.click(rejectButton);

  expect((await screen.findByRole('alert')).textContent).toContain(
    'manual order not found',
  );
  expect(await screen.findByText('贵州茅台 600519')).toBeTruthy();
});

test('renders loading error and empty states', async () => {
  renderTradingPage({ ordersFail: true });
  expect(
    await screen.findByText('Failed to load pending orders.'),
  ).toBeTruthy();

  cleanup();
  vi.unstubAllGlobals();
  renderTradingPage({ orders: [] });
  expect(
    await screen.findByText('No orders are waiting for manual confirmation.'),
  ).toBeTruthy();
  expect(
    await screen.findByText('No completed order decisions are available yet.'),
  ).toBeTruthy();
});
