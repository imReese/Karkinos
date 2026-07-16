import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledOrderJourney,
  ManualBrokerCancellationTicketExport,
  ManualBrokerCancellationTicketPreview,
} from './api';
import { ManualBrokerCancellationTicketPanel } from './manual-broker-cancellation-ticket-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const submitIntentId = '1'.repeat(64);
const ticketFingerprint = '2'.repeat(64);

const journey: ControlledOrderJourney = {
  submit_intent_id: submitIntentId,
  order_id: 'OMS-OPEN-1',
  broker_order_id: 'BROKER-OPEN-1',
  client_order_id: 'KARK-OPEN-1',
  gateway_id: 'fixture-write-edge',
  status: 'open_broker_order_review_required',
  next_operator_action: 'review_open_order_or_prepare_manual_cancel_ticket',
  attention_required: true,
  attention_severity: 'critical',
  blocks_new_submissions: true,
  prepared_at: '2026-07-16T07:45:00+00:00',
  updated_at: '2026-07-16T07:45:02+00:00',
  last_recovery_at: '',
  stages: [],
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  broker_submission_performed: false,
  broker_cancel_performed: false,
  ledger_mutation_performed: false,
  authority_changed: false,
};

const safety = {
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  broker_submission_performed: false,
  broker_cancel_performed: false,
  cancellation_proven: false,
  oms_mutated: false,
  production_ledger_mutated: false,
  risk_state_mutated: false,
  kill_switch_mutated: false,
  capital_authority_changed: false,
  authorizes_submission: false,
  authorizes_cancellation: false,
  releases_submission_interlock: false,
} as const;

const preview: ManualBrokerCancellationTicketPreview = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket.v1',
  submit_intent_id: submitIntentId,
  submit_fingerprint: '3'.repeat(64),
  order_id: journey.order_id,
  order_fingerprint: '4'.repeat(64),
  provider: 'fixture_broker',
  identity: {
    gateway_id: journey.gateway_id,
    account_alias: 'main-cn-account',
    broker_order_id: journey.broker_order_id,
    client_order_id: journey.client_order_id,
  },
  order: {
    symbol: '600519',
    side: 'buy',
    asset_class: 'stock',
    order_type: 'limit',
    limit_price: '10',
    order_quantity: '100',
    lifecycle_status: 'partially_filled',
    filled_quantity: '40',
    cancelled_quantity: '0',
    remaining_quantity: '60',
  },
  lifecycle_evidence: {
    observation_id: 'observation-1',
    evidence_fingerprint: '5'.repeat(64),
    source_sequence: 7,
    captured_at: '2026-07-16T07:46:00+00:00',
    source_name: 'deterministic fixture',
    collector_run_id: 'collector-run-7',
    collector_status: 'healthy',
  },
  ticket_fingerprint: ticketFingerprint,
  generated_at: '2026-07-16T07:47:00+00:00',
  status: 'ready_for_manual_broker_action',
  ready: true,
  blockers: [],
  required_acknowledgement:
    'prepare_manual_broker_cancellation_ticket_without_broker_contact',
  human_steps: [],
  assumptions: [],
  risk_impact: 'No authority change.',
  safety,
  limitations: [],
};

const exported: ManualBrokerCancellationTicketExport = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket_export.v1',
  status: 'export_ready',
  ticket_fingerprint: ticketFingerprint,
  export_fingerprint: '6'.repeat(64),
  filename: 'manual-cancel.json',
  content_type: 'application/json',
  content: '{"broker_cancel_performed":false}',
  artifact: { broker_cancel_performed: false },
  export_performed: true,
  safety,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel(
  response: ManualBrokerCancellationTicketPreview = preview,
) {
  const requests: RecordedRequest[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({
        url,
        method: init?.method ?? 'GET',
        body: init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : null,
      });
      if (url.endsWith('/manual-cancellation-ticket/preview')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/manual-cancellation-ticket/export')) {
        return jsonResponse(exported);
      }
      return jsonResponse(
        { detail: `unexpected request: ${url}` },
        { status: 404 },
      );
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ManualBrokerCancellationTicketPanel journey={journey} locale="en" />
    </QueryClientProvider>,
  );
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('previews and exports evidence without any broker cancel or mutation call', async () => {
  const requests = renderPanel();

  expect(requests).toHaveLength(0);
  expect(screen.queryByText('Cancel broker order')).toBeNull();
  fireEvent.click(screen.getByText('Prepare cancellation package'));

  expect(await screen.findByText('Partially filled')).toBeTruthy();
  expect(screen.getByText('40 / 60')).toBeTruthy();
  expect(requests).toHaveLength(1);
  const acknowledgement = screen.getByLabelText(
    /I understand this is preparation only/,
  );
  fireEvent.click(acknowledgement);
  fireEvent.click(screen.getByText('Create copyable evidence package'));

  expect(
    (
      (await screen.findByLabelText(
        'Evidence package JSON',
      )) as HTMLTextAreaElement
    ).value,
  ).toBe(exported.content);
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].body).toEqual({
    ticket_fingerprint: ticketFingerprint,
    acknowledgement:
      'prepare_manual_broker_cancellation_ticket_without_broker_contact',
  });
  expect(
    requests.every(
      (request) =>
        !request.url.includes('/broker-cancel') &&
        !request.url.endsWith('/submissions') &&
        !request.url.endsWith('/recoveries') &&
        !request.url.includes('/ledger'),
    ),
  ).toBe(true);
});

test('blocked evidence cannot be exported', async () => {
  const requests = renderPanel({
    ...preview,
    status: 'blocked',
    ready: false,
    blockers: ['manual_broker_cancel_lifecycle_collector_unhealthy'],
  });

  fireEvent.click(screen.getByText('Prepare cancellation package'));
  expect(
    await screen.findByText(/lifecycle collector evidence is unhealthy/i),
  ).toBeTruthy();
  expect(
    (screen.getByText('Create copyable evidence package') as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(requests).toHaveLength(1);
});

test('does not render outside the exact persisted open-order action', () => {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <ManualBrokerCancellationTicketPanel
        journey={{
          ...journey,
          next_operator_action: 'review_execution_reconciliation',
        }}
        locale="en"
      />
    </QueryClientProvider>,
  );

  expect(
    screen.queryByTestId('manual-broker-cancellation-ticket-panel'),
  ).toBeNull();
});
