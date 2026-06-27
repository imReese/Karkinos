import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { ActivityPage } from './router';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installActivityFetchMock() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/ledger/entries')) {
      return jsonResponse([
        {
          id: 2,
          entry_type: 'cash_interest',
          timestamp: '2026-06-22T06:24:15+00:00',
          amount: 0.27,
          symbol: null,
          display_name: '现金利息',
          direction: null,
          quantity: null,
          price: null,
          commission: 0,
          asset_class: 'cash',
          note: '批量结息归本：现金利息 0.27 元',
          source: 'broker_statement_manual_correction',
          source_ref: 'synthetic-cash-interest',
          created_at: '2026-06-22T06:24:15+00:00',
        },
        {
          id: 1,
          entry_type: 'trade_buy',
          timestamp: '2026-01-15T03:04:56+00:00',
          amount: 3250,
          symbol: 'SYN001',
          display_name: '合成标的',
          direction: 'buy',
          quantity: 200,
          price: 16.25,
          commission: 5,
          gross_amount: 3250,
          net_cash_impact: -3255.16,
          fee_breakdown: {
            commission: '5',
            stamp_tax: '0',
            transfer_fee: '0.16',
            other_fees: '0',
            total_fee: '5.16',
          },
          fee_rule_id: 'synthetic_fee_rule',
          fee_rule_version: 'fixture',
          cost_basis_method: 'moving_average_buy_cost',
          asset_class: 'stock',
          note: 'internal_fee_rule_missing',
          source: 'manual',
          source_ref: 'synthetic-trade-buy',
          created_at: null,
        },
      ]);
    }
    if (url.includes('/api/portfolio/pending-fund-orders')) {
      return jsonResponse([]);
    }
    if (url.includes('/api/portfolio/positions')) {
      return jsonResponse([]);
    }
    if (url.includes('/api/settings')) {
      return jsonResponse({
        host: '127.0.0.1',
        port: 8000,
        live_auto_start: false,
        initial_cash: 10000,
        start_date: '2026-01-01',
        end_date: '2026-06-22',
        assets: [],
        strategy: 'dual_ma',
        short_period: 5,
        long_period: 20,
        data_source: 'akshare',
        tushare_token: '',
        notification: {},
        live_poll_interval: 60,
        account_commission_rate: 0.00015,
        account_min_commission: 5,
      });
    }

    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderActivityPage(locale?: 'en' | 'zh') {
  window.localStorage.clear();
  if (locale) {
    window.localStorage.setItem('karkinos.locale', locale);
  }
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  installActivityFetchMock();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <ActivityPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('summarizes activity net cash impact with the shared ledger formatter semantics', async () => {
  renderActivityPage();

  expect(await screen.findByText('Net cash impact')).toBeTruthy();
  expect(await screen.findByText('-CN¥3,254.89')).toBeTruthy();
  expect(await screen.findByText('Commission CN¥5.00')).toBeTruthy();
  expect(await screen.findByText('Stamp tax CN¥0.00')).toBeTruthy();
  expect(await screen.findByText('Transfer fee CN¥0.16')).toBeTruthy();
  expect(screen.queryByText('-CN¥3,250.00')).toBeNull();
  expect(screen.queryByText('synthetic_fee_rule')).toBeNull();
  expect(screen.queryByText('moving_average_buy_cost')).toBeNull();
  expect(screen.queryByText('fee_breakdown')).toBeNull();
});

test('renders public localized notes instead of raw backend note codes', async () => {
  renderActivityPage('zh');

  expect(await screen.findByText('待人工复核说明')).toBeTruthy();
  expect(screen.queryByText('internal_fee_rule_missing')).toBeNull();
});

test('renders professional cash ledger rows without internal noise', async () => {
  renderActivityPage('zh');

  expect(await screen.findByText('结息入账')).toBeTruthy();
  expect(await screen.findByText('对账校正')).toBeTruthy();
  expect(screen.getAllByText('现金利息').length).toBeGreaterThan(0);
  expect(screen.queryByText('券商对账修正')).toBeNull();
  expect(screen.queryByText('无公开备注')).toBeNull();
  expect(screen.queryByText(/批量结息归本/u)).toBeNull();
  expect(screen.queryByText('手续费 ¥0.00')).toBeNull();
});

test('filters recent ledger entries by category', async () => {
  renderActivityPage('zh');

  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: '现金 1 条' }));

  expect(screen.getAllByText('现金利息').length).toBeGreaterThan(0);
  expect(screen.queryByText('合成标的 SYN001')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '交易 1 条' }));

  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect(screen.queryByText('现金利息')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '全部 2 条' }));

  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
});

test('filters recent ledger entries by instrument search', async () => {
  renderActivityPage('zh');

  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);

  fireEvent.change(screen.getByLabelText('搜索标的名称 / 代码'), {
    target: { value: 'SYN001' },
  });

  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect(screen.queryByText('现金利息')).toBeNull();

  fireEvent.change(screen.getByLabelText('搜索标的名称 / 代码'), {
    target: { value: '现金' },
  });

  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(screen.queryByText('合成标的 SYN001')).toBeNull();

  fireEvent.change(screen.getByLabelText('搜索标的名称 / 代码'), {
    target: { value: '不存在' },
  });

  expect(await screen.findByText('没有匹配的账本流水。')).toBeTruthy();
});
