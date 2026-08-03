import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  cleanup,
  fireEvent,
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

const blockedPilotReadiness: NonNullable<
  OperationsTodayResponse['controlled_per_order_pilot_readiness']
> = {
  schema_version: 'karkinos.controlled_per_order_pilot_readiness.v1',
  status: 'blocked',
  scope: {
    provider: '',
    gateway_id: '',
    account_alias: '',
    connector_id: '',
    readonly_release_evidence_ref: '',
    write_release_evidence_id: '',
  },
  gates: [
    {
      key: 'persisted_source_contracts',
      status: 'pass',
      blockers: [],
      evidence_refs: ['karkinos.broker_adapter_readiness.v1'],
      resolution_condition: 'restore_safe_persisted_only_source_contracts',
      manual_acknowledgement_clears_status: false,
    },
    {
      key: 'one_observing_readonly_adapter_release',
      status: 'blocked',
      blockers: ['readonly_adapter_release_missing'],
      evidence_refs: [],
      resolution_condition:
        'accept_and_observe_one_exact_readonly_adapter_release',
      manual_acknowledgement_clears_status: false,
    },
    {
      key: 'signed_readonly_soak_promotion',
      status: 'blocked',
      blockers: ['readonly_adapter_scope_unresolved'],
      evidence_refs: [],
      resolution_condition:
        'complete_exact_scope_soak_and_record_owner_acceptance',
      manual_acknowledgement_clears_status: false,
    },
    {
      key: 'one_active_manual_each_order_write_release',
      status: 'blocked',
      blockers: ['active_manual_each_order_write_release_missing'],
      evidence_refs: [],
      resolution_condition: 'issue_one_short_lived_exact_scope_write_release',
      manual_acknowledgement_clears_status: false,
    },
    {
      key: 'one_exact_provider_account_gateway_scope',
      status: 'blocked',
      blockers: ['pilot_scope_evidence_incomplete'],
      evidence_refs: [],
      resolution_condition:
        'resolve_provider_account_gateway_connector_scope_drift',
      manual_acknowledgement_clears_status: false,
    },
    {
      key: 'no_unresolved_order_or_session_authority',
      status: 'blocked',
      blockers: ['controlled_operator_view_untrusted'],
      evidence_refs: [],
      resolution_condition:
        'close_controlled_journeys_and_remove_session_authority',
      manual_acknowledgement_clears_status: false,
    },
  ],
  required_next_order_gates: [
    'canonical_manually_confirmed_oms_order',
    'fresh_offline_operator_signature',
  ],
  readiness_fingerprint: `sha256:${'a'.repeat(64)}`,
  observed_at: null,
  gate_count: 6,
  passed_gate_count: 1,
  blocked_gate_count: 5,
  blockers: [
    'one_observing_readonly_adapter_release:readonly_adapter_release_missing',
  ],
  next_safe_action: 'owner_select_and_review_real_broker_provider',
  release_scope: 'pilot_admission_prerequisites_not_v1_8_completion',
  persisted_facts_only: true,
  read_only_projection: true,
  provider_contacted: false,
  database_writes_performed: false,
  broker_submission_enabled: false,
  broker_cancellation_enabled: false,
  does_not_mutate_oms: true,
  does_not_mutate_production_ledger: true,
  does_not_mutate_risk_state: true,
  does_not_mutate_kill_switch: true,
  does_not_mutate_capital_authority: true,
  authorizes_execution: false,
  automatic_scale_up_enabled: false,
  limitations: [
    'Ready means only that the owner may open a separate exact-order review.',
  ],
};

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function renderOperationsPage(
  projection: unknown = safeProjection,
  locale: 'en' | 'zh' = 'en',
) {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', locale);
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

test('renders a structured workspace while Operations evidence loads', () => {
  window.localStorage.clear();
  window.localStorage.setItem('karkinos.locale', 'en');
  installMatchMediaMock();
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => undefined)),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <OperationsPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  expect(screen.getByTestId('operations-loading')).toBeTruthy();
  expect(
    document.querySelector(
      '[data-workbench-primitive="evidence-loading-layout"]',
    ),
  ).toBeTruthy();
  expect(screen.getByTestId('evidence-loading-metrics').children).toHaveLength(
    4,
  );
  expect(screen.getByTestId('evidence-loading-rows').children).toHaveLength(4);
});

test('renders persisted attention evidence without write or execution affordances', async () => {
  const fetchMock = renderOperationsPage();

  expect(
    await screen.findByRole('heading', { name: 'Operations evidence' }),
  ).toBeTruthy();
  const page = await screen.findByTestId('operations-page');
  expect(page.textContent).toContain('Read only');
  expect(page.textContent).toContain('No external connection');
  expect(page.textContent).toContain('No execution authority');

  const attention = await screen.findByRole('list', {
    name: 'Evidence review queue',
  });
  const attentionQueue = screen.getByTestId('operations-attention-queue');
  const commandGrid = screen.getByTestId('operations-command-grid');
  const healthMetrics = page.querySelector(
    '[data-workbench-primitive="metric-strip"]',
  );
  expect(attention.getAttribute('data-density')).toBe('compact');
  expect(commandGrid.className).toContain('app-operations-command-grid');
  expect(attention.className).toContain('app-operations-attention-list');
  expect(attention.className).toContain('divide-y');
  expect(healthMetrics).toBeTruthy();
  expect(healthMetrics?.getAttribute('aria-label')).toBe('Health overview');
  expect(
    attentionQueue.compareDocumentPosition(healthMetrics as HTMLElement) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    within(attention).getByRole('heading', { name: 'Market data and NAV' }),
  ).toBeTruthy();
  expect(attention).toBeTruthy();
  expect(
    within(attention).getByText('Review market data freshness'),
  ).toBeTruthy();
  expect(
    within(attention).getByText('new complete market evidence is recorded'),
  ).toBeTruthy();
  expect(
    within(attention).getByText(
      'Viewing or acknowledging this item does not clear its source status.',
    ),
  ).toBeTruthy();
  expect(attention.textContent).not.toContain(
    'sha256:market-attention-fixture',
  );
  fireEvent.click(
    within(attention).getByRole('button', { name: 'Review details' }),
  );
  const evidenceDetail = await screen.findByTestId(
    'operations-evidence-detail',
  );
  expect(evidenceDetail.textContent).toContain(
    'sha256:market-attention-fixture',
  );
  expect(evidenceDetail.textContent).toContain(
    'This page reads recorded facts only.',
  );
  expect(
    within(attention)
      .getByRole('link', { name: 'Open evidence' })
      .getAttribute('href'),
  ).toBe('/market');
  const subsystemRegister = screen.getByTestId('operations-subsystem-register');
  expect(subsystemRegister.querySelector('summary')?.textContent).toContain(
    'Subsystem evidence register',
  );
  fireEvent.click(subsystemRegister.querySelector('summary') as HTMLElement);
  const subsystemTable = screen.getByTestId('operations-subsystem-table');
  expect(within(subsystemTable).getAllByRole('columnheader')).toHaveLength(4);
  expect(subsystemTable.textContent).toContain('Observed at:');
  expect(subsystemTable.textContent).toContain(
    'Limitations: Three fund NAV observations require confirmation.',
  );

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
    within(blocked).getByText('Operations evidence is unavailable'),
  ).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Open evidence' })).toBeNull();
});

test('shows the fail-closed pilot admission gate without execution controls', async () => {
  renderOperationsPage({
    ...safeProjection,
    controlled_per_order_pilot_readiness: blockedPilotReadiness,
  });

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');
  expect(disclosure.hasAttribute('open')).toBe(false);
  expect(disclosure.querySelector('summary')?.className).toContain(
    'app-pilot-readiness-summary',
  );
  expect(disclosure.querySelector('summary')?.className).toContain(
    'focus-visible:ring-inset',
  );
  expect(disclosure.textContent).toContain(
    'Controlled per-order pilot admission evidence',
  );
  expect(disclosure.textContent).toContain('Prerequisites unmet');
  fireEvent.click(
    within(disclosure).getByText(
      'Controlled per-order pilot admission evidence',
    ),
  );

  expect(disclosure.hasAttribute('open')).toBe(true);
  expect(disclosure.textContent).toContain('One read-only adapter release');
  expect(disclosure.textContent).toContain(
    'A read-only adapter release has not been recorded',
  );
  expect(disclosure.textContent).toContain(
    'Accept and observe one exact read-only adapter release',
  );
  expect(disclosure.textContent).toContain(
    'Owner selects and reviews one real broker provider',
  );
  expect(disclosure.textContent).toContain(
    'not proof of v1.8 completion and not order, broker, or capital authority',
  );
  expect(disclosure.textContent).toContain(
    blockedPilotReadiness.readiness_fingerprint,
  );
  expect(within(disclosure).queryByRole('button')).toBeNull();
  expect(within(disclosure).queryByText(/submit order/i)).toBeNull();
  expect(within(disclosure).queryByText(/cancel order/i)).toBeNull();
  expect(disclosure.textContent).not.toContain('Status needs review');
});

test('keeps Chinese operations copy product-facing and technical identities progressively disclosed', async () => {
  renderOperationsPage(
    {
      ...safeProjection,
      controlled_per_order_pilot_readiness: blockedPilotReadiness,
    },
    'zh',
  );

  const page = await screen.findByTestId('operations-page');
  expect(page.textContent).toContain('本页只读取已记录事实');
  expect(page.textContent).not.toContain('GET');
  expect(page.textContent).not.toContain('provider');
  expect(page.textContent).not.toContain('kill switch');

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');
  fireEvent.click(within(disclosure).getByText('受控逐单试点准入证据'));
  expect(disclosure.textContent).toContain('单一只读适配器发布记录');
  expect(disclosure.textContent).toContain(
    '由账户所有者选择并复核一家真实券商接入方',
  );
  expect(disclosure.textContent).not.toMatch(
    /\b(?:release|soak|provider|gateway|connector|owner|schema|runtime|operator)\b/i,
  );

  const evidenceIdentity = within(disclosure).getByTestId(
    'pilot-readiness-identity',
  );
  expect(evidenceIdentity.hasAttribute('open')).toBe(false);
  expect(evidenceIdentity.textContent).toContain(
    blockedPilotReadiness.readiness_fingerprint,
  );

  const persistedEvidence = within(disclosure).getByTestId(
    'pilot-gate-evidence-persisted_source_contracts',
  );
  expect(persistedEvidence.hasAttribute('open')).toBe(false);
  expect(persistedEvidence.textContent).toContain('1 条已记录证据');
  expect(persistedEvidence.textContent).toContain(
    blockedPilotReadiness.gates[0].evidence_refs[0],
  );
});

test('blocks an unsafe pilot admission projection independently', async () => {
  renderOperationsPage({
    ...safeProjection,
    controlled_per_order_pilot_readiness: {
      ...blockedPilotReadiness,
      authorizes_execution: true,
    },
  });

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');

  expect(disclosure.hasAttribute('open')).toBe(true);
  expect(disclosure.textContent).toContain('Pilot admission contract blocked');
  expect(disclosure.textContent).toContain('do not enter exact-order review');
  expect(within(disclosure).queryByRole('button')).toBeNull();
});

test('opens an invalid pilot evidence fingerprint as a contract failure', async () => {
  renderOperationsPage({
    ...safeProjection,
    controlled_per_order_pilot_readiness: {
      ...blockedPilotReadiness,
      readiness_fingerprint: 'sha256:not-a-valid-fingerprint',
    },
  });

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');

  expect(disclosure.hasAttribute('open')).toBe(true);
  expect(disclosure.textContent).toContain('Contract blocked');
  expect(disclosure.textContent).toContain('Pilot admission contract blocked');
});

test('labels a clear optional pilot without granting execution authority', async () => {
  renderOperationsPage({
    ...safeProjection,
    controlled_per_order_pilot_readiness: {
      ...blockedPilotReadiness,
      status: 'ready_for_exact_order_review',
      gates: blockedPilotReadiness.gates.map((gate) => ({
        ...gate,
        status: 'pass',
        blockers: [],
        evidence_refs: [`evidence:${gate.key}`],
      })),
      passed_gate_count: 6,
      blocked_gate_count: 0,
      blockers: [],
      next_safe_action: 'open_exact_order_review_without_submission',
    },
  });

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');

  expect(disclosure.hasAttribute('open')).toBe(false);
  expect(disclosure.textContent).toContain('Ready for review');
  expect(within(disclosure).queryByRole('button')).toBeNull();
});

test('preserves an unknown upstream blocker instead of hiding it behind a generic status', async () => {
  renderOperationsPage({
    ...safeProjection,
    controlled_per_order_pilot_readiness: {
      ...blockedPilotReadiness,
      gates: blockedPilotReadiness.gates.map((gate) =>
        gate.key === 'one_observing_readonly_adapter_release'
          ? { ...gate, blockers: ['new_persisted_evidence_blocker'] }
          : gate,
      ),
    },
  });

  const disclosure = await screen.findByTestId('controlled-pilot-readiness');
  fireEvent.click(
    within(disclosure).getByText(
      'Controlled per-order pilot admission evidence',
    ),
  );

  expect(disclosure.textContent).toContain(
    'Evidence code: new persisted evidence blocker',
  );
  expect(disclosure.textContent).not.toContain('Status needs review');
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
    screen.getByTestId('operations-subsystem-register').textContent,
  ).toContain('Three fund NAV observations require confirmation.');
  expect(screen.getByText('No history events recorded')).toBeTruthy();
  expect(
    screen.getByText(
      'Only the latest state for each subsystem is available; no immutable history has been recorded yet.',
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
    'Operations evidence could not be loaded.',
  );
  expect(screen.getByRole('button', { name: 'Retry read' })).toBeTruthy();
  expect(screen.queryByTestId('operations-attention-market_data')).toBeNull();
});
