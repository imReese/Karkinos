import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import type { OperationsTodayResponse } from '../api';
import { OperationsPage } from './operations-page';

const dailyOperations = {
  candidate_pool_count: 14,
  evidence_passed_count: 0,
  risk_checked_count: 0,
  risk_passed_count: 0,
  risk_blocked_count: 0,
  paper_shadow_review_count: 1,
  manual_ready_count: 0,
  pending_manual_order_count: 0,
  execution_record_count: 0,
  fill_record_count: 0,
  ledger_review_count: 0,
  execution_exception_count: 0,
  default_execution_mode: 'manual_confirmation',
  broker_bridge_status: 'disabled',
  conclusion_status: 'manual_action_required',
  primary_target: 'market',
  limitations: [],
};

const safeProjection: OperationsTodayResponse = {
  schema_version: 'karkinos.operations_today.v1',
  operations_date: '2026-07-17',
  generated_at: '2026-07-17T15:00:00+08:00',
  conclusion_status: 'manual_action_required',
  primary_target: 'market',
  health: {
    total: 3,
    pass: 0,
    degraded: 2,
    blocked: 0,
    manual_action_required: 1,
    skipped: 0,
  },
  subsystems: [
    {
      id: 'market_data',
      status: 'degraded',
      tone: 'warning',
      target: 'market',
      last_run_at: '2026-07-17T14:48:00+08:00',
      next_action: 'review_market_data_freshness',
      limitations: ['Three fund NAV observations require confirmation.'],
      detail_status: 'fund_nav_confirmation_required',
    },
  ],
  attention_items: [
    {
      schema_version: 'karkinos.operations_attention_item.v1',
      subsystem_id: 'market_data',
      status: 'degraded',
      target: 'market',
      evidence: {
        status: 'fund_nav_confirmation_required',
        observed_at: '2026-07-17T14:48:00+08:00',
      },
      next_action: 'review_market_data_freshness',
      resolution_condition: 'new_complete_market_evidence_required',
      task_fingerprint: 'sha256:market-attention-fixture',
      manual_acknowledgement_clears_status: false,
      read_only_projection: true,
      provider_contacted: false,
      database_writes_performed: false,
      authorizes_execution: false,
    },
  ],
  daily_operations: dailyOperations,
  daily_plan: {
    candidate_pool_count: 14,
    manual_ready_count: 0,
    blocked_count: 14,
    order_intent_count: 0,
    conclusion_status: 'no_manual_action',
  },
  paper_shadow: {
    status: 'not_required',
    run_id: null,
    order_intent_count: 0,
    simulated_order_count: 0,
    simulated_fill_count: 0,
    divergence_reviewed_count: 0,
    divergence_status: 'not_required',
    next_manual_review_step: 'none',
    last_run_at: null,
    orders: [],
  },
  limitations: [],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderOperationsPage(projection: unknown = safeProjection) {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  installMatchMediaMock();
  const fetchMock = vi.fn(async () => jsonResponse(projection));
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OperationsPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return fetchMock;
}

function installMatchMediaMock() {
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
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

test('renders persisted attention evidence without write or execution affordances', async () => {
  const fetchMock = renderOperationsPage();

  expect(
    await screen.findByRole('heading', { name: 'Operations evidence' }),
  ).toBeTruthy();
  const page = await screen.findByTestId('operations-page');
  expect(page.textContent).toContain('Read-only projection');
  expect(page.textContent).toContain('Provider not contacted');
  expect(page.textContent).toContain('No execution authority');

  const attention = await screen.findByRole('list', {
    name: 'Evidence review queue',
  });
  expect(
    within(attention).getByRole('heading', { name: 'Market data and NAV' }),
  ).toBeTruthy();
  expect(attention).toBeTruthy();
  expect(
    within(attention).getByText('Review market data freshness'),
  ).toBeTruthy();
  expect(
    within(attention).getByText('new complete market evidence is persisted'),
  ).toBeTruthy();
  expect(
    within(attention).getByText(
      'Viewing or acknowledging this item does not clear its source status.',
    ),
  ).toBeTruthy();
  expect(
    within(attention).getByTitle('sha256:market-attention-fixture'),
  ).toBeTruthy();
  expect(
    within(attention)
      .getByRole('link', { name: 'Open evidence' })
      .getAttribute('href'),
  ).toBe('/market');

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/operations/today',
    expect.objectContaining({ headers: { Accept: 'application/json' } }),
  );
  expect(screen.queryByRole('button', { name: /submit/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /cancel/i })).toBeNull();
  expect(screen.queryByRole('button', { name: /capital/i })).toBeNull();
});

test('blocks drill-down when an attention item violates the read-only contract', async () => {
  renderOperationsPage({
    ...safeProjection,
    attention_items: [
      {
        ...safeProjection.attention_items?.[0],
        authorizes_execution: true,
      },
    ],
  });

  const blocked = await screen.findByTestId('operations-contract-blocked');
  expect(
    within(blocked).getByText('Operations evidence contract blocked'),
  ).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Open evidence' })).toBeNull();
});

test('keeps subsystem evidence visible when the review queue is empty', async () => {
  renderOperationsPage({
    ...safeProjection,
    conclusion_status: 'healthy',
    attention_items: [],
    health: {
      total: 1,
      pass: 1,
      degraded: 0,
      blocked: 0,
      manual_action_required: 0,
      skipped: 0,
    },
  });

  const attentionQueue = await screen.findByTestId(
    'operations-attention-queue',
  );
  expect(within(attentionQueue).getByRole('status').textContent).toContain(
    'No subsystem currently requires evidence review.',
  );
  expect(
    screen.getByRole('link', {
      name: 'Market data and NAV',
      hidden: true,
    }),
  ).toBeTruthy();
  expect(
    screen.getByText('Three fund NAV observations require confirmation.'),
  ).toBeTruthy();
  expect(screen.getByText('No canonical history events')).toBeTruthy();
  expect(
    screen.getByText(
      'The current projection contains latest subsystem state only; it is not rewritten as immutable history.',
    ),
  ).toBeTruthy();
});

test('shows a retryable blocked read state without inventing evidence', async () => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  installMatchMediaMock();
  const fetchMock = vi.fn(async () =>
    jsonResponse({ detail: 'failed' }, { status: 500 }),
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OperationsPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect((await screen.findByTestId('operations-error')).textContent).toContain(
    'The Operations evidence projection could not be loaded.',
  );
  expect(screen.getByRole('button', { name: 'Retry read' })).toBeTruthy();
  expect(screen.queryByTestId('operations-attention-market_data')).toBeNull();
});
