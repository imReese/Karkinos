import { useMemo, useState } from 'react';

import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useControlledBrokerWriteReleaseDossierPreviewMutation,
  useControlledBrokerWriteReleaseIssueMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type BrokerAdapterReadiness,
  type BrokerConnectorSoakPromotionStatus,
  type ControlledBrokerWriteReleaseDossierRequest,
  type ControlledBrokerWriteReleaseOwnerReviewRefs,
} from '../api';
import {
  containsSensitiveManifestKey,
  EMPTY_OWNER_REFS,
  exactSoakAcceptance,
  mutationError,
  OWNER_REVIEW_FIELDS,
  type Locale,
  type OwnerReviewRefField,
} from './contracts';
import { IssueReleaseForm } from './issue-form';
import { IssueReleaseReview } from './issue-review';

export function IssueWriteReleaseFlow({
  locale,
  readiness,
  soak,
}: {
  locale: Locale;
  readiness: BrokerAdapterReadiness | null;
  soak: BrokerConnectorSoakPromotionStatus | null;
}) {
  const [manifestText, setManifestText] = useState('');
  const [selectedReleaseRef, setSelectedReleaseRef] = useState('');
  const [durationSeconds, setDurationSeconds] = useState(4 * 60 * 60);
  const [ownerRefs, setOwnerRefs] =
    useState<ControlledBrokerWriteReleaseOwnerReviewRefs>(EMPTY_OWNER_REFS);
  const [requestSnapshot, setRequestSnapshot] =
    useState<ControlledBrokerWriteReleaseDossierRequest | null>(null);
  const [manifestError, setManifestError] = useState('');
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const preview = useControlledBrokerWriteReleaseDossierPreviewMutation();
  const approvalStatus = useOperatorApprovalStatusQuery(
    Boolean(preview.data?.review_ready),
  );
  const challenge = useControlledBrokerWriteReleaseApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const issue = useControlledBrokerWriteReleaseIssueMutation();
  const readonlyCandidates = useMemo(
    () =>
      (readiness?.releases ?? []).filter(
        (release) => release.status === 'observing_readonly',
      ),
    [readiness?.releases],
  );
  const effectiveReleaseRef =
    selectedReleaseRef || readonlyCandidates[0]?.release_evidence_ref || '';
  const selectedRelease =
    readonlyCandidates.find(
      (release) => release.release_evidence_ref === effectiveReleaseRef,
    ) ?? null;
  const selectedSoak = exactSoakAcceptance(soak, selectedRelease);
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
  const ownerRefsComplete = OWNER_REVIEW_FIELDS.every((field) =>
    ownerRefs[field].trim(),
  );

  const resetSignedSteps = () => {
    challenge.reset();
    verification.reset();
    issue.reset();
    setSelectedKeyId('');
    setSignature('');
    setAcknowledged(false);
  };

  const invalidatePreview = () => {
    preview.reset();
    setRequestSnapshot(null);
    setManifestError('');
    resetSignedSteps();
  };

  const loadPreview = () => {
    let executionEdgeManifest: Record<string, unknown>;
    try {
      const parsed = JSON.parse(manifestText) as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('manifest_not_object');
      }
      executionEdgeManifest = parsed as Record<string, unknown>;
    } catch {
      setManifestError(
        locale === 'zh'
          ? 'Execution manifest 必须是有效的 JSON object。'
          : 'The execution manifest must be a valid JSON object.',
      );
      return;
    }
    if (containsSensitiveManifestKey(executionEdgeManifest)) {
      setManifestError(
        locale === 'zh'
          ? 'Execution manifest 含有凭据或敏感键，已在本地拦截且未发送。'
          : 'The execution manifest contains a credential or sensitive key and was blocked locally without being sent.',
      );
      return;
    }
    if (!selectedRelease || !selectedSoak?.acceptance?.acceptance_id) {
      setManifestError(
        locale === 'zh'
          ? '必须先具备精确匹配、仍为 observing_readonly 的 release 与已签名 soak acceptance。'
          : 'An exact observing_readonly release and signed soak acceptance are required first.',
      );
      return;
    }
    if (!ownerRefsComplete) {
      setManifestError(
        locale === 'zh'
          ? '七类所有者复核引用必须全部填写。'
          : 'All seven owner-review references are required.',
      );
      return;
    }
    const effectiveAt = new Date(Date.now() - 30_000);
    const request: ControlledBrokerWriteReleaseDossierRequest = {
      execution_edge_manifest: executionEdgeManifest,
      readonly_release_evidence_ref: selectedRelease.release_evidence_ref,
      soak_acceptance_id: selectedSoak.acceptance.acceptance_id,
      effective_at: effectiveAt.toISOString(),
      expires_at: new Date(
        effectiveAt.getTime() + durationSeconds * 1_000,
      ).toISOString(),
      owner_review_refs: Object.fromEntries(
        OWNER_REVIEW_FIELDS.map((field) => [field, ownerRefs[field].trim()]),
      ) as ControlledBrokerWriteReleaseOwnerReviewRefs,
    };
    setManifestError('');
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
    issue.reset();
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
    issue.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const issueRelease = () => {
    if (
      !requestSnapshot ||
      !preview.data ||
      !verification.data ||
      !acknowledged
    ) {
      return;
    }
    issue.mutate({
      ...requestSnapshot,
      dossier_fingerprint: preview.data.dossier_fingerprint,
      operator_label: verification.data.operator_id,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement:
        'issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority',
    });
  };

  const changeOwnerRef = (field: OwnerReviewRefField, value: string) => {
    setOwnerRefs((current) => ({ ...current, [field]: value }));
    invalidatePreview();
  };

  return (
    <section className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] p-3 sm:p-4">
      <h3 className="text-sm font-semibold text-[var(--app-text)]">
        {locale === 'zh'
          ? '签发限时能力放行'
          : 'Issue a time-bounded capability release'}
      </h3>
      <p className="app-muted mt-1 text-xs leading-5">
        {locale === 'zh'
          ? '只粘贴经过审查且不含凭证的 manifest。任何 blocker、漂移或缺失来源都会由服务端拒绝。'
          : 'Paste only a reviewed manifest containing no credentials. The server rejects every blocker, drift, or missing source.'}
      </p>

      <IssueReleaseForm
        locale={locale}
        readonlyCandidates={readonlyCandidates}
        effectiveReleaseRef={effectiveReleaseRef}
        onReleaseRefChange={(value) => {
          setSelectedReleaseRef(value);
          invalidatePreview();
        }}
        soakAcceptanceId={selectedSoak?.acceptance?.acceptance_id ?? ''}
        manifestText={manifestText}
        onManifestTextChange={(value) => {
          setManifestText(value);
          invalidatePreview();
        }}
        durationSeconds={durationSeconds}
        onDurationChange={(value) => {
          setDurationSeconds(value);
          invalidatePreview();
        }}
        ownerRefs={ownerRefs}
        onOwnerRefChange={changeOwnerRef}
        previewPending={preview.isPending}
        onLoadPreview={loadPreview}
        manifestError={manifestError}
        previewError={preview.isError ? mutationError(preview.error) : ''}
      />
      <IssueReleaseReview
        locale={locale}
        preview={preview}
        identities={eligibleIdentities}
        effectiveKeyId={effectiveKeyId}
        selectedIdentity={selectedIdentity}
        onIdentityChange={(keyId) => {
          setSelectedKeyId(keyId);
          challenge.reset();
          verification.reset();
          issue.reset();
          setSignature('');
          setAcknowledged(false);
        }}
        challenge={challenge}
        verification={verification}
        signature={signature}
        onSignatureChange={(value) => {
          setSignature(value);
          verification.reset();
          issue.reset();
          setAcknowledged(false);
        }}
        onCreateChallenge={createChallenge}
        onVerifySignature={verifySignature}
        acknowledged={acknowledged}
        onAcknowledgementChange={setAcknowledged}
        issue={issue}
        onIssueRelease={issueRelease}
      />
    </section>
  );
}
