import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { ActivityPage } from './activity-page';

type FetchInput = RequestInfo | URL;

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installActivityFetchMock(extraLedgerEntries: unknown[] = []) {
  const fetchMock = vi.fn(async (input: FetchInput, _init?: RequestInit) => {
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
        ...extraLedgerEntries,
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
        tushare_token_configured: false,
        notification: { type: 'console', configured: true },
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

function renderActivityPage(
  locale?: 'en' | 'zh',
  extraLedgerEntries: unknown[] = [],
) {
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
  const fetchMock = installActivityFetchMock(extraLedgerEntries);
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
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('preserves the ledger workspace hierarchy without inventing facts while projections load', () => {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => undefined)),
  );
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

  const history = screen.getByTestId('activity-history-loading');
  const pending = screen.getByTestId('pending-fund-orders-loading');
  expect(history.getAttribute('aria-busy')).toBe('true');
  expect(pending.getAttribute('aria-busy')).toBe('true');
  expect(within(history).getByText('Recent entries')).toBeTruthy();
  expect(within(pending).getByText('Pending fund subscriptions')).toBeTruthy();
  expect(
    screen.getByTestId('activity-history-loading-rows').children,
  ).toHaveLength(4);
  expect(
    screen.getByTestId('pending-fund-orders-loading-rows').children,
  ).toHaveLength(2);
  expect(screen.queryByText(/\b0 entries\b/u)).toBeNull();
  expect(screen.queryByText(/¥|\$|€|£/u)).toBeNull();
});

test('does not derive authoritative net cash impact from the visible ledger rows', async () => {
  renderActivityPage();

  expect(await screen.findByText('Net cash impact')).toBeTruthy();
  expect(await screen.findByText('Not available')).toBeTruthy();
  expect(
    await screen.findByText(
      'Recent entries are not a complete account history, so no total is shown.',
    ),
  ).toBeTruthy();
  expect(
    document.querySelectorAll('.activity-summary-strip > div'),
  ).toHaveLength(2);
  expect(await screen.findByText('2 entries')).toBeTruthy();
  expect(await screen.findByText('Commission ¥5.00')).toBeTruthy();
  expect(await screen.findByText('Stamp tax ¥0.00')).toBeTruthy();
  expect(await screen.findByText('Transfer fee ¥0.16')).toBeTruthy();
  expect(screen.queryByText('-¥3,254.89')).toBeNull();
  expect(screen.queryByText('-¥3,250.00')).toBeNull();
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
  expect(screen.queryByText('全部交易 1 条')).toBeNull();
  expect(screen.queryByText('全部现金 1 条')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '现金 1 条' }));

  expect(screen.getByRole('button', { name: '全部现金 1 条' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '结息 1 条' })).toBeTruthy();
  expect(screen.queryByText('全部交易 1 条')).toBeNull();
  expect(screen.getAllByText('现金利息').length).toBeGreaterThan(0);
  expect(screen.queryByText('合成标的 SYN001')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '交易 1 条' }));

  expect(screen.getByRole('button', { name: '全部交易 1 条' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '股票 1 条' })).toBeTruthy();
  expect(screen.queryByText('全部现金 1 条')).toBeNull();
  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect(screen.queryByText('现金利息')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '全部 2 条' }));

  expect(screen.queryByText('全部交易 1 条')).toBeNull();
  expect(screen.queryByText('全部现金 1 条')).toBeNull();
  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
});

test('shows contextual second-level filters for the selected ledger category', async () => {
  renderActivityPage('zh', [
    {
      id: 3,
      entry_type: 'trade_buy',
      timestamp: '2026-02-03T03:04:56+00:00',
      amount: 200,
      symbol: 'FUND001',
      display_name: '合成基金',
      direction: 'buy',
      quantity: 100,
      price: 2,
      commission: 0,
      gross_amount: 200,
      net_cash_impact: -200,
      fee_breakdown: {
        commission: '0',
        subscription_fee: '0',
        redemption_fee: '0',
        stamp_tax: '0',
        transfer_fee: '0',
        other_fees: '0',
      },
      fee_rule_id: 'synthetic_fee_rule',
      fee_rule_version: 'fixture',
      cost_basis_method: 'moving_average_buy_cost',
      asset_class: 'fund',
      note: '手工录入基金申购：合成基金，申购金额 200.00',
      source: 'manual',
      source_ref: 'synthetic-fund-buy',
      created_at: null,
    },
  ]);

  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect(await screen.findByText('合成基金 FUND001')).toBeTruthy();
  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(screen.queryByText('全部资产 3 条')).toBeNull();
  expect(screen.queryByText('股票 1 条')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '交易 2 条' }));

  expect(screen.getByRole('button', { name: '全部交易 2 条' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '股票 1 条' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '基金 1 条' })).toBeTruthy();
  expect(screen.queryByText('现金账户 1 条')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '股票 1 条' }));

  expect(screen.getByText('合成标的 SYN001')).toBeTruthy();
  expect(screen.queryByText('合成基金 FUND001')).toBeNull();
  expect(screen.queryByText('现金利息')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '基金 1 条' }));

  expect(await screen.findByText('合成基金 FUND001')).toBeTruthy();
  expect(screen.queryByText('合成标的 SYN001')).toBeNull();
  expect(screen.queryByText('现金利息')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '现金 1 条' }));

  expect(screen.getByRole('button', { name: '全部现金 1 条' })).toBeTruthy();
  expect(screen.getByRole('button', { name: '结息 1 条' })).toBeTruthy();
  expect(screen.queryByText('股票 1 条')).toBeNull();
  expect(screen.queryByText('基金 1 条')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '结息 1 条' }));

  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
  expect(screen.queryByText('合成标的 SYN001')).toBeNull();
  expect(screen.queryByText('合成基金 FUND001')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: '全部 3 条' }));

  expect(screen.queryByText('全部交易 2 条')).toBeNull();
  expect(screen.queryByText('全部现金 1 条')).toBeNull();
  expect(await screen.findByText('合成标的 SYN001')).toBeTruthy();
  expect(await screen.findByText('合成基金 FUND001')).toBeTruthy();
  expect((await screen.findAllByText('现金利息')).length).toBeGreaterThan(0);
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

  expect(await screen.findByText('没有匹配的流水。')).toBeTruthy();
});

test('keeps immutable history as the primary surface and opens entry tools on demand', async () => {
  renderActivityPage('zh');

  expect(await screen.findByRole('heading', { name: '账本流水' })).toBeTruthy();
  const ledgerTitle = await screen.findByText('最近流水');
  expect(ledgerTitle.className).toContain('app-type-section-title');
  expect(
    document.querySelector('[data-activity-surface="audit-history"]'),
  ).toBeTruthy();
  expect(
    document.querySelector('[data-activity-surface="priority-and-entry"]'),
  ).toBeNull();
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByRole('group', { name: '流水录入工具选择' })).toBeNull();

  const entryTrigger = screen.getByRole('button', { name: '新增流水' });
  expect(entryTrigger.className).toContain('app-button-secondary');
  expect(entryTrigger.className).not.toContain('app-button-primary');
  expect(document.querySelector('.activity-summary-strip')).toBeTruthy();
  expect(
    screen.getByRole('group', { name: '流水分类筛选' }).className,
  ).toContain('overflow-x-auto');

  fireEvent.click(entryTrigger);

  const dialog = await screen.findByRole('dialog', { name: '新增流水' });
  const toolButtons = within(dialog)
    .getAllByRole('button')
    .filter((button) =>
      ['手工交易', '资金流水', '分红', '手工调整', '批量基金加仓'].includes(
        button.textContent ?? '',
      ),
    );
  expect(
    dialog.querySelector('[data-workbench-primitive="controlled-action-zone"]'),
  ).toBeTruthy();
  expect(toolButtons.map((button) => button.textContent)).toEqual([
    '手工交易',
    '资金流水',
    '分红',
    '手工调整',
    '批量基金加仓',
  ]);
  expect(screen.queryByLabelText('资金流水发生时间')).toBeNull();

  fireEvent.click(within(dialog).getByRole('button', { name: '资金流水' }));

  expect(await screen.findByLabelText('资金流水发生时间')).toBeTruthy();
  expect(screen.queryByLabelText('证券代码')).toBeNull();
});

test('defers the portfolio positions projection until entry tools open', async () => {
  renderActivityPage('zh');

  expect(await screen.findByText('最近流水')).toBeTruthy();
  const fetchMock = vi.mocked(globalThis.fetch);
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/portfolio/positions'),
    ),
  ).toBe(false);

  fireEvent.click(screen.getByRole('button', { name: '新增流水' }));

  await screen.findByRole('dialog', { name: '新增流水' });
  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/portfolio/positions'),
    ),
  ).toBe(true);
});

test('reuses an unknown cash-flow request identity and rotates it after success', async () => {
  const fetchMock = renderActivityPage('zh');
  await screen.findByText('最近流水');
  const defaultFetch = fetchMock.getMockImplementation();
  const mutationBodies: Array<Record<string, unknown>> = [];
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/api/ledger/cash-flows')) {
      mutationBodies.push(JSON.parse(String(init?.body)));
      if (mutationBodies.length === 1) {
        throw new TypeError('network response lost');
      }
      return jsonResponse({ id: mutationBodies.length });
    }
    return (
      defaultFetch?.(input, init) ?? new Response('Not found', { status: 404 })
    );
  });

  fireEvent.click(screen.getByRole('button', { name: '新增流水' }));
  const dialog = await screen.findByRole('dialog', { name: '新增流水' });
  fireEvent.click(within(dialog).getByRole('button', { name: '资金流水' }));
  const occurredAt = await screen.findByLabelText('资金流水发生时间');
  const amount = screen.getByLabelText('金额');
  const submit = screen.getByRole('button', { name: '保存资金流水' });
  fireEvent.change(occurredAt, { target: { value: '2026-08-26T10:00' } });
  fireEvent.change(amount, { target: { value: '100' } });

  fireEvent.click(submit);
  await waitFor(() => expect(mutationBodies).toHaveLength(1));
  await waitFor(() => expect(submit.hasAttribute('disabled')).toBe(false));

  fireEvent.click(submit);
  await waitFor(() => expect(mutationBodies).toHaveLength(2));
  expect(mutationBodies[1]?.request_id).toBe(mutationBodies[0]?.request_id);
  expect(mutationBodies[1]?.operator_id).toBe(mutationBodies[0]?.operator_id);

  await screen.findByText('资金流水已保存');
  fireEvent.change(screen.getByLabelText('资金流水发生时间'), {
    target: { value: '2026-08-26T10:00' },
  });
  fireEvent.change(screen.getByLabelText('金额'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存资金流水' }));

  await waitFor(() => expect(mutationBodies).toHaveLength(3));
  expect(mutationBodies[2]?.request_id).not.toBe(mutationBodies[1]?.request_id);
});

test('retains fund order identities independently after partial batch failure', async () => {
  const fetchMock = renderActivityPage('zh');
  await screen.findByText('最近流水');
  const defaultFetch = fetchMock.getMockImplementation();
  const mutationBodies: Array<Record<string, unknown>> = [];
  let positionsFetchCount = 0;
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/api/portfolio/positions')) {
      positionsFetchCount += 1;
      const positions = [
        { symbol: 'FUND-A', display_name: '基金 A', asset_class: 'fund' },
        { symbol: 'FUND-B', display_name: '基金 B', asset_class: 'fund' },
      ];
      return jsonResponse(
        positionsFetchCount === 1 ? positions : [...positions].reverse(),
      );
    }
    if (url.includes('/api/portfolio/trade')) {
      mutationBodies.push(JSON.parse(String(init?.body)));
      if (mutationBodies.length === 2) {
        throw new TypeError('network response lost');
      }
      if (mutationBodies.length === 3) {
        return new Response(JSON.stringify({ detail: 'fund order failed' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return jsonResponse({ id: mutationBodies.length });
    }
    return (
      defaultFetch?.(input, init) ?? new Response('Not found', { status: 404 })
    );
  });

  fireEvent.click(screen.getByRole('button', { name: '新增流水' }));
  const dialog = await screen.findByRole('dialog', { name: '新增流水' });
  fireEvent.click(within(dialog).getByRole('button', { name: '批量基金加仓' }));
  fireEvent.change(await screen.findByLabelText('FUND-A 申购金额'), {
    target: { value: '100' },
  });
  fireEvent.change(screen.getByLabelText('FUND-B 申购金额'), {
    target: { value: '200' },
  });

  fireEvent.click(screen.getByRole('button', { name: '保存批量加仓' }));
  await waitFor(() => expect(mutationBodies).toHaveLength(2));
  await waitFor(() =>
    expect(
      screen
        .getByRole('button', { name: '保存批量加仓' })
        .hasAttribute('disabled'),
    ).toBe(false),
  );

  const firstFundA = mutationBodies[0];
  const firstFundB = mutationBodies[1];
  expect(firstFundA?.symbol).toBe('FUND-A');
  expect(firstFundB?.symbol).toBe('FUND-B');
  await waitFor(() =>
    expect(
      screen
        .getAllByRole('spinbutton')
        .map((input) => input.getAttribute('aria-label')),
    ).toEqual(['FUND-B 申购金额', 'FUND-A 申购金额']),
  );

  fireEvent.change(screen.getByLabelText('FUND-A 申购金额'), {
    target: { value: '150' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批量加仓' }));
  expect(
    await screen.findAllByText('Saved fund order changed: FUND-A'),
  ).not.toHaveLength(0);
  expect(mutationBodies).toHaveLength(2);

  fireEvent.change(screen.getByLabelText('FUND-A 申购金额'), {
    target: { value: '100' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批量加仓' }));
  await waitFor(() => expect(mutationBodies).toHaveLength(3));
  expect(mutationBodies[2]?.symbol).toBe('FUND-B');
  expect(mutationBodies[2]?.command_id).toBe(firstFundB?.command_id);
  expect(
    mutationBodies.filter((body) => body.symbol === 'FUND-A'),
  ).toHaveLength(1);

  fireEvent.change(screen.getByLabelText('FUND-B 申购金额'), {
    target: { value: '250' },
  });
  fireEvent.click(screen.getByRole('button', { name: '保存批量加仓' }));
  await waitFor(() => expect(mutationBodies).toHaveLength(4));
  expect(mutationBodies[3]?.symbol).toBe('FUND-B');
  expect(mutationBodies[3]?.amount).toBe(250);
  expect(mutationBodies[3]?.command_id).not.toBe(firstFundB?.command_id);
  expect(
    mutationBodies.filter((body) => body.symbol === 'FUND-A'),
  ).toHaveLength(1);
  await screen.findByText('交易已保存');
});

test('keeps financial direction colors separate from system state colors', async () => {
  renderActivityPage('zh');

  const creditAmount = await screen.findByText('+¥0.27');
  const debitAmount = await screen.findByText('-¥3,255.16');

  expect(creditAmount.className).toContain('var(--app-pnl-positive)');
  expect(debitAmount.className).toContain('var(--app-pnl-negative)');
  expect(creditAmount.className).not.toContain('var(--app-success)');
  expect(debitAmount.className).not.toContain('var(--app-danger)');
});
