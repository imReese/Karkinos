import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledLedgerPostingPreview,
  ControlledOrderJourney,
  OperatorApprovalStatus,
} from './api';
import { ControlledLedgerPostingOperatorPanel } from './controlled-ledger-posting-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const clearanceId = '2'.repeat(64);
const postingFingerprint = '3'.repeat(64);
const challengeId = '4'.repeat(64);
const signature = 'S'.repeat(88);

const journey: ControlledOrderJourney = {
  submit_intent_id: '1'.repeat(64),
  order_id: 'OMS-FIXTURE-POST-1',
  broker_order_id: 'BROKER-FIXTURE-POST-1',
  client_order_id: 'CLIENT-FIXTURE-POST-1',
  gateway_id: 'fixture-write-edge',
  status: 'terminal_cleared_posting_review_required',
  next_operator_action: 'preview_reconciled_ledger_posting',
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
      evidence_id: 'recon-fixture-post-1',
      complete: true,
      required: true,
    },
    {
      key: 'terminal_reconciliation_clearance',
      status: 'cleared',
      evidence_id: clearanceId,
      complete: true,
      required: true,
      terminal_status: 'filled',
      fill_count: 1,
      fill_quantity: '100',
      cancelled_quantity: '0',
    },
    {
      key: 'reconciled_ledger_posting',
      status: 'not_applied',
      evidence_id: '',
      complete: false,
      required: true,
      ledger_entry_count: 0,
      post_ledger_cutoff_id: 0,
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

const postingPreview: ControlledLedgerPostingPreview = {
  schema_version: 'karkinos.controlled_submission_ledger_posting.v1',
  posting_id: '5'.repeat(64),
  posting_fingerprint: postingFingerprint,
  clearance_id: clearanceId,
  submit_intent_id: journey.submit_intent_id,
  order_id: journey.order_id,
  broker_order_id: journey.broker_order_id,
  terminal_status: 'filled',
  operator_id: 'local-owner',
  ledger_entry_count: 1,
  ledger_entries: [
    {
      fill_id: 'fill-fixture-1',
      broker_event_id: 'broker-event-fixture-1',
      entry_type: 'trade_buy',
      timestamp: '2026-07-16T07:46:00+00:00',
      settled_at: '2026-07-16T07:46:00+00:00',
      symbol: '510300.SH',
      direction: 'buy',
      quantity: '100',
      price: '4.1000',
      amount: '410.00',
      commission: '5.00',
      gross_amount: '410.00',
      net_cash_impact: '-415.00',
      fee_breakdown: {
        commission: '5.00',
        stamp_tax: '0',
        transfer_fee: '0',
        other_fees: '0',
        total_fee: '5.00',
        confirmation_source: 'broker_statement',
      },
      asset_class: 'fund',
      source: 'controlled_submission_ledger_posting',
      source_ref: 'fill-fixture-1',
      settlement_status: 'confirmed',
      settlement_source: 'broker_statement',
      account_truth_import_run_id: 'account-truth-fixture-1',
    },
  ],
  pre_valuation_snapshot_id: 'valuation-fixture-1',
  pre_ledger_cutoff_id: 41,
  account_truth_import_run_id: 'account-truth-fixture-1',
  review_status: 'ready_for_final_signature',
  review_ready: true,
  blockers: [],
  required_operator_approval: {
    action: 'post_controlled_submission_ledger',
    artifact_type: 'controlled_submission_ledger_posting',
    artifact_fingerprint: postingFingerprint,
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
  previewResponse = postingPreview,
  statusResponse = approvalStatus,
}: {
  currentJourney?: ControlledOrderJourney;
  previewResponse?: typeof postingPreview;
  statusResponse?: typeof approvalStatus;
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
      if (url.endsWith(`/clearances/${clearanceId}/preview`)) {
        return jsonResponse(previewResponse);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlzLWV4YWN0LXBheWxvYWQ=',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'post_controlled_submission_ledger',
          artifact_type: 'controlled_submission_ledger_posting',
          artifact_fingerprint: postingFingerprint,
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
          action: 'post_controlled_submission_ledger',
          artifact_type: 'controlled_submission_ledger_posting',
          artifact_fingerprint: postingFingerprint,
          expires_at: '2026-07-16T08:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (url.endsWith(`/clearances/${clearanceId}/postings`)) {
        return jsonResponse({
          posting_id: '5'.repeat(64),
          posting_fingerprint: postingFingerprint,
          clearance_id: clearanceId,
          order_id: journey.order_id,
          status: 'applied',
          ledger_entry_count: 1,
          ledger_entry_ids: [42],
          pre_ledger_cutoff_id: 41,
          post_ledger_cutoff_id: 42,
          applied_at: '2026-07-16T08:01:00+00:00',
          persisted: true,
          reused: false,
          production_ledger_mutated: true,
          automatic_posting_enabled: false,
          broker_submission_enabled: false,
          broker_cancel_enabled: false,
          capital_authority_changed: false,
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
      <ControlledLedgerPostingOperatorPanel
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

test('stays idle unless the canonical journey requires a ledger-posting review', () => {
  const currentJourney = {
    ...journey,
    next_operator_action: 'review_account_truth_after_ledger_posting',
  };
  const { fetchMock } = renderPanel({ currentJourney });

  expect(screen.queryByText('Review signed ledger posting')).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
});

test('completes preview, offline proof verification, and exactly-once apply without broker calls', async () => {
  const { requests } = renderPanel();

  expect(screen.getByText('Review signed ledger posting')).toBeTruthy();
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByText('Review signed ledger posting'));
  await screen.findByText('Terminal fills → production ledger');
  await waitFor(() =>
    expect(
      requests.some((request) =>
        request.url.endsWith('/operator-approvals/status'),
      ),
    ).toBe(true),
  );

  fireEvent.click(screen.getByText('Generate read-only posting preview'));
  expect(await screen.findByText('Deterministic delta preview')).toBeTruthy();
  expect(screen.getByText('Ledger events: 1')).toBeTruthy();
  expect(screen.getByText('ledger cutoff #41')).toBeTruthy();
  expect(screen.getByText('510300.SH · Buy')).toBeTruthy();
  expect(screen.getByText('Quantity 100')).toBeTruthy();
  expect(screen.getByText('Price 4.1000')).toBeTruthy();
  expect(screen.getByText('Gross 410.00')).toBeTruthy();
  expect(screen.getByText('Total fees 5.00')).toBeTruthy();
  expect(screen.getByText('Net cash impact -415.00')).toBeTruthy();

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
  expect(await screen.findByText('Final apply confirmation')).toBeTruthy();

  const applyButton = screen.getByText('Apply exact reconciled posting');
  expect(applyButton.hasAttribute('disabled')).toBe(true);
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I confirm applying only the 1 previewed reconciled ledger event(s), once.',
    }),
  );
  expect(applyButton.hasAttribute('disabled')).toBe(false);
  fireEvent.click(applyButton);
  expect(
    await screen.findByText(
      'Posting recorded at ledger cutoff #42; review Account Truth next.',
    ),
  ).toBeTruthy();

  const postRequests = requests.filter((request) => request.method === 'POST');
  expect(postRequests.map((request) => request.url)).toEqual([
    `/api/automation/controlled-ledger-posting/clearances/${clearanceId}/preview`,
    '/api/automation/capital-authority/operator-approvals/challenges',
    '/api/automation/capital-authority/operator-approvals/verifications',
    `/api/automation/controlled-ledger-posting/clearances/${clearanceId}/postings`,
  ]);
  expect(postRequests[1].body).toEqual({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'post_controlled_submission_ledger',
    artifact_type: 'controlled_submission_ledger_posting',
    artifact_fingerprint: postingFingerprint,
    ttl_seconds: 180,
  });
  expect(postRequests[2].body).toEqual({
    challenge_id: challengeId,
    signature_base64: signature,
  });
  expect(postRequests[3].body).toEqual({
    posting_fingerprint: postingFingerprint,
    operator_approval_id: challengeId,
    operator_proof_signature_base64: signature,
    acknowledgement: 'apply_exact_reconciled_ledger_posting_once',
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

test('shows canonical preview blockers and never creates an approval challenge', async () => {
  const { requests } = renderPanel({
    previewResponse: {
      ...postingPreview,
      review_status: 'blocked',
      review_ready: false,
      blockers: ['controlled_ledger_posting_account_truth_stale'],
    },
  });

  fireEvent.click(screen.getByText('Review signed ledger posting'));
  fireEvent.click(screen.getByText('Generate read-only posting preview'));
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

test('keeps apply disabled when no matching trusted public key is configured', async () => {
  renderPanel({
    statusResponse: {
      ...approvalStatus,
      trusted_identity_count: 0,
      enabled_identity_count: 0,
      trusted_identities: [],
    },
  });

  fireEvent.click(screen.getByText('Review signed ledger posting'));
  fireEvent.click(screen.getByText('Generate read-only posting preview'));
  expect(
    await screen.findByText(
      'No enabled Ed25519 public key matches the clearance operator; posting remains disabled.',
    ),
  ).toBeTruthy();
  expect(
    screen
      .getByText('Create 3-minute signing challenge')
      .hasAttribute('disabled'),
  ).toBe(true);
});
