import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { DecisionResponse } from '../api';
import { DecisionCockpitPage } from './decision-cockpit-page';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const dailyDecision: DecisionResponse = {
  lane: 'daily',
  decision_date: '2026-06-12',
  generated_at: '2026-06-12T09:31:00+08:00',
  decision: 'buy',
  requires_manual_confirmation: true,
  summary: {
    candidate_count: 1,
    risk_blocked_count: 0,
    ready_for_manual_confirmation_count: 1,
    portfolio: {
      status: 'available',
      cash: 12000,
      position_count: 2,
      symbols: ['600519', '510300'],
      total_market_value: 28000,
      total_equity: 40000,
    },
    market_data: {
      source_health: 'partial',
      quote_count: 2,
      live_quote_count: 1,
      stale_quote_count: 1,
      missing_symbols: [],
      latest_quote_timestamp: '2026-06-12T09:30:00+08:00',
      has_persistent_cache: true,
    },
    action_tasks: {
      total_count: 1,
      pending_count: 1,
      deferred_count: 0,
      symbols: ['600519'],
    },
    audit: {
      signal_count: 1,
      journal_entry_count: 1,
      risk_checked_count: 1,
      risk_blocked_count: 0,
    },
    account_truth: {
      gate_status: 'pass',
      score: 98,
      has_evidence: true,
      unresolved_mismatch_count: 0,
      required_actions: [],
      blocking_reasons: [],
      limitations: [],
      components: {
        cash: { status: 'pass' },
        position: { status: 'pass' },
        fee: { status: 'pass' },
        cost_basis: { status: 'pass' },
      },
    },
  },
  candidates: [
    {
      action_id: 9,
      action: 'buy',
      symbol: '600519',
      asset_class: 'stock',
      title: 'Increase 600519',
      detail:
        '双均线策略触发目标权重 20%，需要人工确认；这是一段很长的中文证据说明，用来验证窄屏和浏览器 125% 缩放时不会把候选动作卡片从右侧裁掉。',
      urgency: 'high',
      target_weight: 0.2,
      price: 123.45,
      risk_gate_status: 'passed',
      manual_confirmation_required: true,
      manual_confirmation_status: 'ready_for_manual_confirmation',
      evidence: {
        strategy: { strategy_id: 'dual_ma' },
        signal: {
          id: 1,
          timestamp: '2026-06-12T09:30:00+08:00',
          strategy_id: 'dual_ma',
          symbol: '600519',
          target_weight: 0.2,
        },
        risk_gate: {
          status: 'passed',
          decision_id: 'RISK-1',
          passed: true,
          severity: 'info',
          reasons: [],
        },
        after_cost_oos_validation: {
          status: 'attached',
          strategy_id: 'dual_ma',
          backtest_result_id: 101,
          has_after_cost_report: true,
          has_out_of_sample_validation: true,
          missing_requirements: [],
          after_cost: { net_return: 0.08 },
          oos_validation: { validation_status: 'passed' },
          cost_summary: { commission: 12.3, slippage: 4.5 },
          limitations: ['Backtest evidence is not a profitability claim.'],
        },
        data_freshness: {
          status: 'live',
          quote_timestamp: '2026-06-12T09:30:00+08:00',
          quote_source: 'fixture',
          price: 123.45,
        },
        manual_confirmation: {
          required: true,
          status: 'ready_for_manual_confirmation',
          reason: 'Risk gate passed; operator confirmation is still required.',
        },
        journal: {
          has_journal_entry: true,
          latest_event_type: 'risk.signal.recorded',
          latest_event_source: 'risk_decisions',
          latest_event_ref: 'RISK-1',
        },
        account_truth: {
          gate_status: 'pass',
          score: 98,
          has_evidence: true,
          unresolved_mismatch_count: 0,
          required_actions: [],
          blocking_reasons: [],
          limitations: [],
          components: {
            cash: { status: 'pass' },
            position: { status: 'pass' },
            fee: { status: 'pass' },
            cost_basis: { status: 'pass' },
          },
        },
        paper_shadow: {
          status: 'review_required',
          has_evidence: false,
          required_actions: ['review_paper_shadow_evidence'],
          blocking_reasons: [
            'paper_shadow_evidence_required_before_manual_confirmation',
          ],
        },
        cost_impact: {
          status: 'estimated_from_research_costs',
          source: 'after_cost_oos_validation',
          total_commission: 12.3,
          total_slippage: 4.5,
          cost_summary: { commission: 12.3, slippage: 4.5 },
        },
        uncertainty: {
          status: 'review_required',
          factors: [
            'Backtest evidence is not a profitability claim.',
            'review_paper_shadow_evidence',
          ],
        },
      },
    },
  ],
  no_action_reasons: [],
  limitations: ['Decision platform output is research and portfolio evidence.'],
};

const intradayDecision: DecisionResponse = {
  ...dailyDecision,
  lane: 'intraday',
  decision: 'no_action',
  requires_manual_confirmation: false,
  summary: {
    ...dailyDecision.summary,
    candidate_count: 0,
    ready_for_manual_confirmation_count: 0,
    excluded_daily_count: 1,
  },
  candidates: [],
  excluded_daily_symbols: ['018125'],
  no_action_reasons: ['no_intraday_stock_or_etf_action_tasks'],
};

function installDecisionFetchMock({
  todayResponse = dailyDecision,
  intradayResponse = intradayDecision,
}: {
  todayResponse?: DecisionResponse;
  intradayResponse?: DecisionResponse;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();

      if (url.includes('/api/decision/today')) {
        return jsonResponse(todayResponse);
      }
      if (url.includes('/api/decision/intraday')) {
        return jsonResponse(intradayResponse);
      }
      if (url.includes('/api/signals/actions')) {
        return jsonResponse([
          {
            id: 9,
            source_signal_id: 1,
            symbol: '600519',
            title: 'Increase 600519',
            detail:
              'Risk gate passed; prepare a manual order only if approved.',
            direction: 'buy',
            urgency: 'high',
            target_weight: 0.2,
            price: 123.45,
            strategy_id: 'dual_ma',
            timestamp: '2026-06-12T09:31:00+08:00',
            asset_class: 'stock',
            status: 'pending',
            risk_decision_id: 'RISK-1',
            risk_gate_passed: true,
            risk_gate_status: 'passed',
            risk_gate_severity: 'info',
            risk_gate_reasons: [],
            manual_confirmation_required: true,
            manual_confirmation_status: 'ready_for_manual_confirmation',
            manual_confirmation_reason: 'Risk gate passed.',
          },
        ]);
      }
      if (url.includes('/api/signals/journal')) {
        return jsonResponse([
          {
            signal: {
              id: 1,
              timestamp: '2026-06-12T09:30:00+08:00',
              strategy_id: 'dual_ma',
              symbol: '600519',
              direction: 'buy',
              target_weight: 0.2,
              price: 123.45,
              asset_class: 'stock',
            },
            action_task: null,
            risk_decision: null,
            review: null,
            latest_event: {
              event_type: 'risk.signal.recorded',
              timestamp: '2026-06-12T09:31:00+08:00',
              source: 'risk_decisions',
              source_ref: 'RISK-1',
            },
          },
        ]);
      }
      if (url.includes('/api/trading/actions/9/manual-order')) {
        return jsonResponse({
          order_id: 'manual-order-9',
          status: 'pending_confirm',
        });
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

type RenderDecisionOptions = Parameters<typeof installDecisionFetchMock>[0] & {
  locale?: 'en' | 'zh';
};

function renderDecisionCockpit(options?: RenderDecisionOptions) {
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
  const fetchMock = installDecisionFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <DecisionCockpitPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders daily and intraday decision cockpit evidence without execution', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Decision platform')).toBeTruthy();
  expect(await screen.findByText('Decision command register')).toBeTruthy();
  expect(
    await screen.findByLabelText('Decision register item: Candidate actions 1'),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Manual confirmations 1 ready',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Risk blocks 0 blocked',
    ),
  ).toBeTruthy();
  expect(
    await screen.findByLabelText(
      'Decision register item: Execution default Manual confirmation required',
    ),
  ).toBeTruthy();
  expect((await screen.findAllByText('Daily lane')).length).toBeGreaterThan(0);
  expect((await screen.findAllByText('Intraday lane')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('Decision: Buy')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText('600519')).toBeTruthy();
  expect(await screen.findByText('Risk gate: Passed')).toBeTruthy();
  expect(
    await screen.findByText('Manual: Ready for manual confirmation'),
  ).toBeTruthy();
  expect(await screen.findByText('After-cost/OOS: Attached')).toBeTruthy();
  expect(await screen.findByText('Data freshness: Live')).toBeTruthy();
  expect(await screen.findByText('Account truth: Pass')).toBeTruthy();
  expect(await screen.findByText('Account truth score: 98')).toBeTruthy();
  expect(await screen.findByText('Journal: Risk signal recorded')).toBeTruthy();
  expect(await screen.findByText('Signal action queue')).toBeTruthy();
  expect(await screen.findByText('Prepare manual order')).toBeTruthy();
  expect(await screen.findByText('Signal journal')).toBeTruthy();
  expect(await screen.findByText('Market health: Partial')).toBeTruthy();
  expect(
    await screen.findByText('Portfolio equity: CN¥40,000.00'),
  ).toBeTruthy();
  expect(
    await screen.findByText('No intraday stock or ETF action candidates'),
  ).toBeTruthy();
  expect(
    screen.queryByText('no_intraday_stock_or_etf_action_tasks'),
  ).toBeNull();
  expect(
    screen
      .getByRole('link', { name: 'Open Trading approvals: 600519' })
      .getAttribute('href'),
  ).toBe('/trading');
  expect(screen.queryByText(/automatic execution/i)).toBeNull();
});

test('localizes signal journal audit events without exposing dotted event keys', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Signal journal')).toBeTruthy();
  expect(await screen.findByText('Journal: Risk signal recorded')).toBeTruthy();
  expect(await screen.findByText('Risk signal recorded')).toBeTruthy();
  expect(document.body.textContent).not.toContain('risk.signal.recorded');
});

test('prepares manual orders with public notes instead of internal action ids', async () => {
  const { fetchMock } = renderDecisionCockpit();

  await screen.findByText('Signal action queue');
  fireEvent.click(screen.getByRole('button', { name: 'Prepare manual order' }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/trading/actions/9/manual-order',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  const manualOrderCall = fetchMock.mock.calls.find(([input]) =>
    String(input).includes('/api/trading/actions/9/manual-order'),
  );
  expect(manualOrderCall).toBeTruthy();
  const request = manualOrderCall?.[1];
  const body = JSON.parse(String(request?.body ?? '{}')) as {
    note?: string;
  };
  expect(body.note).toBe('Prepared from Decision action queue.');
  expect(body.note).not.toContain('signal action');
  expect(body.note).not.toContain('9');
});

test('surfaces degraded and blocked account-truth gates in decision summaries', async () => {
  const degradedToday = {
    ...dailyDecision,
    summary: {
      ...dailyDecision.summary,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'degraded',
        score: 64,
        unresolved_mismatch_count: 2,
        required_actions: ['review_position_difference'],
        blocking_reasons: [],
        limitations: ['Broker evidence is stale.'],
        components: {
          ...(dailyDecision.summary.account_truth?.components ?? {}),
          position: { status: 'warning' },
        },
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'account_truth_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          account_truth: {
            ...dailyDecision.candidates[0].evidence.account_truth,
            gate_status: 'degraded',
            score: 64,
            unresolved_mismatch_count: 2,
            required_actions: ['review_position_difference'],
            limitations: ['Broker evidence is stale.'],
            components: {
              ...(dailyDecision.candidates[0].evidence.account_truth
                ?.components ?? {}),
              position: { status: 'warning' },
            },
          },
        },
      },
    ],
  };
  const blockedIntraday = {
    ...intradayDecision,
    summary: {
      ...intradayDecision.summary,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'blocked',
        score: 32,
        has_evidence: false,
        unresolved_mismatch_count: 4,
        required_actions: ['import_and_reconcile_broker_evidence'],
        blocking_reasons: ['account_truth_score_unavailable'],
        limitations: ['Account Truth evidence is missing.'],
        components: {
          cash: { status: 'missing' },
          position: { status: 'missing' },
          fee: { status: 'missing' },
          cost_basis: { status: 'missing' },
        },
      },
    },
  };

  renderDecisionCockpit({
    todayResponse: degradedToday,
    intradayResponse: blockedIntraday,
  });

  expect(
    (await screen.findAllByText('Account truth gate')).length,
  ).toBeGreaterThan(0);
  expect((await screen.findAllByText('Degraded · 64')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('Blocked · 32')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText(/2 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/4 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/Review position difference/)).toBeTruthy();
  expect(
    await screen.findByText(/Import broker evidence and run reconciliation/),
  ).toBeTruthy();
  expect(screen.queryByText(/review_position_difference/)).toBeNull();
  expect(screen.queryByText(/import_and_reconcile_broker_evidence/)).toBeNull();
  expect(
    await screen.findByText('Manual: Account truth review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Account truth: Degraded')).toBeTruthy();
});

test('surfaces strategy-attribution gate status in decision summaries', async () => {
  const blockedToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      strategy_attribution: {
        gate_status: 'blocked',
        strategy_id: 'dual_ma',
        assignment_status: 'active',
        attribution_status: 'not_started',
        contribution_status: 'no_linked_fills',
        has_evidence: false,
        required_actions: [
          'link_strategy_signals_orders_fills_and_contribution',
        ],
        blocking_reasons: ['strategy_attribution_not_ready'],
        limitations: [],
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'strategy_attribution_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          strategy_attribution: {
            gate_status: 'blocked',
            strategy_id: 'dual_ma',
            assignment_status: 'active',
            attribution_status: 'not_started',
            contribution_status: 'no_linked_fills',
            has_evidence: false,
            required_actions: [
              'link_strategy_signals_orders_fills_and_contribution',
            ],
            blocking_reasons: ['strategy_attribution_not_ready'],
            limitations: [],
          },
        },
      },
    ],
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: blockedToday });

  expect(
    (await screen.findAllByText('Strategy attribution gate')).length,
  ).toBeGreaterThan(0);
  expect(
    (await screen.findAllByText('Blocked · dual_ma')).length,
  ).toBeGreaterThan(0);
  expect(
    await screen.findByText(
      /Link strategy signals, reviews, orders, fills, and contribution evidence/,
    ),
  ).toBeTruthy();
  expect(
    screen.queryByText(/link_strategy_signals_orders_fills_and_contribution/),
  ).toBeNull();
  expect(
    await screen.findByText('Manual: Strategy attribution review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Strategy attribution: Blocked')).toBeTruthy();
});

test('renders localized candidate evidence chain for decision review', async () => {
  renderDecisionCockpit({ locale: 'zh' });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect(card.textContent).toContain('候选动作证据链');
  expect(card.textContent).toContain('策略来源');
  expect(card.textContent).toContain('dual_ma');
  expect(card.textContent).toContain('行情状态');
  expect(card.textContent).toContain('实时行情');
  expect(card.textContent).toContain('账户事实');
  expect(card.textContent).toContain('通过');
  expect(card.textContent).toContain('风控状态');
  expect(card.textContent).toContain('已通过');
  expect(card.textContent).toContain('研究证据');
  expect(card.textContent).toContain('已关联');
  expect(card.textContent).toContain('模拟证据');
  expect(card.textContent).toContain('需要复核');
  expect(card.textContent).toContain('成本影响');
  expect(card.textContent).toContain('¥12.30');
  expect(card.textContent).toContain('¥4.50');
  expect(card.textContent).toContain('不确定性');
  expect(card.textContent).toContain('研究证据不代表收益保证');
  expect(card.textContent).toContain('人工确认');
  expect(card.textContent).not.toContain('review_paper_shadow_evidence');
  expect(card.textContent).not.toContain('estimated_from_research_costs');
});

test('marks stale data candidates as review-only instead of certain actions', async () => {
  const staleToday = {
    ...dailyDecision,
    decision: 'review_required',
    requires_manual_confirmation: false,
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      market_data: {
        ...dailyDecision.summary.market_data,
        source_health: 'stale',
        live_quote_count: 0,
        stale_quote_count: 1,
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'data_review_required',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          data_freshness: {
            ...dailyDecision.candidates[0].evidence.data_freshness,
            status: 'stale',
            stale_reason: 'quote_older_than_expected_session',
          },
          certainty: {
            status: 'degraded',
            posture: 'review_required',
            required_actions: ['refresh_or_confirm_market_data'],
            uncertain_reasons: ['quote_older_than_expected_session'],
          },
        },
      },
    ],
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: staleToday, locale: 'zh' });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect((await screen.findAllByText('决策: 需要复核')).length).toBeGreaterThan(
    0,
  );
  expect(card.textContent).toContain('操作确定性');
  expect(card.textContent).toContain('需要先复核数据或账户事实');
  expect(card.textContent).toContain('刷新或确认行情');
  expect(card.textContent).toContain('行情早于预期交易时段');
  expect(card.textContent).toContain('人工确认: 需要数据复核');
  expect(card.textContent).not.toContain('打开交易审批');
  expect(card.textContent).not.toContain('quote_older_than_expected_session');
});

test('localizes no-action, degraded, blocked, and review-required decision states', async () => {
  const localizedToday = {
    ...dailyDecision,
    decision: 'review_required',
    requires_manual_confirmation: false,
    summary: {
      ...dailyDecision.summary,
      ready_for_manual_confirmation_count: 0,
      account_truth: {
        ...dailyDecision.summary.account_truth,
        gate_status: 'degraded',
        score: 72,
        unresolved_mismatch_count: 1,
        required_actions: ['review_position_difference'],
      },
    },
    candidates: [
      {
        ...dailyDecision.candidates[0],
        manual_confirmation_status: 'blocked_by_data_quality',
        evidence: {
          ...dailyDecision.candidates[0].evidence,
          data_freshness: {
            ...dailyDecision.candidates[0].evidence.data_freshness,
            status: 'missing',
            reason: 'missing_latest_quote',
          },
          account_truth: {
            ...dailyDecision.candidates[0].evidence.account_truth,
            gate_status: 'degraded',
            score: 72,
            unresolved_mismatch_count: 1,
            required_actions: ['review_position_difference'],
          },
          certainty: {
            status: 'blocked',
            posture: 'blocked',
            required_actions: ['refresh_market_data'],
            uncertain_reasons: [],
          },
        },
      },
    ],
  } as DecisionResponse;
  const localizedIntraday = {
    ...intradayDecision,
    decision: 'no_action',
    no_action_reasons: ['no_intraday_stock_or_etf_action_tasks'],
  } as DecisionResponse;

  renderDecisionCockpit({
    todayResponse: localizedToday,
    intradayResponse: localizedIntraday,
    locale: 'zh',
  });

  const card = await screen.findByTestId('decision-candidate-card-600519');

  expect((await screen.findAllByText('决策: 需要复核')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('决策: 不操作')).length).toBeGreaterThan(
    0,
  );
  expect(card.textContent).toContain('账户事实: 降级');
  expect(card.textContent).toContain('操作确定性');
  expect(card.textContent).toContain('证据修复前阻断');
  expect(card.textContent).toContain('刷新行情');
  expect(card.textContent).toContain('人工确认: 数据质量阻断');
  expect(await screen.findByText('暂无盘中股票或 ETF 候选动作')).toBeTruthy();
  expect(document.body.textContent).not.toContain('未映射状态');
  expect(document.body.textContent).not.toContain('no_action');
  expect(document.body.textContent).not.toContain('blocked_by_data_quality');
  expect(document.body.textContent).not.toContain(
    'no_intraday_stock_or_etf_action_tasks',
  );
});

test('renders localized decision workflow tasks before candidate actions', async () => {
  const workflowToday = {
    ...dailyDecision,
    decision: 'review_required',
    summary: {
      ...dailyDecision.summary,
      workflow_tasks: [
        {
          id: 'data_refresh',
          priority: 10,
          status: 'degraded',
          title: 'Data refresh',
          description:
            'Some decision quotes are stale, cached, or only partially available.',
          required_actions: ['refresh_or_confirm_market_data'],
          blocking_reasons: ['market_data_not_fully_live'],
          evidence: { source_health: 'partial' },
        },
        {
          id: 'account_truth',
          priority: 20,
          status: 'blocked',
          title: 'Account truth',
          description:
            'Broker evidence and local account facts are checked before action review.',
          required_actions: ['preview_import_and_reconcile_broker_evidence'],
          blocking_reasons: ['account_truth_score_unavailable'],
          evidence: { gate_status: 'blocked', score: null },
        },
        {
          id: 'risk_review',
          priority: 30,
          status: 'blocked',
          title: 'Risk review',
          description:
            'At least one candidate is blocked by the pre-trade risk gate.',
          required_actions: ['review_risk_blockers'],
          blocking_reasons: ['risk_gate_blocked'],
          evidence: { risk_blocked_count: 1 },
        },
        {
          id: 'strategy_evidence',
          priority: 40,
          status: 'pass',
          title: 'Strategy evidence',
          description:
            'Strategy candidates are reviewed only after data and account facts.',
          required_actions: [],
          blocking_reasons: [],
          evidence: { candidate_count: 1 },
        },
        {
          id: 'paper_shadow_review',
          priority: 50,
          status: 'review_required',
          title: 'Paper/shadow review',
          description:
            'Candidate actions should be compared against paper/shadow evidence.',
          required_actions: ['review_paper_shadow_evidence'],
          blocking_reasons: [],
          evidence: { candidate_count: 1 },
        },
        {
          id: 'manual_confirmation',
          priority: 60,
          status: 'blocked',
          title: 'Manual confirmation',
          description:
            'Manual confirmation is blocked until upstream evidence is resolved.',
          required_actions: ['resolve_upstream_workflow_blockers'],
          blocking_reasons: ['upstream_workflow_blockers'],
          evidence: { candidate_count: 1 },
        },
      ],
    },
  } as DecisionResponse;

  renderDecisionCockpit({ todayResponse: workflowToday, locale: 'zh' });

  const workflow = await screen.findByTestId('decision-workflow-tasks');
  expect(await screen.findByText('决策工作流')).toBeTruthy();
  expect(workflow.textContent).toContain(
    '先检查数据和账户事实，再查看策略机会',
  );
  expect(workflow.textContent).toContain('数据刷新');
  expect(workflow.textContent).toContain('刷新或确认行情');
  expect(workflow.textContent).toContain('账户事实');
  expect(workflow.textContent).toContain('预览券商凭证导入并完成对账');
  expect(workflow.textContent).toContain('风险复核');
  expect(workflow.textContent).toContain('策略证据');
  expect(workflow.textContent).toContain('模拟复盘');
  expect(workflow.textContent).toContain('人工确认');
  expect(workflow.textContent).not.toContain(
    'preview_import_and_reconcile_broker_evidence',
  );
  expect(workflow.textContent).not.toContain('refresh_or_confirm_market_data');
  expect(workflow.textContent).not.toContain('paper_shadow_review');
  expect(
    workflow.textContent?.indexOf('数据刷新') ?? Number.POSITIVE_INFINITY,
  ).toBeLessThan(workflow.textContent?.indexOf('策略证据') ?? -1);
  expect(
    workflow.textContent?.indexOf('账户事实') ?? Number.POSITIVE_INFINITY,
  ).toBeLessThan(workflow.textContent?.indexOf('策略证据') ?? -1);
});

test('shows strategy display names before internal ids in candidate evidence', async () => {
  renderDecisionCockpit();

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  expect(candidateCard.textContent).toContain('Dual Moving Average');
  expect(candidateCard.textContent).not.toMatch(/Strategy\s*dual_ma/);
  expect(candidateCard.textContent).not.toMatch(/Strategy source\s*dual_ma/);
});

test('keeps decision cockpit candidates accessible on narrow responsive layouts', async () => {
  renderDecisionCockpit();

  expect(await screen.findByText('Decision platform')).toBeTruthy();

  const candidateCard = await screen.findByTestId(
    'decision-candidate-card-600519',
  );
  const summaryGrid = screen.getByTestId('decision-summary-grid');
  const laneGrid = screen.getByTestId('decision-lane-grid');
  const tradingLink = screen.getByRole('link', {
    name: 'Open Trading approvals: 600519',
  });

  expect(summaryGrid.className).toContain('min-w-0');
  expect(laneGrid.className).toContain('min-w-0');
  expect(candidateCard.className).toContain('min-w-0');
  expect(candidateCard.className).toContain('break-words');
  expect(tradingLink.className).toContain('shrink-0');
  expect(tradingLink.className).toContain('whitespace-normal');

  for (const evidenceLine of screen.getAllByTestId('decision-evidence-line')) {
    expect(evidenceLine.className).toContain('min-w-0');
    expect(evidenceLine.textContent).toBeTruthy();
  }
});
