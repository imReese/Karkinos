import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import type { ShadowResearchAutomationStatus } from '../api';
import { ShadowResearchPanel } from './shadow-research-panel';

const privateCash = 'PRIVATE_CASH_MUST_NOT_RENDER';
const privateAccountReference = 'PRIVATE_ACCOUNT_REFERENCE_MUST_NOT_RENDER';
const rawComparison = 'RAW_COMPARISON_MUST_NOT_RENDER';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    status,
  });
}

function qualifiedStatus(): ShadowResearchAutomationStatus {
  return {
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
      research_question: 'Improve the frozen Formula evidence.',
      updated_by: 'human:owner',
      authorization_recorded: true,
      automatic_strategy_replacement_enabled: false,
      broker_submission_enabled: false,
      production_strategy_mutation_enabled: false,
      human_paper_shadow_approval_required: true,
    },
    kill_switch: { enabled: false, reason: '' },
    usage: {
      market_date: '2026-09-01',
      provider_calls: 10,
      reserved_tokens: 0,
      actual_tokens: 1234,
    },
    runs: [
      {
        run_id: 'source-run-1',
        market_date: '2026-09-01',
        status: 'completed',
        candidate_count: 5,
        failure_code: null,
      },
    ],
    candidates: [
      {
        candidate_id: 'source-candidate-1',
        run_id: 'source-run-1',
        session_id: 'session-1',
        draft_id: 'source-draft-1',
        backtest_run_id: 'backtest-1',
        critique_id: 'critique-1',
        baseline_result_id: 7,
        candidate_result_id: 8,
        status: 'evaluated_research_only',
        recommendation: 'formula_research_candidate',
        promotion_status: 'account_qualification_required',
        created_at: '2026-09-01T16:00:00+08:00',
        updated_at: '2026-09-01T16:00:00+08:00',
        comparison: {
          economic_hypothesis: 'Frozen normalized source candidate',
          promotion_gate: { status: 'pass', blockers: [] },
          research_capital_mode: 'normalized_notional',
          account_qualification_status: 'not_evaluated',
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
        selection_id: 'source-selection-1',
        run_id: 'source-run-1',
        market_date: '2026-09-01',
        status: 'no_selection',
        winner_candidate_id: null,
        research_recommendation: {
          schema_version:
            'karkinos.ai.normalized_daily_research_recommendation.v1',
          status: 'best_available_for_further_research',
          research_winner_candidate_id: 'source-candidate-1',
          account_qualification_status: 'not_evaluated',
          account_qualified: false,
          promotion_eligible: false,
          paper_shadow_eligible: false,
          decision_eligible: false,
          execution_eligible: false,
          authority_effect: 'none',
          evidence_fingerprint: `sha256:${'a'.repeat(64)}`,
        },
        expected_candidate_count: 5,
        observed_candidate_count: 5,
        eligible_candidate_count: 0,
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
        backup_id: 'source-backup-1',
        run_id: 'source-run-1',
        market_date: '2026-09-01',
        relative_path: '2026-09-01/backup.json',
        artifact_fingerprint: `sha256:${'b'.repeat(64)}`,
        byte_count: 1024,
        verification_status: 'verified',
        contains_private_account_identifiers: false,
        contains_broker_export_rows: false,
      },
    ],
    qualification_runs: [
      {
        schema_version: 'karkinos.ai.shadow_research_account_qualification.v1',
        qualification_run_id: 'qualification-run-1',
        source_run_id: 'source-run-1',
        market_date: '2026-09-01',
        source_selection_id: 'source-selection-1',
        status: 'completed',
        selection_status: 'winner_selected',
        winner_qualification_candidate_id: 'qualification-candidate-1',
        blockers: [],
        failure_code: null,
        created_at: '2026-09-01T17:00:00+08:00',
        updated_at: '2026-09-01T17:10:00+08:00',
        initial_cash_text: privateCash,
        account_evidence_reference: privateAccountReference,
      },
    ],
    qualification_candidates: [
      {
        schema_version: 'karkinos.ai.shadow_research_account_qualification.v1',
        qualification_candidate_id: 'qualification-candidate-1',
        qualification_run_id: 'qualification-run-1',
        source_candidate_id: 'source-candidate-1',
        source_draft_id: 'source-draft-1',
        source_formula_fingerprint: `sha256:${'c'.repeat(64)}`,
        qualified_formula_fingerprint: `sha256:${'d'.repeat(64)}`,
        status: 'qualified',
        recommendation: 'paper_shadow_review',
        rank: 1,
        created_at: '2026-09-01T17:08:00+08:00',
        raw_comparison: rawComparison,
      },
    ],
    qualification_approvals: [],
    latest_qualification_attempt: null,
    daily_new_candidate_winner_id: null,
    daily_winner_candidate_id: null,
    daily_research_winner_candidate_id: 'source-candidate-1',
    research_outcome: {
      status: 'best_available_formula_for_further_research',
      new_candidate_winner_id: null,
      research_winner_candidate_id: 'source-candidate-1',
      account_qualification_status: 'passed',
      qualification_run_id: 'qualification-run-1',
      winner_qualification_candidate_id: 'qualification-candidate-1',
      incumbent_strategy_policy:
        'leave_current_human_approved_strategy_unchanged',
      incumbent_strategy_state_changed: false,
      daily_trading_decision_status: 'not_evaluated',
      implies_daily_trading_no_action: false,
    },
    automatic_strategy_replacement_enabled: false,
    production_strategy_mutation_enabled: false,
    broker_submission_enabled: false,
    human_paper_shadow_approval_required: true,
    authority_effect: 'research_only',
  } as unknown as ShadowResearchAutomationStatus;
}

function renderPanel() {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
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
  return queryClient;
}

afterEach(() => {
  window.localStorage.removeItem('karkinos.locale');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('shows the exact qualified winner binding and submits only the qualification approval route', async () => {
  const response = qualifiedStatus();
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      if (
        url.endsWith(
          '/api/ai/strategy-research/shadow-qualification-candidates/qualification-candidate-1/paper-shadow-approvals',
        ) &&
        init?.method === 'POST'
      ) {
        return jsonResponse({ target_stage: 'paper_shadow' }, 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = renderPanel();

  expect(
    await screen.findByRole('heading', {
      name: 'Account qualification review',
    }),
  ).toBeTruthy();
  expect(await screen.findByText('Qualified winner selected')).toBeTruthy();
  expect(
    screen.getByText('qualification-candidate-1 → source-candidate-1'),
  ).toBeTruthy();
  expect(
    screen.getByText('Exact normalized source candidate is bound.'),
  ).toBeTruthy();
  expect(screen.queryByText(privateCash)).toBeNull();
  expect(screen.queryByText(privateAccountReference)).toBeNull();
  expect(screen.queryByText(rawComparison)).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Approve for paper/shadow only' }),
  ).toBeNull();

  const approveButton = screen.getByRole('button', {
    name: 'Approve qualified winner for paper/shadow only',
  }) as HTMLButtonElement;
  expect(approveButton.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Qualification approval note'), {
    target: { value: 'Reviewed the exact qualification evidence.' },
  });
  fireEvent.click(
    screen.getByText(
      'I reviewed this exact account-qualified winner and approve it for paper/shadow research only. This grants no order, trade, or capital authority.',
    ),
  );
  fireEvent.click(approveButton);

  await vi.waitFor(() => {
    const approvalCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith(
          '/api/ai/strategy-research/shadow-qualification-candidates/qualification-candidate-1/paper-shadow-approvals',
        ) && init?.method === 'POST',
    );
    expect(approvalCall).toBeTruthy();
    expect(JSON.parse(String(approvalCall?.[1]?.body))).toEqual({
      approved_by: 'human:owner',
      notes: 'Reviewed the exact qualification evidence.',
      confirmation:
        'approve_exact_account_qualified_candidate_for_paper_shadow_only_without_order_trade_or_capital_authority',
    });
  });
  await vi.waitFor(() => {
    expect(queryClient.isMutating()).toBe(0);
    expect(queryClient.isFetching()).toBe(0);
  });
  expect(
    fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith('/api/ai/strategy-research/shadow-automation'),
    ).length,
  ).toBeGreaterThanOrEqual(2);
  expect(
    fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith('/api/strategy-promotion/states'),
    ).length,
  ).toBeGreaterThanOrEqual(2);
});

test('shows qualification blockers without exposing any approval control or private payload', async () => {
  const response = qualifiedStatus();
  response.qualification_runs[0] = {
    ...response.qualification_runs[0],
    status: 'blocked',
    selection_status: 'no_selection',
    winner_qualification_candidate_id: null,
    blockers: ['qualification_valuation_or_ledger_not_complete'],
  };
  response.qualification_candidates[0] = {
    ...response.qualification_candidates[0],
    status: 'blocked',
    recommendation: 'keep_researching',
  };
  response.research_outcome = {
    ...response.research_outcome,
    account_qualification_status: 'blocked',
    winner_qualification_candidate_id: null,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPanel();

  expect(await screen.findByText('Qualification blocked')).toBeTruthy();
  expect(
    screen.getByText('The current valuation or ledger evidence is incomplete'),
  ).toBeTruthy();
  expect(
    screen.queryByRole('button', {
      name: 'Approve qualified winner for paper/shadow only',
    }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Approve for paper/shadow only' }),
  ).toBeNull();
  expect(screen.queryByText(privateCash)).toBeNull();
  expect(screen.queryByText(privateAccountReference)).toBeNull();
  expect(screen.queryByText(rawComparison)).toBeNull();
});

test('shows the current blocked attempt instead of falling back to an older completed qualification run', async () => {
  const response = qualifiedStatus();
  response.research_outcome = {
    ...response.research_outcome,
    account_qualification_status: 'blocked',
    qualification_run_id: null,
    winner_qualification_candidate_id: null,
  };
  response.latest_qualification_attempt = {
    schema_version:
      'karkinos.ai.shadow_research_account_qualification_attempt.v1',
    attempt_id: 'qualification-attempt-current',
    source_run_id: 'source-run-current',
    market_date: '2026-09-02',
    status: 'blocked',
    failure_code: 'qualification_valuation_or_ledger_not_complete',
    blockers: ['qualification_valuation_or_ledger_not_complete'],
    evidence_fingerprint: 'e'.repeat(64),
    created_at: '2026-09-02T17:00:00+08:00',
    finished_at: '2026-09-02T17:00:00+08:00',
    provider_call_performed: false,
    automatic_strategy_replacement_enabled: false,
    production_strategy_mutation_enabled: false,
    broker_order_created: false,
    broker_submission_enabled: false,
    ledger_mutation_performed: false,
    capital_authority_granted: false,
    private_account_values_redacted: true,
    authority_effect: 'none',
  };
  response.daily_selections[0] = {
    ...response.daily_selections[0],
    run_id: 'source-run-current',
    market_date: '2026-09-02',
  };
  response.daily_backups[0] = {
    ...response.daily_backups[0],
    run_id: 'source-run-current',
    market_date: '2026-09-02',
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );

  renderPanel();

  await screen.findByText('qualification-attempt-current');
  const section = screen.getByTestId('shadow-research-qualification');
  expect(within(section).getByText('Qualification blocked')).toBeTruthy();
  expect(
    within(section).getByText('qualification-attempt-current'),
  ).toBeTruthy();
  expect(
    within(section).getByText(
      'The current valuation or ledger evidence is incomplete',
    ),
  ).toBeTruthy();
  expect(within(section).queryByText('qualification-run-1')).toBeNull();
  expect(within(section).queryByText(/qualification-candidate-1/)).toBeNull();
  expect(
    within(section).queryByRole('button', {
      name: 'Approve qualified winner for paper/shadow only',
    }),
  ).toBeNull();
});

test('renders the exact qualification approval boundary in Chinese', async () => {
  window.localStorage.setItem('karkinos.locale', 'zh');
  const response = qualifiedStatus();
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/api/ai/strategy-research/shadow-automation')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/api/strategy-promotion/states')) {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  renderPanel();

  expect(
    await screen.findByRole('heading', { name: '账户资格复核' }),
  ).toBeTruthy();
  expect(
    await screen.findByText(
      '我已复核这个精确的账户资格优胜者，仅批准其进入 paper/shadow 研究；该批准不授予下单、交易或资本权限。',
    ),
  ).toBeTruthy();
  expect(
    screen.getByRole('button', {
      name: '仅批准资格优胜者进入 paper/shadow',
    }),
  ).toBeTruthy();
});
