import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient, postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';
import { liveOperationsRefetchInterval } from './refetch-policy';
import type { OperationsStatus } from './status';

export type BrokerAdapterReadinessRelease = {
  release_evidence_ref: string;
  manifest_fingerprint: string;
  manifest_status: string;
  provider: string;
  gateway_id: string;
  account_alias: string;
  collector_id: string;
  collection_modes: string[];
  review_status: string;
  review_id: string;
  reviewed_at?: string | null;
  conformance_status: string;
  conformance_run_id: string;
  conformance_report_fingerprint: string;
  collector_status: string;
  collector_run_id: string;
  collector_updated_at?: string | null;
  status: string;
  next_manual_action: string;
  blockers: string[];
  does_not_authorize_provider_activation: boolean;
};

export type BrokerAdapterReadiness = {
  schema_version: 'karkinos.broker_adapter_readiness.v1';
  status: string;
  subsystem_status: OperationsStatus;
  evidence_store_status: string;
  configured_release_count: number;
  accepted_release_count: number;
  blocked_release_count: number;
  next_manual_action: string;
  latest_release: BrokerAdapterReadinessRelease | null;
  releases: BrokerAdapterReadinessRelease[];
  blockers: string[];
  limitations: string[];
  persisted_facts_only: boolean;
  provider_contacted: boolean;
  adapter_registered: boolean;
  default_registered: boolean;
  broker_submission_enabled: boolean;
  does_not_submit_broker_order: boolean;
  does_not_cancel_broker_order: boolean;
  does_not_mutate_oms: boolean;
  does_not_mutate_production_ledger: boolean;
  does_not_mutate_risk_state: boolean;
  does_not_mutate_kill_switch: boolean;
  does_not_mutate_capital_authority: boolean;
  authorizes_execution: boolean;
};

export type ControlledPerOrderPilotReadinessGate = {
  key: string;
  status: 'pass' | 'blocked';
  blockers: string[];
  evidence_refs: string[];
  resolution_condition: string;
  manual_acknowledgement_clears_status: false;
};

export type ControlledPerOrderPilotReadiness = {
  schema_version: 'karkinos.controlled_per_order_pilot_readiness.v1';
  status: 'ready_for_exact_order_review' | 'blocked';
  scope: {
    provider: string;
    gateway_id: string;
    account_alias: string;
    connector_id: string;
    readonly_release_evidence_ref: string;
    write_release_evidence_id: string;
  };
  gates: ControlledPerOrderPilotReadinessGate[];
  required_next_order_gates: string[];
  readiness_fingerprint: string;
  observed_at: string | null;
  gate_count: number;
  passed_gate_count: number;
  blocked_gate_count: number;
  blockers: string[];
  next_safe_action: string;
  release_scope: 'pilot_admission_prerequisites_not_v1_8_completion';
  persisted_facts_only: true;
  read_only_projection: true;
  provider_contacted: false;
  database_writes_performed: false;
  broker_submission_enabled: false;
  broker_cancellation_enabled: false;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  does_not_mutate_risk_state: true;
  does_not_mutate_kill_switch: true;
  does_not_mutate_capital_authority: true;
  authorizes_execution: false;
  automatic_scale_up_enabled: false;
  limitations: string[];
};

export type BrokerConnectorSoakPromotionConnector = {
  connector_id: string;
  account_alias: string;
  review_status: string;
  promotion_ready: boolean;
  promotion_blockers: string[];
  owner_acceptance_recorded: boolean;
  account_truth_reconciliation_linked: boolean;
  operational_evidence: {
    status: string;
    selected_trading_day_count: number;
    target_trading_day_count: number;
    phase_coverage: Record<string, string[]>;
    drill_coverage: Record<string, boolean>;
    latest_soak_status: string;
    blockers: string[];
  };
  acceptance?: {
    status?: string;
    acceptance_id?: string | null;
    recorded_at?: string | null;
    operator_identity_verified?: boolean;
    authorizes_execution?: boolean;
  };
  runtime_execution_authority: string;
  broker_submission_enabled: boolean;
  authorizes_execution: boolean;
};

export type BrokerConnectorSoakPromotionStatus = {
  schema_version: 'karkinos.broker_connector_soak_promotion_status.v1';
  contract_status: string;
  connector_count: number;
  connectors: BrokerConnectorSoakPromotionConnector[];
  promotion_ready: boolean;
  promotion_blockers: string[];
  owner_acceptance_recorded: boolean;
  account_truth_reconciliation_linked: boolean;
  runtime_execution_authority: string;
  broker_submission_enabled: boolean;
  automatic_promotion_enabled: boolean;
};

export type SignedBrokerAdapterReleaseReviewDecision =
  'accepted' | 'rejected' | 'revoked';

export type SignedBrokerAdapterReleaseReviewDossierRequest = {
  manifest: Record<string, unknown>;
  source_name: string;
  review_id: string;
  decision: SignedBrokerAdapterReleaseReviewDecision;
  reviewed_at: string;
  reason_ref: string;
};

export type SignedBrokerAdapterReleaseReviewStatus = {
  schema_version: 'karkinos.signed_broker_adapter_release_review_status.v1';
  contract_status: string;
  recorded_manifest_count: number;
  recorded_review_count: number;
  supported_decisions: SignedBrokerAdapterReleaseReviewDecision[];
  operator_signature_required: true;
  review_store_available: boolean;
  provider_contact_performed: false;
  adapter_registered: false;
  broker_submission_enabled: false;
  broker_cancellation_enabled: false;
  capital_authority_changed: false;
  authorizes_execution: false;
};

export type SignedBrokerAdapterReleaseCurrentReview = {
  status: string;
  review_id?: string;
  release_evidence_ref: string;
  manifest_fingerprint?: string;
  decision?: SignedBrokerAdapterReleaseReviewDecision;
  reviewer_ref?: string;
  reviewed_at?: string;
  reason_ref?: string;
  conformance_run_id?: string;
  conformance_report_fingerprint?: string;
  review_fingerprint: string;
  integrity_blockers: string[];
  persisted?: true;
  reused?: boolean;
  created_at?: string;
};

export type SignedBrokerAdapterReleaseReviewListItem = {
  schema_version: 'karkinos.signed_broker_adapter_release_review_list.v1';
  release_evidence_ref: string;
  manifest_fingerprint: string;
  manifest: Record<string, unknown>;
  current_review: SignedBrokerAdapterReleaseCurrentReview;
  blockers: string[];
  reviewable: boolean;
  provider_contact_performed: false;
  adapter_registered: false;
  authorizes_execution: false;
};

export type SignedBrokerAdapterReleaseReviewDossier = {
  schema_version: 'karkinos.signed_broker_adapter_release_review_dossier.v1';
  action: 'review_broker_adapter_release';
  review_id: string;
  decision: SignedBrokerAdapterReleaseReviewDecision;
  reviewed_at: string;
  reason_ref: string;
  manifest: Record<string, unknown>;
  manifest_fingerprint: string;
  manifest_evidence: {
    file_fingerprint: string;
    source_name: string;
    validation_status: string;
    recordable: boolean;
    blockers: string[];
    record_blockers: string[];
  };
  current_review: SignedBrokerAdapterReleaseCurrentReview;
  conformance: {
    status: string;
    run_id?: string;
    report_fingerprint?: string;
    blockers: string[];
  };
  dossier_fingerprint: string;
  generated_at: string;
  review_status: 'ready_for_signature' | 'blocked';
  review_ready: boolean;
  review_blockers: string[];
  required_operator_approval: {
    action: 'review_broker_adapter_release';
    artifact_type: 'broker_adapter_release_review_dossier';
    artifact_fingerprint: string;
  };
  provider_contact_performed: false;
  adapter_registered: false;
  broker_submission_enabled: false;
  broker_cancellation_enabled: false;
  capital_authority_changed: false;
  authorizes_execution: false;
};

export type SignedBrokerAdapterReleaseReviewRecord = {
  schema_version: 'karkinos.broker_adapter_release_review.v1';
  status: SignedBrokerAdapterReleaseReviewDecision;
  review_id: string;
  release_evidence_ref: string;
  manifest_fingerprint: string;
  decision: SignedBrokerAdapterReleaseReviewDecision;
  reviewer_ref: string;
  reviewed_at: string;
  reason_ref: string;
  conformance_run_id: string;
  conformance_report_fingerprint: string;
  review_fingerprint: string;
  dossier_fingerprint: string;
  operator_id: string;
  operator_key_id: string;
  operator_public_key_fingerprint: string;
  operator_approval_id: string;
  operator_identity_verified: true;
  persisted: true;
  reused: boolean;
  created_at: string;
  provider_contact_performed: false;
  adapter_registered: false;
  broker_submission_enabled: false;
  broker_cancellation_enabled: false;
  capital_authority_changed: false;
  authorizes_execution: false;
};

export type ControlledBrokerWriteReleaseOwnerReviewRefs = {
  broker_agreement_review: string;
  account_permissions_review: string;
  program_trading_reporting_review: string;
  provider_acceptance_test_report: string;
  deployment_authorization: string;
  risk_controls_review: string;
  rollback_drill_review: string;
};

export type ControlledBrokerWriteReleaseDossierRequest = {
  execution_edge_manifest: Record<string, unknown>;
  readonly_release_evidence_ref: string;
  soak_acceptance_id: string;
  effective_at: string;
  expires_at: string;
  owner_review_refs: ControlledBrokerWriteReleaseOwnerReviewRefs;
};

export type ControlledBrokerWriteReleaseDossier = {
  schema_version: 'karkinos.controlled_broker_write_release_dossier.v1';
  dossier_fingerprint: string;
  generated_at: string;
  review_status: 'ready_for_signature' | 'blocked';
  review_ready: boolean;
  review_blockers: string[];
  scope: {
    provider: string;
    gateway_id: string;
    account_alias: string;
    connector_id: string;
  };
  readonly_adapter_release: {
    release_evidence_ref?: string;
    manifest_fingerprint?: string;
    status?: string;
  };
  soak_promotion: {
    connector_id: string;
    account_alias: string;
    dossier_fingerprint: string;
    acceptance_id: string;
    promotion_ready: boolean;
  };
  effective_at: string;
  expires_at: string;
  execution_mode: 'manual_each_order';
  required_operator_approval: {
    action: 'issue_controlled_broker_write_release';
    artifact_type: 'controlled_broker_write_release_dossier';
    artifact_fingerprint: string;
  };
  provider_contact_performed: false;
  adapter_registered: false;
  broker_submission_performed: false;
  broker_cancellation_performed: false;
  capital_authority_changed: false;
};

export type ControlledBrokerWriteReleaseEvidence = {
  schema_version: 'karkinos.controlled_broker_write_release.v1';
  status: 'current_clear_signed_release' | 'blocked' | string;
  release_evidence_id: string;
  evidence_fingerprint: string;
  provider: string;
  gateway_id: string;
  account_alias: string;
  execution_edge_ref?: string;
  readonly_release_evidence_ref?: string;
  soak_acceptance_id?: string;
  operator_id?: string;
  operator_identity_verified?: boolean;
  execution_mode: 'manual_each_order';
  effective_at: string;
  expires_at: string;
  blockers?: string[];
  revoked?: boolean;
  authorizes_order_submission_by_itself: false;
  does_not_grant_capital_authority: true;
};

export type ControlledBrokerWriteReleaseStatus = {
  schema_version: 'karkinos.controlled_broker_write_release_status.v1';
  contract_status: string;
  recorded_release_count: number;
  active_release_count: number;
  active_release_ids: string[];
  maximum_release_seconds: number;
  supported_revocation_reasons: ControlledBrokerWriteReleaseRevocationReason[];
  release_provider_available: boolean;
  default_registered: false;
  gateway_registered: false;
  broker_contact_performed: false;
  broker_submission_performed: false;
  broker_cancellation_performed: false;
  automatic_execution_allowed: false;
  strategy_direct_submission_allowed: false;
  authorizes_order_submission_by_itself: false;
  does_not_grant_capital_authority: true;
};

export type ControlledBrokerWriteReleaseRecord =
  ControlledBrokerWriteReleaseEvidence & {
    status: 'recorded_expiring_manual_each_order_release' | string;
    dossier_fingerprint: string;
    operator_approval_id: string;
    created_at: string;
    persisted: true;
    reused: boolean;
  };

export type ControlledBrokerWriteReleaseRevocationReason =
  | 'adapter_or_deployment_changed'
  | 'incident_or_anomaly'
  | 'owner_disabled'
  | 'provider_scope_changed'
  | 'regulatory_or_permission_change'
  | 'scheduled_expiry_superseded';

export type ControlledBrokerWriteReleaseRevocationPreview = {
  schema_version: 'karkinos.controlled_broker_write_release_revocation.v1';
  action: 'revoke_controlled_broker_write_release';
  release_evidence_id: string;
  release_evidence_fingerprint: string;
  reason_code: ControlledBrokerWriteReleaseRevocationReason;
  revocation_fingerprint: string;
  status: 'ready_for_signature' | 'already_revoked' | 'blocked';
  ready: boolean;
  blockers: string[];
  required_operator_approval: {
    action: 'revoke_controlled_broker_write_release';
    artifact_type: 'controlled_broker_write_release_revocation';
    artifact_fingerprint: string;
  };
  broker_contact_performed: false;
  broker_submission_performed: false;
  broker_cancellation_performed: false;
  capital_authority_changed: false;
  resume_enabled: false;
};

export type ControlledBrokerWriteReleaseRevocation = {
  schema_version: 'karkinos.controlled_broker_write_release_revocation.v1';
  release_evidence_id: string;
  release_evidence_fingerprint: string;
  reason_code: ControlledBrokerWriteReleaseRevocationReason;
  revocation_fingerprint: string;
  revocation_id: string;
  operator_id: string;
  operator_approval_id: string;
  status: 'revoked';
  created_at: string;
  persisted: true;
  reused: boolean;
  resume_enabled: false;
};

export function useBrokerConnectorSoakPromotionStatusQuery() {
  return useQuery({
    queryKey: ['broker-soak', 'promotion', 'status'],
    queryFn: () =>
      apiClient<BrokerConnectorSoakPromotionStatus>(
        '/api/automation/broker-soak/promotion/status',
      ),
    staleTime: 5_000,
    refetchInterval: liveOperationsRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useSignedBrokerAdapterReleaseReviewStatusQuery(
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['signed-broker-adapter-release-review', 'status'],
    queryFn: () =>
      apiClient<SignedBrokerAdapterReleaseReviewStatus>(
        '/api/automation/broker-adapter-release-review/status',
      ),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}

export function useSignedBrokerAdapterReleaseReviewsQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['signed-broker-adapter-release-review', 'releases'],
    queryFn: () =>
      apiClient<SignedBrokerAdapterReleaseReviewListItem[]>(
        '/api/automation/broker-adapter-release-review/releases?limit=100',
      ),
    enabled,
    staleTime: 2_000,
    refetchOnWindowFocus: true,
  });
}

export function useSignedBrokerAdapterReleaseReviewDossierPreviewMutation() {
  return useMutation({
    mutationFn: (request: SignedBrokerAdapterReleaseReviewDossierRequest) =>
      postJson<SignedBrokerAdapterReleaseReviewDossier>(
        '/api/automation/broker-adapter-release-review/dossiers/preview',
        request,
      ),
  });
}

export function useSignedBrokerAdapterReleaseReviewApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'review_broker_adapter_release';
      artifact_type: 'broker_adapter_release_review_dossier';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useSignedBrokerAdapterReleaseReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      request: SignedBrokerAdapterReleaseReviewDossierRequest & {
        dossier_fingerprint: string;
        operator_label: string;
        operator_approval_id: string;
        operator_proof_signature_base64: string;
        acknowledgement: 'review_broker_adapter_release_without_registration_or_execution_authority';
      },
    ) =>
      postJson<SignedBrokerAdapterReleaseReviewRecord>(
        '/api/automation/broker-adapter-release-review/reviews',
        request,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['signed-broker-adapter-release-review'],
        }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useControlledBrokerWriteReleaseStatusQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['controlled-broker-write-release', 'status'],
    queryFn: () =>
      apiClient<ControlledBrokerWriteReleaseStatus>(
        '/api/automation/controlled-broker-write-release/status',
      ),
    enabled,
    staleTime: 5_000,
    refetchOnWindowFocus: true,
  });
}

export function useControlledBrokerWriteReleasesQuery(enabled: boolean) {
  return useQuery({
    queryKey: ['controlled-broker-write-release', 'releases'],
    queryFn: () =>
      apiClient<ControlledBrokerWriteReleaseEvidence[]>(
        '/api/automation/controlled-broker-write-release/releases?limit=100',
      ),
    enabled,
    staleTime: 2_000,
    refetchOnWindowFocus: true,
  });
}

export function useControlledBrokerWriteReleaseDossierPreviewMutation() {
  return useMutation({
    mutationFn: (request: ControlledBrokerWriteReleaseDossierRequest) =>
      postJson<ControlledBrokerWriteReleaseDossier>(
        '/api/automation/controlled-broker-write-release/dossiers/preview',
        request,
      ),
  });
}

export function useControlledBrokerWriteReleaseApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action:
        | 'issue_controlled_broker_write_release'
        | 'revoke_controlled_broker_write_release';
      artifact_type:
        | 'controlled_broker_write_release_dossier'
        | 'controlled_broker_write_release_revocation';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledBrokerWriteReleaseIssueMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      request: ControlledBrokerWriteReleaseDossierRequest & {
        dossier_fingerprint: string;
        operator_label: string;
        operator_approval_id: string;
        operator_proof_signature_base64: string;
        acknowledgement: 'issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority';
      },
    ) =>
      postJson<ControlledBrokerWriteReleaseRecord>(
        '/api/automation/controlled-broker-write-release/releases',
        request,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['controlled-broker-write-release'],
        }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useControlledBrokerWriteReleaseRevocationPreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      releaseId: string;
      reason_code: ControlledBrokerWriteReleaseRevocationReason;
    }) => {
      const { releaseId, ...body } = request;
      return postJson<ControlledBrokerWriteReleaseRevocationPreview>(
        `/api/automation/controlled-broker-write-release/releases/${encodeURIComponent(
          releaseId,
        )}/revocation/preview`,
        body,
      );
    },
  });
}

export function useControlledBrokerWriteReleaseRevocationMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      releaseId: string;
      reason_code: ControlledBrokerWriteReleaseRevocationReason;
      revocation_fingerprint: string;
      operator_label: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'revoke_exact_broker_write_release_without_resume_or_broker_action';
    }) => {
      const { releaseId, ...body } = request;
      return postJson<ControlledBrokerWriteReleaseRevocation>(
        `/api/automation/controlled-broker-write-release/releases/${encodeURIComponent(
          releaseId,
        )}/revocations`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['controlled-broker-write-release'],
        }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}
