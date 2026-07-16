import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledBrokerRecoveryPreview,
  ControlledOrderJourney,
  OperatorApprovalStatus,
} from './api';
import { ControlledBrokerRecoveryOperatorPanel } from './controlled-broker-recovery-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const submitIntentId = '1'.repeat(64);
const recoveryFingerprint = '2'.repeat(64);
const challengeId = '3'.repeat(64);
const signature = 'S'.repeat(88);

const journey: ControlledOrderJourney = {
  submit_intent_id: submitIntentId,
  order_id: 'OMS-UNKNOWN-1',
  broker_order_id: '',
  client_order_id: 'KARK-UNKNOWN-1',
  gateway_id: 'fixture-write-edge',
  status: 'submission_unknown',
  next_operator_action: 'query_submission_outcome_without_resubmit',
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

const approvalStatus: OperatorApprovalStatus = {
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
      public_key_fingerprint: 'a'.repeat(64),
    },
  ],
  private_key_storage_enabled: false,
  runtime_execution_authority: 'disabled',
  broker_submission_enabled: false,
};

const recoveryPreview: ControlledBrokerRecoveryPreview = {
  schema_version: 'karkinos.controlled_broker_submission_recovery.v1',
  submit_intent_id: submitIntentId,
  submit_fingerprint: '4'.repeat(64),
  recovery_fingerprint: recoveryFingerprint,
  order_id: journey.order_id,
  order_fingerprint: '5'.repeat(64),
  gateway_id: journey.gateway_id,
  client_order_id: journey.client_order_id,
  operator_id: 'local-owner',
  source_status: 'submission_unknown',
  source_result_fingerprint: '6'.repeat(64),
  prepared_at: journey.prepared_at,
  last_recovery_at: '',
  review_status: 'ready_for_final_signature',
  review_ready: true,
  blockers: [],
  recovery_wait_remaining_seconds: 0,
  gateway_query_capability: true,
  required_operator_approval: {
    action: 'query_unknown_controlled_broker_submission',
    artifact_type: 'controlled_broker_submission_recovery',
    artifact_fingerprint: recoveryFingerprint,
  },
  reads_persisted_facts_only: true,
  provider_contact_performed: false,
  broker_query_performed: false,
  broker_submission_performed: false,
  broker_cancel_performed: false,
  production_ledger_mutated: false,
  authority_changed: false,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel(
  previewResponse: ControlledBrokerRecoveryPreview = recoveryPreview,
) {
  const requests: RecordedRequest[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : null;
      requests.push({ url, method, body });
      if (url.endsWith('/operator-approvals/status')) {
        return jsonResponse(approvalStatus);
      }
      if (url.endsWith(`/intents/${submitIntentId}/recovery/preview`)) {
        return jsonResponse(previewResponse);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi1leGFjdC1yZWNvdmVyeQ==',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'query_unknown_controlled_broker_submission',
          artifact_type: 'controlled_broker_submission_recovery',
          artifact_fingerprint: recoveryFingerprint,
          issued_at: '2026-07-16T08:00:00+00:00',
          expires_at: '2026-07-16T08:03:00+00:00',
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
          action: 'query_unknown_controlled_broker_submission',
          artifact_type: 'controlled_broker_submission_recovery',
          artifact_fingerprint: recoveryFingerprint,
          expires_at: '2026-07-16T08:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (url.endsWith(`/intents/${submitIntentId}/recoveries`)) {
        return jsonResponse({
          submit_intent_id: submitIntentId,
          recovery_fingerprint: recoveryFingerprint,
          recovery_operator_approval_id: challengeId,
          recovery_claim_id: '7'.repeat(64),
          status: 'submitted',
          broker_order_id: 'BROKER-RECOVERED-1',
          broker_status: 'accepted',
          recovery_query_performed: true,
          external_call_performed: true,
          recovery_resubmission_enabled: false,
          production_ledger_mutated: false,
        });
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
      <ControlledBrokerRecoveryOperatorPanel journey={journey} locale="en" />
    </QueryClientProvider>,
  );
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('completes signed query-only recovery without submit, cancel, or ledger calls', async () => {
  const requests = renderPanel();

  expect(screen.getByText('Sign and query unknown order outcome')).toBeTruthy();
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByText('Sign and query unknown order outcome'));
  expect(
    screen.getByText(/definitive evidence may only resolve the existing OMS/),
  ).toBeTruthy();
  await waitFor(() =>
    expect(
      requests.some((request) =>
        request.url.endsWith('/operator-approvals/status'),
      ),
    ).toBe(true),
  );
  fireEvent.click(screen.getByText('Generate query evidence preview'));
  expect(await screen.findByText('Bound evidence')).toBeTruthy();
  expect(screen.getByText('No resubmit')).toBeTruthy();
  expect(screen.getByText('No cancel')).toBeTruthy();
  expect(screen.getByText('No ledger write')).toBeTruthy();

  fireEvent.click(screen.getByText('Create 3-minute signing challenge'));
  fireEvent.change(await screen.findByLabelText('Detached signature Base64'), {
    target: { value: signature },
  });
  fireEvent.click(screen.getByText('Verify signature'));
  expect(await screen.findByText('Final query confirmation')).toBeTruthy();
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I confirm one query for the preview-bound client order id only; no resubmit, cancel, ledger write, or authority change is allowed.',
    }),
  );
  fireEvent.click(screen.getByText('Run one exact read-only query'));
  expect(
    await screen.findByText(
      'Read-only query audited: Submitted; no resubmit, cancel, or ledger write occurred.',
    ),
  ).toBeTruthy();

  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    `/api/automation/controlled-broker-submission/intents/${submitIntentId}/recovery/preview`,
    '/api/automation/capital-authority/operator-approvals/challenges',
    '/api/automation/capital-authority/operator-approvals/verifications',
    `/api/automation/controlled-broker-submission/intents/${submitIntentId}/recoveries`,
  ]);
  expect(postRequests[1].body).toEqual({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'query_unknown_controlled_broker_submission',
    artifact_type: 'controlled_broker_submission_recovery',
    artifact_fingerprint: recoveryFingerprint,
    ttl_seconds: 180,
  });
  expect(postRequests[3].body).toEqual({
    recovery_fingerprint: recoveryFingerprint,
    operator_approval_id: challengeId,
    operator_proof_signature_base64: signature,
    acknowledgement: 'query_exact_unknown_submission_once_without_resubmit',
  });
  expect(requests.some((request) => request.url.endsWith('/submissions'))).toBe(
    false,
  );
  expect(requests.some((request) => request.url.includes('/cancel'))).toBe(
    false,
  );
  expect(requests.some((request) => request.url.includes('/ledger'))).toBe(
    false,
  );
  expect(JSON.stringify(requests)).not.toContain('private_key');
});

test('shows persisted blockers and never creates a challenge', async () => {
  const requests = renderPanel({
    ...recoveryPreview,
    review_status: 'blocked',
    review_ready: false,
    blockers: ['controlled_broker_recovery_query_wait_required'],
    recovery_wait_remaining_seconds: 17,
  });

  fireEvent.click(screen.getByText('Sign and query unknown order outcome'));
  fireEvent.click(screen.getByText('Generate query evidence preview'));
  expect((await screen.findByRole('alert')).textContent).toContain('17s');
  expect(screen.queryByText('Create 3-minute signing challenge')).toBeNull();
  expect(
    requests.some((request) =>
      request.url.endsWith('/operator-approvals/challenges'),
    ),
  ).toBe(false);
});

test('stays absent when canonical journey has no recovery action', () => {
  vi.stubGlobal('fetch', vi.fn());
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <ControlledBrokerRecoveryOperatorPanel
        journey={{
          ...journey,
          next_operator_action: 'run_or_review_execution_reconciliation',
        }}
        locale="en"
      />
    </QueryClientProvider>,
  );

  expect(screen.queryByText('Sign and query unknown order outcome')).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
