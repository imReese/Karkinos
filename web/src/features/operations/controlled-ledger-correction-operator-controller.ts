import { useMemo, useState } from 'react';

import {
  useControlledLedgerCorrectionApplyMutation,
  useControlledLedgerCorrectionApprovalChallengeMutation,
  useControlledLedgerCorrectionPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type ControlledLedgerCorrectionReason,
} from './api';
import {
  controlledLedgerCorrectionContext,
  type ControlledLedgerCorrectionOperatorPanelProps,
} from './controlled-ledger-correction-operator-model';

export function useControlledLedgerCorrectionOperatorController({
  journey,
  locale,
}: ControlledLedgerCorrectionOperatorPanelProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ControlledLedgerCorrectionReason | ''>(
    '',
  );
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const { actionable, postingId } = controlledLedgerCorrectionContext(journey);
  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledLedgerCorrectionPreviewMutation();
  const challenge = useControlledLedgerCorrectionApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyCorrection = useControlledLedgerCorrectionApplyMutation();
  const eligibleIdentities = useMemo(
    () =>
      (approvalStatus.data?.trusted_identities ?? []).filter(
        (identity) => identity.enabled,
      ),
    [approvalStatus.data?.trusted_identities],
  );
  const effectiveKeyId = selectedKeyId || eligibleIdentities[0]?.key_id || '';
  const selectedIdentity = eligibleIdentities.find(
    (identity) => identity.key_id === effectiveKeyId,
  );

  const resetSignatureSteps = () => {
    challenge.reset();
    verification.reset();
    applyCorrection.reset();
    setSignature('');
    setAcknowledged(false);
  };

  const resetAfterInputs = () => {
    preview.reset();
    resetSignatureSteps();
  };

  const close = () => {
    setOpen(false);
    setReason('');
    setSelectedKeyId('');
    resetAfterInputs();
  };

  const changeReason = (value: ControlledLedgerCorrectionReason | '') => {
    setReason(value);
    resetAfterInputs();
  };

  const selectKey = (keyId: string) => {
    setSelectedKeyId(keyId);
    resetAfterInputs();
  };

  const loadPreview = () => {
    if (!reason || !selectedIdentity) {
      return;
    }
    resetAfterInputs();
    preview.mutate({
      postingId,
      reason_code: reason,
      operator_id: selectedIdentity.operator_id,
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

  const changeSignature = (value: string) => {
    setSignature(value);
    verification.reset();
    applyCorrection.reset();
    setAcknowledged(false);
  };

  const verifySignature = () => {
    if (!challenge.data || !signature.trim()) {
      return;
    }
    verification.reset();
    applyCorrection.reset();
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
    applyCorrection.mutate({
      postingId,
      reason_code: preview.data.reason_code,
      operator_id: preview.data.operator_id,
      correction_fingerprint: preview.data.correction_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement: 'apply_exact_compensating_ledger_correction_once',
    });
  };

  return {
    acknowledged,
    actionable,
    apply,
    applyCorrection,
    challenge,
    changeReason,
    changeSignature,
    close,
    createChallenge,
    effectiveKeyId,
    eligibleIdentities,
    journey,
    loadPreview,
    locale,
    open,
    openPanel: () => setOpen(true),
    postingId,
    preview,
    reason,
    selectKey,
    selectedIdentity,
    setAcknowledged,
    signature,
    verification,
    verifySignature,
    approvalStatus,
  };
}

export type ControlledLedgerCorrectionOperatorController = ReturnType<
  typeof useControlledLedgerCorrectionOperatorController
>;
