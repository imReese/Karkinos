import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { BacktestReport } from '../../backtest/api';
import { StrategyHypothesisPanel } from './strategy-hypothesis-panel';

const report: BacktestReport = {
  id: 17,
  created_at: '2026-07-15T01:00:00+00:00',
  config: {
    start_date: '2025-01-02',
    end_date: '2025-01-09',
    initial_cash: 100_000,
    strategy: 'dual_ma',
    assets: [{ symbol: '600000', asset_class: 'stock' }],
  },
  metrics: {
    initial_cash: 100_000,
    final_equity: 99_500,
    total_return: -0.005,
    annual_return: -0.1,
    sharpe: -0.1,
    sortino: -0.1,
    max_drawdown: 0.03,
    win_rate: 0.4,
    duration_days: 8,
  },
  metrics_json: {
    dataset_snapshot: {
      schema_version: 'karkinos.dataset_snapshot.v1',
      snapshot_id: 'sha256:dataset-001',
      provider: { configured_source: 'fixture', available_sources: [] },
      cache: { store_available: true, metadata_available: true },
      date_range: { start: '2025-01-02', end: '2025-01-09' },
      row_count: 8,
      adjustment_mode: 'none',
      data_quality: { status: 'ok', issues: [] },
      symbol_universe: [
        {
          symbol: '600000',
          asset_class: 'stock',
          frequency: '1d',
          row_count: 8,
        },
      ],
    },
  },
  cost_summary_json: { total_commission: 10, total_trades: 2 },
  equity_curve: [],
};

const formula = {
  schema_version: 'karkinos.ai.formula_ast.v1',
  entry: {
    op: 'gt',
    left: { op: 'field', name: 'close' },
    right: {
      op: 'rolling_mean',
      input: { op: 'field', name: 'close' },
      window: 3,
    },
  },
  exit: {
    op: 'lt',
    left: { op: 'field', name: 'close' },
    right: {
      op: 'rolling_mean',
      input: { op: 'field', name: 'close' },
      window: 3,
    },
  },
  position_size: { op: 'equal_weight' },
} as const;

const draft = {
  schema_version: 'karkinos.ai.strategy_hypothesis_draft.v1',
  draft_id: 'draft-001',
  workflow_id: 'workflow-001',
  session_id: 'session-001',
  context_snapshot_id: 'context-001',
  context_fingerprint: 'context-fingerprint-001',
  evidence_reference_id: 'evidence-001',
  provider_id: 'deepseek-edge',
  model_id: 'deepseek-chat',
  prompt_version: 'prompt-v1',
  provider_provenance: {
    usage: { prompt_tokens: 200, completion_tokens: 100, total_tokens: 300 },
    latency_ms: 125,
    reasoning_content_present: true,
    reasoning_content_persisted: false,
  },
  research_question: 'Is the trend hypothesis supported?',
  economic_hypothesis:
    'A short moving-average crossover may capture trend persistence.',
  selected_universe: ['600000'],
  universe_fingerprint: 'universe-fingerprint-001',
  dataset_snapshot_id: 'sha256:dataset-001',
  test_window: { start_date: '2025-01-02', end_date: '2025-01-09' },
  frequency: '1d',
  formula_ast: formula,
  formula_fingerprint: 'sha256:formula-001',
  parameter_values: { window: 3 },
  parameter_ranges: { window: [3, 5] },
  entry_conditions: 'Close above the rolling mean.',
  exit_conditions: 'Close below the rolling mean.',
  position_sizing_hypothesis: 'Equal weight.',
  portfolio_constraints: { max_weight: 1 },
  cost_model_reference: 'karkinos.backtest.multi_asset_commission.default.v1',
  required_evidence: ['Canonical after-cost result.'],
  anti_lookahead_assumptions: ['Only completed bars are used.'],
  proposed_deterministic_tests: ['Replay the exact snapshot.'],
  sample_split_plan: 'Add walk-forward validation later.',
  failure_conditions: ['Negative after-cost return.'],
  limitations: ['Short single-symbol sample.'],
  risk_impact: 'High concentration and turnover risk.',
  citations: ['saved_backtest_evidence.performance_summary'],
  validation: { status: 'valid', errors: [] },
  executable: false,
  requires_human_review: true,
  decision_input_created: false,
  trade_plan_created: false,
  authority_effect: 'none',
} as const;

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderPanel(selectedReport: BacktestReport | null = report) {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const requests: Array<{
    url: string;
    method: string;
    body: Record<string, unknown>;
  }> = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : {};
      requests.push({ url, method, body });
      if (url.endsWith('/hypotheses')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.strategy_research_api.v1',
          session_id: 'session-001',
          status: 'completed',
          failure_code: null,
          research_question: 'Is the trend hypothesis supported?',
          selection: body.selection,
          selection_fingerprint: 'selection-fingerprint-001',
          context_snapshot_id: 'context-001',
          context_fingerprint: 'context-fingerprint-001',
          evidence_reference_id: 'evidence-001',
          provider_id: 'deepseek-edge',
          model_id: 'deepseek-chat',
          prompt_version: 'prompt-v1',
          binding_validity: 'valid',
          binding_errors: [],
          drafts: [draft],
          reviews: [],
          reused: false,
          non_authoritative: true,
          non_executable: true,
          requires_human_review: true,
          trade_plan_created: false,
          authority_effect: 'none',
        });
      }
      if (url.endsWith('/backtests')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.strategy_research_api.v1',
          backtest_run_id: 'formula-backtest-001',
          status: 'completed',
          failure_code: null,
          session_id: 'session-001',
          draft_id: 'draft-001',
          formula_fingerprint: 'sha256:formula-001',
          dataset_snapshot_id: 'sha256:dataset-001',
          cost_model_reference:
            'karkinos.backtest.multi_asset_commission.default.v1',
          canonical_backtest: {
            result_id: 18,
            initial_cash: 100_000,
            final_equity: 98_000,
            total_return: -0.02,
            sharpe: -0.2,
            max_drawdown: 0.05,
            duration_days: 8,
            cost_summary: { total_commission: 12, total_trades: 2 },
            research_evidence_bundle: {},
            dataset_snapshot: {},
            formula_binding: {},
          },
          reused: false,
          research_only: true,
          non_authoritative: true,
          non_executable: true,
          requires_human_review: true,
          authority_effect: 'none',
        });
      }
      if (url.endsWith('/critiques')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.strategy_research_api.v1',
          critique_id: 'critique-001',
          session_id: 'session-001',
          draft_id: 'draft-001',
          backtest_run_id: 'formula-backtest-001',
          status: 'completed',
          failure_code: null,
          provider_id: 'deepseek-edge',
          model_id: 'deepseek-chat',
          prompt_version: 'prompt-v1',
          artifact: {
            schema_version: 'karkinos.ai.strategy_backtest_critique.v1',
            supported_claims: ['The result is replayable.'],
            contradicted_claims: ['After-cost return is negative.'],
            evidence_gaps: ['No out-of-sample evidence.'],
            cost_turnover_sensitivity: 'Needs doubled-cost stress.',
            concentration_risk: 'Single symbol.',
            sample_dependence: 'Short sample.',
            possible_overfitting: 'One parameter.',
            recommended_ablations: ['Compare buy-and-hold.'],
            recommended_walk_forward_stress_tests: [
              'Run walk-forward windows.',
            ],
            explicit_failure_conditions: ['Negative OOS return.'],
            uncertainty: 'Evidence is insufficient.',
            citations: ['canonical_research_evidence'],
            provider_provenance: {
              usage: { total_tokens: 180 },
              latency_ms: 90,
            },
            trade_plan_created: false,
            authority_effect: 'none',
          },
          reused: false,
          non_authoritative: true,
          non_executable: true,
          requires_human_review: true,
          trade_plan_created: false,
          authority_effect: 'none',
        });
      }
      if (url.endsWith('/reviews')) {
        return jsonResponse(
          { review_id: 'review-001', authority_effect: 'none' },
          { status: 201 },
        );
      }
      return jsonResponse({ detail: 'not found' }, { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PreferencesProvider>
        <StrategyHypothesisPanel report={selectedReport} />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  return { requests };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('requires separate export, backtest, critique, and review confirmations', async () => {
  const { requests } = renderPanel();
  fireEvent.click(
    screen.getByRole('button', { name: 'Open AI strategy research' }),
  );

  const generate = screen.getByRole('button', {
    name: 'Generate hypothesis drafts',
  });
  expect((generate as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Research question'), {
    target: { value: 'Is the trend hypothesis supported?' },
  });
  fireEvent.click(
    screen.getByLabelText(/I authorize sending only the displayed sanitized/),
  );
  expect((generate as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(generate);

  expect(await screen.findByText('Locally validated')).toBeTruthy();
  expect(screen.getByText(/300 tokens · 125 ms/)).toBeTruthy();
  const backtestButton = screen.getByRole('button', {
    name: 'Run canonical research backtest',
  });
  expect((backtestButton as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      /I select this validated draft and authorize one local/,
    ),
  );
  fireEvent.click(backtestButton);

  expect(await screen.findByText('Canonical after-cost result')).toBeTruthy();
  const critiqueButton = screen.getByRole('button', {
    name: 'Request evidence critique',
  });
  expect((critiqueButton as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(
    screen.getByLabelText(
      /I authorize sending this normalized draft and canonical/,
    ),
  );
  fireEvent.click(critiqueButton);

  expect(await screen.findByText('AI evidence critique')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Review note'), {
    target: { value: 'Keep the failed result and add OOS evidence.' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Record human review' }));
  expect(await screen.findByText(/Human review recorded/)).toBeTruthy();

  await waitFor(() => expect(requests).toHaveLength(4));
  expect(requests.map((request) => request.url)).toEqual([
    '/api/ai/strategy-research/hypotheses',
    '/api/ai/strategy-research/backtests',
    '/api/ai/strategy-research/critiques',
    '/api/ai/strategy-research/sessions/session-001/reviews',
  ]);
  expect(requests[0].body.confirmation).toContain(
    'sanitized_strategy_research',
  );
  expect(requests[1].body.confirmation).toContain('canonical_backtest');
  expect(requests[2].body.confirmation).toContain(
    'canonical_backtest_evidence',
  );
  expect(
    screen.queryByRole('button', { name: /buy|sell|submit|cancel|capital/i }),
  ).toBeNull();
});

test('shows a locally blocked formula and never enables its backtest', async () => {
  renderPanel();
  const blockedDraft = {
    ...draft,
    validation: { status: 'blocked', errors: ['unknown_operator:python'] },
    formula_fingerprint: null,
  };
  const originalFetch = vi.mocked(fetch);
  originalFetch.mockImplementationOnce(async () =>
    jsonResponse({
      schema_version: 'karkinos.ai.strategy_research_api.v1',
      session_id: 'session-blocked',
      status: 'completed',
      failure_code: null,
      research_question: 'Blocked formula?',
      selection: {},
      selection_fingerprint: 'selection-blocked',
      context_snapshot_id: 'context-blocked',
      context_fingerprint: 'context-blocked-fingerprint',
      evidence_reference_id: 'evidence-blocked',
      provider_id: 'deepseek-edge',
      model_id: 'deepseek-chat',
      prompt_version: 'prompt-v1',
      binding_validity: 'valid',
      binding_errors: [],
      drafts: [blockedDraft],
      reviews: [],
      reused: false,
      non_authoritative: true,
      non_executable: true,
      requires_human_review: true,
      authority_effect: 'none',
    }),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Open AI strategy research' }),
  );
  fireEvent.change(screen.getByLabelText('Research question'), {
    target: { value: 'Blocked formula?' },
  });
  fireEvent.click(
    screen.getByLabelText(/I authorize sending only the displayed sanitized/),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate hypothesis drafts' }),
  );

  expect(await screen.findByText('Blocked by Formula DSL')).toBeTruthy();
  expect(screen.getByText('unknown_operator:python')).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Run canonical research backtest' }),
  ).toBeNull();
  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
});

test('shows drift as historical and blocks follow-on actions', async () => {
  renderPanel();
  vi.mocked(fetch).mockImplementationOnce(async () =>
    jsonResponse({
      schema_version: 'karkinos.ai.strategy_research_api.v1',
      session_id: 'session-drifted',
      status: 'completed',
      failure_code: null,
      research_question: 'Drifted research?',
      selection: {},
      selection_fingerprint: 'selection-drifted',
      context_snapshot_id: 'context-drifted',
      context_fingerprint: 'context-drifted-fingerprint',
      evidence_reference_id: 'evidence-drifted',
      provider_id: 'deepseek-edge',
      model_id: 'deepseek-chat',
      prompt_version: 'prompt-v1',
      binding_validity: 'invalidated_by_drift',
      binding_errors: ['research_audit_drift'],
      drafts: [draft],
      reviews: [],
      reused: true,
      non_authoritative: true,
      non_executable: true,
      requires_human_review: true,
      authority_effect: 'none',
    }),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Open AI strategy research' }),
  );
  fireEvent.change(screen.getByLabelText('Research question'), {
    target: { value: 'Drifted research?' },
  });
  fireEvent.click(
    screen.getByLabelText(/I authorize sending only the displayed sanitized/),
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate hypothesis drafts' }),
  );

  expect(await screen.findByText(/no longer current/)).toBeTruthy();
  expect(screen.getByText(/historical \/ not current/)).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Run canonical research backtest' }),
  ).toBeNull();
});

test('blocks export when the saved dataset snapshot is incomplete', () => {
  const incompleteReport = structuredClone(report);
  incompleteReport.metrics_json!.dataset_snapshot!.data_quality = {
    status: 'stale',
    issues: [{ code: 'fixture_stale' }],
  };
  renderPanel(incompleteReport);
  fireEvent.click(
    screen.getByRole('button', { name: 'Open AI strategy research' }),
  );

  expect(screen.getByRole('alert').textContent).toContain(
    'no complete dataset snapshot',
  );
  expect(
    screen.getByRole('button', { name: 'Generate hypothesis drafts' }),
  ).toHaveProperty('disabled', true);
  expect(vi.mocked(fetch)).not.toHaveBeenCalled();
});
