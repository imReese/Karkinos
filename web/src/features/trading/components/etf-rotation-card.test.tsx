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
