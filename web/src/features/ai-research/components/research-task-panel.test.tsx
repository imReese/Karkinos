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

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderPanel({
  backtestResultId = 7,
  tasks = [],
}: {
  backtestResultId?: number | null;
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
      if (url.endsWith('/reviews')) {
        const reviewed = {
          ...authoritativeTask,
          status: 'context_revision_requested',
        };
        return jsonResponse({ task: reviewed, review: {}, reused: false });
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
        <ResearchTaskPanel backtestResultId={backtestResultId} />
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

  expect(screen.getByText('Model execution off')).toBeTruthy();
  expect(screen.getByText('No trading authority')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Open research tasks' }));
  expect(
    await screen.findByText('No human research task has been recorded yet.'),
  ).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(1);
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
});
