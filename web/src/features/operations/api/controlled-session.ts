import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';

export type ControlledExecutionOperatorSession = {
  session_id: string;
  reservation_id: string;
  authorization_id: string;
  account_alias: string;
  strategy_id: string;
  status: string;
  persisted_status: string;
  is_current_window: boolean;
  effective_at: string;
  expires_at: string;
  authorized_capital: string | null;
  effective_capital_at_risk: string | null;
  remaining_budget: {
    capital_headroom: string | null;
    cash_headroom: string | null;
    turnover_headroom: string | null;
    remaining_order_slots: number;
    reserved_order_count: number;
    admitted_order_count: number;
  };
  allowed_symbols: string[];
  last_order: {
    order_id: string;
    admitted_at: string;
    admission_id: string;
    submission_status: string;
    submit_intent_id: string;
  };
  last_reconciliation: {
    run_id: string;
    run_status: string;
    item_status: string;
    suggested_action: string;
    updated_at: string;
  };
  latest_gate_snapshot: {
    snapshot_id: string;
    status: string;
    observed_at: string;
    blockers: string[];
  };
  pause: {
    status: string;
    pause_event_id: string;
    paused_at: string;
    reasons: string[];
    resume_available: false;
    replacement_review_required: boolean;
  };
  blockers: string[];
  runtime_authentication_evaluated: false;
  runtime_authority_granted: false;
  broker_submission_enabled: false;
};

export type ControlledSessionRevocationReason =
  | 'manual_operator_stop'
  | 'end_of_strategy_window'
  | 'operational_concern'
  | 'risk_review'
  | 'account_or_reconciliation_concern';

export type ControlledSessionRevocationPreview = {
  schema_version: 'karkinos.controlled_session_runtime_authority.v1';
  action: 'revoke_controlled_session';
  session_id: string;
  session_fingerprint: string;
  reservation_id: string;
  reason_code: ControlledSessionRevocationReason;
  revocation_fingerprint: string;
  revocation_id: string;
  status: 'ready_for_signed_revocation' | 'blocked';
  ready: boolean;
  already_revoked: boolean;
  blockers: string[];
  required_operator_approval: {
    action: 'revoke_controlled_session';
    artifact_type: 'controlled_session_revocation';
    artifact_fingerprint: string;
  };
  broker_submission_enabled: false;
};

export type ControlledSessionRevocationResult = {
  schema_version: 'karkinos.controlled_session_runtime_authority.v1';
  action: 'revoke_controlled_session';
  revocation_id: string;
  revocation_fingerprint: string;
  session_id: string;
  session_fingerprint: string;
  reservation_id: string;
  reason_code: ControlledSessionRevocationReason;
  operator_id: string;
  operator_approval_id: string;
  status: 'revoked';
  automatic_resume_enabled: false;
  broker_submission_enabled: false;
  persisted: true;
  reused: boolean;
  revoked_at: string;
  current_session: {
    session_id: string;
    status: 'revoked';
    automatic_resume_enabled: false;
    broker_submission_enabled: false;
  };
};

export type ControlledOrderJourneyStage = {
  key:
    | 'controlled_submission'
    | 'controlled_submission_rejection_review'
    | 'execution_reconciliation'
    | 'terminal_reconciliation_clearance'
    | 'reconciled_ledger_posting'
    | 'append_only_ledger_correction'
    | 'post_ledger_account_truth';
  status: string;
  evidence_id: string;
  complete: boolean;
  required: boolean;
  terminal_status?: string;
  fill_count?: number;
  fill_quantity?: string;
  cancelled_quantity?: string;
  ledger_entry_count?: number;
  post_ledger_cutoff_id?: number;
  reason_code?: string;
  reviewer_id?: string;
  reviewed_at?: string;
  review_fingerprint?: string;
  account_truth_gate_status?: string;
  ledger_coverage_status?: string;
  source_fingerprint?: string;
  captured_at?: string;
  blockers?: string[];
};

export type ControlledOrderJourney = {
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  client_order_id: string;
  gateway_id: string;
  status: string;
  next_operator_action: string;
  attention_required: boolean;
  attention_severity: 'critical' | 'warning' | 'none';
  blocks_new_submissions: boolean;
  prepared_at: string;
  updated_at: string;
  last_recovery_at: string;
  stages: ControlledOrderJourneyStage[];
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  broker_submission_performed: false;
  broker_cancel_performed: false;
  ledger_mutation_performed: false;
  authority_changed: false;
};

export type ControlledExecutionOperatorView = {
  schema_version:
    | 'karkinos.controlled_execution_operator_view.v3'
    | 'karkinos.controlled_execution_operator_view.v4';
  as_of: string;
  status: string;
  next_operator_action: string;
  session_count: number;
  visible_session_count: number;
  current_window_session_count: number;
  blocked_current_session_count: number;
  paused_session_count: number;
  sessions: ControlledExecutionOperatorSession[];
  latest_submission: Record<string, unknown> | null;
  latest_reconciliation: Record<string, unknown> | null;
  order_journey_count: number;
  visible_order_journey_count: number;
  latest_order_journey: ControlledOrderJourney | null;
  recent_order_journeys: ControlledOrderJourney[];
  attention_order_journey_count: number;
  visible_attention_order_journey_count: number;
  attention_queue_truncated: boolean;
  primary_attention_order_journey: ControlledOrderJourney | null;
  attention_order_journeys: ControlledOrderJourney[];
  source_blockers: string[];
  reads_persisted_facts_only: true;
  provider_contact_performed: false;
  runtime_connector_query_performed: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  authority_issue_enabled: false;
  authority_renew_enabled: false;
  authority_resume_enabled: false;
  automatic_scale_up_enabled: false;
  does_not_mutate_account_truth: true;
  does_not_mutate_oms: true;
  does_not_mutate_production_ledger: true;
  limitations: string[];
};

export function useControlledSessionRevocationPreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      sessionId: string;
      reason_code: ControlledSessionRevocationReason;
    }) => {
      const { sessionId, ...body } = request;
      return postJson<ControlledSessionRevocationPreview>(
        `/api/automation/controlled-sessions/runtime-authority/sessions/${encodeURIComponent(
          sessionId,
        )}/revocation/preview`,
        body,
      );
    },
  });
}

export function useControlledSessionRevocationApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'revoke_controlled_session';
      artifact_type: 'controlled_session_revocation';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledSessionRevocationMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      sessionId: string;
      reason_code: ControlledSessionRevocationReason;
      revocation_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'revoke_exact_controlled_session_no_auto_resume';
    }) => {
      const { sessionId, ...body } = request;
      return postJson<ControlledSessionRevocationResult>(
        `/api/automation/controlled-sessions/runtime-authority/sessions/${encodeURIComponent(
          sessionId,
        )}/revocations`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}
