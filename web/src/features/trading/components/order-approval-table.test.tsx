import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { OrderApprovalTable } from './order-approval-table';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderOrderApprovalTable() {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'zh');
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/trading/orders?status=pending_confirm')) {
        return jsonResponse([
          {
            id: 1,
            order_id: 'ORD-SIDE-REVIEW',
            timestamp: '2026-06-18T10:00:00+08:00',
            symbol: 'SYN001',
            display_name: '合成样例股票A',
            side: 'broker_special_side',
            order_type: 'limit',
            quantity: 100,
            price: 8.8,
            intent_id: 'INT-1',
            risk_decision_id: 'RISK-1',
            execution_mode: 'manual',
            status: 'pending_confirm',
            payload_json: '{"intent_id":"INT-1","risk_decision_id":"RISK-1"}',
            note: null,
            created_at: '2026-06-18T10:00:00+08:00',
            updated_at: '2026-06-18T10:00:00+08:00',
          },
        ]);
      }
      if (url.includes('/api/portfolio/positions')) {
        return jsonResponse([]);
      }
      return new Response('Not found', { status: 404 });
    }),
  );

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OrderApprovalTable />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('formats unknown approval order sides through public status labels', async () => {
  renderOrderApprovalTable();

  const panel = await screen.findByTestId('order-approval-panel');
  expect(panel.getAttribute('data-layout')).toBe('compact-approval');

  const count = await screen.findByTestId('order-approval-count');
  expect(count.textContent).toContain('1 等待审批');
  expect(count.className).toContain('rounded-full');

  expect(await screen.findByText('合成样例股票A SYN001')).toBeTruthy();
  expect(await screen.findByText('待确认状态')).toBeTruthy();
  expect(screen.queryByText('broker_special_side')).toBeNull();
});
