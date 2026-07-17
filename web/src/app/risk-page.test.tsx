import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from './preferences';
import { RiskPage } from './router';

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

const accountState = {
  summary: {
    total_equity: 120000,
    available_cash: 24000,
    total_deposits: 100000,
    positions_count: 3,
    unrealized_pnl: 1800,
    realized_pnl: 200,
    cash_ratio: 0.2,
    valuation_timestamp: '2026-06-12T15:00:00+08:00',
    quote_status: 'live',
  },
  snapshot: {
    cash: 24000,
    total_equity: 120000,
    total_deposits: 100000,
    positions: [
      {
        symbol: '600003',
        name: '示例制造',
        display_name: '示例制造',
        asset_class: 'stock',
        quantity: 200,
        available_qty: 200,
        frozen_qty: 0,
        avg_cost: 16.2345,
        market_value: 3252,
        unrealized_pnl: -3.16,
        realized_pnl: 0,
        commission_paid: 5.16,
      },
    ],
    allocation: [
      {
        symbol: '600519',
        name: '贵州茅台',
        weight: 0.34,
        value: 40800,
        asset_class: 'stock',
      },
    ],
    allocation_grouped: [],
  },
  risks: [],
  next_step: 'Review manual confirmations before any execution.',
};

const riskAlerts = [
  {
    kind: 'cash_buffer',
    level: 'medium',
    title: 'Cash buffer is close to the floor',
    detail: 'Cash ratio is 20%; review before adding new buy orders.',
  },
];

const riskWorkspace = {
  metrics: [
    {
      key: 'cash_ratio',
      label: 'Cash ratio',
      value: 0.2,
      display_value: '20.0%',
      level: 'medium',
      detail: 'Immediate liquidity buffer.',
    },
  ],
  drawdown: {
    current_drawdown: 0.01,
    max_drawdown: 0.08,
    latest_equity: 120000,
    peak_equity: 121200,
    peak_timestamp: '2026-06-11T15:00:00+08:00',
    trough_timestamp: '2026-06-12T15:00:00+08:00',
  },
  drawdown_series: [
    {
      timestamp: '2026-06-12T15:00:00+08:00',
      equity: 120000,
      peak_equity: 121200,
      drawdown: 0.01,
    },
  ],
  exposure_buckets: [],
  concentration: [],
};

const explainability = {
  equity_bridge: [],
  recent_drivers: [
    {
      kind: 'trade_buy',
      title: '买入 600003',
      detail: '数量 200 · 价格 ¥16.25 · 手续费 ¥5.00',
      timestamp: '2026-01-15T03:04:56+00:00',
      symbol: '600003',
      quantity: 200,
      price: 16.25,
      commission: 5,
      gross_amount: 3250,
      net_cash_impact: -3255,
      amount: -3255,
    },
    {
      kind: 'cash_deposit',
      title: 'cash_deposit',
      detail: 'RMB cash deposit recorded from user request',
      timestamp: '2026-04-01T00:00:00+00:00',
      symbol: null,
      amount: 3000,
    },
  ],
  positions: [
    {
      symbol: '600003',
      quantity: 200,
      market_value: 3252,
      unrealized_pnl: -3.16,
      last_activity_at: '2026-01-15T03:04:56+00:00',
    },
  ],
  timeline: [
    {
      date: '2026-04-01',
      equity: 3000,
      delta: 0,
      external_flow: 3000,
      market_pnl: 0,
      events: [
        {
          category: 'capital',
          impact_source: 'external',
          kind: 'cash_deposit',
          title: 'cash_deposit',
          detail: 'RMB cash deposit recorded from user request',
          timestamp: '2026-04-01T00:00:00+00:00',
          symbol: null,
          amount: 3000,
        },
      ],
    },
  ],
};

const pendingManualOrder = {
  id: 1,
  order_id: 'ORD-RISK-1',
  timestamp: '2026-01-15T11:04:56+08:00',
  symbol: '600003',
  side: 'buy',
  order_type: 'limit',
  quantity: 200,
  price: 16.25,
  intent_id: 'INT-RISK-1',
  risk_decision_id: 'RISK-1',
  execution_mode: 'manual',
  status: 'pending_confirm',
  payload_json: '{"intent_id":"INT-RISK-1","risk_decision_id":"RISK-1"}',
  note: null,
  created_at: '2026-01-15T11:04:56+08:00',
  updated_at: '2026-01-15T11:04:56+08:00',
};

const decisionNeedsRiskGate = {
  lane: 'daily',
  decision_date: '2026-06-12',
  generated_at: '2026-06-12T09:31:00+08:00',
  decision: 'review_required',
  requires_manual_confirmation: false,
  summary: {
    candidate_count: 50,
    risk_blocked_count: 0,
    ready_for_manual_confirmation_count: 0,
    workflow_tasks: [
      {
        id: 'risk_review',
        priority: 30,
        status: 'review_required',
        title: 'Risk review',
        description: 'Candidates have not passed the pre-trade risk gate.',
        required_actions: ['run_pre_trade_risk_gate'],
        blocking_reasons: ['risk_gate_not_checked'],
        evidence: {
          total_action_count: 50,
          risk_checked_count: 0,
          risk_blocked_count: 0,
        },
      },
    ],
  },
  candidates: [],
  no_action_reasons: [],
};

function installRiskFetchMock({
  manualOrders = [],
  riskAlertsResponse = riskAlerts,
  decisionResponse = decisionNeedsRiskGate,
  batchRiskResponse,
}: {
  manualOrders?: unknown[];
  riskAlertsResponse?: unknown[];
  decisionResponse?: unknown;
  batchRiskResponse?: unknown;
} = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : input.toString();

    if (url.includes('/api/decision/pre-trade-risk/batch')) {
      return jsonResponse(
        batchRiskResponse ?? {
          schema_version: 'karkinos.pre_trade_risk_batch.v1',
          status: 'completed',
          processed_count: 50,
          passed_count: 48,
          blocked_count: 2,
          skipped_count: 0,
          candidate_count: 50,
          does_not_create_order: true,
          does_not_submit_broker_order: true,
          does_not_write_ledger: true,
          risk_decision_writes_performed: true,
          default_execution_mode: 'manual_confirmation',
          results: [],
        },
      );
    }
    if (url.includes('/api/portfolio/state')) {
      return jsonResponse(accountState);
    }
    if (url.includes('/api/portfolio/positions')) {
      return jsonResponse(accountState.snapshot.positions);
    }
    if (url.includes('/api/portfolio/risk-summary')) {
      return jsonResponse(riskAlertsResponse);
    }
    if (url.includes('/api/portfolio/risk-workspace')) {
      return jsonResponse(riskWorkspace);
    }
    if (url.includes('/api/decision/today')) {
      return jsonResponse(decisionResponse);
    }
    if (url.includes('/api/portfolio/explainability')) {
      return jsonResponse(explainability);
    }
    if (url.includes('/api/trading/kill-switch')) {
      return jsonResponse({
        kill_switch_enabled: false,
        reason: '',
        updated_at: null,
      });
    }
    if (url.includes('/api/trading/orders')) {
      return jsonResponse(manualOrders);
    }
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderRiskPage(options?: {
  locale?: 'en' | 'zh';
  manualOrders?: unknown[];
  riskAlertsResponse?: unknown[];
  decisionResponse?: unknown;
  batchRiskResponse?: unknown;
}) {
  window.localStorage.clear();
  if (options?.locale) {
    window.localStorage.setItem('karkinos.locale', options.locale);
  }
  const fetchMock = installRiskFetchMock({
    manualOrders: options?.manualOrders,
    riskAlertsResponse: options?.riskAlertsResponse,
    decisionResponse: options?.decisionResponse,
    batchRiskResponse: options?.batchRiskResponse,
  });
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <RiskPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { fetchMock, queryClient };
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders risk boundaries and blocking register without execution controls', async () => {
  renderRiskPage();

  expect(await screen.findByText('Risk control center')).toBeTruthy();
  const handoff = await screen.findByTestId('risk-decision-handoff');
  expect(handoff.textContent).toContain(
    'Run pre-trade risk gate for candidates',
  );
  expect(handoff.textContent).toContain(
    '50 candidates are waiting for risk checks; 0 have been checked.',
  );
  expect(
    within(handoff).getByRole('button', { name: 'Run batch risk gate' }),
  ).toBeTruthy();
  expect(
    within(handoff)
      .getByRole('link', { name: 'Return to decision platform' })
      .getAttribute('href'),
  ).toBe('/decision');

  const controlGrid = await screen.findByTestId('risk-trading-control-grid');
  expect(controlGrid.className).toContain('gap-3');
  expect(
    within(controlGrid)
      .getByTestId('kill-switch-panel')
      .getAttribute('data-layout'),
  ).toBe('compact-control');
  expect(
    within(controlGrid)
      .getByTestId('order-approval-panel')
      .getAttribute('data-layout'),
  ).toBe('compact-approval');

  expect(await screen.findByText('Risk boundary register')).toBeTruthy();
  expect(await screen.findByText('Blocking register')).toBeTruthy();

  const boundaryRegister = await screen.findByTestId('risk-boundary-register');
  expect(boundaryRegister.className).toContain('min-w-0');
  expect(
    within(boundaryRegister).getByLabelText(
      'Risk boundary item: Cash Buffer 20.0% Healthy reserve',
    ),
  ).toBeTruthy();
  expect(
    within(boundaryRegister).getByText('Manual confirmation required'),
  ).toBeTruthy();

  const blockRegister = await screen.findByTestId('risk-blocking-register');
  expect(blockRegister.className).toContain('min-w-0');
  expect(within(blockRegister).getByText('Cash Buffer')).toBeTruthy();
  expect(within(blockRegister).queryByText('cash_buffer')).toBeNull();
  expect(within(blockRegister).getByText('Warning')).toBeTruthy();
  expect(within(blockRegister).queryByText('medium')).toBeNull();
  expect(
    within(blockRegister).getByText('Cash buffer is close to the floor'),
  ).toBeTruthy();
  expect(screen.queryByText(/automatic execution/i)).toBeNull();
});

test('localizes decision risk handoff without asking users to inspect every risk metric', async () => {
  renderRiskPage({ locale: 'zh' });

  const handoff = await screen.findByTestId('risk-decision-handoff');
  expect(handoff.textContent).toContain('候选动作需要下单前风控');
  expect(handoff.textContent).toContain(
    '50 个候选等待风控检查；当前已检查 0 个。',
  );
  expect(
    within(handoff).getByRole('button', { name: '运行批量风控' }),
  ).toBeTruthy();
  expect(handoff.textContent).toContain('不要逐个翻候选，也不要直接下单。');
  expect(
    within(handoff)
      .getByRole('link', { name: '回到决策平台' })
      .getAttribute('href'),
  ).toBe('/decision');
});

test('runs batch pre-trade risk gate from the risk handoff panel', async () => {
  const user = userEvent.setup();
  const { fetchMock } = renderRiskPage({ locale: 'zh' });

  const handoff = await screen.findByTestId('risk-decision-handoff');
  await user.click(
    within(handoff).getByRole('button', { name: '运行批量风控' }),
  );

  expect(
    fetchMock.mock.calls.some(([input]) =>
      String(input).includes('/api/decision/pre-trade-risk/batch'),
    ),
  ).toBe(true);
  expect(
    await screen.findByText('批量风控完成：通过 48，阻断 2。'),
  ).toBeTruthy();
});

test('explains data-quality blocking without claiming that risk ran', async () => {
  const user = userEvent.setup();
  renderRiskPage({
    locale: 'zh',
    batchRiskResponse: {
      schema_version: 'karkinos.pre_trade_risk_batch.v1',
      status: 'blocked_by_data_quality',
      processed_count: 0,
      passed_count: 0,
      blocked_count: 0,
      skipped_count: 3,
      candidate_count: 3,
      does_not_create_order: true,
      does_not_submit_broker_order: true,
      does_not_write_ledger: true,
      risk_decision_writes_performed: false,
      database_writes_performed: false,
      persisted_facts_only: true,
      valuation_snapshot_id: 'valuation-fixture',
      ledger_cutoff_id: 21,
      valuation_status: 'degraded',
      blockers: [
        {
          code: 'valuation_snapshot_not_complete',
          status: 'degraded',
        },
      ],
      default_execution_mode: 'manual_confirmation',
      results: [],
    },
  });

  const handoff = await screen.findByTestId('risk-decision-handoff');
  await user.click(
    within(handoff).getByRole('button', { name: '运行批量风控' }),
  );

  expect(
    await within(handoff).findByText(
      '批量风控未运行：估值或行情证据尚未完整，已跳过 3 个候选。未写入风险决策、订单或账本；请先处理数据状态后重试。',
    ),
  ).toBeTruthy();
  expect(handoff.textContent).not.toContain('批量风控完成');
});

test('keeps the last persisted risk projection visible when a post-run refresh fails', async () => {
  const user = userEvent.setup();
  const { fetchMock, queryClient } = renderRiskPage({ locale: 'zh' });

  const handoff = await screen.findByTestId('risk-decision-handoff');
  await user.click(
    within(handoff).getByRole('button', { name: '运行批量风控' }),
  );
  expect(
    await screen.findByText('批量风控完成：通过 48，阻断 2。'),
  ).toBeTruthy();

  fetchMock.mockRejectedValueOnce(new Error('temporary refresh failure'));
  await act(async () => {
    await queryClient.refetchQueries({
      queryKey: ['portfolio-risk-workspace'],
      exact: true,
    });
  });

  expect(
    await screen.findByText(
      '部分风控数据暂时无法刷新。当前显示最近一次成功加载的持久化投影，继续操作前请复核数据状态。',
    ),
  ).toBeTruthy();
  expect(screen.getByText('现金占比')).toBeTruthy();
  expect(screen.queryByText('风控中心加载失败。')).toBeNull();
});

test('localizes risk blocking detail codes before rendering alerts', async () => {
  renderRiskPage({
    riskAlertsResponse: [
      {
        ...riskAlerts[0],
        detail: 'quote_older_than_expected_session',
      },
    ],
    locale: 'zh',
  });

  const blockRegister = await screen.findByTestId('risk-blocking-register');

  expect(within(blockRegister).getByText('行情早于预期交易时段')).toBeTruthy();
  expect(blockRegister.textContent).not.toContain(
    'quote_older_than_expected_session',
  );
});

test('shows instrument names before symbols in risk manual approval rows', async () => {
  renderRiskPage({ manualOrders: [pendingManualOrder] });

  expect(await screen.findByText('Pending order approvals')).toBeTruthy();
  expect(await screen.findByText('示例制造 600003')).toBeTruthy();
  expect(screen.queryByText(/^600003$/u)).toBeNull();
  expect(screen.getByLabelText('Reject reason: 示例制造 600003')).toBeTruthy();
});

test('renders recent risk drivers as readable audit events', async () => {
  renderRiskPage();

  const recentDrivers = await screen.findByText('Recent impact events');
  expect(recentDrivers).toBeTruthy();
  expect(await screen.findByText('Buy 示例制造 600003')).toBeTruthy();
  expect(
    await screen.findByText(
      'Gross amount ¥3,250.00 · Cash impact -¥3,255.00 · Quantity 200 · Price ¥16.25 · Fee ¥5.00',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText('数量 200 · 价格 ¥16.25 · 手续费 ¥5.00'),
  ).toBeNull();
  expect(
    (await screen.findAllByText(/-.*¥3,255\.00/)).length,
  ).toBeGreaterThanOrEqual(2);
  expect(await screen.findAllByText('Amount ¥3,000.00')).toHaveLength(2);
  expect(screen.queryByText('现金流入组合。')).toBeNull();
  expect(
    screen.queryByText('RMB cash deposit recorded from user request'),
  ).toBeNull();
  expect(screen.queryByText('2026-01-15T03:04:56+00:00')).toBeNull();
});

test('localizes risk explainability ledger titles instead of rendering internal kinds', async () => {
  renderRiskPage({ locale: 'zh' });

  const recentList = await screen.findByTestId('risk-recent-impact-list');
  expect(within(recentList).getByText('资金转入')).toBeTruthy();
  expect(await screen.findAllByText(/金额\s+¥3,000\.00/u)).toHaveLength(2);
  expect(document.body.textContent).not.toContain('cash_deposit');
});

test('uses account instrument names for risk explainability events that only carry symbols', async () => {
  renderRiskPage({ locale: 'zh' });

  const recentList = await screen.findByTestId('risk-recent-impact-list');
  expect(within(recentList).getByText('买入 示例制造 600003')).toBeTruthy();
  expect(
    within(recentList).getByText(
      '成交金额 ¥3,250.00 · 现金影响 -¥3,255.00 · 数量 200 · 价格 ¥16.25 · 手续费 ¥5.00',
    ),
  ).toBeTruthy();
  expect(recentList.textContent).not.toContain('买入 600003');
});

test('keeps explainability columns compact with local event scrolling', async () => {
  renderRiskPage();

  const topGrid = await screen.findByTestId('risk-explainability-top-grid');
  expect(topGrid.className).toContain('items-start');

  const recentList = await screen.findByTestId('risk-recent-impact-list');
  expect(recentList.className).toContain('max-h');
  expect(recentList.className).toContain('overflow-y-auto');
});
