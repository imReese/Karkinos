import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
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
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
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
          detail: 'Risk gate passed; prepare a manual order only if approved.',
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
    return new Response('Not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderDecisionCockpit(
  options?: Parameters<typeof installDecisionFetchMock>[0],
) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  installDecisionFetchMock(options);
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
  expect((await screen.findAllByText('Decision: buy')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText('600519')).toBeTruthy();
  expect(await screen.findByText('Risk gate: passed')).toBeTruthy();
  expect(
    await screen.findByText('Manual: ready for confirmation'),
  ).toBeTruthy();
  expect(await screen.findByText('After-cost/OOS: attached')).toBeTruthy();
  expect(await screen.findByText('Data freshness: live')).toBeTruthy();
  expect(await screen.findByText('Account truth: pass')).toBeTruthy();
  expect(await screen.findByText('Account truth score: 98')).toBeTruthy();
  expect(await screen.findByText('Journal: risk.signal.recorded')).toBeTruthy();
  expect(await screen.findByText('Signal action queue')).toBeTruthy();
  expect(await screen.findByText('Prepare manual order')).toBeTruthy();
  expect(await screen.findByText('Signal journal')).toBeTruthy();
  expect(await screen.findByText('Market health: partial')).toBeTruthy();
  expect(
    await screen.findByText('Portfolio equity: CN¥40,000.00'),
  ).toBeTruthy();
  expect(
    await screen.findByText('no_intraday_stock_or_etf_action_tasks'),
  ).toBeTruthy();
  expect(
    screen
      .getByRole('link', { name: 'Open Trading approvals: 600519' })
      .getAttribute('href'),
  ).toBe('/trading');
  expect(screen.queryByText(/automatic execution/i)).toBeNull();
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
  expect((await screen.findAllByText('degraded · 64')).length).toBeGreaterThan(
    0,
  );
  expect((await screen.findAllByText('blocked · 32')).length).toBeGreaterThan(
    0,
  );
  expect(await screen.findByText(/2 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/4 unresolved differences/)).toBeTruthy();
  expect(await screen.findByText(/review_position_difference/)).toBeTruthy();
  expect(
    await screen.findByText(/import_and_reconcile_broker_evidence/),
  ).toBeTruthy();
  expect(
    await screen.findByText('Manual: account truth review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Account truth: degraded')).toBeTruthy();
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
    (await screen.findAllByText('blocked · dual_ma')).length,
  ).toBeGreaterThan(0);
  expect(
    await screen.findByText(
      /link_strategy_signals_orders_fills_and_contribution/,
    ),
  ).toBeTruthy();
  expect(
    await screen.findByText('Manual: strategy attribution review required'),
  ).toBeTruthy();
  expect(await screen.findByText('Strategy attribution: blocked')).toBeTruthy();
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
