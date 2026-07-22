import { useMemo, useState } from 'react';

import {
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledBrokerWriteReleaseApprovalChallengeMutation,
  useControlledBrokerWriteReleaseDossierPreviewMutation,
  useControlledBrokerWriteReleaseIssueMutation,
  useControlledBrokerWriteReleaseRevocationMutation,
  useControlledBrokerWriteReleaseRevocationPreviewMutation,
  useControlledBrokerWriteReleasesQuery,
  useControlledBrokerWriteReleaseStatusQuery,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type BrokerAdapterReadiness,
  type BrokerAdapterReadinessRelease,
  type BrokerConnectorSoakPromotionStatus,
  type ControlledBrokerWriteReleaseDossierRequest,
  type ControlledBrokerWriteReleaseOwnerReviewRefs,
  type ControlledBrokerWriteReleaseRevocationReason,
} from './api';

type Locale = 'en' | 'zh';
type OwnerReviewRefField = keyof ControlledBrokerWriteReleaseOwnerReviewRefs;

const OWNER_REVIEW_FIELDS: OwnerReviewRefField[] = [
  'broker_agreement_review',
  'account_permissions_review',
  'program_trading_reporting_review',
  'provider_acceptance_test_report',
  'deployment_authorization',
  'risk_controls_review',
  'rollback_drill_review',
];

const EMPTY_OWNER_REFS: ControlledBrokerWriteReleaseOwnerReviewRefs = {
  broker_agreement_review: '',
  account_permissions_review: '',
  program_trading_reporting_review: '',
  provider_acceptance_test_report: '',
  deployment_authorization: '',
  risk_controls_review: '',
  rollback_drill_review: '',
};

const REVOCATION_REASONS: ControlledBrokerWriteReleaseRevocationReason[] = [
  'incident_or_anomaly',
  'owner_disabled',
  'adapter_or_deployment_changed',
  'provider_scope_changed',
  'regulatory_or_permission_change',
  'scheduled_expiry_superseded',
];

const SENSITIVE_MANIFEST_KEY_PARTS = [
  'password',
  'passwd',
  'secret',
  'token',
  'credential',
  'private_key',
  'api_key',
];

function mutationError(error: unknown) {
  return error instanceof Error
    ? error.message
    : String(error || 'unknown_error');
}

function shortenedIdentity(value: string) {
  if (value.length <= 24) {
    return value || '—';
  }
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

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

function ownerReviewLabel(field: OwnerReviewRefField, locale: Locale) {
  const labels: Record<OwnerReviewRefField, { en: string; zh: string }> = {
    broker_agreement_review: {
      en: 'Broker agreement review',
      zh: '券商协议复核',
    },
    account_permissions_review: {
      en: 'Account permissions review',
      zh: '账户权限复核',
    },
    program_trading_reporting_review: {
      en: 'Program-trading reporting review',
      zh: '程序化交易报告复核',
    },
    provider_acceptance_test_report: {
      en: 'Provider acceptance-test report',
      zh: 'Provider 验收测试报告',
    },
    deployment_authorization: {
      en: 'Deployment authorization',
      zh: '部署授权',
    },
    risk_controls_review: {
      en: 'Risk-controls review',
      zh: '风控复核',
    },
    rollback_drill_review: {
      en: 'Rollback-drill review',
      zh: '回滚演练复核',
    },
  };
  return labels[field][locale];
}

function revocationReasonLabel(
  reason: ControlledBrokerWriteReleaseRevocationReason,
  locale: Locale,
) {
  const labels: Record<
    ControlledBrokerWriteReleaseRevocationReason,
    { en: string; zh: string }
  > = {
    adapter_or_deployment_changed: {
      en: 'Adapter or deployment changed',
      zh: 'Adapter 或部署已变化',
    },
    incident_or_anomaly: {
      en: 'Incident or anomaly',
      zh: '事故或异常',
    },
    owner_disabled: { en: 'Owner disabled', zh: '所有者主动关闭' },
    provider_scope_changed: {
      en: 'Provider scope changed',
      zh: 'Provider scope 已变化',
    },
    regulatory_or_permission_change: {
      en: 'Regulatory or permission change',
      zh: '监管或权限变化',
    },
    scheduled_expiry_superseded: {
      en: 'Superseded before scheduled expiry',
      zh: '计划到期前被替代',
    },
  };
  return labels[reason][locale];
}

function exactSoakAcceptance(
  soak: BrokerConnectorSoakPromotionStatus | null,
  release: BrokerAdapterReadinessRelease | null,
) {
  if (!soak || !release) {
    return null;
  }
  return (
    soak.connectors.find(
      (connector) =>
        connector.connector_id === release.collector_id &&
        connector.account_alias === release.account_alias &&
        connector.promotion_ready &&
        connector.owner_acceptance_recorded &&
        Boolean(connector.acceptance?.acceptance_id),
    ) ?? null
  );
}

export function ControlledBrokerWriteReleaseOperatorPanel({
  locale,
  readiness,
  soak,
}: {
  locale: Locale;
  readiness: BrokerAdapterReadiness | null;
  soak: BrokerConnectorSoakPromotionStatus | null;
}) {
  const [open, setOpen] = useState(false);
  const status = useControlledBrokerWriteReleaseStatusQuery(open);
  const releases = useControlledBrokerWriteReleasesQuery(open);

  return (
    <section
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
      data-testid="controlled-broker-write-release-panel"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {locale === 'zh'
                ? '执行边缘能力门禁'
                : 'Execution-edge capability gate'}
            </div>
            <h2 className="app-card-title mt-1.5">
              {locale === 'zh'
                ? '签名式券商写入放行'
                : 'Signed broker write-edge release'}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {locale === 'zh'
                ? '把严格 execution manifest、最新只读 release、已签名 soak acceptance 与所有者复核引用冻结为最长 12 小时的 manual_each_order 能力放行。该放行只是逐单提交的必要条件，不注册 gateway，不授予订单或资本权限。'
                : 'Freeze a strict execution manifest, newest read-only release, signed soak acceptance, and owner-review references into an at-most-12-hour manual_each_order capability release. It is necessary for a later per-order submission but registers no gateway and grants no order or capital authority.'}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <span className="app-chip">
              {!open
                ? locale === 'zh'
                  ? '复核已关闭'
                  : 'Review closed'
                : status.isLoading
                  ? locale === 'zh'
                    ? '读取中'
                    : 'Loading'
                  : status.isError
                    ? locale === 'zh'
                      ? '状态不可用'
                      : 'Status unavailable'
                    : status.data?.active_release_count
                      ? locale === 'zh'
                        ? `${status.data.active_release_count} 个当前放行`
                        : `${status.data.active_release_count} current release`
                      : locale === 'zh'
                        ? '无当前放行'
                        : 'No current release'}
            </span>
            <button
              type="button"
              className="app-button-secondary min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
              onClick={() => setOpen((value) => !value)}
            >
              {open
                ? locale === 'zh'
                  ? '关闭'
                  : 'Close'
                : locale === 'zh'
                  ? '打开能力复核'
                  : 'Open capability review'}
            </button>
          </div>
        </div>

        <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-xs">
          <span className="app-chip">manual_each_order only</span>
          <span className="app-chip">gateway registration: disabled</span>
          <span className="app-chip">capital authority: unchanged</span>
        </div>

        {open && status.isError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {mutationError(status.error)}
          </div>
        ) : null}

        {open ? (
          <div className="mt-4 grid min-w-0 gap-4 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-4 xl:grid-cols-2">
            <IssueWriteReleaseFlow
              locale={locale}
              readiness={readiness}
              soak={soak}
            />
            <RevokeWriteReleaseFlow
              locale={locale}
              releases={releases.data ?? []}
              loading={releases.isLoading}
              error={releases.isError ? mutationError(releases.error) : ''}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function IssueWriteReleaseFlow({
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
  const selectedIdentity = eligibleIdentities.find(
    (identity) => identity.key_id === effectiveKeyId,
  );
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

      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '只读 adapter release' : 'Read-only adapter release'}
        <select
          aria-label={
            locale === 'zh'
              ? '选择只读 adapter release'
              : 'Select read-only adapter release'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={effectiveReleaseRef}
          onChange={(event) => {
            setSelectedReleaseRef(event.target.value);
            invalidatePreview();
          }}
        >
          {readonlyCandidates.length === 0 ? (
            <option value="">
              {locale === 'zh'
                ? '无可用只读 release'
                : 'No eligible read-only release'}
            </option>
          ) : null}
          {readonlyCandidates.map((release) => (
            <option
              key={release.release_evidence_ref}
              value={release.release_evidence_ref}
            >
              {release.provider} · {release.account_alias} ·{' '}
              {release.release_evidence_ref}
            </option>
          ))}
        </select>
      </label>

      <div className="app-muted mt-2 break-words text-xs">
        {locale === 'zh' ? '精确 soak acceptance：' : 'Exact soak acceptance: '}
        {selectedSoak?.acceptance?.acceptance_id
          ? shortenedIdentity(selectedSoak.acceptance.acceptance_id)
          : locale === 'zh'
            ? '缺失或未通过'
            : 'missing or not accepted'}
      </div>

      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh'
          ? 'Execution-edge manifest JSON'
          : 'Execution-edge manifest JSON'}
        <textarea
          aria-label="Execution-edge manifest JSON"
          className="app-field min-h-32 min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
          spellCheck={false}
          value={manifestText}
          onChange={(event) => {
            setManifestText(event.target.value);
            invalidatePreview();
          }}
          placeholder='{"schema_version":"karkinos.broker_execution_edge_manifest.v1",…}'
        />
      </label>

      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '放行期限' : 'Release duration'}
        <select
          aria-label={
            locale === 'zh' ? '选择放行期限' : 'Select release duration'
          }
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={durationSeconds}
          onChange={(event) => {
            setDurationSeconds(Number(event.target.value));
            invalidatePreview();
          }}
        >
          {[1, 4, 8, 12].map((hours) => (
            <option key={hours} value={hours * 60 * 60}>
              {hours}h
            </option>
          ))}
        </select>
      </label>

      <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">
        {OWNER_REVIEW_FIELDS.map((field) => (
          <label
            className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]"
            key={field}
          >
            {ownerReviewLabel(field, locale)}
            <input
              aria-label={ownerReviewLabel(field, locale)}
              className="app-field min-w-0 rounded-xl px-3 py-2 text-xs"
              value={ownerRefs[field]}
              onChange={(event) => {
                setOwnerRefs((current) => ({
                  ...current,
                  [field]: event.target.value,
                }));
                invalidatePreview();
              }}
              placeholder="review:…"
            />
          </label>
        ))}
      </div>

      <button
        type="button"
        className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={preview.isPending}
        onClick={loadPreview}
      >
        {preview.isPending
          ? locale === 'zh'
            ? '核验中'
            : 'Checking'
          : locale === 'zh'
            ? '生成只读放行预览'
            : 'Generate read-only release preview'}
      </button>

      {manifestError ? (
        <div className="app-error-text mt-2 text-xs" role="alert">
          {manifestError}
        </div>
      ) : null}
      {preview.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(preview.error)}
        </div>
      ) : null}

      {preview.data ? (
        <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] p-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-[var(--app-text)]">
              {preview.data.scope.provider || '—'} ·{' '}
              {preview.data.scope.account_alias || '—'}
            </span>
            <span className="app-chip">
              {formatPublicStatus(preview.data.review_status, locale)}
            </span>
          </div>
          <div className="app-muted mt-2 grid min-w-0 gap-1 text-xs sm:grid-cols-2">
            <div className="truncate" title={preview.data.dossier_fingerprint}>
              dossier: {shortenedIdentity(preview.data.dossier_fingerprint)}
            </div>
            <div className="truncate" title={preview.data.scope.gateway_id}>
              gateway: {preview.data.scope.gateway_id || '—'}
            </div>
            <div>{preview.data.effective_at}</div>
            <div>{preview.data.expires_at}</div>
          </div>
          {preview.data.review_blockers.length ? (
            <ul className="app-muted mt-2 grid gap-1 pl-5 text-xs">
              {preview.data.review_blockers.slice(0, 8).map((blocker) => (
                <li className="list-disc break-words" key={blocker}>
                  {formatPublicOperationalNote(blocker, locale)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {preview.data?.review_ready ? (
        <OfflineSignatureSteps
          locale={locale}
          action="issue_controlled_broker_write_release"
          artifactType="controlled_broker_write_release_dossier"
          identities={eligibleIdentities}
          effectiveKeyId={effectiveKeyId}
          selectedIdentity={selectedIdentity ?? null}
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
        />
      ) : null}

      {verification.data ? (
        <div className="mt-3">
          <label className="flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              {locale === 'zh'
                ? '我确认仅签发这一精确、会过期的 manual_each_order 能力放行；它不注册 gateway、不提交或撤销订单，也不授予资本权限。'
                : 'I confirm issuing only this exact, expiring manual_each_order capability release. It registers no gateway, submits or cancels no order, and grants no capital authority.'}
            </span>
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!acknowledged || issue.isPending}
            onClick={issueRelease}
          >
            {issue.isPending
              ? locale === 'zh'
                ? '记录中'
                : 'Recording'
              : locale === 'zh'
                ? '记录限时能力放行'
                : 'Record time-bounded capability release'}
          </button>
        </div>
      ) : null}

      {issue.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(issue.error)}
        </div>
      ) : null}
      {issue.data ? (
        <div
          className="mt-2 break-words text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh' ? '已记录：' : 'Recorded: '}
          {shortenedIdentity(issue.data.release_evidence_id)} ·{' '}
          {issue.data.expires_at}
        </div>
      ) : null}
    </section>
  );
}

function RevokeWriteReleaseFlow({
  locale,
  releases,
  loading,
  error,
}: {
  locale: Locale;
  releases: Array<{
    release_evidence_id: string;
    status: string;
    provider: string;
    account_alias: string;
    gateway_id: string;
    expires_at: string;
    revoked?: boolean;
  }>;
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
  const selectedRelease = releases.find(
    (release) => release.release_evidence_id === effectiveReleaseId,
  );
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
    revoke.reset();
    setSelectedKeyId('');
    setSignature('');
    setAcknowledged(false);
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

      {loading ? (
        <div className="app-muted mt-3 text-xs">
          {locale === 'zh' ? '读取 release…' : 'Loading releases…'}
        </div>
      ) : error ? (
        <div className="app-error-text mt-3 text-xs" role="alert">
          {error}
        </div>
      ) : releases.length === 0 ? (
        <div className="app-muted mt-3 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] p-3 text-xs">
          {locale === 'zh'
            ? '尚无持久化 write release；系统保持默认关闭。'
            : 'No persisted write release exists; the system remains default closed.'}
        </div>
      ) : (
        <>
          <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '选择 release' : 'Select release'}
            <select
              aria-label={
                locale === 'zh'
                  ? '选择撤销 release'
                  : 'Select release to revoke'
              }
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              value={effectiveReleaseId}
              onChange={(event) => {
                setSelectedReleaseId(event.target.value);
                preview.reset();
                resetSignedSteps();
              }}
            >
              {releases.map((release) => (
                <option
                  key={release.release_evidence_id}
                  value={release.release_evidence_id}
                >
                  {release.provider} · {release.account_alias} ·{' '}
                  {release.status}
                </option>
              ))}
            </select>
          </label>
          {selectedRelease ? (
            <div className="app-muted mt-2 grid min-w-0 gap-1 text-xs sm:grid-cols-2">
              <div className="truncate" title={selectedRelease.gateway_id}>
                gateway: {selectedRelease.gateway_id || '—'}
              </div>
              <div>{selectedRelease.expires_at || '—'}</div>
            </div>
          ) : null}
          <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '撤销原因' : 'Revocation reason'}
            <select
              aria-label={
                locale === 'zh' ? '选择撤销原因' : 'Select revocation reason'
              }
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              value={reason}
              onChange={(event) => {
                setReason(
                  event.target
                    .value as ControlledBrokerWriteReleaseRevocationReason,
                );
                preview.reset();
                resetSignedSteps();
              }}
            >
              {REVOCATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {revocationReasonLabel(value, locale)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            disabled={preview.isPending}
            onClick={loadPreview}
          >
            {preview.isPending
              ? locale === 'zh'
                ? '生成中'
                : 'Loading'
              : locale === 'zh'
                ? '生成只读撤销预览'
                : 'Generate read-only revocation preview'}
          </button>
        </>
      )}

      {preview.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(preview.error)}
        </div>
      ) : null}
      {preview.data ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger-border)_72%,transparent)] p-3 text-xs">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <span className="truncate" title={preview.data.release_evidence_id}>
              {shortenedIdentity(preview.data.release_evidence_id)}
            </span>
            <span className="app-chip">
              {formatPublicStatus(preview.data.status, locale)}
            </span>
          </div>
          {preview.data.blockers.length ? (
            <ul className="app-muted mt-2 grid gap-1 pl-5">
              {preview.data.blockers.map((blocker) => (
                <li className="list-disc break-words" key={blocker}>
                  {formatPublicOperationalNote(blocker, locale)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {preview.data?.ready ? (
        <OfflineSignatureSteps
          locale={locale}
          action="revoke_controlled_broker_write_release"
          artifactType="controlled_broker_write_release_revocation"
          identities={eligibleIdentities}
          effectiveKeyId={effectiveKeyId}
          selectedIdentity={selectedIdentity ?? null}
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
        />
      ) : null}

      {verification.data ? (
        <div className="mt-3">
          <label className="flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              {locale === 'zh'
                ? '我确认永久撤销这一精确 release；它不会恢复，也不会提交、撤销或查询任何券商订单。'
                : 'I confirm permanently revoking this exact release. It cannot resume and will not submit, cancel, or query any broker order.'}
            </span>
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            disabled={!acknowledged || revoke.isPending}
            onClick={revokeRelease}
          >
            {revoke.isPending
              ? locale === 'zh'
                ? '撤销中'
                : 'Revoking'
              : locale === 'zh'
                ? '永久撤销该 release 一次'
                : 'Permanently revoke this release once'}
          </button>
        </div>
      ) : null}

      {revoke.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(revoke.error)}
        </div>
      ) : null}
      {revoke.data ? (
        <div
          className="mt-2 break-words text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh' ? '已永久撤销：' : 'Permanently revoked: '}
          {shortenedIdentity(revoke.data.release_evidence_id)}
        </div>
      ) : null}
    </section>
  );
}

function OfflineSignatureSteps({
  locale,
  action,
  artifactType,
  identities,
  effectiveKeyId,
  selectedIdentity,
  onIdentityChange,
  challenge,
  verification,
  signature,
  onSignatureChange,
  onCreateChallenge,
  onVerifySignature,
}: {
  locale: Locale;
  action:
    | 'issue_controlled_broker_write_release'
    | 'revoke_controlled_broker_write_release';
  artifactType:
    | 'controlled_broker_write_release_dossier'
    | 'controlled_broker_write_release_revocation';
  identities: Array<{
    operator_id: string;
    key_id: string;
    public_key_fingerprint: string;
  }>;
  effectiveKeyId: string;
  selectedIdentity: {
    operator_id: string;
    key_id: string;
    public_key_fingerprint: string;
  } | null;
  onIdentityChange: (keyId: string) => void;
  challenge: ReturnType<
    typeof useControlledBrokerWriteReleaseApprovalChallengeMutation
  >;
  verification: ReturnType<typeof useOperatorApprovalVerificationMutation>;
  signature: string;
  onSignatureChange: (value: string) => void;
  onCreateChallenge: () => void;
  onVerifySignature: () => void;
}) {
  return (
    <div className="mt-3 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] pt-3">
      {identities.length === 0 ? (
        <div className="app-error-text text-xs">
          {locale === 'zh'
            ? '没有启用的可信离线签名身份；mutation 保持关闭。'
            : 'No enabled trusted offline signer identity is configured; mutation remains closed.'}
        </div>
      ) : (
        <>
          <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '可信签名身份' : 'Trusted signer identity'}
            <select
              aria-label={
                locale === 'zh'
                  ? '选择可信签名身份'
                  : 'Select trusted signer identity'
              }
              className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
              value={effectiveKeyId}
              onChange={(event) => onIdentityChange(event.target.value)}
            >
              {identities.map((identity) => (
                <option key={identity.key_id} value={identity.key_id}>
                  {identity.operator_id} · {identity.key_id}
                </option>
              ))}
            </select>
          </label>
          {selectedIdentity ? (
            <div className="app-muted mt-2 truncate text-xs">
              key fingerprint:{' '}
              {shortenedIdentity(selectedIdentity.public_key_fingerprint)}
            </div>
          ) : null}
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            disabled={!selectedIdentity || challenge.isPending}
            onClick={onCreateChallenge}
          >
            {challenge.isPending
              ? locale === 'zh'
                ? '创建中'
                : 'Creating'
              : locale === 'zh'
                ? '创建 3 分钟离线签名 challenge'
                : 'Create 3-minute offline signing challenge'}
          </button>
        </>
      )}

      {challenge.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(challenge.error)}
        </div>
      ) : null}
      {challenge.data ? (
        <div className="mt-3 min-w-0">
          <div className="app-muted text-xs leading-5">
            {locale === 'zh'
              ? `使用 scripts/operator_signer.py，expected action 为 ${action}，artifact type 为 ${artifactType}。只粘贴 payload；私钥不得进入 Karkinos。`
              : `Use scripts/operator_signer.py with expected action ${action} and artifact type ${artifactType}. Paste only the payload; the private key must never enter Karkinos.`}
          </div>
          <textarea
            aria-label={
              locale === 'zh' ? '离线签名 payload' : 'Offline signing payload'
            }
            className="app-field mt-2 min-h-20 w-full rounded-xl px-3 py-2 font-mono text-xs"
            readOnly
            value={challenge.data.signing_payload_base64}
          />
          <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '离线签名 Base64' : 'Offline signature Base64'}
            <textarea
              aria-label={
                locale === 'zh' ? '离线签名 Base64' : 'Offline signature Base64'
              }
              className="app-field min-h-20 w-full rounded-xl px-3 py-2 font-mono text-xs"
              value={signature}
              onChange={(event) => onSignatureChange(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!signature.trim() || verification.isPending}
            onClick={onVerifySignature}
          >
            {verification.isPending
              ? locale === 'zh'
                ? '验证中'
                : 'Verifying'
              : locale === 'zh'
                ? '验证离线签名'
                : 'Verify offline signature'}
          </button>
        </div>
      ) : null}

      {verification.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(verification.error)}
        </div>
      ) : null}
      {verification.data ? (
        <div
          className="mt-2 text-xs text-[var(--app-success-text)]"
          role="status"
        >
          {locale === 'zh'
            ? '可信身份验证通过：'
            : 'Trusted identity verified: '}
          {verification.data.operator_id}
        </div>
      ) : null}
    </div>
  );
}
