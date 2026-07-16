import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledOrderJourney,
  ControlledSubmissionClearancePreview,
  OperatorApprovalStatus,
} from './api';
import { ControlledTerminalClearanceOperatorPanel } from './controlled-terminal-clearance-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const submitIntentId = '1'.repeat(64);
const reconciliationRunId = 'execution-reconciliation:2026-07-16';
const clearanceFingerprint = '2'.repeat(64);
const clearanceId = '3'.repeat(64);
const challengeId = '4'.repeat(64);
const signature = 'S'.repeat(88);

const journey: ControlledOrderJourney = {
  submit_intent_id: submitIntentId,
  order_id: 'OMS-FIXTURE-CLEAR-1',
  broker_order_id: 'BROKER-FIXTURE-CLEAR-1',
  client_order_id: 'CLIENT-FIXTURE-CLEAR-1',
  gateway_id: 'fixture-write-edge',
  status: 'terminal_clearance_review_required',
  next_operator_action: 'preview_terminal_clearance',
  attention_required: true,
  attention_severity: 'warning',
  blocks_new_submissions: true,
  prepared_at: '2026-07-16T07:45:00+00:00',
  updated_at: '2026-07-16T07:45:02+00:00',
  last_recovery_at: '',
  stages: [
    {
      key: 'controlled_submission',
      status: 'submitted',
      evidence_id: submitIntentId,
      complete: true,
      required: true,
    },
    {
      key: 'execution_reconciliation',
      status: 'controlled_submission_broker_evidence_available',
      evidence_id: reconciliationRunId,
      complete: true,
      required: true,
    },
    {
      key: 'terminal_reconciliation_clearance',
      status: 'not_cleared',
      evidence_id: '',
      complete: false,
      required: true,
    },
    {
      key: 'reconciled_ledger_posting',
      status: 'not_applied',
      evidence_id: '',
      complete: false,
      required: false,
    },
    {
      key: 'append_only_ledger_correction',
      status: 'not_applicable',
      evidence_id: '',
      complete: false,
      required: false,
    },
  ],
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

const clearancePreview: ControlledSubmissionClearancePreview = {
  schema_version: 'karkinos.controlled_submission_reconciliation_clearance.v3',
  clearance_id: clearanceId,
  clearance_fingerprint: clearanceFingerprint,
  submit_intent_id: submitIntentId,
  order_id: journey.order_id,
  broker_order_id: journey.broker_order_id,
  client_order_id: journey.client_order_id,
  review_reconciliation_run_id: reconciliationRunId,
  broker_evidence_fingerprint: '5'.repeat(64),
  account_truth_import_run_id: 'account-truth-fixture-1',
  terminal_status: 'filled',
  terminal_evidence_source: 'broker_order_lifecycle_and_account_truth',
  lifecycle_observation_id: 'lifecycle-fixture-1',
  lifecycle_evidence_fingerprint: '6'.repeat(64),
  operator_id: 'local-owner',
  fill_count: 1,
  fill_quantity: '100',
  cancelled_quantity: '0',
  fills: [
    {
      fill_id: '7'.repeat(64),
      broker_event_id: 'broker-event-fixture-1',
      account_truth_import_run_id: 'account-truth-fixture-1',
      timestamp: '2026-07-16T07:46:00+00:00',
      symbol: '510300.SH',
      side: 'buy',
      asset_class: 'fund',
      fill_price: '4.1000',
      fill_quantity: '100',
      fee: '5.00',
      tax: '0',
      transfer_fee: '0',
      provider_name: 'broker_statement',
    },
  ],
  review_status: 'ready_for_final_signature',
  review_ready: true,
  blockers: [],
  required_operator_approval: {
    action: 'clear_controlled_submission_reconciliation',
    artifact_type: 'controlled_submission_reconciliation_clearance',
    artifact_fingerprint: clearanceFingerprint,
  },
  interlock_released: false,
  oms_mutated: false,
  production_ledger_mutated: false,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel({
  currentJourney = journey,
  previewResponse = clearancePreview,
  statusResponse = approvalStatus,
}: {
  currentJourney?: ControlledOrderJourney;
  previewResponse?: ControlledSubmissionClearancePreview;
  statusResponse?: OperatorApprovalStatus;
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
      if (url.endsWith('/operator-approvals/status')) {
        return jsonResponse(statusResponse);
      }
      if (
        url.endsWith(
          `/intents/${submitIntentId}/reconciliation-clearance/preview`,
        )
      ) {
        return jsonResponse(previewResponse);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlzLWV4YWN0LXBheWxvYWQ=',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'clear_controlled_submission_reconciliation',
          artifact_type: 'controlled_submission_reconciliation_clearance',
          artifact_fingerprint: clearanceFingerprint,
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
          action: 'clear_controlled_submission_reconciliation',
          artifact_type: 'controlled_submission_reconciliation_clearance',
          artifact_fingerprint: clearanceFingerprint,
          expires_at: '2026-07-16T08:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (
        url.endsWith(`/intents/${submitIntentId}/reconciliation-clearances`)
      ) {
        return jsonResponse({
          clearance_id: clearanceId,
          clearance_fingerprint: clearanceFingerprint,
          submit_intent_id: submitIntentId,
          order_id: journey.order_id,
          status: 'cleared',
          terminal_status: 'filled',
          fill_count: 1,
          fill_quantity: '100',
          cancelled_quantity: '0',
          cleared_at: '2026-07-16T08:01:00+00:00',
          persisted: true,
          reused: false,
          interlock_released: true,
          oms_terminal_status: 'filled',
          real_fills_recorded: true,
          terminal_outcome_recorded: true,
          production_ledger_mutated: false,
          automatic_submission_enabled: false,
          strategy_direct_submission_enabled: false,
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
      <ControlledTerminalClearanceOperatorPanel
        journey={currentJourney}
        locale="en"
      />
    </QueryClientProvider>,
  );
  return { fetchMock, requests };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('stays idle unless the canonical journey requires terminal clearance', () => {
  const currentJourney = {
    ...journey,
    next_operator_action: 'query_submission_outcome_without_resubmit',
  };
  const { fetchMock } = renderPanel({ currentJourney });

  expect(screen.queryByText('Review signed terminal clearance')).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});

test('completes preview, offline proof, and exactly-once clearance without broker or ledger calls', async () => {
  const { requests } = renderPanel();

  expect(screen.getByText('Review signed terminal clearance')).toBeTruthy();
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByText('Review signed terminal clearance'));
  await screen.findByText('Reconciled evidence → exact terminal clearance');
  await waitFor(() =>
    expect(
      requests.some((request) =>
        request.url.endsWith('/operator-approvals/status'),
      ),
    ).toBe(true),
  );

  fireEvent.click(screen.getByText('Generate read-only terminal preview'));
  expect(
    await screen.findByText('Deterministic terminal evidence'),
  ).toBeTruthy();
  expect(screen.getByText('Filled quantity: 100')).toBeTruthy();
  expect(screen.getByText('Cancelled quantity: 0')).toBeTruthy();
  expect(screen.getByText('Fills: 1')).toBeTruthy();
  expect(screen.getByText('510300.SH · Buy')).toBeTruthy();
  expect(screen.getByText('Quantity 100')).toBeTruthy();
  expect(screen.getByText('Price 4.1000')).toBeTruthy();
  expect(screen.getByText('Fee 5.00')).toBeTruthy();

  fireEvent.click(screen.getByText('Create 3-minute signing challenge'));
  expect(
    (
      (await screen.findByLabelText(
        'Payload to sign Base64',
      )) as HTMLTextAreaElement
    ).value,
  ).toBe('c2lnbi10aGlzLWV4YWN0LXBheWxvYWQ=');
  fireEvent.change(screen.getByLabelText('Detached signature Base64'), {
    target: { value: signature },
  });
  fireEvent.click(screen.getByText('Verify signature'));
  expect(await screen.findByText('Final clearance confirmation')).toBeTruthy();

  const applyButton = screen.getByText('Record exact terminal outcome once');
  expect(applyButton.hasAttribute('disabled')).toBe(true);
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I confirm recording only the 1 previewed actual fill(s) and exact terminal outcome, then releasing this order interlock; this step does not post the production ledger.',
    }),
  );
  expect(applyButton.hasAttribute('disabled')).toBe(false);
  fireEvent.click(applyButton);
  expect(
    await screen.findByText(
      'Terminal Filled recorded; review signed ledger posting next.',
    ),
  ).toBeTruthy();

  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    `/api/automation/controlled-broker-submission/intents/${submitIntentId}/reconciliation-clearance/preview`,
    '/api/automation/capital-authority/operator-approvals/challenges',
    '/api/automation/capital-authority/operator-approvals/verifications',
    `/api/automation/controlled-broker-submission/intents/${submitIntentId}/reconciliation-clearances`,
  ]);
  expect(postRequests[0].body).toEqual({
    reconciliation_run_id: reconciliationRunId,
  });
  expect(postRequests[1].body).toEqual({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'clear_controlled_submission_reconciliation',
    artifact_type: 'controlled_submission_reconciliation_clearance',
    artifact_fingerprint: clearanceFingerprint,
    ttl_seconds: 180,
  });
  expect(postRequests[2].body).toEqual({
    challenge_id: challengeId,
    signature_base64: signature,
  });
  expect(postRequests[3].body).toEqual({
    reconciliation_run_id: reconciliationRunId,
    clearance_fingerprint: clearanceFingerprint,
    operator_approval_id: challengeId,
    operator_proof_signature_base64: signature,
    acknowledgement:
      'clear_exact_terminal_outcome_without_automatic_ledger_mutation',
  });
  expect(JSON.stringify(requests)).not.toContain('private_key');
  expect(
    requests.some((request) => request.url.includes('/broker-gateway/')),
  ).toBe(false);
  expect(requests.some((request) => request.url.endsWith('/submissions'))).toBe(
    false,
  );
  expect(requests.some((request) => request.url.includes('/cancel'))).toBe(
    false,
  );
  expect(
    requests.some((request) =>
      request.url.includes('/controlled-ledger-posting/'),
    ),
  ).toBe(false);
});

test('shows canonical blockers and never creates a signature challenge', async () => {
  const { requests } = renderPanel({
    previewResponse: {
      ...clearancePreview,
      review_status: 'blocked',
      review_ready: false,
      blockers: ['controlled_submission_clearance_account_truth_stale'],
    },
  });

  fireEvent.click(screen.getByText('Review signed terminal clearance'));
  fireEvent.click(screen.getByText('Generate read-only terminal preview'));
  expect((await screen.findByRole('alert')).textContent).toContain(
    'Blockers: Review item',
  );
  expect(screen.queryByText('Create 3-minute signing challenge')).toBeNull();
  expect(
    requests.some((request) =>
      request.url.endsWith('/operator-approvals/challenges'),
    ),
  ).toBe(false);
});

test('keeps clearance disabled without a matching trusted public key', async () => {
  renderPanel({
    statusResponse: {
      ...approvalStatus,
      trusted_identity_count: 0,
      enabled_identity_count: 0,
      trusted_identities: [],
    },
  });

  fireEvent.click(screen.getByText('Review signed terminal clearance'));
  fireEvent.click(screen.getByText('Generate read-only terminal preview'));
  expect(
    await screen.findByText(
      'No enabled Ed25519 public key matches the order operator; clearance remains disabled.',
    ),
  ).toBeTruthy();
  expect(
    screen
      .getByText('Create 3-minute signing challenge')
      .hasAttribute('disabled'),
  ).toBe(true);
});
