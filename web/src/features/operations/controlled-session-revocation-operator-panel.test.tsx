import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  ControlledExecutionOperatorSession,
  ControlledSessionRevocationPreview,
  ControlledSessionRevocationResult,
  OperatorApprovalStatus,
} from './api';
import { ControlledSessionRevocationOperatorPanel } from './controlled-session-revocation-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const sessionId = '1'.repeat(64);
const revocationFingerprint = '2'.repeat(64);
const revocationId = '3'.repeat(64);
const challengeId = '4'.repeat(64);
const approvalId = '5'.repeat(64);
const signature = 'S'.repeat(88);

const session: ControlledExecutionOperatorSession = {
  session_id: sessionId,
  reservation_id: '6'.repeat(64),
  authorization_id: 'authorization-fixture-1',
  account_alias: 'fixture-account',
  strategy_id: 'dual_ma',
  status: 'paused',
  persisted_status: 'enabled',
  is_current_window: true,
  effective_at: '2026-07-18T01:00:00+00:00',
  expires_at: '2026-07-18T03:00:00+00:00',
  authorized_capital: '100000',
  effective_capital_at_risk: '25000',
  remaining_budget: {
    capital_headroom: '75000',
    cash_headroom: '50000',
    turnover_headroom: '120000',
    remaining_order_slots: 2,
    reserved_order_count: 3,
    admitted_order_count: 1,
  },
  allowed_symbols: ['510300.SH'],
  last_order: {
    order_id: 'OMS-FIXTURE-1',
    admitted_at: '2026-07-18T01:30:00+00:00',
    admission_id: 'admission-fixture-1',
    submission_status: 'accepted',
    submit_intent_id: 'submit-fixture-1',
  },
  last_reconciliation: {
    run_id: 'reconciliation-fixture-1',
    run_status: 'clear',
    item_status: 'matched',
    suggested_action: 'no_action',
    updated_at: '2026-07-18T01:40:00+00:00',
  },
  latest_gate_snapshot: {
    snapshot_id: 'gate-fixture-1',
    status: 'blocked',
    observed_at: '2026-07-18T01:45:00+00:00',
    blockers: ['kill_switch_enabled'],
  },
  pause: {
    status: 'paused',
    pause_event_id: 'pause-fixture-1',
    paused_at: '2026-07-18T01:45:00+00:00',
    reasons: ['kill_switch_enabled'],
    resume_available: false,
    replacement_review_required: true,
  },
  blockers: ['runtime_session_paused'],
  runtime_authentication_evaluated: false,
  runtime_authority_granted: false,
  broker_submission_enabled: false,
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

const preview: ControlledSessionRevocationPreview = {
  schema_version: 'karkinos.controlled_session_runtime_authority.v1',
  action: 'revoke_controlled_session',
  session_id: sessionId,
  session_fingerprint: '7'.repeat(64),
  reservation_id: session.reservation_id,
  reason_code: 'risk_review',
  revocation_fingerprint: revocationFingerprint,
  revocation_id: revocationId,
  status: 'ready_for_signed_revocation',
  ready: true,
  already_revoked: false,
  blockers: [],
  required_operator_approval: {
    action: 'revoke_controlled_session',
    artifact_type: 'controlled_session_revocation',
    artifact_fingerprint: revocationFingerprint,
  },
  broker_submission_enabled: false,
};

const result: ControlledSessionRevocationResult = {
  schema_version: 'karkinos.controlled_session_runtime_authority.v1',
  action: 'revoke_controlled_session',
  revocation_id: revocationId,
  revocation_fingerprint: revocationFingerprint,
  session_id: sessionId,
  session_fingerprint: preview.session_fingerprint,
  reservation_id: session.reservation_id,
  reason_code: 'risk_review',
  operator_id: 'local-owner',
  operator_approval_id: approvalId,
  status: 'revoked',
  automatic_resume_enabled: false,
  broker_submission_enabled: false,
  persisted: true,
  reused: false,
  revoked_at: '2026-07-18T01:50:00+00:00',
  current_session: {
    session_id: sessionId,
    status: 'revoked',
    automatic_resume_enabled: false,
    broker_submission_enabled: false,
  },
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel(currentSession = session) {
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
      if (url.endsWith('/revocation/preview')) {
        return jsonResponse(preview);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlz',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'revoke_controlled_session',
          artifact_type: 'controlled_session_revocation',
          artifact_fingerprint: revocationFingerprint,
          issued_at: '2026-07-18T01:47:00+00:00',
          expires_at: '2026-07-18T01:50:00+00:00',
          reused: false,
          operator_identity_verified: false,
          authorizes_execution: false,
        });
      }
      if (url.endsWith('/operator-approvals/verifications')) {
        return jsonResponse({
          approval_id: approvalId,
          approval_status: 'verified',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action: 'revoke_controlled_session',
          artifact_type: 'controlled_session_revocation',
          artifact_fingerprint: revocationFingerprint,
          expires_at: '2026-07-18T01:50:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (url.endsWith('/revocations')) {
        return jsonResponse(result);
      }
      return jsonResponse({ detail: 'unexpected request' }, { status: 404 });
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ControlledSessionRevocationOperatorPanel
        session={currentSession}
        locale="en"
      />
    </QueryClientProvider>,
  );
  return requests;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test('previews, verifies, and revokes one exact session without broker controls', async () => {
  const requests = renderPanel();

  fireEvent.click(
    screen.getByRole('button', {
      name: 'Review and revoke this session authority',
    }),
  );
  expect(
    screen.getByText(/cannot submit or cancel a broker order/i),
  ).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Revocation reason'), {
    target: { value: 'risk_review' },
  });
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Generate read-only revocation preview',
    }),
  );
  expect(
    await screen.findByText('Deterministic revocation evidence'),
  ).toBeTruthy();

  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: 'Create 3-minute signing challenge',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Create 3-minute signing challenge',
    }),
  );
  expect(await screen.findByDisplayValue('c2lnbi10aGlz')).toBeTruthy();

  fireEvent.change(screen.getByLabelText('Detached signature Base64'), {
    target: { value: signature },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Verify signature' }));
  expect(await screen.findByText('Final revocation confirmation')).toBeTruthy();

  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Permanently revoke this session once',
    }),
  );
  expect(
    await screen.findByText(
      'Session revoked (Risk review); runtime admission is permanently closed.',
    ),
  ).toBeTruthy();

  const previewRequest = requests.find((item) =>
    item.url.endsWith('/revocation/preview'),
  );
  expect(previewRequest).toMatchObject({
    method: 'POST',
    body: { reason_code: 'risk_review' },
  });
  const challengeRequest = requests.find((item) =>
    item.url.endsWith('/operator-approvals/challenges'),
  );
  expect(challengeRequest?.body).toMatchObject({
    operator_id: 'local-owner',
    key_id: 'owner-key-1',
    action: 'revoke_controlled_session',
    artifact_type: 'controlled_session_revocation',
    artifact_fingerprint: revocationFingerprint,
    ttl_seconds: 180,
  });
  const revokeRequest = requests.find((item) =>
    item.url.endsWith('/revocations'),
  );
  expect(revokeRequest).toMatchObject({
    method: 'POST',
    body: {
      reason_code: 'risk_review',
      revocation_fingerprint: revocationFingerprint,
      operator_approval_id: approvalId,
      operator_proof_signature_base64: signature,
      acknowledgement: 'revoke_exact_controlled_session_no_auto_resume',
    },
  });
  expect(screen.queryByText('Submit broker order')).toBeNull();
  expect(screen.queryByText('Cancel broker order')).toBeNull();
});

test('does not offer revocation for already closed authority', () => {
  renderPanel({
    ...session,
    status: 'revoked',
    persisted_status: 'revoked',
    is_current_window: false,
  });

  expect(
    screen.queryByRole('button', {
      name: 'Review and revoke this session authority',
    }),
  ).toBeNull();
});
