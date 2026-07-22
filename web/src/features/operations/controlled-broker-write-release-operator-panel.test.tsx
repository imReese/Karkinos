import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type {
  BrokerAdapterReadiness,
  BrokerAdapterReadinessRelease,
  BrokerConnectorSoakPromotionStatus,
  ControlledBrokerWriteReleaseDossier,
  ControlledBrokerWriteReleaseEvidence,
  ControlledBrokerWriteReleaseRevocationPreview,
  ControlledBrokerWriteReleaseStatus,
  OperatorApprovalStatus,
} from './api';
import { ControlledBrokerWriteReleaseOperatorPanel } from './controlled-broker-write-release-operator-panel';

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

const releaseId = '1'.repeat(64);
const dossierFingerprint = '2'.repeat(64);
const revocationFingerprint = '3'.repeat(64);
const challengeId = '4'.repeat(64);
const approvalId = '5'.repeat(64);
const signature = 'S'.repeat(88);
const soakAcceptanceId = '6'.repeat(64);

const readonlyRelease: BrokerAdapterReadinessRelease = {
  release_evidence_ref: 'reviewed-readonly-release-v1',
  manifest_fingerprint: '7'.repeat(64),
  manifest_status: 'clear',
  provider: 'reviewed-provider',
  gateway_id: 'reviewed-gateway',
  account_alias: 'reviewed-account',
  collector_id: 'reviewed-collector',
  collection_modes: ['poll'],
  review_status: 'accepted',
  review_id: 'readonly-review-v1',
  reviewed_at: '2026-07-18T01:00:00+00:00',
  conformance_status: 'clear',
  conformance_run_id: 'readonly-conformance-v1',
  conformance_report_fingerprint: '8'.repeat(64),
  collector_status: 'recorded',
  collector_run_id: 'readonly-collector-run-v1',
  collector_updated_at: '2026-07-18T01:20:00+00:00',
  status: 'observing_readonly',
  next_manual_action: 'continue_readonly_evidence_observation',
  blockers: [],
  does_not_authorize_provider_activation: true,
};

const readiness: BrokerAdapterReadiness = {
  schema_version: 'karkinos.broker_adapter_readiness.v1',
  status: 'observing_readonly',
  subsystem_status: 'pass',
  evidence_store_status: 'available',
  configured_release_count: 1,
  accepted_release_count: 1,
  blocked_release_count: 0,
  next_manual_action: 'continue_readonly_evidence_observation',
  latest_release: readonlyRelease,
  releases: [readonlyRelease],
  blockers: [],
  limitations: [],
  persisted_facts_only: true,
  provider_contacted: false,
  adapter_registered: false,
  default_registered: false,
  broker_submission_enabled: false,
  does_not_submit_broker_order: true,
  does_not_cancel_broker_order: true,
  does_not_mutate_oms: true,
  does_not_mutate_production_ledger: true,
  does_not_mutate_risk_state: true,
  does_not_mutate_kill_switch: true,
  does_not_mutate_capital_authority: true,
  authorizes_execution: false,
};

const soak: BrokerConnectorSoakPromotionStatus = {
  schema_version: 'karkinos.broker_connector_soak_promotion_status.v1',
  contract_status: 'evidence_ready_for_signed_owner_acceptance',
  connector_count: 1,
  connectors: [
    {
      connector_id: readonlyRelease.collector_id,
      account_alias: readonlyRelease.account_alias,
      review_status: 'ready',
      promotion_ready: true,
      promotion_blockers: [],
      owner_acceptance_recorded: true,
      account_truth_reconciliation_linked: true,
      operational_evidence: {
        status: 'clear',
        selected_trading_day_count: 20,
        target_trading_day_count: 20,
        phase_coverage: {},
        drill_coverage: {},
        latest_soak_status: 'healthy',
        blockers: [],
      },
      acceptance: {
        status: 'recorded_verified_owner_acceptance',
        acceptance_id: soakAcceptanceId,
        recorded_at: '2026-07-18T01:30:00+00:00',
        operator_identity_verified: true,
        authorizes_execution: false,
      },
      runtime_execution_authority: 'disabled',
      broker_submission_enabled: false,
      authorizes_execution: false,
    },
  ],
  promotion_ready: true,
  promotion_blockers: [],
  owner_acceptance_recorded: true,
  account_truth_reconciliation_linked: true,
  runtime_execution_authority: 'disabled',
  broker_submission_enabled: false,
  automatic_promotion_enabled: false,
};

const releaseStatus: ControlledBrokerWriteReleaseStatus = {
  schema_version: 'karkinos.controlled_broker_write_release_status.v1',
  contract_status: 'default_closed_waiting_for_signed_write_release',
  recorded_release_count: 0,
  active_release_count: 0,
  active_release_ids: [],
  maximum_release_seconds: 43_200,
  supported_revocation_reasons: ['incident_or_anomaly', 'owner_disabled'],
  release_provider_available: false,
  default_registered: false,
  gateway_registered: false,
  broker_contact_performed: false,
  broker_submission_performed: false,
  broker_cancellation_performed: false,
  automatic_execution_allowed: false,
  strategy_direct_submission_allowed: false,
  authorizes_order_submission_by_itself: false,
  does_not_grant_capital_authority: true,
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
      public_key_fingerprint: '9'.repeat(64),
    },
  ],
  private_key_storage_enabled: false,
  runtime_execution_authority: 'disabled',
  broker_submission_enabled: false,
};

const dossier: ControlledBrokerWriteReleaseDossier = {
  schema_version: 'karkinos.controlled_broker_write_release_dossier.v1',
  dossier_fingerprint: dossierFingerprint,
  generated_at: '2026-07-18T02:00:00+00:00',
  review_status: 'ready_for_signature',
  review_ready: true,
  review_blockers: [],
  scope: {
    provider: readonlyRelease.provider,
    gateway_id: readonlyRelease.gateway_id,
    account_alias: readonlyRelease.account_alias,
    connector_id: readonlyRelease.collector_id,
  },
  readonly_adapter_release: {
    release_evidence_ref: readonlyRelease.release_evidence_ref,
    manifest_fingerprint: readonlyRelease.manifest_fingerprint,
    status: 'observing_readonly',
  },
  soak_promotion: {
    connector_id: readonlyRelease.collector_id,
    account_alias: readonlyRelease.account_alias,
    dossier_fingerprint: 'a'.repeat(64),
    acceptance_id: soakAcceptanceId,
    promotion_ready: true,
  },
  effective_at: '2026-07-18T01:59:30.000Z',
  expires_at: '2026-07-18T05:59:30.000Z',
  execution_mode: 'manual_each_order',
  required_operator_approval: {
    action: 'issue_controlled_broker_write_release',
    artifact_type: 'controlled_broker_write_release_dossier',
    artifact_fingerprint: dossierFingerprint,
  },
  provider_contact_performed: false,
  adapter_registered: false,
  broker_submission_performed: false,
  broker_cancellation_performed: false,
  capital_authority_changed: false,
};

const recordedRelease: ControlledBrokerWriteReleaseEvidence = {
  schema_version: 'karkinos.controlled_broker_write_release.v1',
  status: 'current_clear_signed_release',
  release_evidence_id: releaseId,
  evidence_fingerprint: 'b'.repeat(64),
  provider: readonlyRelease.provider,
  gateway_id: readonlyRelease.gateway_id,
  account_alias: readonlyRelease.account_alias,
  execution_edge_ref: 'reviewed-edge-v1',
  readonly_release_evidence_ref: readonlyRelease.release_evidence_ref,
  soak_acceptance_id: soakAcceptanceId,
  operator_id: 'local-owner',
  operator_identity_verified: true,
  execution_mode: 'manual_each_order',
  effective_at: dossier.effective_at,
  expires_at: dossier.expires_at,
  blockers: [],
  revoked: false,
  authorizes_order_submission_by_itself: false,
  does_not_grant_capital_authority: true,
};

const revocationPreview: ControlledBrokerWriteReleaseRevocationPreview = {
  schema_version: 'karkinos.controlled_broker_write_release_revocation.v1',
  action: 'revoke_controlled_broker_write_release',
  release_evidence_id: releaseId,
  release_evidence_fingerprint: recordedRelease.evidence_fingerprint,
  reason_code: 'incident_or_anomaly',
  revocation_fingerprint: revocationFingerprint,
  status: 'ready_for_signature',
  ready: true,
  blockers: [],
  required_operator_approval: {
    action: 'revoke_controlled_broker_write_release',
    artifact_type: 'controlled_broker_write_release_revocation',
    artifact_fingerprint: revocationFingerprint,
  },
  broker_contact_performed: false,
  broker_submission_performed: false,
  broker_cancellation_performed: false,
  capital_authority_changed: false,
  resume_enabled: false,
};

type RecordedRequest = {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
};

function renderPanel({
  listedReleases = [],
}: {
  listedReleases?: ControlledBrokerWriteReleaseEvidence[];
} = {}) {
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
      if (url.endsWith('/controlled-broker-write-release/status')) {
        return jsonResponse(releaseStatus);
      }
      if (url.includes('/controlled-broker-write-release/releases?')) {
        return jsonResponse(listedReleases);
      }
      if (url.endsWith('/dossiers/preview')) {
        return jsonResponse(dossier);
      }
      if (url.endsWith('/operator-approvals/status')) {
        return jsonResponse(approvalStatus);
      }
      if (url.endsWith('/operator-approvals/challenges')) {
        const action = String(body?.action || '');
        const artifactType = String(body?.artifact_type || '');
        const artifactFingerprint = String(body?.artifact_fingerprint || '');
        return jsonResponse({
          challenge_id: challengeId,
          challenge_status: 'pending_signature',
          signing_payload_base64: 'c2lnbi10aGlz',
          operator_id: 'local-owner',
          key_id: 'owner-key-1',
          action,
          artifact_type: artifactType,
          artifact_fingerprint: artifactFingerprint,
          issued_at: '2026-07-18T02:00:00+00:00',
          expires_at: '2026-07-18T02:03:00+00:00',
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
          action: 'verified-action',
          artifact_type: 'verified-artifact',
          artifact_fingerprint: dossierFingerprint,
          expires_at: '2026-07-18T02:03:00+00:00',
          operator_identity_verified: true,
          authorizes_execution: false,
          reused: false,
        });
      }
      if (
        url.endsWith('/controlled-broker-write-release/releases') &&
        method === 'POST'
      ) {
        return jsonResponse({
          ...recordedRelease,
          status: 'recorded_expiring_manual_each_order_release',
          dossier_fingerprint: dossierFingerprint,
          operator_approval_id: approvalId,
          created_at: '2026-07-18T02:01:00+00:00',
          persisted: true,
          reused: false,
        });
      }
      if (url.endsWith('/revocation/preview')) {
        return jsonResponse(revocationPreview);
      }
      if (url.endsWith('/revocations')) {
        return jsonResponse({
          schema_version:
            'karkinos.controlled_broker_write_release_revocation.v1',
          release_evidence_id: releaseId,
          release_evidence_fingerprint: recordedRelease.evidence_fingerprint,
          reason_code: 'incident_or_anomaly',
          revocation_fingerprint: revocationFingerprint,
          revocation_id: 'c'.repeat(64),
          operator_id: 'local-owner',
          operator_approval_id: approvalId,
          status: 'revoked',
          created_at: '2026-07-18T02:02:00+00:00',
          persisted: true,
          reused: false,
          resume_enabled: false,
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
      <ControlledBrokerWriteReleaseOperatorPanel
        locale="en"
        readiness={readiness}
        soak={soak}
      />
    </QueryClientProvider>,
  );
  return requests;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test('stays collapsed without reading or creating any mutation', async () => {
  const requests = renderPanel();

  expect(await screen.findByText('Review closed')).toBeTruthy();
  expect(screen.queryByLabelText('Execution-edge manifest JSON')).toBeNull();
  expect(requests).toHaveLength(0);
  expect(screen.queryByText('Submit broker order')).toBeNull();
  expect(screen.queryByText('Cancel broker order')).toBeNull();
});

test('blocks nested credential keys locally without sending the manifest', async () => {
  const requests = renderPanel();

  fireEvent.click(
    screen.getByRole('button', { name: 'Open capability review' }),
  );
  fireEvent.change(screen.getByLabelText('Execution-edge manifest JSON'), {
    target: {
      value: JSON.stringify({ nested: { api_key: 'must-not-leave' } }),
    },
  });
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Generate read-only release preview',
    }),
  );

  expect(
    await screen.findByText(/blocked locally without being sent/),
  ).toBeTruthy();
  expect(
    requests.some((request) => request.url.endsWith('/dossiers/preview')),
  ).toBe(false);
  expect(JSON.stringify(requests)).not.toContain('must-not-leave');
});

test('previews and records one exact signed release without broker or capital action', async () => {
  const requests = renderPanel();
  const manifest = {
    schema_version: 'karkinos.broker_execution_edge_manifest.v1',
    execution_edge_ref: 'reviewed-edge-v1',
    provider: readonlyRelease.provider,
  };

  fireEvent.click(
    screen.getByRole('button', { name: 'Open capability review' }),
  );
  fireEvent.change(screen.getByLabelText('Execution-edge manifest JSON'), {
    target: { value: JSON.stringify(manifest) },
  });
  for (const label of [
    'Broker agreement review',
    'Account permissions review',
    'Program-trading reporting review',
    'Provider acceptance-test report',
    'Deployment authorization',
    'Risk-controls review',
    'Rollback-drill review',
  ]) {
    fireEvent.change(screen.getByLabelText(label), {
      target: { value: `review:${label.toLowerCase().replace(/ /g, '-')}` },
    });
  }
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Generate read-only release preview',
    }),
  );
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
  fireEvent.change(screen.getByLabelText('Offline signature Base64'), {
    target: { value: signature },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Verify offline signature' }),
  );
  expect(
    await screen.findByText('Trusted identity verified: local-owner'),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Record time-bounded capability release',
    }),
  );
  expect(await screen.findByText(/Recorded:/)).toBeTruthy();

  const previewRequest = requests.find((request) =>
    request.url.endsWith('/dossiers/preview'),
  );
  expect(previewRequest).toMatchObject({
    method: 'POST',
    body: {
      execution_edge_manifest: manifest,
      readonly_release_evidence_ref: readonlyRelease.release_evidence_ref,
      soak_acceptance_id: soakAcceptanceId,
    },
  });
  expect(
    Object.keys(
      previewRequest?.body?.owner_review_refs as Record<string, string>,
    ),
  ).toHaveLength(7);
  const issueRequest = requests.find(
    (request) =>
      request.url.endsWith('/controlled-broker-write-release/releases') &&
      request.method === 'POST',
  );
  expect(issueRequest?.body).toMatchObject({
    dossier_fingerprint: dossierFingerprint,
    operator_label: 'local-owner',
    operator_approval_id: approvalId,
    operator_proof_signature_base64: signature,
    acknowledgement:
      'issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority',
  });
  expect(
    requests.some((request) =>
      request.url.includes('/controlled-broker-submission'),
    ),
  ).toBe(false);
  expect(
    requests.some((request) =>
      request.url.includes('/controlled-broker-cancellation'),
    ),
  ).toBe(false);
});

test('previews and permanently revokes a persisted release without a broker call', async () => {
  const requests = renderPanel({ listedReleases: [recordedRelease] });

  fireEvent.click(
    screen.getByRole('button', { name: 'Open capability review' }),
  );
  expect(await screen.findByLabelText('Select release to revoke')).toBeTruthy();
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Generate read-only revocation preview',
    }),
  );
  expect(await screen.findByTitle(releaseId)).toBeTruthy();

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
  fireEvent.change(await screen.findByLabelText('Offline signature Base64'), {
    target: { value: signature },
  });
  fireEvent.click(
    screen.getByRole('button', { name: 'Verify offline signature' }),
  );
  expect(
    await screen.findByText('Trusted identity verified: local-owner'),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(
    screen.getByRole('button', {
      name: 'Permanently revoke this release once',
    }),
  );
  expect(await screen.findByText(/Permanently revoked:/)).toBeTruthy();

  const previewRequest = requests.find((request) =>
    request.url.endsWith('/revocation/preview'),
  );
  expect(previewRequest).toMatchObject({
    method: 'POST',
    body: { reason_code: 'incident_or_anomaly' },
  });
  const revokeRequest = requests.find((request) =>
    request.url.endsWith('/revocations'),
  );
  expect(revokeRequest?.body).toMatchObject({
    reason_code: 'incident_or_anomaly',
    revocation_fingerprint: revocationFingerprint,
    operator_label: 'local-owner',
    operator_approval_id: approvalId,
    operator_proof_signature_base64: signature,
    acknowledgement:
      'revoke_exact_broker_write_release_without_resume_or_broker_action',
  });
  expect(
    requests.some(
      (request) =>
        request.url.includes('/controlled-broker-submission') ||
        request.url.includes('/controlled-broker-cancellation'),
    ),
  ).toBe(false);
});
