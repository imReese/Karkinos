import { useMemo, useState } from 'react';

import {
  useControlledLedgerPostingApplyMutation,
  useControlledLedgerPostingPreviewMutation,
  useOperatorApprovalChallengeMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
} from './api';
import {
  controlledLedgerPostingContext,
  type ControlledLedgerPostingOperatorPanelProps,
} from './controlled-ledger-posting-operator-model';

export function useControlledLedgerPostingOperatorController({
  journey,
  locale,
}: ControlledLedgerPostingOperatorPanelProps) {
  const [open, setOpen] = useState(false);
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const { clearanceId, actionable } = controlledLedgerPostingContext(journey);

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledLedgerPostingPreviewMutation();
  const challenge = useOperatorApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyPosting = useControlledLedgerPostingApplyMutation();
  const valuationPublicationPublished = Boolean(
    applyPosting.data &&
    applyPosting.data.post_apply_status !==
      'valuation_publication_recovery_required' &&
    applyPosting.data.post_valuation_publication_status === 'published' &&
    !applyPosting.data.post_valuation_publication_recovery_required &&
    applyPosting.data.post_valuation_snapshot_id,
  );
  const valuationPublicationRecoveryRequired =
    Boolean(applyPosting.data) && !valuationPublicationPublished;
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
    applyPosting.reset();
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
    preview.mutate({ clearanceId });
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
    applyPosting.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const apply = () => {
    if (
      !preview.data ||
      !verification.data ||
      !acknowledged ||
      applyPosting.isPending ||
      valuationPublicationPublished
    ) {
      return;
    }
    applyPosting.mutate({
      clearanceId,
      posting_fingerprint: preview.data.posting_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement: 'apply_exact_reconciled_ledger_posting_once',
    });
  };

  const selectKey = (keyId: string) => {
    setSelectedKeyId(keyId);
    resetSignatureSteps();
  };

  const updateSignature = (value: string) => {
    setSignature(value);
    verification.reset();
    applyPosting.reset();
    setAcknowledged(false);
  };

  return {
    journey,
    locale,
    clearanceId,
    actionable,
    open,
    openPanel: () => setOpen(true),
    close,
    approvalStatus,
    preview,
    challenge,
    verification,
    applyPosting,
    valuationPublicationPublished,
    valuationPublicationRecoveryRequired,
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

export type ControlledLedgerPostingOperatorController = ReturnType<
  typeof useControlledLedgerPostingOperatorController
>;
