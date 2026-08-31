import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';

export type ControlledSubmissionClearanceFill = {
  fill_id: string;
  broker_event_id: string;
  account_truth_import_run_id: string;
  timestamp: string;
  symbol: string;
  side: string;
  asset_class: string;
  fill_price: string;
  fill_quantity: string;
  fee: string;
  tax: string;
  transfer_fee: string;
  provider_name: string;
};

export type ControlledSubmissionClearancePreview = {
  schema_version: string;
  clearance_id: string;
  clearance_fingerprint: string;
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  client_order_id: string;
  review_reconciliation_run_id: string;
  broker_evidence_fingerprint: string;
  account_truth_import_run_id: string;
  terminal_status: string;
  terminal_evidence_source: string;
  lifecycle_observation_id: string;
  lifecycle_evidence_fingerprint: string;
  operator_id: string;
  fill_count: number;
  fill_quantity: string;
  cancelled_quantity: string;
  fills: ControlledSubmissionClearanceFill[];
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'clear_controlled_submission_reconciliation';
    artifact_type: 'controlled_submission_reconciliation_clearance';
    artifact_fingerprint: string;
  };
  interlock_released: false;
  oms_mutated: false;
  production_ledger_mutated: false;
};

export type ControlledSubmissionClearanceResult = {
  clearance_id: string;
  clearance_fingerprint: string;
  submit_intent_id: string;
  order_id: string;
  status: 'cleared';
  terminal_status: string;
  fill_count: number;
  fill_quantity: string;
  cancelled_quantity: string;
  cleared_at: string;
  persisted: true;
  reused: boolean;
  interlock_released: true;
  oms_terminal_status: string;
  real_fills_recorded: boolean;
  terminal_outcome_recorded: true;
  production_ledger_mutated: false;
  automatic_submission_enabled: false;
  strategy_direct_submission_enabled: false;
};

export function useControlledSubmissionClearancePreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      reconciliation_run_id: string;
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledSubmissionClearancePreview>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/reconciliation-clearance/preview`,
        body,
      );
    },
  });
}

export function useControlledSubmissionClearanceApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'clear_controlled_submission_reconciliation';
      artifact_type: 'controlled_submission_reconciliation_clearance';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledSubmissionClearanceApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      submitIntentId: string;
      reconciliation_run_id: string;
      clearance_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'clear_exact_terminal_outcome_without_automatic_ledger_mutation';
    }) => {
      const { submitIntentId, ...body } = request;
      return postJson<ControlledSubmissionClearanceResult>(
        `/api/automation/controlled-broker-submission/intents/${encodeURIComponent(
          submitIntentId,
        )}/reconciliation-clearances`,
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
