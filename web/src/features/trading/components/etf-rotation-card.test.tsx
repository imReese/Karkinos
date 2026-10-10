import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type { EtfRotationDashboardResponse } from '../api-etf-rotation';
import { EtfRotationTradingCard } from './etf-rotation-card';
import { EtfRotationOverviewPanel } from '../../overview/components/overview-etf-rotation-panel';

function makeFixtureData(
  overrides?: Partial<EtfRotationDashboardResponse>,
): EtfRotationDashboardResponse {
  return {
    status: 'success',
    strategy: {
      strategy_name: '全球大类资产跨市场轮动策略',
      universe_summary: '8 支核心标的',
      backtest_range: '2021-01-04 至 2026-10-09',
      cumulative_return_pct: 160.53,
      cagr_pct: 18.94,
      max_drawdown_pct: 11.87,
      sharpe_ratio: 1.09,
      calmar_ratio: 1.6,
      benchmark_name: '沪深300ETF (510300)',
      benchmark_return_pct: -8.65,
      excess_return_pct: 169.18,
    },
    rebalance: {
      status: 'success',
      plan_id: 'PLAN-20261009-ABC12345',
      evaluated_at: '2026-10-09T15:00:00+08:00',
      as_of_date: '2026-10-09',
      total_equity: 200000.0,
      capital_source: 'available_cash',
      is_demo: false,
      is_custom_simulation: false,
      account_available: true,
      available_cash: 200000.0,
      turnover_ratio: 0.5,
      total_sell_amount: 0.0,
      total_buy_amount: 100000.0,
      estimated_net_cash_flow: -100000.0,
      orders_count: 1,
      orders: [
        {
          symbol: '512890',
          name: '红利低波ETF',
          side: 'buy',
          side_display: '买入',
          quantity: 10000,
          price: 2.15,
          amount: 21500.0,
          target_weight: 0.5,
          current_weight: 0.0,
          reason: '动量前两名',
        },
      ],
    },
    orders: [
      {
        symbol: '512890',
        name: '红利低波ETF',
        side: 'buy',
        side_display: '买入',
        quantity: 10000,
        price: 2.15,
        amount: 21500.0,
        target_weight: 0.5,
        current_weight: 0.0,
        reason: '动量前两名',
      },
    ],
    execution_status: 'ready_to_trade',
    has_pending_orders: true,
    can_execute: true,
    is_demo: false,
    is_custom_simulation: false,
    capital_quarantined: false,
    last_execution: null,
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('does NOT display last_execution receipt when its plan_id does not match current plan_id', () => {
  const data = makeFixtureData({
    execution_status: 'ready_to_trade',
    last_execution: {
      status: 'success',
      plan_id: 'PLAN-OLD-DIFFERENT',
      batch_id: 'BATCH-OLD',
      executed_at: '2026-10-08T15:00:00+08:00',
      operator: 'reese',
      note: 'old receipt',
      broker_mode: 'simulation_preview',
      orders_count: 1,
      total_sell_amount: 0,
      total_buy_amount: 10000,
      executed_orders: [],
      message: '旧计划的调仓试算',
    },
  });

  renderWithClient(<EtfRotationTradingCard data={data} />);
  expect(screen.queryByText(/模拟调仓试算已记录/)).toBeNull();
  expect(screen.queryByText(/BATCH-OLD/)).toBeNull();
});

test('displays active success receipt when execution_status is already_executed_today and plan_id matches', () => {
  const data = makeFixtureData({
    execution_status: 'already_executed_today',
    can_execute: false,
    last_execution: {
      status: 'success',
      plan_id: 'PLAN-20261009-ABC12345',
      batch_id: 'BATCH-CURRENT-123',
      executed_at: '2026-10-09T15:00:00+08:00',
      operator: 'reese',
      note: 'current receipt',
      broker_mode: 'simulation_preview',
      orders_count: 1,
      total_sell_amount: 0,
      total_buy_amount: 21500,
      executed_orders: [],
      message: '当前计划的模拟调仓试算已记录',
    },
  });

  renderWithClient(<EtfRotationTradingCard data={data} />);
  expect(screen.getByText(/BATCH-CURRENT-123/)).toBeDefined();
  expect(screen.getByText('当前计划的模拟调仓试算已记录')).toBeDefined();
});

test('displays rejection feedback when mutation returns rejected status', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: 'rejected',
        plan_id: 'PLAN-20261009-ABC12345',
        message: '演示资金隔离模式下已阻止记录调仓试算',
        executed_orders: [],
      }),
    }),
  );

  const data = makeFixtureData({ can_execute: true });
  renderWithClient(<EtfRotationTradingCard data={data} />);

  const button = screen.getByRole('button', { name: /模拟调仓试算/ });
  fireEvent.click(button);

  await waitFor(() => {
    expect(screen.getByText('调仓试算请求已被拒绝')).toBeDefined();
    expect(
      screen.getByText('演示资金隔离模式下已阻止记录调仓试算'),
    ).toBeDefined();
  });
});

test('displays network error feedback when execute mutation fails', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockRejectedValue(new Error('Failed to fetch from server')),
  );

  const data = makeFixtureData({ can_execute: true });
  renderWithClient(<EtfRotationTradingCard data={data} />);

  const button = screen.getByRole('button', { name: /模拟调仓试算/ });
  fireEvent.click(button);

  await waitFor(() => {
    expect(
      screen.getByText('调仓试算请求失败 (网络或服务器异常)'),
    ).toBeDefined();
    expect(screen.getByText('Failed to fetch from server')).toBeDefined();
  });
});

test('overview panel displays rejection feedback when execute mutation is rejected', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        status: 'rejected',
        plan_id: 'PLAN-20261009-ABC12345',
        message: '当前调仓计划基于自定义假设输入，已阻止记录',
        executed_orders: [],
      }),
    }),
  );

  const data = makeFixtureData({ can_execute: true });
  renderWithClient(<EtfRotationOverviewPanel data={data} />);

  const button = screen.getByRole('button', { name: /模拟调仓试算/ });
  fireEvent.click(button);

  await waitFor(() => {
    expect(screen.getByText('调仓试算请求已被拒绝')).toBeDefined();
    expect(
      screen.getByText('当前调仓计划基于自定义假设输入，已阻止记录'),
    ).toBeDefined();
  });
});

test('displays dataset verified badge, dataset id, and report link when bound to verified dataset', () => {
  const data = makeFixtureData({
    strategy: {
      ...makeFixtureData().strategy,
      verification_status: 'bound_dataset_verified',
      dataset_id: 'sha256:112233445566778899aabbccddeeff00',
      report_url: '/research?tab=backtest&id=42',
    },
  });
  renderWithClient(<EtfRotationTradingCard data={data} />);

  expect(screen.getByTestId('dataset-verified-badge')).toBeDefined();
  expect(screen.getByText('不可变 Dataset 已验证')).toBeDefined();
  expect(screen.getByText(/数据集: sha256:11223344/)).toBeDefined();
  expect(screen.getByRole('link', { name: /查看回测报告/ })).toBeDefined();
});

test('displays forward paper book tracking card when paper_book is provided', () => {
  const data = makeFixtureData({
    paper_book: {
      book_id: 'book-etf-test-1',
      observation_id: 'obs-etf-test-1',
      settled_sessions: 15,
      equity: '105230.50',
      net_return: '0.0523',
      net_return_pct: 5.23,
      max_drawdown: '0.021',
      max_drawdown_pct: 2.1,
      fees_paid: '45.00',
      slippage_cost: '62.50',
      health_status: 'within_rule',
      through_session: '2026-10-09',
      evaluation_start: '2026-09-01',
    },
  });
  renderWithClient(<EtfRotationTradingCard data={data} />);

  expect(screen.getByTestId('etf-paper-book-forward-card')).toBeDefined();
  expect(screen.getByText('15 个交易日已结算')).toBeDefined();
  expect(screen.getByTestId('paper-health-status')).toBeDefined();
  expect(screen.getByText('策略健康度正常 (within_rule)')).toBeDefined();
  expect(screen.getByTestId('paper-net-return').textContent).toContain(
    '+5.23%',
  );
  expect(screen.getByTestId('paper-max-drawdown').textContent).toContain(
    '2.10%',
  );
  expect(screen.getByTestId('paper-costs').textContent).toContain('¥107.50');
  expect(screen.getByTestId('paper-equity').textContent).toContain(
    '105,230.50',
  );
});

test('overview panel displays forward paper book strip when paper_book is present', () => {
  const data = makeFixtureData({
    paper_book: {
      book_id: 'book-etf-test-1',
      observation_id: 'obs-etf-test-1',
      settled_sessions: 8,
      equity: '102100.00',
      net_return: '0.021',
      net_return_pct: 2.1,
      max_drawdown: '0.015',
      max_drawdown_pct: 1.5,
      fees_paid: '20.00',
      slippage_cost: '30.00',
      health_status: 'within_rule',
      through_session: '2026-10-09',
      evaluation_start: '2026-09-01',
    },
  });
  renderWithClient(<EtfRotationOverviewPanel data={data} />);

  const strip = screen.getByTestId('overview-paper-book-strip');
  expect(strip).toBeDefined();
  expect(strip.textContent).toContain('前向 Paper Book:');
  expect(strip.textContent).toContain('+2.10%');
  expect(strip.textContent).toContain('8日结算');
});
