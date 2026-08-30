import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
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
    schema_version: 'karkinos.ai.shadow_research_policy.v4',
    policy_id: 'ai_shadow_research',
    enabled: true,
    after_close_time: '15:30',
    timezone: 'Asia/Shanghai',
    max_provider_calls_per_market_date: 10,
    daily_token_budget: null,
    token_budget_mode: 'unbounded_daily',
    max_candidates_per_run: 5,
    baseline_backtest_result_id: null,
    research_capital_mode: 'normalized_notional',
    require_complete_account_evidence: false,
    promotion_requires_complete_account_evidence: true,
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
    reserved_tokens: 450560,
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
        iteration_lineage: {
          iteration_number: 1,
          total_iterations: 5,
          formula_fingerprint: `sha256:${'1'.repeat(64)}`,
          parent_candidate_id: null,
          parent_draft_id: null,
          parent_formula_fingerprint: null,
          iteration_context_fingerprint: `sha256:${'2'.repeat(64)}`,
          sequential_feedback_bound: true,
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
  daily_selections: [
    {
      schema_version: 'karkinos.ai.daily_strategy_selection.v1',
      selection_id: 'selection-1',
      run_id: 'run-1',
      market_date: '2026-08-11',
      status: 'winner_selected',
      winner_candidate_id: 'candidate-1',
      expected_candidate_count: 5,
      observed_candidate_count: 5,
      eligible_candidate_count: 1,
      blockers: [],
      selection_scope: 'new_candidate_research_only',
      incumbent_strategy_policy:
        'leave_current_human_approved_strategy_unchanged',
      incumbent_strategy_state_changed: false,
      daily_trading_decision_status: 'not_evaluated',
      implies_daily_trading_no_action: false,
      integrity_status: 'verified',
    },
  ],
  daily_backups: [
    {
      schema_version: 'karkinos.ai.daily_strategy_backup_receipt.v1',
      backup_id: 'backup-1',
      run_id: 'run-1',
      market_date: '2026-08-11',
      relative_path: '2026-08-11/backup.json',
      artifact_fingerprint: `sha256:${'a'.repeat(64)}`,
      byte_count: 1024,
      verification_status: 'verified',
      contains_private_account_identifiers: false,
      contains_broker_export_rows: false,
    },
  ],
  daily_new_candidate_winner_id: 'candidate-1',
  daily_winner_candidate_id: 'candidate-1',
  research_outcome: {
    status: 'new_candidate_available_for_human_review',
    new_candidate_winner_id: 'candidate-1',
    incumbent_strategy_policy:
      'leave_current_human_approved_strategy_unchanged',
    incumbent_strategy_state_changed: false,
    daily_trading_decision_status: 'not_evaluated',
    implies_daily_trading_no_action: false,
  },
  provider_call_window: {
    schema_version: 'karkinos.ai.provider_call_window.v1',
    policy_id: 'deepseek.beijing_weekday_peak.v1',
    policy_fingerprint: `sha256:${'f'.repeat(64)}`,
    provider_id: 'deepseek',
    timezone: 'Asia/Shanghai',
    status: 'eligible_off_peak',
    pricing_period: 'off_peak',
    failure_code: null,
    evaluated_at: '2026-08-11T18:00:00+08:00',
    next_eligible_at: null,
    minimum_runway_seconds: 7500,
    provider_call_performed: false,
    authority_effect: 'none',
  },
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

test('shows the next off-peak window and disables manual run during peak', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
      return jsonResponse({
        ...status,
        provider_call_window: {
          ...status.provider_call_window,
          status: 'deferred_for_provider_off_peak',
          pricing_period: 'peak',
          failure_code: 'deepseek_peak_pricing_window',
          evaluated_at: '2026-08-11T16:00:00+08:00',
          next_eligible_at: '2026-08-11T18:00:00+08:00',
        },
      });
    }
    if (url.endsWith('/api/strategy-promotion/states')) {
      return jsonResponse([]);
    }
    throw new Error(`Unexpected request: ${url}`);
  });
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

  expect(await screen.findByText('Deferred to off-peak')).toBeTruthy();
  expect(
    screen.getByText('Next eligible: 2026-08-11T18:00:00+08:00'),
  ).toBeTruthy();
  expect(
    (
      screen.getByRole('button', {
        name: 'Check and run now',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
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
  expect(
    screen.getAllByText('Account-qualified promotion winner'),
  ).toHaveLength(2);
  expect(screen.getByText('Sequential round 1/5')).toBeTruthy();
  expect(screen.getByText('Verified')).toBeTruthy();
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

test('records the exact five-round unbounded-daily-token authorization', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const disabledStatus = {
    ...status,
    policy: { ...status.policy, enabled: false, authorization_recorded: false },
  };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.endsWith('/api/ai/strategy-research/shadow-automation/policy') &&
        init?.method === 'PUT'
      ) {
        return jsonResponse({ ...status.policy, enabled: true });
      }
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(disabledStatus);
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

  await screen.findByDisplayValue(
    'Improve the persisted baseline without increasing risk.',
  );
  fireEvent.click(screen.getByLabelText('Paused'));
  fireEvent.click(
    await screen.findByText(
      /I authorize five strictly sequential normalized-notional research rounds and ten provider calls/,
    ),
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
    expect(body.enabled).toBe(true);
    expect(body.max_candidates_per_run).toBe(5);
    expect(body.max_provider_calls_per_market_date).toBe(10);
    expect(body.daily_token_budget).toBeNull();
    expect(body.token_budget_mode).toBe('unbounded_daily');
    expect(body.research_capital_mode).toBe('normalized_notional');
    expect(body.require_complete_account_evidence).toBe(false);
    expect(body.confirmation).toBe(
      'authorize_five_sequential_after_close_deepseek_normalized_notional_strategy_research_without_account_strategy_trade_or_capital_authority',
    );
  });
});

test('manual run and policy pause preserve the unbounded token policy', async () => {
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
    expect(body.daily_token_budget).toBeNull();
    expect(body.token_budget_mode).toBe('unbounded_daily');
    expect(body.confirmation).toBe(
      'pause_after_close_ai_strategy_research_without_changing_trading_authority',
    );
  });
  await vi.waitFor(() => {
    expect(queryClient.isMutating()).toBe(0);
    expect(queryClient.isFetching()).toBe(0);
  });
});

test('blocks an enabled legacy partial policy until five sequential rounds are saved', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const partialPolicyStatus = {
    ...status,
    policy: {
      ...status.policy,
      max_provider_calls_per_market_date: 2,
      daily_token_budget: 450560,
      token_budget_mode: 'legacy_bounded_daily',
      max_candidates_per_run: 1,
    },
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(partialPolicyStatus);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
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
    await screen.findByText(/Enabled research is blocked until/),
  ).toBeTruthy();
  const runButton = screen.getByRole('button', {
    name: 'Check and run now',
  }) as HTMLButtonElement;
  expect(runButton.disabled).toBe(true);
});

test('requires explicit normalized-notional reauthorization for an account-bound policy', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const accountBoundStatus = {
    ...status,
    policy: {
      ...status.policy,
      schema_version: 'karkinos.ai.shadow_research_policy.v3',
      research_capital_mode: 'account_bound',
      require_complete_account_evidence: true,
    },
  };
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (
        url.endsWith('/api/ai/strategy-research/shadow-automation/policy') &&
        init?.method === 'PUT'
      ) {
        return jsonResponse(status.policy);
      }
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(accountBoundStatus);
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

  expect(
    await screen.findByText(/persisted policy is legacy account-bound/),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', { name: 'Check and run now' }),
  ).toHaveProperty('disabled', true);

  fireEvent.click(
    screen.getByText(
      /I authorize five strictly sequential normalized-notional research rounds/,
    ),
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
    expect(body.research_capital_mode).toBe('normalized_notional');
    expect(body.require_complete_account_evidence).toBe(false);
    expect(body.confirmation).toBe(
      'authorize_five_sequential_after_close_deepseek_normalized_notional_strategy_research_without_account_strategy_trade_or_capital_authority',
    );
  });
});

test('keeps the current strategy while blocking promotion without a verified new winner', async () => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const noWinnerStatus = {
    ...status,
    daily_new_candidate_winner_id: null,
    daily_winner_candidate_id: null,
    research_outcome: {
      status: 'no_new_candidate_current_strategy_unchanged',
      new_candidate_winner_id: null,
      incumbent_strategy_policy:
        'leave_current_human_approved_strategy_unchanged',
      incumbent_strategy_state_changed: false,
      daily_trading_decision_status: 'not_evaluated',
      implies_daily_trading_no_action: false,
    },
    daily_selections: status.daily_selections.map((selection) => ({
      ...selection,
      status: 'no_selection',
      winner_candidate_id: null,
      blockers: ['no_candidate_passed_advancement_gate'],
    })),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(noWinnerStatus);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
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
    await screen.findByText('A slower trend filter reduces churn.'),
  ).toBeTruthy();
  expect(
    screen.getByText('No complete normalized research recommendation'),
  ).toBeTruthy();
  expect(screen.getByText(/No new winner means no new promotion/)).toBeTruthy();
  expect(
    screen.getByText(
      'This candidate passed its own gate but is not the verified new-candidate winner, so public paper/shadow approval remains blocked.',
    ),
  ).toBeTruthy();
  expect(
    screen.queryByRole('button', {
      name: 'Approve for paper/shadow only',
    }),
  ).toBeNull();
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
