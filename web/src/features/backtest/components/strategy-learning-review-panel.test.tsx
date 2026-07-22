import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { StrategyLearningReviewPanel } from './strategy-learning-review-panel';

const unsupportedItem = {
  review_id: 'decision-review-learning-1',
  signal_id: 41,
  strategy_id: 'dual_ma',
  symbol: '510300',
  reviewed_at: '2026-07-18T10:00:00+00:00',
  user_decision: 'acted',
  outcome: 'evidence_not_supported',
  learning_status: 'strategy_research_required',
  priority: 'high',
  safe_next_action: 'open_human_strategy_research_task',
  stored_target_fingerprint: 'stored-target-41',
  current_target_fingerprint: 'stored-target-41',
  target_binding_valid: true,
  audit_integrity_valid: true,
  valuation_snapshot_id: 'valuation-learning-41',
  ledger_cutoff_id: 87,
  contribution_fingerprint: 'contribution-learning-41',
  blockers: [],
  evidence_refs: [
    'decision_outcome_review:decision-review-learning-1',
    'signal:41',
    'valuation_snapshot:valuation-learning-41',
    'ledger_cutoff:87',
  ],
  research_handoff: {
    schema_version: 'karkinos.strategy_learning_research_handoff.v1',
    kind: 'copy_only_human_started_research',
    research_question:
      'Re-evaluate strategy dual_ma for 510300 against current canonical evidence.',
    review_id: 'decision-review-learning-1',
    evidence_refs: ['decision_outcome_review:decision-review-learning-1'],
    historical_review_is_current_fact: false,
    requires_human_started_capture: true,
    requires_human_started_research_task: true,
    invokes_ai: false,
    creates_memory: false,
    authorizes_strategy_change: false,
    authorizes_execution: false,
  },
  item_fingerprint: 'strategy-learning-item-41',
  persisted_facts_only: true,
  provider_contacted: false,
  database_writes_performed: false,
  financial_recalculation_performed: false,
  ai_invoked: false,
  memory_created: false,
  strategy_changed: false,
  authorizes_execution: false,
  capital_authority_changed: false,
} as const;

function queueResponse(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schema_version: 'karkinos.strategy_learning_review.v1',
    status: 'review_required',
    reviewed_signal_count: 1,
    action_item_count: 1,
    critical_item_count: 0,
    outcome_counts: { evidence_not_supported: 1 },
    strategy_summaries: [],
    items: [unsupportedItem],
    limitations: [],
    queue_fingerprint: 'strategy-learning-queue-1',
    generated_at: '2026-07-18T12:00:00+00:00',
    persisted_facts_only: true,
    provider_contacted: false,
    database_writes_performed: false,
    financial_recalculation_performed: false,
    ai_invoked: false,
    memory_created: false,
    strategy_changed: false,
    authorizes_execution: false,
    capital_authority_changed: false,
    ...overrides,
  };
}

function renderPanel(
  response: Record<string, unknown>,
  locale: 'en' | 'zh' = 'en',
) {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', locale);
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <StrategyLearningReviewPanel />
      </QueryClientProvider>
    </PreferencesProvider>,
  );
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test('shows an empty persisted-only queue without authority controls', async () => {
  const fetchMock = renderPanel(
    queueResponse({
      status: 'not_configured',
      reviewed_signal_count: 0,
      action_item_count: 0,
      items: [],
    }),
  );

  expect(
    await screen.findByText(/No reviewed learning evidence yet/),
  ).toBeTruthy();
  expect(screen.getByText('Persisted facts only')).toBeTruthy();
  expect(screen.getByText('AI not invoked')).toBeTruthy();
  expect(screen.getByText('No execution or capital authority')).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0]?.[0]).toBe(
    '/api/strategy-learning/review-queue',
  );
});

test('shows exact evidence and a copy-only human research handoff', async () => {
  renderPanel(queueResponse());

  expect(
    await screen.findByText(
      'Open a separate human-started strategy research task',
    ),
  ).toBeTruthy();
  expect(
    screen.getByText('valuation_snapshot:valuation-learning-41'),
  ).toBeTruthy();
  expect(screen.getByText('ledger_cutoff:87')).toBeTruthy();
  expect(screen.getByText('Copy-only research handoff')).toBeTruthy();
  expect(
    screen.getByText(
      'Re-evaluate strategy dual_ma for 510300 against current canonical evidence.',
    ),
  ).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
});

test('renders integrity failures as blocking and never emits a research handoff', async () => {
  const blockedItem = {
    ...unsupportedItem,
    learning_status: 'audit_integrity_blocked',
    priority: 'critical',
    safe_next_action: 'repair_post_decision_review_integrity_before_learning',
    target_binding_valid: false,
    audit_integrity_valid: false,
    blockers: ['stored_review_request_fingerprint_mismatch'],
    research_handoff: null,
    item_fingerprint: 'strategy-learning-item-blocked-41',
  };
  renderPanel(
    queueResponse({
      status: 'blocked',
      critical_item_count: 1,
      items: [blockedItem],
    }),
    'zh',
  );

  expect(
    await screen.findByText('先修复并回放决策后复盘，再从中学习'),
  ).toBeTruthy();
  expect(
    screen.getByText('stored_review_request_fingerprint_mismatch'),
  ).toBeTruthy();
  expect(screen.getByText('无执行或资本权限')).toBeTruthy();
  await waitFor(() => {
    expect(screen.queryByText('仅复制的研究交接')).toBeNull();
  });
});
