import { useMemo, useState } from 'react';

import {
  useControlledSubmissionClearanceApplyMutation,
  useControlledSubmissionClearanceApprovalChallengeMutation,
  useControlledSubmissionClearancePreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
} from './api';
import {
  controlledTerminalClearanceContext,
  type ControlledTerminalClearanceOperatorPanelProps,
} from './controlled-terminal-clearance-operator-model';

export function useControlledTerminalClearanceOperatorController({
  journey,
  locale,
}: ControlledTerminalClearanceOperatorPanelProps) {
  const [open, setOpen] = useState(false);
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const { reconciliationRunId, actionable } =
    controlledTerminalClearanceContext(journey);

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledSubmissionClearancePreviewMutation();
  const challenge = useControlledSubmissionClearanceApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyClearance = useControlledSubmissionClearanceApplyMutation();
  const eligibleIdentities = useMemo(
    () =>
      (approvalStatus.data?.trusted_identities ?? []).filter(
        (identity) =>
          identity.enabled &&
          (!preview.data?.operator_id ||
            identity.operator_id === preview.data.operator_id),
      ),
    [approvalStatus.data?.trusted_identities, preview.data?.operator_id],
  );
  const effectiveKeyId = selectedKeyId || eligibleIdentities[0]?.key_id || '';
  const selectedIdentity = eligibleIdentities.find(
    (identity) => identity.key_id === effectiveKeyId,
  );

  const resetSignatureSteps = () => {
    challenge.reset();
    verification.reset();
    applyClearance.reset();
    setSignature('');
    setAcknowledged(false);
  };

  const close = () => {
    setOpen(false);
    setSelectedKeyId('');
    preview.reset();
    resetSignatureSteps();
  };

  const loadPreview = () => {
    preview.reset();
    resetSignatureSteps();
    preview.mutate({
      submitIntentId: journey.submit_intent_id,
      reconciliation_run_id: reconciliationRunId,
    });
  };

  const createChallenge = () => {
    const required = preview.data?.required_operator_approval;
    if (!required || !selectedIdentity) {
      return;
    }
    resetSignatureSteps();
    challenge.mutate({
      operator_id: selectedIdentity.operator_id,
      key_id: selectedIdentity.key_id,
      action: required.action,
      artifact_type: required.artifact_type,
      artifact_fingerprint: required.artifact_fingerprint,
      ttl_seconds: 180,
    });
  };

  const verifySignature = () => {
    if (!challenge.data || !signature.trim()) {
      return;
    }
    verification.reset();
    applyClearance.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const apply = () => {
    if (!preview.data || !verification.data || !acknowledged) {
      return;
    }
    applyClearance.mutate({
      submitIntentId: journey.submit_intent_id,
      reconciliation_run_id: reconciliationRunId,
      clearance_fingerprint: preview.data.clearance_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement:
        'clear_exact_terminal_outcome_without_automatic_ledger_mutation',
    });
  };

  const selectKey = (keyId: string) => {
    setSelectedKeyId(keyId);
    resetSignatureSteps();
  };

  const updateSignature = (value: string) => {
    setSignature(value);
    verification.reset();
    applyClearance.reset();
    setAcknowledged(false);
  };

  return {
    journey,
    locale,
    reconciliationRunId,
    actionable,
    open,
    openPanel: () => setOpen(true),
    close,
    approvalStatus,
    preview,
    challenge,
    verification,
    applyClearance,
    eligibleIdentities,
    effectiveKeyId,
    selectedIdentity,
    signature,
    acknowledged,
    setAcknowledged,
    loadPreview,
    createChallenge,
    verifySignature,
    apply,
    selectKey,
    updateSignature,
  };
}

export type ControlledTerminalClearanceOperatorController = ReturnType<
  typeof useControlledTerminalClearanceOperatorController
>;
