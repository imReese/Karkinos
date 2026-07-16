import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledLedgerCorrectionPreview,
  ControlledOrderJourney,
  OperatorApprovalStatus,
} from './api';
import { ControlledLedgerCorrectionOperatorPanel } from './controlled-ledger-correction-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const postingId = '3'.repeat(64);
const correctionFingerprint = '4'.repeat(64);
const challengeId = '5'.repeat(64);
const signature = 'S'.repeat(88);

const journey: ControlledOrderJourney = {
  submit_intent_id: '1'.repeat(64),
  order_id: 'OMS-FIXTURE-CORRECTION-1',
  broker_order_id: 'BROKER-FIXTURE-CORRECTION-1',
  client_order_id: 'CLIENT-FIXTURE-CORRECTION-1',
  gateway_id: 'fixture-write-edge',
  status: 'ledger_posted_account_truth_review_required',
  next_operator_action: 'review_account_truth_after_ledger_posting',
  attention_required: true,
  attention_severity: 'warning',
  blocks_new_submissions: false,
  prepared_at: '2026-07-16T07:45:00+00:00',
  updated_at: '2026-07-16T07:45:02+00:00',
  last_recovery_at: '',
  stages: [
    {
      key: 'controlled_submission',
      status: 'submitted',
      evidence_id: '1'.repeat(64),
      complete: true,
      required: true,
    },
    {
      key: 'execution_reconciliation',
      status: 'matched',
      evidence_id: 'recon-fixture-correction-1',
      complete: true,
      required: true,
    },
    {
      key: 'terminal_reconciliation_clearance',
      status: 'cleared',
      evidence_id: '2'.repeat(64),
      complete: true,
      required: true,
    },
    {
      key: 'reconciled_ledger_posting',
      status: 'applied',
      evidence_id: postingId,
      complete: true,
      required: true,
      ledger_entry_count: 2,
      post_ledger_cutoff_id: 42,
    },
    {
      key: 'append_only_ledger_correction',
      status: 'not_required',
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

const positionBefore = {
  quantity: '100',
  available_qty: '100',
  frozen_qty: '0',
  avg_cost: '10.02',
  realized_pnl: '0',
  commission_paid: '2',
  broker_displayed_cost_basis: '1002',
  broker_displayed_unit_cost: '10.02',
  broker_cost_basis_difference: '0',
  broker_cost_basis_method: 'broker_statement',
  broker_cost_basis_status: 'confirmed',
};

const positionAfter = {
  ...positionBefore,
  quantity: '0',
  available_qty: '0',
  avg_cost: '0',
  commission_paid: '0',
  broker_displayed_cost_basis: '0',
  broker_displayed_unit_cost: '0',
};

const correctionPreview: ControlledLedgerCorrectionPreview = {
  schema_version: 'karkinos.controlled_submission_ledger_correction.v1',
  action: 'reverse_controlled_submission_ledger_posting',
  posting_id: postingId,
  posting_fingerprint: '6'.repeat(64),
  original_ledger_entry_ids: [41, 42],
  original_ledger_entry_fingerprint: '7'.repeat(64),
  reason_code: 'operator_confirmed_mapping_error',
  operator_id: 'local-owner',
  account_truth_import_run_id: 'account-truth-fixture-1',
  pre_valuation_snapshot_id: 'valuation-fixture-1',
  pre_valuation_as_of: '2026-07-16T08:00:00+00:00',
  pre_valuation_status: 'complete',
  pre_ledger_cutoff_id: 42,
  pre_ledger_fingerprint: '8'.repeat(64),
  plan_fingerprint: '9'.repeat(64),
  correction_plan: {
    schema_version: 'karkinos.controlled_submission_ledger_correction_plan.v1',
    posting_id: postingId,
    original_ledger_entry_ids: [41, 42],
    effective_at: '2026-07-16T08:01:01+00:00',
    symbol: '600519',
    asset_class: 'stock',
    cash_delta: '1002',
    total_deposits_delta: '0',
    position_before: positionBefore,
    position_after: positionAfter,
    derivation: 'canonical_replay_excluding_exact_original_posting_entries',
    arbitrary_financial_input_used: false,
  },
  correction_id: 'a'.repeat(64),
  correction_fingerprint: correctionFingerprint,
  generated_at: '2026-07-16T08:01:00+00:00',
  review_status: 'ready_for_final_signature',
  review_ready: true,
  blockers: [],
  required_operator_approval: {
    action: 'reverse_controlled_submission_ledger_posting',
    artifact_type: 'controlled_submission_ledger_correction',
    artifact_fingerprint: correctionFingerprint,
  },
  production_ledger_mutated: false,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel({
  currentJourney = journey,
  previewResponse = correctionPreview,
  statusResponse = approvalStatus,
}: {
  currentJourney?: ControlledOrderJourney;
  previewResponse?: ControlledLedgerCorrectionPreview;
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
      if (url.endsWith(`/postings/${postingId}/preview`)) {
        return jsonResponse(previewResponse);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlzLWV4YWN0LXBheWxvYWQ=',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'reverse_controlled_submission_ledger_posting',
          artifact_type: 'controlled_submission_ledger_correction',
          artifact_fingerprint: correctionFingerprint,
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
          action: 'reverse_controlled_submission_ledger_posting',
          artifact_type: 'controlled_submission_ledger_correction',
          artifact_fingerprint: correctionFingerprint,
          expires_at: '2026-07-16T08:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (url.endsWith(`/postings/${postingId}/corrections`)) {
        return jsonResponse({
          correction_id: 'a'.repeat(64),
          correction_fingerprint: correctionFingerprint,
          posting_id: postingId,
          status: 'applied',
          reason_code: 'operator_confirmed_mapping_error',
          original_ledger_entry_ids: [41, 42],
          correction_ledger_entry_id: 43,
          pre_ledger_cutoff_id: 42,
          post_ledger_cutoff_id: 43,
          applied_at: '2026-07-16T08:02:00+00:00',
          post_apply_status: 'account_truth_recheck_required',
          persisted: true,
          reused: false,
          production_ledger_mutated: true,
          original_ledger_entries_deleted: false,
          automatic_correction_enabled: false,
          broker_submission_enabled: false,
          broker_cancel_enabled: false,
          capital_authority_changed: false,
        });
      }
      return jsonResponse(
        { detail: `unexpected request: ${url}` },
        { status: 500 },
      );
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ControlledLedgerCorrectionOperatorPanel
        journey={currentJourney}
        locale="en"
      />
    </QueryClientProvider>,
  );
  return { requests, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('stays absent until an applied posting exists and disappears after correction', () => {
  const incomplete = {
    ...journey,
    stages: journey.stages.map((stage) =>
      stage.key === 'reconciled_ledger_posting'
        ? { ...stage, evidence_id: '', complete: false }
        : stage,
    ),
  };
  const { fetchMock } = renderPanel({ currentJourney: incomplete });
  expect(
    screen.queryByText('Posting error? Review append-only correction'),
  ).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();

  const corrected = {
    ...journey,
    stages: journey.stages.map((stage) =>
      stage.key === 'append_only_ledger_correction'
        ? { ...stage, evidence_id: 'a'.repeat(64), complete: true }
        : stage,
    ),
  };
  renderPanel({ currentJourney: corrected });
  expect(
    screen.queryByText('Posting error? Review append-only correction'),
  ).toBeNull();

  const zeroFillPosting = {
    ...journey,
    stages: journey.stages.map((stage) =>
      stage.key === 'reconciled_ledger_posting'
        ? { ...stage, ledger_entry_count: 0 }
        : stage,
    ),
  };
  renderPanel({ currentJourney: zeroFillPosting });
  expect(
    screen.queryByText('Posting error? Review append-only correction'),
  ).toBeNull();
});

test('previews canonical replay, verifies offline proof, and appends one correction', async () => {
  const { requests } = renderPanel();

  fireEvent.click(
    screen.getByText('Posting error? Review append-only correction'),
  );
  expect(
    await screen.findByText('Posted facts → compensating event'),
  ).toBeTruthy();
  await waitFor(() =>
    expect(
      requests.some((request) =>
        request.url.endsWith('/operator-approvals/status'),
      ),
    ).toBe(true),
  );
  fireEvent.change(screen.getByLabelText('Confirmed error type'), {
    target: { value: 'operator_confirmed_mapping_error' },
  });
  fireEvent.click(
    screen.getByText('Generate canonical replay correction preview'),
  );

  expect(
    await screen.findByText('Deterministic compensation preview'),
  ).toBeTruthy();
  expect(screen.getByText('Original entries: 41, 42')).toBeTruthy();
  expect(screen.getByText('Cash compensation: 1002')).toBeTruthy();
  expect(screen.getByText('Quantity: 100 → 0')).toBeTruthy();
  expect(screen.getByText('Deposit delta: 0')).toBeTruthy();

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
  expect(await screen.findByText('Final correction confirmation')).toBeTruthy();

  const applyButton = screen.getByText('Append exact compensating event');
  expect(applyButton.hasAttribute('disabled')).toBe(true);
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I confirm appending only the exact previewed compensation once; the original ledger history must remain.',
    }),
  );
  fireEvent.click(applyButton);
  expect(
    await screen.findByText(
      'Correction appended at ledger cutoff #43; Account Truth must now be re-imported and reviewed.',
    ),
  ).toBeTruthy();

  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    `/api/automation/controlled-ledger-corrections/postings/${postingId}/preview`,
    '/api/automation/capital-authority/operator-approvals/challenges',
    '/api/automation/capital-authority/operator-approvals/verifications',
    `/api/automation/controlled-ledger-corrections/postings/${postingId}/corrections`,
  ]);
  expect(postRequests[0].body).toEqual({
    reason_code: 'operator_confirmed_mapping_error',
    operator_id: 'local-owner',
  });
  expect(postRequests[1].body).toEqual({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'reverse_controlled_submission_ledger_posting',
    artifact_type: 'controlled_submission_ledger_correction',
    artifact_fingerprint: correctionFingerprint,
    ttl_seconds: 180,
  });
  expect(postRequests[3].body).toEqual({
    reason_code: 'operator_confirmed_mapping_error',
    operator_id: 'local-owner',
    correction_fingerprint: correctionFingerprint,
    operator_approval_id: challengeId,
    operator_proof_signature_base64: signature,
    acknowledgement: 'apply_exact_compensating_ledger_correction_once',
  });
  expect(JSON.stringify(requests)).not.toContain('private_key');
  expect(
    requests.some((request) => request.url.includes('broker-gateway')),
  ).toBe(false);
  expect(requests.some((request) => request.url.includes('/submissions'))).toBe(
    false,
  );
  expect(requests.some((request) => request.url.includes('/cancel'))).toBe(
    false,
  );
});

test('shows canonical blockers and never creates a signing challenge', async () => {
  const { requests } = renderPanel({
    previewResponse: {
      ...correctionPreview,
      review_status: 'blocked',
      review_ready: false,
      blockers: ['controlled_ledger_correction_account_truth_stale'],
    },
  });

  fireEvent.click(
    screen.getByText('Posting error? Review append-only correction'),
  );
  fireEvent.change(await screen.findByLabelText('Confirmed error type'), {
    target: { value: 'operator_confirmed_mapping_error' },
  });
  fireEvent.click(
    screen.getByText('Generate canonical replay correction preview'),
  );
  expect((await screen.findByRole('alert')).textContent).toContain('Blockers');
  expect(screen.queryByText('Create 3-minute signing challenge')).toBeNull();
  expect(
    requests.some((request) =>
      request.url.endsWith('/operator-approvals/challenges'),
    ),
  ).toBe(false);
});

test('keeps preview disabled when no trusted public key is configured', async () => {
  renderPanel({
    statusResponse: {
      ...approvalStatus,
      trusted_identity_count: 0,
      enabled_identity_count: 0,
      trusted_identities: [],
    },
  });

  fireEvent.click(
    screen.getByText('Posting error? Review append-only correction'),
  );
  expect(
    await screen.findByText(
      'No enabled Ed25519 public key is configured; correction preview and apply remain disabled.',
    ),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Confirmed error type'), {
    target: { value: 'operator_confirmed_mapping_error' },
  });
  expect(
    screen
      .getByText('Generate canonical replay correction preview')
      .hasAttribute('disabled'),
  ).toBe(true);
});
