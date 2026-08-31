import { useMutation, useQueryClient } from '@tanstack/react-query';

import { postJson } from '../../../shared/api/client';
import type { OperatorApprovalChallenge } from './operator-approval';

export type ControlledLedgerPostingEntry = {
  fill_id: string;
  broker_event_id: string;
  entry_type: string;
  timestamp: string;
  settled_at: string;
  symbol: string;
  direction: string;
  quantity: string;
  price: string;
  amount: string;
  commission: string;
  gross_amount: string;
  net_cash_impact: string;
  fee_breakdown: {
    commission: string;
    stamp_tax: string;
    transfer_fee: string;
    other_fees: string;
    total_fee: string;
    confirmation_source: string;
  };
  asset_class: string;
  source: string;
  source_ref: string;
  settlement_status: string;
  settlement_source: string;
  account_truth_import_run_id: string;
};

export type ControlledLedgerPostingPreview = {
  schema_version: string;
  posting_id: string;
  posting_fingerprint: string;
  clearance_id: string;
  submit_intent_id: string;
  order_id: string;
  broker_order_id: string;
  terminal_status: string;
  operator_id: string;
  ledger_entry_count: number;
  ledger_entries: ControlledLedgerPostingEntry[];
  pre_valuation_snapshot_id: string;
  pre_ledger_cutoff_id: number;
  account_truth_import_run_id: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'post_controlled_submission_ledger';
    artifact_type: 'controlled_submission_ledger_posting';
    artifact_fingerprint: string;
  };
  production_ledger_mutated: false;
};

export type ControlledLedgerPostingResult = {
  posting_id: string;
  posting_fingerprint: string;
  clearance_id: string;
  order_id: string;
  status: 'applied';
  ledger_entry_count: number;
  ledger_entry_ids: number[];
  pre_ledger_cutoff_id: number;
  post_ledger_cutoff_id: number;
  applied_at: string;
  post_apply_status:
    | 'reconciled'
    | 'post_apply_review_required'
    | 'valuation_publication_recovery_required';
  post_valuation_publication_status: 'published' | 'publication_failed';
  post_valuation_publication_recovery_required: boolean;
  post_valuation_snapshot_id: string;
  persisted: true;
  reused: boolean;
  production_ledger_mutated: boolean;
  automatic_posting_enabled: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  capital_authority_changed: false;
};

function isControlledLedgerPostingValuationPublished(
  result: ControlledLedgerPostingResult | undefined,
) {
  return Boolean(
    result &&
    result.post_apply_status !== 'valuation_publication_recovery_required' &&
    result.post_valuation_publication_status === 'published' &&
    !result.post_valuation_publication_recovery_required &&
    result.post_valuation_snapshot_id,
  );
}

export type ControlledLedgerCorrectionReason =
  | 'broker_evidence_superseded'
  | 'duplicate_controlled_posting'
  | 'operator_confirmed_mapping_error';

export type ControlledLedgerCorrectionPositionState = {
  quantity: string;
  available_qty: string;
  frozen_qty: string;
  avg_cost: string;
  realized_pnl: string;
  commission_paid: string;
  broker_displayed_cost_basis: string;
  broker_displayed_unit_cost: string;
  broker_cost_basis_difference: string;
  broker_cost_basis_method: string;
  broker_cost_basis_status: string;
};

export type ControlledLedgerCorrectionPlan = {
  schema_version: string;
  posting_id: string;
  original_ledger_entry_ids: number[];
  effective_at: string;
  symbol: string;
  asset_class: string;
  cash_delta: string;
  total_deposits_delta: '0';
  position_before: ControlledLedgerCorrectionPositionState;
  position_after: ControlledLedgerCorrectionPositionState;
  derivation: 'canonical_replay_excluding_exact_original_posting_entries';
  arbitrary_financial_input_used: false;
};

export type ControlledLedgerCorrectionPreview = {
  schema_version: string;
  action: 'reverse_controlled_submission_ledger_posting';
  posting_id: string;
  posting_fingerprint: string;
  original_ledger_entry_ids: number[];
  original_ledger_entry_fingerprint: string;
  reason_code: ControlledLedgerCorrectionReason;
  operator_id: string;
  account_truth_import_run_id: string;
  pre_valuation_snapshot_id: string;
  pre_valuation_as_of: string;
  pre_valuation_status: string;
  pre_ledger_cutoff_id: number;
  pre_ledger_fingerprint: string;
  plan_fingerprint: string;
  correction_plan: ControlledLedgerCorrectionPlan;
  correction_id: string;
  correction_fingerprint: string;
  generated_at: string;
  review_status: string;
  review_ready: boolean;
  blockers: string[];
  required_operator_approval?: {
    action: 'reverse_controlled_submission_ledger_posting';
    artifact_type: 'controlled_submission_ledger_correction';
    artifact_fingerprint: string;
  };
  production_ledger_mutated: false;
};

export type ControlledLedgerCorrectionResult = {
  correction_id: string;
  correction_fingerprint: string;
  posting_id: string;
  status: 'applied';
  reason_code: ControlledLedgerCorrectionReason;
  original_ledger_entry_ids: number[];
  correction_ledger_entry_id: number;
  pre_ledger_cutoff_id: number;
  post_ledger_cutoff_id: number;
  applied_at: string;
  post_apply_status: 'account_truth_recheck_required';
  persisted: true;
  reused: boolean;
  production_ledger_mutated: true;
  original_ledger_entries_deleted: false;
  automatic_correction_enabled: false;
  broker_submission_enabled: false;
  broker_cancel_enabled: false;
  capital_authority_changed: false;
};

export function useControlledLedgerPostingPreviewMutation() {
  return useMutation({
    mutationFn: ({ clearanceId }: { clearanceId: string }) =>
      postJson<ControlledLedgerPostingPreview>(
        `/api/automation/controlled-ledger-posting/clearances/${encodeURIComponent(
          clearanceId,
        )}/preview`,
      ),
  });
}

export function useControlledLedgerCorrectionPreviewMutation() {
  return useMutation({
    mutationFn: (request: {
      postingId: string;
      reason_code: ControlledLedgerCorrectionReason;
      operator_id: string;
    }) => {
      const { postingId, ...body } = request;
      return postJson<ControlledLedgerCorrectionPreview>(
        `/api/automation/controlled-ledger-corrections/postings/${encodeURIComponent(
          postingId,
        )}/preview`,
        body,
      );
    },
  });
}

export function useControlledLedgerCorrectionApprovalChallengeMutation() {
  return useMutation({
    mutationFn: (request: {
      operator_id: string;
      key_id: string;
      action: 'reverse_controlled_submission_ledger_posting';
      artifact_type: 'controlled_submission_ledger_correction';
      artifact_fingerprint: string;
      ttl_seconds: number;
    }) =>
      postJson<OperatorApprovalChallenge>(
        '/api/automation/capital-authority/operator-approvals/challenges',
        request,
      ),
  });
}

export function useControlledLedgerPostingApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      clearanceId: string;
      posting_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'apply_exact_reconciled_ledger_posting_once';
    }) => {
      const { clearanceId, ...body } = request;
      return postJson<ControlledLedgerPostingResult>(
        `/api/automation/controlled-ledger-posting/clearances/${encodeURIComponent(
          clearanceId,
        )}/postings`,
        body,
      );
    },
    onSuccess: async (result) => {
      if (!isControlledLedgerPostingValuationPublished(result)) {
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
      ]);
    },
  });
}

export function useControlledLedgerCorrectionApplyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: {
      postingId: string;
      reason_code: ControlledLedgerCorrectionReason;
      operator_id: string;
      correction_fingerprint: string;
      operator_approval_id: string;
      operator_proof_signature_base64: string;
      acknowledgement: 'apply_exact_compensating_ledger_correction_once';
    }) => {
      const { postingId, ...body } = request;
      return postJson<ControlledLedgerCorrectionResult>(
        `/api/automation/controlled-ledger-corrections/postings/${encodeURIComponent(
          postingId,
        )}/corrections`,
        body,
      );
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['automation', 'cockpit'] }),
        queryClient.invalidateQueries({ queryKey: ['operations', 'today'] }),
        queryClient.invalidateQueries({ queryKey: ['account-overview'] }),
        queryClient.invalidateQueries({ queryKey: ['account-state'] }),
        queryClient.invalidateQueries({ queryKey: ['account-equity-curve'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-equity-curve-series'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-score'] }),
        queryClient.invalidateQueries({
          queryKey: ['account-truth-import-runs'],
        }),
        queryClient.invalidateQueries({ queryKey: ['account-truth-reports'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-risk-summary'] }),
        queryClient.invalidateQueries({
          queryKey: ['portfolio-explainability'],
        }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-positions'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-allocation'] }),
        queryClient.invalidateQueries({ queryKey: ['portfolio-snapshot'] }),
        queryClient.invalidateQueries({
          queryKey: ['portfolio-live-holdings'],
        }),
        queryClient.invalidateQueries({ queryKey: ['ledger-entries'] }),
      ]);
    },
  });
}
