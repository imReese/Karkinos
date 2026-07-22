import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  SignedBrokerAdapterReleaseReviewDossier,
  SignedBrokerAdapterReleaseReviewListItem,
  SignedBrokerAdapterReleaseReviewStatus,
} from './api';
import { SignedBrokerAdapterReleaseReviewOperatorPanel } from './signed-broker-adapter-release-review-operator-panel';

const manifest = {
  schema_version: 'karkinos.broker_adapter_release_manifest.v1',
  release_evidence_ref: 'fixture-release-reviewed-v1',
  collector_id: 'deterministic-fixture-collector',
  deployment_id: 'fixture-deployment-1',
  collector_version: 'fixture-v1',
  deployment_fingerprint: 'd'.repeat(64),
  provider: 'deterministic_fixture',
  gateway_id: 'fixture-gateway-1',
  account_alias: 'fixture-account',
  adapter_authorization_ref: 'test-only-user-authorization',
  collection_modes: ['callback', 'poll'],
  capabilities: {
    can_read_account: false,
    can_read_cash: false,
    can_read_positions: false,
    can_read_orders: true,
    can_read_fills: true,
    can_read_market_session: false,
    can_read_heartbeat: true,
    can_submit_orders: false,
    can_cancel_orders: false,
  },
  boundaries: {
    runtime_auth_material_external: true,
    strategy_imports_adapter: false,
    ai_imports_adapter: false,
    core_imports_provider_sdk: false,
    writes_oms: false,
    writes_production_ledger: false,
    writes_risk_state: false,
    writes_kill_switch: false,
    writes_capital_authority: false,
    default_registered: false,
  },
  review_refs: {
    adapter_adr: 'fixture-adr-v1',
    capability_matrix: 'fixture-capability-matrix-v1',
    threat_model: 'fixture-threat-model-v1',
    deployment_runbook: 'fixture-deployment-runbook-v1',
    rollback_runbook: 'fixture-rollback-runbook-v1',
    privacy_review: 'fixture-privacy-review-v1',
  },
  limitations: ['Deterministic fixture only.'],
};

const dossierFingerprint = '1'.repeat(64);
const manifestFingerprint = '2'.repeat(64);
const reviewFingerprint = '3'.repeat(64);
const approvalId = '4'.repeat(64);
const challengeId = '5'.repeat(64);
const signature = 'A'.repeat(88);

const status: SignedBrokerAdapterReleaseReviewStatus = {
  schema_version: 'karkinos.signed_broker_adapter_release_review_status.v1',
  contract_status: 'signed_provider_neutral_adapter_review',
  recorded_manifest_count: 1,
  recorded_review_count: 1,
  supported_decisions: ['accepted', 'rejected', 'revoked'],
  operator_signature_required: true,
  review_store_available: true,
  provider_contact_performed: false,
  adapter_registered: false,
  broker_submission_enabled: false,
  broker_cancellation_enabled: false,
  capital_authority_changed: false,
  authorizes_execution: false,
};

const acceptedRelease: SignedBrokerAdapterReleaseReviewListItem = {
  schema_version: 'karkinos.signed_broker_adapter_release_review_list.v1',
  release_evidence_ref: manifest.release_evidence_ref,
  manifest_fingerprint: manifestFingerprint,
  manifest,
  current_review: {
    status: 'accepted',
    review_id: 'prior-accepted-review-v1',
    release_evidence_ref: manifest.release_evidence_ref,
    manifest_fingerprint: manifestFingerprint,
    decision: 'accepted',
    reviewer_ref: `operator_approval:${approvalId}`,
    reviewed_at: '2026-07-18T02:00:00+00:00',
    reason_ref: 'owner-reviewed-provider-boundary-v1',
    conformance_run_id: 'conformance-v1',
    conformance_report_fingerprint: '6'.repeat(64),
    review_fingerprint: reviewFingerprint,
    integrity_blockers: [],
    persisted: true,
    reused: false,
    created_at: '2026-07-18T02:00:01+00:00',
  },
  blockers: [],
  reviewable: true,
  provider_contact_performed: false,
  adapter_registered: false,
  authorizes_execution: false,
};

function dossier(
  decision: 'accepted' | 'rejected' | 'revoked',
): SignedBrokerAdapterReleaseReviewDossier {
  return {
    schema_version: 'karkinos.signed_broker_adapter_release_review_dossier.v1',
    action: 'review_broker_adapter_release',
    review_id: `signed-${decision}-review-v1`,
    decision,
    reviewed_at: '2026-07-18T03:00:00+00:00',
    reason_ref: `${decision}-reason-v1`,
    manifest,
    manifest_fingerprint: manifestFingerprint,
    manifest_evidence: {
      file_fingerprint: '7'.repeat(64),
      source_name: 'owner-reviewed-adapter-release.json',
      validation_status: 'pass',
      recordable: true,
      blockers: [],
      record_blockers: [],
    },
    current_review:
      decision === 'revoked'
        ? acceptedRelease.current_review
        : {
            status: 'not_found',
            release_evidence_ref: manifest.release_evidence_ref,
            review_fingerprint: '',
            integrity_blockers: [],
          },
    conformance: {
      status: decision === 'accepted' ? 'clear' : 'not_required',
      run_id: decision === 'accepted' ? 'conformance-v1' : '',
      report_fingerprint: decision === 'accepted' ? '6'.repeat(64) : '',
      blockers: [],
    },
    dossier_fingerprint: dossierFingerprint,
    generated_at: '2026-07-18T03:00:00+00:00',
    review_status: 'ready_for_signature',
    review_ready: true,
    review_blockers: [],
    required_operator_approval: {
      action: 'review_broker_adapter_release',
      artifact_type: 'broker_adapter_release_review_dossier',
      artifact_fingerprint: dossierFingerprint,
    },
    provider_contact_performed: false,
    adapter_registered: false,
    broker_submission_enabled: false,
    broker_cancellation_enabled: false,
    capital_authority_changed: false,
    authorizes_execution: false,
  };
}

function jsonResponse(value: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(value), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel() {
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
      if (url.endsWith('/broker-adapter-release-review/status')) {
        return jsonResponse(status);
      }
      if (url.includes('/broker-adapter-release-review/releases?')) {
        return jsonResponse([acceptedRelease]);
      }
      if (url.endsWith('/broker-adapter-release-review/dossiers/preview')) {
        return jsonResponse(
          dossier(
            String(body?.decision) as 'accepted' | 'rejected' | 'revoked',
          ),
        );
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
              key_id: 'adapter-review-key-1',
              algorithm: 'ed25519',
              enabled: true,
              public_key_fingerprint: '8'.repeat(64),
            },
          ],
          supported_actions: ['review_broker_adapter_release'],
          default_challenge_ttl_seconds: 180,
          maximum_challenge_ttl_seconds: 300,
          private_key_storage_enabled: false,
          runtime_execution_authority: 'disabled',
          broker_submission_enabled: false,
          safety: {},
        });
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlz',
          operator_id: 'local-owner',
          key_id: 'adapter-review-key-1',
          action: 'review_broker_adapter_release',
          artifact_type: 'broker_adapter_release_review_dossier',
          artifact_fingerprint: dossierFingerprint,
          issued_at: '2026-07-18T03:00:00+00:00',
          expires_at: '2026-07-18T03:03:00+00:00',
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
          key_id: 'adapter-review-key-1',
          action: 'review_broker_adapter_release',
          artifact_type: 'broker_adapter_release_review_dossier',
          artifact_fingerprint: dossierFingerprint,
          expires_at: '2026-07-18T03:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (
        url.endsWith('/broker-adapter-release-review/reviews') &&
        method === 'POST'
      ) {
        const decision = String(body?.decision) as
          'accepted' | 'rejected' | 'revoked';
        return jsonResponse({
          schema_version: 'karkinos.broker_adapter_release_review.v1',
          status: decision,
          decision,
          review_id: body?.review_id,
          release_evidence_ref: manifest.release_evidence_ref,
          manifest_fingerprint: manifestFingerprint,
          reviewer_ref: `operator_approval:${approvalId}`,
          reviewed_at: body?.reviewed_at,
          reason_ref: body?.reason_ref,
          conformance_run_id: decision === 'accepted' ? 'conformance-v1' : '',
          conformance_report_fingerprint:
            decision === 'accepted' ? '6'.repeat(64) : '',
          review_fingerprint: reviewFingerprint,
          dossier_fingerprint: dossierFingerprint,
          operator_id: 'local-owner',
          operator_key_id: 'adapter-review-key-1',
          operator_public_key_fingerprint: '8'.repeat(64),
          operator_approval_id: approvalId,
          operator_identity_verified: true,
          persisted: true,
          reused: false,
          created_at: '2026-07-18T03:00:01+00:00',
          provider_contact_performed: false,
          adapter_registered: false,
          broker_submission_enabled: false,
          broker_cancellation_enabled: false,
          capital_authority_changed: false,
          authorizes_execution: false,
        });
      }
      return jsonResponse({ detail: 'unexpected request' }, { status: 404 });
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SignedBrokerAdapterReleaseReviewOperatorPanel locale="en" />
    </QueryClientProvider>,
  );
  return requests;
}

async function completeSignedDecision() {
  expect(await screen.findByTitle(dossierFingerprint)).toBeTruthy();
  await waitFor(() =>
    expect(
      (
        screen.getByRole('button', {
          name: 'Create 3-minute offline signing challenge',
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Create 3-minute offline signing challenge',
    }),
  );
  expect(await screen.findByDisplayValue('c2lnbi10aGlz')).toBeTruthy();
  fireEvent.change(
    screen.getByLabelText('Adapter review offline signature Base64'),
    { target: { value: signature } },
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Verify offline signature' }),
  );
  expect(
    await screen.findByText('Trusted identity verified: local-owner'),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(
    screen.getByRole('button', { name: 'Record signed adapter decision' }),
  );
  expect(await screen.findByText(/Recorded:/)).toBeTruthy();
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test('stays collapsed without reading or exposing broker actions', async () => {
  const requests = renderPanel();

  expect(await screen.findByText('Decision review closed')).toBeTruthy();
  expect(requests).toHaveLength(0);
  expect(screen.queryByText('Submit broker order')).toBeNull();
  expect(screen.queryByText('Cancel broker order')).toBeNull();
});

test('blocks nested credential keys locally without sending the manifest', async () => {
  const requests = renderPanel();
  fireEvent.click(
    screen.getByRole('button', { name: 'Open provider decision review' }),
  );
  fireEvent.change(
    screen.getByLabelText('Read-only adapter release manifest JSON'),
    {
      target: {
        value: JSON.stringify({ nested: { api_key: 'must-not-leave' } }),
      },
    },
  );
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate signed review preview' }),
  );

  expect(
    await screen.findByText(/blocked locally without being sent/),
  ).toBeTruthy();
  expect(
    requests.some((request) => request.url.endsWith('/dossiers/preview')),
  ).toBe(false);
  expect(JSON.stringify(requests)).not.toContain('must-not-leave');
});

test('records one exact signed acceptance without broker or authority action', async () => {
  const requests = renderPanel();
  fireEvent.click(
    screen.getByRole('button', { name: 'Open provider decision review' }),
  );
  fireEvent.change(
    screen.getByLabelText('Read-only adapter release manifest JSON'),
    { target: { value: JSON.stringify(manifest) } },
  );
  fireEvent.change(screen.getByLabelText('Adapter release review ID'), {
    target: { value: 'signed-accepted-review-v1' },
  });
  fireEvent.change(screen.getByLabelText('Adapter release reason reference'), {
    target: { value: 'accepted-reason-v1' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate signed review preview' }),
  );
  await completeSignedDecision();

  const previewRequest = requests.find((request) =>
    request.url.endsWith('/dossiers/preview'),
  );
  const recordRequest = requests.find((request) =>
    request.url.endsWith('/broker-adapter-release-review/reviews'),
  );
  expect(previewRequest?.body).toMatchObject({
    manifest,
    review_id: 'signed-accepted-review-v1',
    decision: 'accepted',
    reason_ref: 'accepted-reason-v1',
  });
  expect(recordRequest?.body).toMatchObject({
    manifest,
    dossier_fingerprint: dossierFingerprint,
    operator_label: 'local-owner',
    operator_approval_id: approvalId,
    operator_proof_signature_base64: signature,
    acknowledgement:
      'review_broker_adapter_release_without_registration_or_execution_authority',
  });
  expect(JSON.stringify(requests)).not.toContain('/submit');
  expect(JSON.stringify(requests)).not.toContain('/cancel');
});

test('records a one-way signed revocation from the persisted accepted manifest', async () => {
  const requests = renderPanel();
  fireEvent.click(
    screen.getByRole('button', { name: 'Open provider decision review' }),
  );
  fireEvent.change(screen.getByLabelText('Select review decision'), {
    target: { value: 'revoked' },
  });
  expect(
    await screen.findByLabelText('Select accepted adapter release to revoke'),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Adapter release review ID'), {
    target: { value: 'signed-revoked-review-v1' },
  });
  fireEvent.change(screen.getByLabelText('Adapter release reason reference'), {
    target: { value: 'revoked-reason-v1' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Generate signed review preview' }),
  );
  await completeSignedDecision();

  const recordRequest = requests.find((request) =>
    request.url.endsWith('/broker-adapter-release-review/reviews'),
  );
  expect(recordRequest?.body).toMatchObject({
    manifest,
    decision: 'revoked',
    review_id: 'signed-revoked-review-v1',
    reason_ref: 'revoked-reason-v1',
  });
  expect(JSON.stringify(requests)).not.toContain('/submit');
  expect(JSON.stringify(requests)).not.toContain('/cancel');
});
