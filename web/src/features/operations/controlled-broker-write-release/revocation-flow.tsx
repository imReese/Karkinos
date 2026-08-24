import { useMemo, useState } from 'react';

import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useControlledBrokerWriteReleaseRevocationMutation,
  useControlledBrokerWriteReleaseRevocationPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type ControlledBrokerWriteReleaseEvidence,
  type ControlledBrokerWriteReleaseRevocationReason,
} from '../api';
import type { Locale } from './contracts';
import { RevocationForm } from './revocation-form';
import { RevocationReview } from './revocation-review';

export function RevokeWriteReleaseFlow({
  locale,
  releases,
  loading,
  error,
}: {
  locale: Locale;
  releases: ControlledBrokerWriteReleaseEvidence[];
  loading: boolean;
  error: string;
}) {
  const [selectedReleaseId, setSelectedReleaseId] = useState('');
  const [reason, setReason] =
    useState<ControlledBrokerWriteReleaseRevocationReason>(
      'incident_or_anomaly',
    );
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const preview = useControlledBrokerWriteReleaseRevocationPreviewMutation();
  const approvalStatus = useOperatorApprovalStatusQuery(
    Boolean(preview.data?.ready),
  );
  const challenge = useControlledBrokerWriteReleaseApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const revoke = useControlledBrokerWriteReleaseRevocationMutation();
  const effectiveReleaseId =
    selectedReleaseId || releases[0]?.release_evidence_id || '';
  const selectedRelease =
    releases.find(
      (release) => release.release_evidence_id === effectiveReleaseId,
    ) ?? null;
  const eligibleIdentities = useMemo(
    () =>
      (approvalStatus.data?.trusted_identities ?? []).filter(
        (identity) => identity.enabled,
      ),
    [approvalStatus.data?.trusted_identities],
  );
  const effectiveKeyId = selectedKeyId || eligibleIdentities[0]?.key_id || '';
  const selectedIdentity =
    eligibleIdentities.find((identity) => identity.key_id === effectiveKeyId) ??
    null;

  const resetSignedSteps = () => {
    challenge.reset();
    verification.reset();
    revoke.reset();
    setSelectedKeyId('');
    setSignature('');
    setAcknowledged(false);
  };

  const invalidatePreview = () => {
    preview.reset();
    resetSignedSteps();
  };

  const loadPreview = () => {
    if (!effectiveReleaseId) {
      return;
    }
    preview.reset();
    resetSignedSteps();
    preview.mutate({ releaseId: effectiveReleaseId, reason_code: reason });
  };

  const createChallenge = () => {
    const required = preview.data?.required_operator_approval;
    if (!required || !selectedIdentity) {
      return;
    }
    challenge.reset();
    verification.reset();
    revoke.reset();
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
    revoke.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const revokeRelease = () => {
    if (!preview.data || !verification.data || !acknowledged) {
      return;
    }
    revoke.mutate({
      releaseId: preview.data.release_evidence_id,
      reason_code: preview.data.reason_code,
      revocation_fingerprint: preview.data.revocation_fingerprint,
      operator_label: verification.data.operator_id,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement:
        'revoke_exact_broker_write_release_without_resume_or_broker_action',
    });
  };

  return (
    <section className="min-w-0 rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] p-3 sm:p-4">
      <h3 className="text-sm font-semibold text-[var(--app-text)]">
        {locale === 'zh' ? '单向撤销能力放行' : 'One-way capability revocation'}
      </h3>
      <p className="app-muted mt-1 text-xs leading-5">
        {locale === 'zh'
          ? '即使来源证据后来漂移，也可以撤销已记录 release。撤销不能恢复，不会调用 gateway，也不会声明未结订单已处理。'
          : 'A recorded release remains revocable even after source evidence drifts. Revocation cannot resume, calls no gateway, and makes no claim about open orders.'}
      </p>

      <RevocationForm
        locale={locale}
        releases={releases}
        loading={loading}
        error={error}
        effectiveReleaseId={effectiveReleaseId}
        selectedRelease={selectedRelease}
        onReleaseChange={(value) => {
          setSelectedReleaseId(value);
          invalidatePreview();
        }}
        reason={reason}
        onReasonChange={(value) => {
          setReason(value);
          invalidatePreview();
        }}
        previewPending={preview.isPending}
        onLoadPreview={loadPreview}
      />
      <RevocationReview
        locale={locale}
        preview={preview}
        identities={eligibleIdentities}
        effectiveKeyId={effectiveKeyId}
        selectedIdentity={selectedIdentity}
        onIdentityChange={(keyId) => {
          setSelectedKeyId(keyId);
          challenge.reset();
          verification.reset();
          revoke.reset();
          setSignature('');
          setAcknowledged(false);
        }}
        challenge={challenge}
        verification={verification}
        signature={signature}
        onSignatureChange={(value) => {
          setSignature(value);
          verification.reset();
          revoke.reset();
          setAcknowledged(false);
        }}
        onCreateChallenge={createChallenge}
        onVerifySignature={verifySignature}
        acknowledged={acknowledged}
        onAcknowledgementChange={setAcknowledged}
        revoke={revoke}
        onRevokeRelease={revokeRelease}
      />
    </section>
  );
}
