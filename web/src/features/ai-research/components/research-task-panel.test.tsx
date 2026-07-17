import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { ResearchTaskPanel } from './research-task-panel';

const authoritativeTask = {
  schema_version: 'karkinos.ai.human_research_task.v1',
  task_id: 'ai-research-task-001',
  capture_id: 'ai-capture-001',
  context_snapshot_id: 'ai-context-001',
  context_fingerprint: 'context-fingerprint-001',
  account_alias: 'primary',
  valuation_snapshot_id: 'valuation-001',
  ledger_cutoff_id: 88,
  ledger_fingerprint: 'ledger-fingerprint-001',
  created_by: 'human:owner',
  title: 'Review frozen evidence',
  research_question: 'Which claims are supported?',
  evidence: [
    {
      evidence_reference_id: 'evidence-portfolio-001',
      tool_name: 'portfolio_projection.read',
      status: 'complete',
      authoritative: true,
      as_of: '2026-07-13T14:00:00+00:00',
      record_fingerprint: 'record-fingerprint-001',
    },
  ],
  all_evidence_authoritative: true,
  blockers: [],
  status: 'awaiting_human_review',
  created_at: '2026-07-13T14:00:00+00:00',
  updated_at: '2026-07-13T14:00:00+00:00',
  persisted_facts_only: true,
  provider_fetch_used: false,
  model_execution_enabled: false,
  model_invocation_count: 0,
  workflow_started: false,
  authority_effect: 'none',
  does_not_mutate_financial_state: true,
} as const;

const completedFixtureAnalysis = {
  schema_version: 'karkinos.ai.task_fixture_analysis.v1',
  analysis_id: 'ai-task-analysis-001',
  task_id: authoritativeTask.task_id,
  workflow_id: 'ai-workflow-001',
  workflow_status: 'completed',
  workflow_failure_code: null,
  partial_result: false,
  context_snapshot_id: authoritativeTask.context_snapshot_id,
  context_fingerprint: authoritativeTask.context_fingerprint,
  binding_validity: 'valid',
  binding_errors: [],
  memory_validity: 'human_review_required_exact_context_only',
  artifacts: ['claim', 'debate', 'report', 'memory'].map((kind, index) => ({
    artifact_id: `ai-artifact-${index + 1}`,
    stage_id: kind,
    role_id: `fixture.${kind}`,
    kind,
    content:
      kind === 'report'
        ? {
            summary:
              'A deterministic fixture reviewed exact persisted evidence without external model execution.',
          }
        : {},
    evidence_reference_ids: ['evidence-portfolio-001'],
    fingerprint: `artifact-fingerprint-${index + 1}`,
    created_at: '2026-07-13T14:00:00+00:00',
    authority_effect: 'none',
  })),
  tool_calls: [],
  audit_replay: {
    valid: true,
    event_count: 12,
    last_event_hash: 'event-hash-001',
    errors: [],
  },
  requested_by: 'human:owner',
  created_at: '2026-07-13T14:00:00+00:00',
  reused: false,
  provider_id: 'karkinos.fixture.offline.v1',
  model_id: 'karkinos.fixture.research.v1',
  fixture_only: true,
  fixture_stage_run_count: 4,
  network_io_used: false,
  external_model_invocation_count: 0,
  real_provider_registered: false,
  background_execution_used: false,
  persisted_facts_only: true,
  research_output_is_account_fact: false,
  authority_effect: 'none',
  does_not_mutate_financial_state: true,
} as const;

const completedAnalysisReview = {
  schema_version: 'karkinos.ai.fixture_analysis_review.v1',
  review_id: 'ai-analysis-review-001',
  analysis_id: completedFixtureAnalysis.analysis_id,
  task_id: completedFixtureAnalysis.task_id,
  workflow_id: completedFixtureAnalysis.workflow_id,
  decision: 'accept_as_reviewed_memory',
  effective_status: 'reviewed_memory',
  note: 'Reviewed exact fixture evidence and limitations.',
  reviewed_by: 'human:owner',
  created_at: '2026-07-13T15:00:00+00:00',
  memory_artifact_id: 'ai-artifact-4',
  stored_analysis_target_fingerprint: 'analysis-target-001',
  current_analysis_target_fingerprint: 'analysis-target-001',
  analysis_target_binding_valid: true,
  analysis_acceptance_eligible: true,
  memory_recall_eligible: true,
  invalidation_reasons: [],
  audit_replay: {
    valid: true,
    event_count: 1,
    last_event_hash: 'review-event-hash-001',
    errors: [],
  },
  reused: false,
  fixture_only: true,
  research_memory_only: true,
  persisted_facts_only: true,
  network_io_used: false,
  external_model_invocation_count: 0,
  research_output_is_account_fact: false,
  decision_handoff_enabled: false,
  trade_plan_created: false,
  authority_effect: 'none',
  does_not_mutate_financial_state: true,
} as const;

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderPanel({
  analyses = [],
  analysisReviews = [],
  backtestResultId = 7,
  strategyId = 'dual_ma',
  tasks = [],
}: {
  analyses?: Array<Record<string, unknown>>;
  analysisReviews?: Array<Record<string, unknown>>;
  backtestResultId?: number | null;
  strategyId?: string | null;
  tasks?: Array<Record<string, unknown>>;
} = {}) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const requests: Array<{ url: string; method: string; body: unknown }> = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      requests.push({ url, method, body });
      if (url.includes('/api/ai/research-contexts/capture')) {
        return jsonResponse({
          capture_id: 'ai-capture-created',
          capture_status: 'completed',
          context: {
            snapshot_id: 'ai-context-created',
            valuation_snapshot_id: 'valuation-created',
            ledger_cutoff_id: 99,
            ledger_fingerprint: 'ledger-created',
          },
          model_invocation_count: 0,
          workflow_started: false,
          authority_effect: 'none',
        });
      }
      if (
        url.includes('/api/ai/research-task-analyses/') &&
        url.endsWith('/reviews') &&
        method === 'POST'
      ) {
        return jsonResponse(completedAnalysisReview);
      }
      if (url.endsWith('/reviews')) {
        const reviewed = {
          ...authoritativeTask,
          status: 'context_revision_requested',
        };
        return jsonResponse({ task: reviewed, review: {}, reused: false });
      }
      if (url.endsWith('/fixture-analyses') && method === 'POST') {
        return jsonResponse(completedFixtureAnalysis);
      }
      if (url.endsWith('/api/ai/research-tasks') && method === 'POST') {
        return jsonResponse({
          ...authoritativeTask,
          task_id: 'ai-research-task-created',
          capture_id: 'ai-capture-created',
        });
      }
      if (url.includes('/api/ai/research-tasks?limit=20')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.human_research_task_list.v1',
          tasks,
          model_execution_enabled: false,
          workflow_started: false,
          authority_effect: 'none',
        });
      }
      if (url.includes('/api/ai/research-task-analyses?limit=20')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.task_fixture_analysis_list.v1',
          analyses,
          fixture_only: true,
          network_io_used: false,
          external_model_invocation_count: 0,
          authority_effect: 'none',
        });
      }
      if (url.includes('/api/ai/research-task-analysis-reviews?')) {
        return jsonResponse({
          schema_version: 'karkinos.ai.fixture_analysis_review_list.v1',
          reviews: analysisReviews,
          fixture_only: true,
          research_memory_only: true,
          network_io_used: false,
          external_model_invocation_count: 0,
          decision_handoff_enabled: false,
          authority_effect: 'none',
        });
      }
      return jsonResponse({ detail: 'not found' }, { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <ResearchTaskPanel
          backtestResultId={backtestResultId}
          strategyId={strategyId}
        />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return { fetchMock, requests };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('stays idle until explicitly opened', async () => {
  const { fetchMock } = renderPanel();

  expect(screen.getByText('External models off')).toBeTruthy();
  expect(screen.getByText('No trading authority')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  expect(
    await screen.findByText('No human research task has been recorded yet.'),
  ).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test('captures exact persisted context before recording a task', async () => {
  const { requests } = renderPanel();
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  await screen.findByText('No human research task has been recorded yet.');
  fireEvent.change(screen.getByLabelText('Research question'), {
    target: { value: 'Review the frozen portfolio and saved backtest.' },
  });
  fireEvent.click(
    screen.getByRole('checkbox', { name: /Bind saved backtest evidence/ }),
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Capture evidence and record task',
    }),
  );

  expect(
    await screen.findByText(
      'The task was recorded without starting model execution.',
    ),
  ).toBeTruthy();
  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    '/api/ai/research-contexts/capture',
    '/api/ai/research-tasks',
  ]);
  expect(postRequests[0].body).toMatchObject({
    evidence_types: [
      'portfolio',
      'account_state',
      'operations',
      'account_truth',
      'research_evidence',
    ],
    backtest_result_id: 7,
    confirmation: 'capture_read_only_research_context',
  });
  expect(postRequests[1].body).toMatchObject({
    capture_id: 'ai-capture-created',
    confirmation: 'record_human_research_task_without_model_execution',
  });
  expect(JSON.stringify(postRequests)).not.toContain('model_id');
  expect(JSON.stringify(postRequests)).not.toContain('provider_id');
});

test('explicitly binds current strategy outcome evidence by exact strategy id', async () => {
  const { requests } = renderPanel();
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  await screen.findByText('No human research task has been recorded yet.');
  fireEvent.change(screen.getByLabelText('Research question'), {
    target: { value: 'Review actual strategy outcomes and limitations.' },
  });
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: /Bind current strategy outcome evidence/,
    }),
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Capture evidence and record task',
    }),
  );

  await screen.findByText(
    'The task was recorded without starting model execution.',
  );
  const capture = requests.find((request) =>
    request.url.includes('/api/ai/research-contexts/capture'),
  );
  expect(capture?.body).toMatchObject({
    evidence_types: [
      'portfolio',
      'account_state',
      'operations',
      'account_truth',
      'strategy_contribution',
    ],
    strategy_id: 'dual_ma',
  });
});

test('does not offer strategy outcome capture without an exact strategy id', async () => {
  renderPanel({ strategyId: null });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  await screen.findByText('No human research task has been recorded yet.');

  const contributionCheckbox = screen.getByRole('checkbox', {
    name: /Bind current strategy outcome evidence/,
  }) as HTMLInputElement;
  expect(contributionCheckbox.disabled).toBe(true);
  expect(
    screen.getByText(
      'No exact current strategy is available for contribution capture.',
    ),
  ).toBeTruthy();
});

test('blocks acceptance for incomplete evidence and records revision only', async () => {
  const blockedTask = {
    ...authoritativeTask,
    all_evidence_authoritative: false,
    blockers: ['evidence_not_authoritative:account_truth.read:unreconciled'],
    status: 'blocked_by_evidence',
    evidence: [
      {
        ...authoritativeTask.evidence[0],
        tool_name: 'account_truth.read',
        status: 'unreconciled',
        authoritative: false,
      },
    ],
  };
  const { requests } = renderPanel({ tasks: [blockedTask] });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  expect(await screen.findByText('Blocked by evidence')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Human review note'), {
    target: { value: 'Reconcile account truth before analysis.' },
  });

  expect(
    (
      screen.getByRole('button', {
        name: 'Accept context',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Request revision' }));

  await waitFor(() => {
    expect(
      requests.some(
        (request) =>
          request.url.endsWith('/reviews') &&
          (request.body as { decision?: string }).decision ===
            'context_revision_requested',
      ),
    ).toBe(true);
  });
  expect(
    screen.queryByRole('button', { name: /submit|cancel|resume/i }),
  ).toBeNull();
  expect(
    screen.queryByRole('button', { name: 'Run offline fixture analysis' }),
  ).toBeNull();
});

test('starts the offline fixture only after accepted context and renders artifacts', async () => {
  const acceptedTask = {
    ...authoritativeTask,
    status: 'context_accepted',
  };
  const { requests } = renderPanel({ tasks: [acceptedTask] });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  expect(await screen.findByText('Context accepted')).toBeTruthy();

  fireEvent.click(
    screen.getByRole('button', { name: 'Run offline fixture analysis' }),
  );

  expect(await screen.findByText('Fixture workflow')).toBeTruthy();
  expect(screen.getByText('Exact context valid')).toBeTruthy();
  expect(
    screen.getByText('Human review required; exact context only'),
  ).toBeTruthy();
  expect(screen.getByText('Audit replay valid')).toBeTruthy();
  expect(
    screen.getByText(
      'A deterministic fixture reviewed exact persisted evidence without external model execution.',
    ),
  ).toBeTruthy();
  expect(screen.getByText(/claim · 1/)).toBeTruthy();
  expect(screen.getByText(/debate · 1/)).toBeTruthy();
  expect(screen.getByText(/report · 1/)).toBeTruthy();
  expect(screen.getByText(/memory · 1/)).toBeTruthy();

  const fixtureRequest = requests.find((request) =>
    request.url.endsWith('/fixture-analyses'),
  );
  expect(fixtureRequest?.body).toMatchObject({
    requested_by: 'human:owner',
    confirmation: 'run_deterministic_fixture_analysis_without_external_model',
  });
  expect(JSON.stringify(requests)).not.toContain('broker');
  expect(
    screen.queryByRole('button', { name: /submit|cancel|resume|trade|order/i }),
  ).toBeNull();
});

test('invalidates fixture report and memory when exact evidence binding drifts', async () => {
  const drifted = {
    ...completedFixtureAnalysis,
    binding_validity: 'evidence_drift',
    binding_errors: ['canonical evidence payload fingerprint drift'],
    memory_validity: 'invalidated_by_evidence_drift',
    audit_replay: {
      ...completedFixtureAnalysis.audit_replay,
      valid: false,
      errors: ['canonical evidence payload fingerprint drift'],
    },
  };
  renderPanel({
    tasks: [{ ...authoritativeTask, status: 'context_accepted' }],
    analyses: [drifted],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));

  expect(
    await screen.findByText('Evidence drift — output invalidated'),
  ).toBeTruthy();
  expect(screen.getByText('Invalidated by evidence drift')).toBeTruthy();
  expect(screen.getByText('Audit replay blocked')).toBeTruthy();
  expect(
    screen.getByText('canonical evidence payload fingerprint drift'),
  ).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Run offline fixture analysis' }),
  ).toBeNull();
  fireEvent.change(await screen.findByLabelText('Analysis review note'), {
    target: { value: 'Recapture evidence before accepting memory.' },
  });
  expect(
    (
      screen.getByRole('button', {
        name: 'Accept as reviewed memory',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole('button', {
        name: 'Request analysis revision',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});

test('records exact human acceptance only as reviewed research memory', async () => {
  const { requests } = renderPanel({
    tasks: [{ ...authoritativeTask, status: 'context_accepted' }],
    analyses: [completedFixtureAnalysis],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  expect(await screen.findByText('Human analysis review')).toBeTruthy();
  expect(
    screen.getByText(
      'This decision only controls research-memory recall. It cannot enter Decision or grant trading authority.',
    ),
  ).toBeTruthy();
  fireEvent.change(await screen.findByLabelText('Analysis review note'), {
    target: { value: 'Reviewed exact fixture evidence and limitations.' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Accept as reviewed memory' }),
  );

  expect(await screen.findByText('Reviewed memory')).toBeTruthy();
  expect(
    screen.getByText('Eligible for reviewed research recall'),
  ).toBeTruthy();
  const reviewRequest = requests.find(
    (request) => request.method === 'POST' && request.url.endsWith('/reviews'),
  );
  expect(reviewRequest?.body).toMatchObject({
    reviewed_by: 'human:owner',
    decision: 'accept_as_reviewed_memory',
    note: 'Reviewed exact fixture evidence and limitations.',
    confirmation:
      'record_fixture_analysis_review_without_decision_or_execution_authority',
  });
  expect(JSON.stringify(reviewRequest)).not.toContain('model_id');
  expect(JSON.stringify(reviewRequest)).not.toContain('provider_id');
  expect(
    screen.queryByRole('button', { name: /trade|order|submit|cancel|resume/i }),
  ).toBeNull();
});

test('shows persisted invalidation and removes memory recall eligibility', async () => {
  const invalidatedReview = {
    ...completedAnalysisReview,
    effective_status: 'invalidated_by_evidence_drift',
    current_analysis_target_fingerprint: 'analysis-target-drifted',
    analysis_target_binding_valid: false,
    analysis_acceptance_eligible: false,
    memory_recall_eligible: false,
    invalidation_reasons: ['analysis_target_fingerprint_drift'],
  };
  renderPanel({
    tasks: [{ ...authoritativeTask, status: 'context_accepted' }],
    analyses: [completedFixtureAnalysis],
    analysisReviews: [invalidatedReview],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));

  expect(await screen.findByText('Invalidated by evidence drift')).toBeTruthy();
  expect(screen.getByText('Not eligible for research recall')).toBeTruthy();
  expect(screen.getByText('analysis_target_fingerprint_drift')).toBeTruthy();
  expect(
    screen.queryByRole('button', { name: 'Accept as reviewed memory' }),
  ).toBeNull();
});
