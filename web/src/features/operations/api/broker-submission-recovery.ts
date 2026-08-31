import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';

export type ControlledBrokerRecoveryPreview = {
  schema_version: string;
  submit_intent_id: string;
  submit_fingerprint: string;
  recovery_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  gateway_id: string;
  client_order_id: string;
  operator_id: string;
  source_status: string;
  source_result_fingerprint: string;
  prepared_at: string;
  last_recovery_at: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  recovery_wait_remaining_seconds: number;
  gateway_query_capability: boolean;
  required_operator_approval?: {
    action: 'query_unknown_controlled_broker_submission';
    artifact_type: 'controlled_broker_submission_recovery';
    artifact_fingerprint: string;
  };
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_query_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  production_ledger_mutated: false;
  authority_changed: false;
};

export type ControlledBrokerRecoveryResult = {
  submit_intent_id: string;
  recovery_fingerprint: string;
  recovery_operator_approval_id: string;
  recovery_claim_id: string;
  status: string;
  broker_order_id: string;
  broker_status: string;
  recovery_query_performed: boolean;
  external_call_performed: boolean;
  recovery_resubmission_enabled: false;
  production_ledger_mutated: false;
};

export type ManualBrokerCancellationSafety = {
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  cancellation_proven: false;
  oms_mutated: false;
  production_ledger_mutated: false;
  risk_state_mutated: false;
  kill_switch_mutated: false;
  capital_authority_changed: false;
  authorizes_submission: false;
  authorizes_cancellation: false;
  releases_submission_interlock: false;
};

export type ManualBrokerCancellationTicketPreview = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket.v1';
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  provider: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    broker_order_id: string;
    client_order_id: string;
  };
  order: {
    symbol: string;
    side: string;
    asset_class: string;
    order_type: string;
    limit_price: string | null;
    order_quantity: string;
    lifecycle_status: string;
    filled_quantity: string;
    cancelled_quantity: string;
    remaining_quantity: string;
  };
  lifecycle_evidence: {
    observation_id: string;
    evidence_fingerprint: string;
    source_sequence: number;
    captured_at: string;
    source_name: string;
    collector_run_id: string;
    collector_status: string;
  };
  ticket_fingerprint: string;
  generated_at: string;
  status: string;
  ready: boolean;
  blockers: string[];
  required_acknowledgement: 'prepare_manual_broker_cancellation_ticket_without_broker_contact';
  human_steps: string[];
  assumptions: string[];
  risk_impact: string;
  safety: ManualBrokerCancellationSafety;
  limitations: string[];
};

export type ManualBrokerCancellationTicketExport = {
  schema_version: 'karkinos.manual_broker_cancellation_ticket_export.v1';
  status: 'export_ready';
  ticket_fingerprint: string;
  export_fingerprint: string;
  filename: string;
  content_type: 'application/json';
  content: string;
  artifact: Record<string, unknown>;
  export_performed: true;
  safety: ManualBrokerCancellationSafety;
};

export type ControlledBrokerRejectionSafety = {
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_query_performed: false;
  broker_submission_performed: false;
  broker_retry_performed: false;
  broker_cancel_performed: false;
  oms_mutated: false;
  production_ledger_mutated: false;
  account_truth_mutated: false;
  risk_state_mutated: false;
  kill_switch_mutated: false;
  capital_authority_changed: false;
  authorizes_submission: false;
  authorizes_retry: false;
  authorizes_cancellation: false;
  releases_submission_interlock: false;
};

export type ControlledBrokerRejectionEvidencePreview = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence.v1';
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    client_order_id: string;
    operator_id: string;
  };
  order: {
    symbol: string;
    side: string;
    asset_class: string;
    quantity: string;
    order_type: string;
    limit_price: string | null;
  };
  rejection_evidence: {
    classification: string;
    intent_status: string;
    broker_status: string;
    result_status: string;
    submitted: boolean | null;
    definitive: boolean;
    error_type: string;
    reason_codes: string[];
    result_fingerprint: string;
    prepared_at: string;
    evidence_as_of: string;
  };
  retry_policy: {
    same_intent_retry_allowed: false;
    same_client_order_id_retry_allowed: false;
    automatic_retry_allowed: false;
    new_order_requires_new_decision_and_all_gates: true;
  };
  review_fingerprint: string;
  generated_at: string;
  status: string;
  ready: boolean;
  blockers: string[];
  required_acknowledgement: 'export_exact_rejection_evidence_without_retry_or_authority_change';
  human_steps: string[];
  assumptions: string[];
  risk_impact: string;
  safety: ControlledBrokerRejectionSafety;
  limitations: string[];
};

export type ControlledBrokerRejectionEvidenceExport = {
  schema_version: 'karkinos.controlled_broker_rejection_evidence_export.v1';
  status: 'export_ready';
  review_fingerprint: string;
  export_fingerprint: string;
  filename: string;
  content_type: 'application/json';
  content: string;
  artifact: Record<string, unknown>;
  export_performed: true;
  safety: ControlledBrokerRejectionSafety;
};

export type ControlledBrokerRejectionReview = {
  schema_version: 'karkinos.controlled_broker_rejection_review.v1';
  review_id: string;
  review_fingerprint: string;
  submit_intent_id: string;
  submit_fingerprint: string;
  order_id: string;
  order_fingerprint: string;
  result_fingerprint: string;
  identity: {
    gateway_id: string;
    account_alias: string;
    client_order_id: string;
    operator_id: string;
  };
  reviewer_id: string;
  disposition: 'acknowledged_no_retry';
  rejection_classification: string;
  evidence_as_of: string;
  recorded_at: string;
  operator_acknowledgement: 'record_exact_rejection_review_without_retry_or_authority_change';
  retry_policy: {
    same_intent_retry_allowed: false;
    same_client_order_id_retry_allowed: false;
    automatic_retry_allowed: false;
    new_order_requires_new_decision_and_all_gates: true;
  };
  status: 'recorded' | 'already_recorded';
  reused: boolean;
  review_recorded: true;
  record_performed: boolean;
  safety: ControlledBrokerRejectionSafety;
  limitations: string[];
};

export function useControlledBrokerRecoveryPreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ControlledBrokerRecoveryPreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/recovery/preview`,
      ),
  });
}

export function useManualBrokerCancellationTicketPreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ManualBrokerCancellationTicketPreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/manual-cancellation-ticket/preview`,
      ),
  });
}

export function useManualBrokerCancellationTicketExportMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      ticket_fingerprint: string;
      acknowledgement: 'prepare_manual_broker_cancellation_ticket_without_broker_contact';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ManualBrokerCancellationTicketExport>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/manual-cancellation-ticket/export`,
        body,
      );
    },
  });
}

export function useControlledBrokerRejectionEvidencePreviewMutation() {
  return useMutation({
    mutationFn: ({ submitIntentId }: { submitIntentId: string }) =>
      postJson<ControlledBrokerRejectionEvidencePreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-evidence/preview`,
      ),
  });
}

export function useControlledBrokerRejectionEvidenceExportMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      review_fingerprint: string;
      acknowledgement: 'export_exact_rejection_evidence_without_retry_or_authority_change';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRejectionEvidenceExport>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-evidence/export`,
        body,
      );
    },
  });
}

export function useControlledBrokerRejectionReviewMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      review_fingerprint: string;
      reviewer_id: string;
      disposition: 'acknowledged_no_retry';
      acknowledgement: 'record_exact_rejection_review_without_retry_or_authority_change';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRejectionReview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/rejection-reviews`,
        body,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['automation', 'cockpit'],
      });
    },
  });
}

export function useControlledBrokerRecoveryApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'query_unknown_controlled_broker_submission';
      artifact_type: 'controlled_broker_submission_recovery';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledBrokerRecoveryApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      recovery_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'query_exact_unknown_submission_once_without_resubmit';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledBrokerRecoveryResult>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/recoveries`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({
          queryKey: ['execution-reconciliation', 'runs'],
        }),
      ]);
    },
  });
}
