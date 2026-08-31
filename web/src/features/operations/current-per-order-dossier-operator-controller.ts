import { useMemo, useState } from 'react';

import {
  useCurrentPerOrderConfirmationMutation,
  useCurrentPerOrderDossierApprovalChallengeMutation,
  useCurrentPerOrderDossierCandidatesQuery,
  useCurrentPerOrderDossierPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
} from './api';
import type { CurrentPerOrderDossierOperatorPanelProps } from './current-per-order-dossier-operator-model';

export function useCurrentPerOrderDossierOperatorController({
  locale,
}: CurrentPerOrderDossierOperatorPanelProps) {
  const [open, setOpen] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState('');
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const candidates = useCurrentPerOrderDossierCandidatesQuery(open);
  const preview = useCurrentPerOrderDossierPreviewMutation();
  const approvalStatus = useOperatorApprovalStatusQuery(
    open && Boolean(preview.data?.review_ready),
  );
  const challenge = useCurrentPerOrderDossierApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const confirmation = useCurrentPerOrderConfirmationMutation();
  const candidateRows = candidates.data?.candidates ?? [];
  const effectiveOrderId = selectedOrderId || candidateRows[0]?.order_id || '';
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
    confirmation.reset();
    setSignature('');
    setAcknowledged(false);
  };

  const resetPreview = () => {
    preview.reset();
    setSelectedKeyId('');
    resetSignatureSteps();
  };

  const close = () => {
    setOpen(false);
    setSelectedOrderId('');
    resetPreview();
  };

  const toggleOpen = () => {
    if (open) {
      close();
    } else {
      setOpen(true);
    }
  };

  const loadPreview = () => {
    if (!effectiveOrderId) {
      return;
    }
    resetPreview();
    preview.mutate({ orderId: effectiveOrderId });
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
    confirmation.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const recordConfirmation = () => {
    if (
      !preview.data ||
      !verification.data ||
      !effectiveOrderId ||
      !acknowledged
    ) {
      return;
    }
    confirmation.mutate({
      orderId: effectiveOrderId,
      dossier_fingerprint: preview.data.dossier_fingerprint,
      operator_label: verification.data.operator_id,
      operator_approval_id: verification.data.approval_id,
      acknowledgement: 'confirm_exact_non_submitting_dossier_for_review',
    });
  };

  const selectOrder = (orderId: string) => {
    setSelectedOrderId(orderId);
    resetPreview();
  };

  const selectKey = (keyId: string) => {
    setSelectedKeyId(keyId);
    resetSignatureSteps();
  };

  const updateSignature = (value: string) => {
    setSignature(value);
    verification.reset();
    confirmation.reset();
    setAcknowledged(false);
  };

  return {
    locale,
    open,
    toggleOpen,
    candidates,
    preview,
    approvalStatus,
    challenge,
    verification,
    confirmation,
    candidateRows,
    effectiveOrderId,
    eligibleIdentities,
    effectiveKeyId,
    selectedIdentity,
    signature,
    acknowledged,
    setAcknowledged,
    selectOrder,
    selectKey,
    updateSignature,
    loadPreview,
    createChallenge,
    verifySignature,
    recordConfirmation,
  };
}

export type CurrentPerOrderDossierOperatorController = ReturnType<
  typeof useCurrentPerOrderDossierOperatorController
>;
