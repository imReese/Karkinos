import { useMemo, useState } from 'react';

import {
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  useSignedBrokerAdapterReleaseReviewApprovalChallengeMutation,
  useSignedBrokerAdapterReleaseReviewDossierPreviewMutation,
  useSignedBrokerAdapterReleaseReviewMutation,
  useSignedBrokerAdapterReleaseReviewsQuery,
  useSignedBrokerAdapterReleaseReviewStatusQuery,
  type SignedBrokerAdapterReleaseReviewDecision,
  type SignedBrokerAdapterReleaseReviewDossierRequest,
} from './api';

type Locale = 'en' | 'zh';

const SENSITIVE_MANIFEST_KEY_PARTS = [
  'password',
  'passwd',
  'secret',
  'token',
  'credential',
  'private_key',
  'api_key',
];

function containsSensitiveManifestKey(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some(containsSensitiveManifestKey);
  }
  if (!value || typeof value !== 'object') {
    return false;
  }
  return Object.entries(value).some(
    ([key, item]) =>
      SENSITIVE_MANIFEST_KEY_PARTS.some((part) =>
        key.toLowerCase().includes(part),
      ) || containsSensitiveManifestKey(item),
  );
}

export function useSignedBrokerAdapterReleaseReviewOperatorController(
  locale: Locale,
) {
  const [open, setOpen] = useState(false);
  const [decision, setDecision] =
    useState<SignedBrokerAdapterReleaseReviewDecision>('accepted');
  const [manifestText, setManifestText] = useState('');
  const [sourceName, setSourceName] = useState(
    'owner-reviewed-adapter-release.json',
  );
  const [reviewId, setReviewId] = useState('');
  const [reasonRef, setReasonRef] = useState('');
  const [selectedReleaseRef, setSelectedReleaseRef] = useState('');
  const [requestSnapshot, setRequestSnapshot] =
    useState<SignedBrokerAdapterReleaseReviewDossierRequest | null>(null);
  const [inputError, setInputError] = useState('');
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const status = useSignedBrokerAdapterReleaseReviewStatusQuery(open);
  const releases = useSignedBrokerAdapterReleaseReviewsQuery(open);
  const preview = useSignedBrokerAdapterReleaseReviewDossierPreviewMutation();
  const approvalStatus = useOperatorApprovalStatusQuery(
    Boolean(preview.data?.review_ready),
  );
  const challenge =
    useSignedBrokerAdapterReleaseReviewApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const record = useSignedBrokerAdapterReleaseReviewMutation();
  const revocableReleases = useMemo(
    () =>
      (releases.data ?? []).filter(
        (item) =>
          item.current_review.status === 'accepted' &&
          item.blockers.length === 0,
      ),
    [releases.data],
  );
  const effectiveReleaseRef =
    selectedReleaseRef || revocableReleases[0]?.release_evidence_ref || '';
  const selectedRelease =
    revocableReleases.find(
      (item) => item.release_evidence_ref === effectiveReleaseRef,
    ) ?? null;
  const effectiveManifestText =
    decision === 'revoked' && selectedRelease
      ? JSON.stringify(selectedRelease.manifest, null, 2)
      : manifestText;
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

  const resetSignedSteps = () => {
    challenge.reset();
    verification.reset();
    record.reset();
    setSelectedKeyId('');
    setSignature('');
    setAcknowledged(false);
  };

  const invalidatePreview = () => {
    preview.reset();
    setRequestSnapshot(null);
    setInputError('');
    resetSignedSteps();
  };

  const loadPreview = () => {
    let manifest: Record<string, unknown>;
    try {
      const parsed = JSON.parse(effectiveManifestText) as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('manifest_not_object');
      }
      manifest = parsed as Record<string, unknown>;
    } catch {
      setInputError(
        locale === 'zh'
          ? 'Adapter manifest 必须是有效的 JSON object。'
          : 'The adapter manifest must be a valid JSON object.',
      );
      return;
    }
    if (containsSensitiveManifestKey(manifest)) {
      setInputError(
        locale === 'zh'
          ? 'Adapter manifest 含有凭据或敏感键，已在本地拦截且未发送。'
          : 'The adapter manifest contains a credential or sensitive key and was blocked locally without being sent.',
      );
      return;
    }
    if (!reviewId.trim() || !reasonRef.trim()) {
      setInputError(
        locale === 'zh'
          ? 'Review ID 与 reason reference 都必须填写。'
          : 'Review ID and reason reference are both required.',
      );
      return;
    }
    if (decision === 'revoked' && !selectedRelease) {
      setInputError(
        locale === 'zh'
          ? '没有可撤销的当前 accepted release。'
          : 'There is no current accepted release available to revoke.',
      );
      return;
    }
    const request: SignedBrokerAdapterReleaseReviewDossierRequest = {
      manifest,
      source_name: sourceName.trim() || 'owner-reviewed-adapter-release.json',
      review_id: reviewId.trim(),
      decision,
      reviewed_at: new Date(Date.now() - 30_000).toISOString(),
      reason_ref: reasonRef.trim(),
    };
    setInputError('');
    setRequestSnapshot(request);
    resetSignedSteps();
    preview.mutate(request);
  };

  const createChallenge = () => {
    const required = preview.data?.required_operator_approval;
    if (!required || !selectedIdentity) {
      return;
    }
    challenge.reset();
    verification.reset();
    record.reset();
    setSignature('');
    setAcknowledged(false);
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
    record.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const recordDecision = () => {
    if (
      !requestSnapshot ||
      !preview.data ||
      !verification.data ||
      !acknowledged
    ) {
      return;
    }
    record.mutate({
      ...requestSnapshot,
      dossier_fingerprint: preview.data.dossier_fingerprint,
      operator_label: verification.data.operator_id,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement:
        'review_broker_adapter_release_without_registration_or_execution_authority',
    });
  };

  return {
    acknowledged,
    approvalStatus,
    challenge,
    decision,
    effectiveKeyId,
    effectiveManifestText,
    effectiveReleaseRef,
    eligibleIdentities,
    inputError,
    manifestReadOnly: decision === 'revoked',
    open,
    preview,
    reasonRef,
    record,
    releases,
    revocableReleases,
    reviewId,
    selectedIdentity,
    signature,
    sourceName,
    status,
    verification,
    createChallenge,
    loadPreview,
    onAcknowledgedChange: setAcknowledged,
    onDecisionChange: (value: SignedBrokerAdapterReleaseReviewDecision) => {
      setDecision(value);
      invalidatePreview();
    },
    onManifestTextChange: (value: string) => {
      setManifestText(value);
      invalidatePreview();
    },
    onReasonRefChange: (value: string) => {
      setReasonRef(value);
      invalidatePreview();
    },
    onReleaseRefChange: (value: string) => {
      setSelectedReleaseRef(value);
      invalidatePreview();
    },
    onReviewIdChange: (value: string) => {
      setReviewId(value);
      invalidatePreview();
    },
    onSelectedKeyIdChange: (value: string) => {
      setSelectedKeyId(value);
      resetSignedSteps();
    },
    onSignatureChange: (value: string) => {
      setSignature(value);
      verification.reset();
      record.reset();
      setAcknowledged(false);
    },
    onSourceNameChange: (value: string) => {
      setSourceName(value);
      invalidatePreview();
    },
    recordDecision,
    toggleOpen: () => setOpen((value) => !value),
    verifySignature,
  };
}

export type SignedBrokerAdapterReleaseReviewOperatorController = ReturnType<
  typeof useSignedBrokerAdapterReleaseReviewOperatorController
>;
