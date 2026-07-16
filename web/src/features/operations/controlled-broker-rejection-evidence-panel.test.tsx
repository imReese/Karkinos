import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { ControlledBrokerRejectionEvidencePanel } from './controlled-broker-rejection-evidence-panel';
import type {
  ControlledBrokerRejectionEvidenceExport,
  ControlledBrokerRejectionEvidencePreview,
  ControlledBrokerRejectionReview,
  ControlledOrderJourney,
} from './api';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const submitIntentId = '1'.repeat(64);
const reviewFingerprint = '2'.repeat(64);

const journey: ControlledOrderJourney = {
  submit_intent_id: submitIntentId,
  order_id: 'OMS-REJECTED-1',
  broker_order_id: '',
  client_order_id: 'KARK-REJECTED-1',
  gateway_id: 'fixture-write-edge',
  status: 'submission_rejected',
  next_operator_action: 'review_rejection_evidence_without_retry',
  prepared_at: '2026-07-16T08:45:00+00:00',
  updated_at: '2026-07-16T08:45:02+00:00',
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
  broker_query_performed: false,
  broker_submission_performed: false,
  broker_retry_performed: false,
  broker_cancel_performed: false,
  oms_mutated: false,
  production_ledger_mutated: false,
  account_truth_mutated: false,
  risk_state_mutated: false,
  kill_switch_mutated: false,
  capital_authority_changed: false,
  authorizes_submission: false,
  authorizes_retry: false,
  authorizes_cancellation: false,
  releases_submission_interlock: false,
} as const;

const preview: ControlledBrokerRejectionEvidencePreview = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence.v1',
  submit_intent_id: submitIntentId,
  submit_fingerprint: '3'.repeat(64),
  order_id: journey.order_id,
  order_fingerprint: '4'.repeat(64),
  identity: {
    gateway_id: journey.gateway_id,
    account_alias: 'main-cn-account',
    client_order_id: journey.client_order_id,
    operator_id: 'fixture-owner',
  },
  order: {
    symbol: '600519',
    side: 'buy',
    asset_class: 'stock',
    quantity: '100',
    order_type: 'limit',
    limit_price: '10',
  },
  rejection_evidence: {
    classification: 'definitive_gateway_rejection',
    intent_status: 'rejected',
    broker_status: 'rejected',
    result_status: 'rejected',
    submitted: false,
    definitive: true,
    error_type: '',
    reason_codes: [],
    result_fingerprint: '5'.repeat(64),
    prepared_at: journey.prepared_at,
    evidence_as_of: journey.updated_at,
  },
  retry_policy: {
    same_intent_retry_allowed: false,
    same_client_order_id_retry_allowed: false,
    automatic_retry_allowed: false,
    new_order_requires_new_decision_and_all_gates: true,
  },
  review_fingerprint: reviewFingerprint,
  generated_at: '2026-07-16T08:46:00+00:00',
  status: 'ready_for_human_review',
  ready: true,
  blockers: [],
  required_acknowledgement:
    'export_exact_rejection_evidence_without_retry_or_authority_change',
  human_steps: [],
  assumptions: [],
  risk_impact: 'Read-only evidence.',
  safety,
  limitations: [],
};

const exported: ControlledBrokerRejectionEvidenceExport = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence_export.v1',
  status: 'export_ready',
  review_fingerprint: reviewFingerprint,
  export_fingerprint: '6'.repeat(64),
  filename: 'rejection.json',
  content_type: 'application/json',
  content: '{"retry_performed":false}',
  artifact: { retry_performed: false },
  export_performed: true,
  safety,
};

const recordedReview: ControlledBrokerRejectionReview = {
  schema_version: 'karkinos.controlled_broker_rejection_review.v1',
  review_id: '7'.repeat(64),
  review_fingerprint: reviewFingerprint,
  submit_intent_id: submitIntentId,
  submit_fingerprint: preview.submit_fingerprint,
  order_id: journey.order_id,
  order_fingerprint: preview.order_fingerprint,
  result_fingerprint: preview.rejection_evidence.result_fingerprint,
  identity: preview.identity,
  reviewer_id: 'local-operator',
  disposition: 'acknowledged_no_retry',
  rejection_classification: 'definitive_gateway_rejection',
  evidence_as_of: preview.rejection_evidence.evidence_as_of,
  recorded_at: '2026-07-16T08:47:00+00:00',
  operator_acknowledgement:
    'record_exact_rejection_review_without_retry_or_authority_change',
  retry_policy: preview.retry_policy,
  status: 'recorded',
  reused: false,
  review_recorded: true,
  record_performed: true,
  safety,
  limitations: [],
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel(
  response: ControlledBrokerRejectionEvidencePreview = preview,
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
      if (url.endsWith('/rejection-evidence/preview')) {
        return jsonResponse(response);
      }
      if (url.endsWith('/rejection-evidence/export')) {
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
      <ControlledBrokerRejectionEvidencePanel journey={journey} locale="en" />
    </QueryClientProvider>,
  );
  return requests;
}

function renderReviewPanel() {
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
      if (url.endsWith('/rejection-evidence/preview')) {
        return jsonResponse(preview);
      }
      if (url.endsWith('/rejection-reviews')) {
        return jsonResponse(recordedReview);
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
      <ControlledBrokerRejectionEvidencePanel journey={journey} locale="en" />
    </QueryClientProvider>,
  );
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('previews and exports rejection evidence without query, retry, or mutation', async () => {
  const requests = renderPanel();

  expect(requests).toHaveLength(0);
  expect(screen.queryByText('Retry broker order')).toBeNull();
  fireEvent.click(screen.getByText('Review rejection evidence'));

  expect(await screen.findByText('Definitive gateway rejection')).toBeTruthy();
  expect(screen.getByText(/600519 · buy · 100/)).toBeTruthy();
  expect(requests).toHaveLength(1);
  fireEvent.click(
    screen.getByLabelText(/persisted submit intent and client order id/),
  );
  fireEvent.click(screen.getByText('Create copyable review package'));

  expect(
    (
      (await screen.findByLabelText(
        'Rejection evidence JSON',
      )) as HTMLTextAreaElement
    ).value,
  ).toBe(exported.content);
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].body).toEqual({
    review_fingerprint: reviewFingerprint,
    acknowledgement:
      'export_exact_rejection_evidence_without_retry_or_authority_change',
  });
  expect(
    requests.every(
      (request) =>
        !request.url.endsWith('/recoveries') &&
        !request.url.endsWith('/submissions') &&
        !request.url.includes('/broker-cancel') &&
        !request.url.includes('/ledger'),
    ),
  ).toBe(true);
});

test('blocked rejection evidence cannot be exported', async () => {
  const requests = renderPanel({
    ...preview,
    status: 'blocked',
    ready: false,
    blockers: ['controlled_broker_rejection_result_not_definitive'],
  });

  fireEvent.click(screen.getByText('Review rejection evidence'));
  expect(
    await screen.findByText(/persisted rejection evidence is not definitive/i),
  ).toBeTruthy();
  expect(
    (screen.getByText('Create copyable review package') as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(requests).toHaveLength(1);
});

test('records an explicit reviewer-bound no-retry acknowledgement', async () => {
  const requests = renderReviewPanel();

  fireEvent.click(screen.getByText('Review rejection evidence'));
  expect(await screen.findByText('Definitive gateway rejection')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Reviewer ID'), {
    target: { value: 'local-operator' },
  });
  fireEvent.click(
    screen.getByLabelText(/persisted submit intent and client order id/),
  );
  fireEvent.click(screen.getByText('Record no-retry review'));

  expect(
    await screen.findByText(
      'Rejection review recorded; the original intent must not be retried.',
    ),
  ).toBeTruthy();
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1]).toEqual({
    url: `/api/automation/controlled-broker-submission/intents/${submitIntentId}/rejection-reviews`,
    method: 'POST',
    body: {
      review_fingerprint: reviewFingerprint,
      reviewer_id: 'local-operator',
      disposition: 'acknowledged_no_retry',
      acknowledgement:
        'record_exact_rejection_review_without_retry_or_authority_change',
    },
  });
  expect(
    requests.every(
      (request) =>
        !request.url.endsWith('/recoveries') &&
        !request.url.endsWith('/submissions') &&
        !request.url.includes('/broker-cancel') &&
        !request.url.includes('/ledger'),
    ),
  ).toBe(true);
});

test('does not render outside the exact persisted rejected-order action', () => {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <ControlledBrokerRejectionEvidencePanel
        journey={{
          ...journey,
          next_operator_action: 'run_or_review_execution_reconciliation',
        }}
        locale="en"
      />
    </QueryClientProvider>,
  );

  expect(
    screen.queryByTestId('controlled-broker-rejection-evidence-panel'),
  ).toBeNull();
});
