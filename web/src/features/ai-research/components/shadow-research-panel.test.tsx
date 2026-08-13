import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { ShadowResearchPanel } from './shadow-research-panel';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status,
  });
}

const status = {
  schema_version: 'karkinos.ai.shadow_research_automation.v1',
  policy: {
    enabled: true,
    after_close_time: '15:30',
    timezone: 'Asia/Shanghai',
    max_provider_calls_per_market_date: 3,
    daily_token_budget: 700000,
    max_candidates_per_run: 2,
    baseline_backtest_result_id: null,
    require_complete_account_evidence: true,
    research_question:
      'Improve the persisted baseline without increasing risk.',
    updated_by: 'human:owner',
    authorization_recorded: true,
    automatic_strategy_replacement_enabled: false,
    broker_submission_enabled: false,
    production_strategy_mutation_enabled: false,
    human_paper_shadow_approval_required: true,
  },
  kill_switch: { enabled: false, reason: '' },
  usage: {
    market_date: '2026-08-11',
    provider_calls: 2,
    reserved_tokens: 131072,
    actual_tokens: 1900,
  },
  runs: [
    {
      run_id: 'run-1',
      market_date: '2026-08-11',
      status: 'completed',
      candidate_count: 1,
      failure_code: null,
    },
  ],
  candidates: [
    {
      candidate_id: 'candidate-1',
      run_id: 'run-1',
      session_id: 'session-1',
      draft_id: 'draft-1',
      backtest_run_id: 'backtest-1',
      critique_id: 'critique-1',
      baseline_result_id: 7,
      candidate_result_id: 8,
      status: 'awaiting_human_approval',
      recommendation: 'paper_shadow_review',
      promotion_status: 'awaiting_human_approval',
      created_at: '2026-08-11T08:00:00Z',
      updated_at: '2026-08-11T08:00:00Z',
      comparison: {
        economic_hypothesis: 'A slower trend filter reduces churn.',
        risk_impact: 'Delayed exits remain the primary risk.',
        failure_conditions: ['OOS drawdown exceeds baseline'],
        baseline: {
          result_id: 7,
          total_return: 0.05,
          sharpe: 0.6,
          max_drawdown: 0.12,
          total_cost: 30,
          total_commission: 20,
          total_slippage: 10,
          total_trades: 6,
          gross_turnover: 50000,
          oos_fold_count: 2,
          mean_oos_return: 0.02,
          worst_oos_return: -0.01,
          oos_validation_status: 'benchmark_not_supplied',
          evidence_gate_status: 'pass',
          dataset_snapshot_id: 'sha256:latest',
        },
        candidate: {
          result_id: 8,
          total_return: 0.12,
          sharpe: 1.2,
          max_drawdown: 0.08,
          total_cost: 20,
          total_commission: 15,
          total_slippage: 5,
          total_trades: 4,
          gross_turnover: 30000,
          oos_fold_count: 3,
          mean_oos_return: 0.04,
          worst_oos_return: 0.01,
          oos_validation_status: 'benchmark_not_supplied',
          evidence_gate_status: 'pass',
          dataset_snapshot_id: 'sha256:latest',
        },
        deepseek_critique: {
          supported_claims: ['Drawdown improved.'],
          evidence_gaps: ['More regimes are needed.'],
        },
        recommendation: 'paper_shadow_review',
        promotion_gate: { status: 'pass', blockers: [] },
      },
      automatic_strategy_replacement_enabled: false,
      production_strategy_mutation_enabled: false,
      broker_submission_enabled: false,
      human_paper_shadow_approval_required: true,
    },
  ],
  automatic_strategy_replacement_enabled: false,
  production_strategy_mutation_enabled: false,
  broker_submission_enabled: false,
  human_paper_shadow_approval_required: true,
  authority_effect: 'research_only',
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('shows old/new OOS evidence and records only an explicit paper-shadow approval', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(status);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      if (url.includes('/paper-shadow-approvals') && init?.method === 'POST') {
        return jsonResponse({ target_stage: 'paper_shadow' }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <ShadowResearchPanel />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(
    await screen.findByRole('heading', {
      name: 'Automated shadow strategy research',
    }),
  ).toBeTruthy();
  expect(await screen.findByText('Current baseline')).toBeTruthy();
  expect(screen.getByText('New candidate')).toBeTruthy();
  expect(screen.getByText('A slower trend filter reduces churn.')).toBeTruthy();
  expect(screen.getByText('More regimes are needed.')).toBeTruthy();
  expect(screen.getAllByText('Mean / worst OOS')).toHaveLength(2);
  const approveButton = screen.getByRole('button', {
    name: 'Approve for paper/shadow only',
  }) as HTMLButtonElement;
  expect(approveButton.disabled).toBe(true);

  fireEvent.change(screen.getByLabelText('Human review note'), {
    target: { value: 'Reviewed cost, drawdown, OOS, and critique.' },
  });
  fireEvent.click(
    screen.getByText(
      'I reviewed the baseline comparison, costs, rolling OOS, risks and critique. Approve this candidate for paper/shadow research only.',
    ),
  );
  expect(approveButton.disabled).toBe(false);
  fireEvent.click(approveButton);

  await vi.waitFor(() => {
    const approvalCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('/paper-shadow-approvals'),
    );
    expect(approvalCall).toBeTruthy();
    const body = JSON.parse(String(approvalCall?.[1]?.body));
    expect(body.confirmation).toBe(
      'approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority',
    );
    expect(body.approved_by).toBe('human:owner');
  });
  await vi.waitFor(() => {
    expect(queryClient.isMutating()).toBe(0);
    expect(queryClient.isFetching()).toBe(0);
  });
});

test('manual run and policy pause use the bounded shadow-research endpoints', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.endsWith('/api/ai/strategy-research/shadow-automation/run') &&
        init?.method === 'POST'
      ) {
        return jsonResponse(status);
      }
      if (
        url.endsWith('/api/ai/strategy-research/shadow-automation/policy') &&
        init?.method === 'PUT'
      ) {
        return jsonResponse({ ...status.policy, enabled: false });
      }
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(status);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <ShadowResearchPanel />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  const runButton = (await screen.findByRole('button', {
    name: 'Check and run now',
  })) as HTMLButtonElement;
  await vi.waitFor(() => expect(runButton.disabled).toBe(false));
  fireEvent.click(runButton);
  await vi.waitFor(() => {
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input).endsWith(
            '/api/ai/strategy-research/shadow-automation/run',
          ) && init?.method === 'POST',
      ),
    ).toBe(true);
  });

  fireEvent.click(screen.getByLabelText('Authorized'));
  fireEvent.click(
    screen.getByText('I confirm pausing recurring AI strategy research.'),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save standing policy' }));

  await vi.waitFor(() => {
    const policyCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith(
          '/api/ai/strategy-research/shadow-automation/policy',
        ) && init?.method === 'PUT',
    );
    expect(policyCall).toBeTruthy();
    const body = JSON.parse(String(policyCall?.[1]?.body));
    expect(body.enabled).toBe(false);
    expect(body.confirmation).toBe(
      'pause_after_close_ai_strategy_research_without_changing_trading_authority',
    );
  });
  await vi.waitFor(() => {
    expect(queryClient.isMutating()).toBe(0);
    expect(queryClient.isFetching()).toBe(0);
  });
});

test('pauses an approved candidate through the canonical lifecycle state', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const approvedStatus = {
    ...status,
    candidates: status.candidates.map((candidate) => ({
      ...candidate,
      promotion_status: 'paper_shadow_approved',
    })),
  };
  let promotionStage = 'paper_shadow';
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(approvedStatus);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([
          {
            strategy_id: 'ai_formula_shadow:candidate-1',
            stage: promotionStage,
            gate_status:
              promotionStage === 'paper_shadow'
                ? 'paper_shadow_enabled'
                : 'paused',
            live_like_enabled: false,
          },
        ]);
      }
      if (
        url.endsWith(
          '/api/strategy-promotion/ai_formula_shadow%3Acandidate-1/lifecycle',
        ) &&
        init?.method === 'POST'
      ) {
        promotionStage = 'paused';
        return jsonResponse({
          strategy_id: 'ai_formula_shadow:candidate-1',
          stage: 'paused',
          gate_status: 'paused',
          live_like_enabled: false,
        });
      }
      if (url.includes('/paper-shadow-approvals') && init?.method === 'POST') {
        promotionStage = 'paper_shadow';
        return jsonResponse({ target_stage: 'paper_shadow' }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <ShadowResearchPanel />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(await screen.findByText('Paper/shadow approved')).toBeTruthy();
  const pauseButton = screen.getByRole('button', {
    name: 'Pause / revoke paper-shadow',
  }) as HTMLButtonElement;
  expect(pauseButton.disabled).toBe(true);

  fireEvent.change(screen.getByLabelText('Pause / revocation reason'), {
    target: { value: 'Observed a paper/shadow divergence.' },
  });
  fireEvent.click(
    screen.getByText(
      'I confirm pausing this exact candidate. Existing approval remains auditable, but new tickets must fail closed until a new explicit review.',
    ),
  );
  expect(pauseButton.disabled).toBe(false);
  fireEvent.click(pauseButton);

  await vi.waitFor(() => {
    const pauseCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes('ai_formula_shadow%3Acandidate-1/lifecycle'),
    );
    expect(pauseCall).toBeTruthy();
    expect(JSON.parse(String(pauseCall?.[1]?.body))).toEqual({
      target_stage: 'paused',
      reason: 'Observed a paper/shadow divergence.',
      actor: 'human:owner',
      confirmation:
        'pause_or_retire_strategy_without_execution_or_capital_authority',
    });
  });
  expect(await screen.findByText('Paper/shadow paused / revoked')).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Pause / revoke paper-shadow' }),
  ).toBeNull();

  const reapproveButton = screen.getByRole('button', {
    name: 'Re-review for paper/shadow',
  }) as HTMLButtonElement;
  expect(reapproveButton.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Human review note'), {
    target: { value: 'Re-reviewed after the explicit pause.' },
  });
  fireEvent.click(
    screen.getByText(
      'I reviewed the baseline comparison, costs, rolling OOS, risks and critique. Approve this candidate for paper/shadow research only.',
    ),
  );
  fireEvent.click(reapproveButton);
  await vi.waitFor(() => {
    const approvalCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/paper-shadow-approvals'),
    );
    expect(approvalCalls).toHaveLength(1);
    const body = JSON.parse(String(approvalCalls[0]?.[1]?.body));
    expect(body.notes).toBe('Re-reviewed after the explicit pause.');
    expect(body.confirmation).toBe(
      'approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority',
    );
  });
  await vi.waitFor(() => expect(queryClient.isMutating()).toBe(0));
  await vi.waitFor(() => expect(queryClient.isFetching()).toBe(0));
  expect(await screen.findByText('Paper/shadow approved')).toBeTruthy();
});
