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
