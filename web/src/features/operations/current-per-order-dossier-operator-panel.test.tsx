import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  CurrentPerOrderDossierCandidates,
  CurrentPerOrderDossierPreview,
} from './api';
import { CurrentPerOrderDossierOperatorPanel } from './current-per-order-dossier-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const orderId = 'OMS-FIXTURE-REVIEW-1';
const dossierFingerprint = 'd'.repeat(64);
const capitalFingerprint = 'a'.repeat(64);
const batchFingerprint = 'b'.repeat(64);
const gatewayFingerprint = 'e'.repeat(64);
const challengeId = 'c'.repeat(64);
const signature = 'S'.repeat(88);

const candidates: CurrentPerOrderDossierCandidates = {
  schema_version: 'karkinos.current_per_order_confirmation_candidates.v1',
  candidate_count: 1,
  candidates: [
    {
      order_id: orderId,
      symbol: '510300.SH',
      side: 'buy',
      asset_class: 'fund',
      quantity: '100',
      order_type: 'limit',
      limit_price: '4.1',
      oms_status: 'manually_confirmed',
      updated_at: '2026-07-17T08:00:00+00:00',
      order_fingerprint: 'f'.repeat(64),
      dossier_fingerprint: dossierFingerprint,
      review_status: 'review_ready_non_submitting',
      review_ready: true,
      review_blockers: [],
      evidence_resolution_status: 'resolved',
      confirmation_status: 'missing',
      authorizes_execution: false,
    },
  ],
  truncated: false,
  selection_contract: 'canonical_manually_confirmed_oms_orders_only',
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  runtime_connector_query_performed: false,
  does_not_mutate_oms: true,
  does_not_mutate_production_ledger: true,
  does_not_mutate_risk: true,
  does_not_mutate_kill_switch: true,
  does_not_change_capital_authority: true,
  broker_submission_enabled: false,
  broker_cancel_enabled: false,
  authorizes_execution: false,
};

const preview: CurrentPerOrderDossierPreview = {
  schema_version: 'karkinos.current_per_order_confirmation_dossier.v1',
  underlying_dossier_schema_version:
    'karkinos.per_order_confirmation_dossier.v5',
  order: {
    order_id: orderId,
    intent_key: 'fixture-intent-1',
    symbol: '510300.SH',
    side: 'buy',
    asset_class: 'fund',
    quantity: '100',
    order_type: 'limit',
    limit_price: '4.1',
    source: 'daily_trading_plan',
    source_ref: 'decision-fixture-1',
  },
  order_fingerprint: 'f'.repeat(64),
  dossier_fingerprint: dossierFingerprint,
  generated_at: '2026-07-17T08:01:00+00:00',
  evidence_resolution: {
    status: 'resolved',
    selected_capital_evaluation_event_id: 41,
    selected_capital_evaluation_recorded_at: '2026-07-17T08:00:00+00:00',
    capital_evaluation_input_fingerprint: capitalFingerprint,
    prior_batch_reconciliation_fingerprint: batchFingerprint,
    execution_gateway_verification_fingerprint: gatewayFingerprint,
    blockers: [],
    scan_limit: 500,
    scan_truncated: false,
  },
  capital_evaluation: {
    status: 'pass',
    authorization_id: 'fixture-authorization-1',
    policy_version: 'policy-v1',
    effective_at: '2026-07-17T07:55:00+00:00',
    expires_at: '2026-07-17T09:00:00+00:00',
    scope: {
      account_alias: 'fixture-review-account',
      strategy_id: 'fixture-strategy-1',
      symbol: '510300.SH',
      evidence_connector_id: 'fixture-readonly-edge',
      execution_gateway_id: 'fixture-disabled-gateway',
    },
    effective_limits: { max_order_value: '1000' },
    remaining_budget: { order_value: '590' },
  },
  broker_adapter_release: {
    schema_version: 'karkinos.per_order_broker_adapter_release_binding.v1',
    status: 'pass',
    expected_scope: {
      collector_id: 'fixture-readonly-edge',
      gateway_id: 'fixture-disabled-gateway',
      account_alias: 'fixture-review-account',
    },
    matching_release_count: 1,
    release: {
      release_evidence_ref: 'release-evidence-v1',
      manifest_fingerprint: '7'.repeat(64),
      provider: 'deterministic-fixture',
      gateway_id: 'fixture-disabled-gateway',
      account_alias: 'fixture-review-account',
      collector_id: 'fixture-readonly-edge',
      review_status: 'accepted',
      conformance_status: 'clear',
      collector_status: 'recorded',
      collector_run_id: 'collector-run-v1',
      status: 'observing_readonly',
      does_not_authorize_provider_activation: true,
    },
    blockers: [],
    persisted_evidence_only: true,
    provider_contact_performed: false,
    broker_submission_enabled: false,
    authorizes_execution: false,
  },
  prior_execution_reconciliation: {
    status: 'pass',
    run_id: 'fixture-prior-run-1',
    run_date: '2026-07-16',
    reconciliation_status: 'clear',
  },
  execution_gateway_verification: {
    status: 'pass',
    verification_fingerprint: gatewayFingerprint,
    recorded_at: '2026-07-17T08:00:00+00:00',
  },
  kill_switch: { status: 'pass', enabled: false, reason: '' },
  confirmation: {
    status: 'missing',
    confirmation_id: '',
    recorded_at: '',
    operator_label: '',
  },
  review_status: 'review_ready_non_submitting',
  review_ready: true,
  current_evidence_resolved: true,
  review_blockers: [],
  hard_submission_blockers: [
    'runtime_execution_authority_disabled',
    'live_gateway_not_implemented',
    'broker_submission_disabled',
  ],
  submission_status: 'blocked',
  required_operator_approval: {
    action: 'attest_per_order_dossier',
    artifact_type: 'per_order_dossier',
    artifact_fingerprint: dossierFingerprint,
  },
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  runtime_connector_query_performed: false,
  does_not_mutate_oms: true,
  does_not_mutate_production_ledger: true,
  does_not_mutate_risk: true,
  does_not_mutate_kill_switch: true,
  does_not_change_capital_authority: true,
  broker_submission_enabled: false,
  broker_cancel_enabled: false,
  authorizes_execution: false,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel({
  candidatesResponse = candidates,
  previewResponse = preview,
}: {
  candidatesResponse?: CurrentPerOrderDossierCandidates;
  previewResponse?: CurrentPerOrderDossierPreview;
} = {}) {
  const requests: RecordedRequest[] = [];
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      requests.push({ url, method, body });
      if (url.includes('/controlled-bridge/dossiers/current')) {
        return jsonResponse(candidatesResponse);
      }
      if (url.endsWith(`/orders/${orderId}/dossier/current/preview`)) {
        return jsonResponse(previewResponse);
      }
      if (url.endsWith('/operator-approvals/status')) {
        return jsonResponse({
          schema_version: 'karkinos.operator_approval_status.v1',
          contract_status: 'public_key_verification_only',
          trusted_identity_count: 1,
          enabled_identity_count: 1,
          trusted_identities: [
            {
              operator_id: 'local-owner',
              key_id: 'owner-key-1',
              algorithm: 'ed25519',
              enabled: true,
              public_key_fingerprint: '1'.repeat(64),
            },
          ],
          private_key_storage_enabled: false,
          runtime_execution_authority: 'disabled',
          broker_submission_enabled: false,
        });
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi1leGFjdC1kb3NzaWVy',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'attest_per_order_dossier',
          artifact_type: 'per_order_dossier',
          artifact_fingerprint: dossierFingerprint,
          issued_at: '2026-07-17T08:02:00+00:00',
          expires_at: '2026-07-17T08:05:00+00:00',
          reused: false,
          operator_identity_verified: false,
          authorizes_execution: false,
        });
      }
      if (url.endsWith('/operator-approvals/verifications')) {
        return jsonResponse({
          approval_id: challengeId,
          approval_status: 'verified',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'attest_per_order_dossier',
          artifact_type: 'per_order_dossier',
          artifact_fingerprint: dossierFingerprint,
          expires_at: '2026-07-17T08:05:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (url.endsWith(`/orders/${orderId}/dossier/current/confirmations`)) {
        return jsonResponse({
          status: 'recorded_verified_identity',
          confirmation_id: '2'.repeat(64),
          order_id: orderId,
          dossier_fingerprint: dossierFingerprint,
          operator_label: 'local-owner',
          operator_identity_verified: true,
          authorizes_execution: false,
          broker_submission_enabled: false,
          reused: false,
        });
      }
      return jsonResponse(
        { detail: `unexpected request: ${url}` },
        { status: 404 },
      );
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
    <QueryClientProvider client={queryClient}>
      <CurrentPerOrderDossierOperatorPanel locale="en" />
    </QueryClientProvider>,
  );
  return { fetchMock, requests };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('stays collapsed without reads, then records an exact non-authorizing review', async () => {
  const { fetchMock, requests } = renderPanel();

  expect(screen.getByText('Open per-order review')).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Open per-order review'));
  expect(await screen.findByText(/Current candidates \(1\)/)).toBeTruthy();
  fireEvent.click(screen.getByText('Resolve current exact evidence'));
  expect(await screen.findByText('510300.SH · Buy 100')).toBeTruthy();
  expect(screen.getByText('release-evidence-v1')).toBeTruthy();
  expect(screen.getByText('Read-only observation active')).toBeTruthy();
  expect(
    screen.getByText(
      'Submission remains blocked with 3 hard gates. This review removes none of them.',
    ),
  ).toBeTruthy();

  await waitFor(() =>
    expect(
      requests.some((request) =>
        request.url.endsWith('/operator-approvals/status'),
      ),
    ).toBe(true),
  );
  fireEvent.click(
    screen.getByText('Create 3-minute offline signing challenge'),
  );
  expect(
    (
      (await screen.findByLabelText(
        'Offline signing payload (base64)',
      )) as HTMLTextAreaElement
    ).value,
  ).toBe('c2lnbi1leGFjdC1kb3NzaWVy');
  fireEvent.change(screen.getByLabelText('Paste detached signature (base64)'), {
    target: { value: signature },
  });
  fireEvent.click(screen.getByText('Verify offline signature'));
  const recordButton = await screen.findByText(
    'Record non-authorizing per-order review',
  );
  expect(recordButton.hasAttribute('disabled')).toBe(true);
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: /I confirm this records only a non-authorizing review/,
    }),
  );
  fireEvent.click(recordButton);
  expect(
    await screen.findByText(
      'The per-order review fact is recorded. Broker submit, cancel, and capital authority remain disabled.',
    ),
  ).toBeTruthy();

  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    `/api/automation/controlled-bridge/orders/${orderId}/dossier/current/preview`,
    '/api/automation/capital-authority/operator-approvals/challenges',
    '/api/automation/capital-authority/operator-approvals/verifications',
    `/api/automation/controlled-bridge/orders/${orderId}/dossier/current/confirmations`,
  ]);
  expect(postRequests[1].body).toEqual({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'attest_per_order_dossier',
    artifact_type: 'per_order_dossier',
    artifact_fingerprint: dossierFingerprint,
    ttl_seconds: 180,
  });
  expect(postRequests[3].body).toEqual({
    dossier_fingerprint: dossierFingerprint,
    operator_label: 'local-owner',
    operator_approval_id: challengeId,
    acknowledgement: 'confirm_exact_non_submitting_dossier_for_review',
  });
  expect(JSON.stringify(requests)).not.toContain('private_key');
  expect(JSON.stringify(postRequests[3].body)).not.toContain(signature);
  expect(JSON.stringify(postRequests[3].body)).not.toContain(
    capitalFingerprint,
  );
  expect(JSON.stringify(postRequests[3].body)).not.toContain(batchFingerprint);
  expect(JSON.stringify(postRequests[3].body)).not.toContain(
    gatewayFingerprint,
  );
  expect(requests.some((request) => request.url.includes('/submissions'))).toBe(
    false,
  );
  expect(requests.some((request) => request.url.includes('/cancel'))).toBe(
    false,
  );
});

test('shows canonical blockers and never opens a signing path', async () => {
  const { requests } = renderPanel({
    previewResponse: {
      ...preview,
      review_status: 'blocked_review',
      review_ready: false,
      current_evidence_resolved: false,
      review_blockers: ['current_execution_gateway_verification_ref_ambiguous'],
      required_operator_approval: null,
    },
  });

  fireEvent.click(screen.getByText('Open per-order review'));
  await screen.findByText(/Current candidates \(1\)/);
  fireEvent.click(screen.getByText('Resolve current exact evidence'));
  expect(
    await screen.findByText('Current evidence is insufficient for signing'),
  ).toBeTruthy();
  expect(
    screen.queryByText('Create 3-minute offline signing challenge'),
  ).toBeNull();
  expect(
    requests.some((request) =>
      request.url.endsWith('/operator-approvals/challenges'),
    ),
  ).toBe(false);
});

test('keeps the default closed state when no canonical order exists', async () => {
  const { requests } = renderPanel({
    candidatesResponse: {
      ...candidates,
      candidate_count: 0,
      candidates: [],
    },
  });

  fireEvent.click(screen.getByText('Open per-order review'));
  expect(
    await screen.findByText(
      'No canonical manually_confirmed OMS order is available. The system stays default-closed and creates no sample order or broker contact.',
    ),
  ).toBeTruthy();
  expect(requests).toHaveLength(1);
  expect(requests[0].method).toBe('GET');
  expect(screen.queryByText('Resolve current exact evidence')).toBeNull();
});
