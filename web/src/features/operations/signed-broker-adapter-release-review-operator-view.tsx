import { formatPublicStatus } from '../../shared/public-labels';
import type {
  SignedBrokerAdapterReleaseReviewDecision,
  SignedBrokerAdapterReleaseReviewDossier,
} from './api';
import type { SignedBrokerAdapterReleaseReviewOperatorController } from './signed-broker-adapter-release-review-operator-controller';

type Locale = 'en' | 'zh';

const DECISIONS: SignedBrokerAdapterReleaseReviewDecision[] = [
  'accepted',
  'rejected',
  'revoked',
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

function decisionLabel(
  decision: SignedBrokerAdapterReleaseReviewDecision,
  locale: Locale,
) {
  const labels: Record<
    SignedBrokerAdapterReleaseReviewDecision,
    { en: string; zh: string }
  > = {
    accepted: { en: 'Accept read-only release', zh: '接受只读 release' },
    rejected: { en: 'Reject candidate release', zh: '拒绝候选 release' },
    revoked: { en: 'Revoke accepted release', zh: '撤销已接受 release' },
  };
  return labels[decision][locale];
}

function ReleaseReviewHeader({
  controller,
  locale,
}: {
  controller: SignedBrokerAdapterReleaseReviewOperatorController;
  locale: Locale;
}) {
  const { open, status, toggleOpen } = controller;
  return (
    <>
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">
            {locale === 'zh'
              ? 'Provider 决策证据'
              : 'Provider decision evidence'}
          </div>
          <h2 className="app-card-title mt-1.5">
            {locale === 'zh'
              ? '签名式只读 Adapter Release 审查'
              : 'Signed read-only adapter release review'}
          </h2>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {locale === 'zh'
              ? '把严格只读 manifest、最新 deterministic conformance、owner decision 与三分钟离线签名绑定为 append-only accept/reject/revoke 证据。它不会选择或联系券商，不注册 adapter，也不授予执行或资本权限。'
              : 'Bind a strict read-only manifest, newest deterministic conformance, owner decision, and three-minute offline signature into append-only accept/reject/revoke evidence. This does not select or contact a broker, register an adapter, or grant execution or capital authority.'}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="app-chip">
            {!open
              ? locale === 'zh'
                ? '决策复核已关闭'
                : 'Decision review closed'
              : status.isLoading
                ? locale === 'zh'
                  ? '读取中'
                  : 'Loading'
                : status.isError
                  ? locale === 'zh'
                    ? '状态不可用'
                    : 'Status unavailable'
                  : locale === 'zh'
                    ? `${status.data?.recorded_review_count ?? 0} 条已记录审查`
                    : `${status.data?.recorded_review_count ?? 0} recorded reviews`}
          </span>
          <button
            type="button"
            className="app-button-secondary min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
            onClick={toggleOpen}
          >
            {open
              ? locale === 'zh'
                ? '关闭'
                : 'Close'
              : locale === 'zh'
                ? '打开 Provider 决策复核'
                : 'Open provider decision review'}
          </button>
        </div>
      </div>
      <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-xs">
        <span className="app-chip">read-only release only</span>
        <span className="app-chip">adapter registration: disabled</span>
        <span className="app-chip">execution authority: unchanged</span>
      </div>
      {open && status.isError ? (
        <div className="app-error-text mt-3 text-sm" role="alert">
          {mutationError(status.error)}
        </div>
      ) : null}
    </>
  );
}

function ReleaseReviewForm({
  controller,
  locale,
}: {
  controller: SignedBrokerAdapterReleaseReviewOperatorController;
  locale: Locale;
}) {
  const {
    decision,
    effectiveManifestText,
    effectiveReleaseRef,
    inputError,
    loadPreview,
    manifestReadOnly,
    onDecisionChange,
    onManifestTextChange,
    onReasonRefChange,
    onReleaseRefChange,
    onReviewIdChange,
    onSourceNameChange,
    preview,
    reasonRef,
    releases,
    revocableReleases,
    reviewId,
    sourceName,
  } = controller;
  return (
    <>
      <div className="grid min-w-0 gap-3 lg:grid-cols-3">
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
          {locale === 'zh' ? '审查决策' : 'Review decision'}
          <select
            aria-label={
              locale === 'zh' ? '选择审查决策' : 'Select review decision'
            }
            className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
            value={decision}
            onChange={(event) =>
              onDecisionChange(
                event.target.value as SignedBrokerAdapterReleaseReviewDecision,
              )
            }
          >
            {DECISIONS.map((item) => (
              <option key={item} value={item}>
                {decisionLabel(item, locale)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
          Review ID
          <input
            aria-label="Adapter release review ID"
            className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
            value={reviewId}
            onChange={(event) => onReviewIdChange(event.target.value)}
            placeholder="adapter-review:2026-001"
          />
        </label>
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
          {locale === 'zh' ? '原因引用' : 'Reason reference'}
          <input
            aria-label="Adapter release reason reference"
            className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
            value={reasonRef}
            onChange={(event) => onReasonRefChange(event.target.value)}
            placeholder="owner-reviewed-boundary:v1"
          />
        </label>
      </div>
      {decision === 'revoked' ? (
        <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
          {locale === 'zh'
            ? '选择当前 accepted release'
            : 'Select current accepted release'}
          <select
            aria-label="Select accepted adapter release to revoke"
            className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
            value={effectiveReleaseRef}
            onChange={(event) => onReleaseRefChange(event.target.value)}
          >
            {revocableReleases.length === 0 ? (
              <option value="">
                {locale === 'zh'
                  ? '没有可撤销 release'
                  : 'No revocable release'}
              </option>
            ) : null}
            {revocableReleases.map((item) => (
              <option
                key={item.release_evidence_ref}
                value={item.release_evidence_ref}
              >
                {item.release_evidence_ref}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {releases.isError ? (
        <div className="app-error-text mt-3 text-xs" role="alert">
          {mutationError(releases.error)}
        </div>
      ) : null}
      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? 'Manifest 来源名称' : 'Manifest source name'}
        <input
          aria-label="Adapter manifest source name"
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={sourceName}
          onChange={(event) => onSourceNameChange(event.target.value)}
        />
      </label>
      <label className="mt-3 grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        Read-only adapter release manifest JSON
        <textarea
          aria-label="Read-only adapter release manifest JSON"
          className="app-field min-h-52 min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
          spellCheck={false}
          readOnly={manifestReadOnly}
          value={effectiveManifestText}
          onChange={(event) => onManifestTextChange(event.target.value)}
          placeholder='{"schema_version":"karkinos.broker_adapter_release_manifest.v1",…}'
        />
      </label>
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
            ? '生成签名审查预览'
            : 'Generate signed review preview'}
      </button>
      {inputError ? (
        <div className="app-error-text mt-2 text-xs" role="alert">
          {inputError}
        </div>
      ) : null}
      {preview.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(preview.error)}
        </div>
      ) : null}
    </>
  );
}

function ReleaseReviewEvidence({
  dossier,
  locale,
}: {
  dossier: SignedBrokerAdapterReleaseReviewDossier;
  locale: Locale;
}) {
  return (
    <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] p-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-[var(--app-text)]">
          {decisionLabel(dossier.decision, locale)} ·{' '}
          {String(dossier.manifest.provider || '—')}
        </span>
        <span className="app-chip">
          {formatPublicStatus(dossier.review_status, locale)}
        </span>
      </div>
      <div
        className="app-muted app-type-micro mt-2 break-all font-mono"
        title={dossier.dossier_fingerprint}
      >
        dossier {shortenedIdentity(dossier.dossier_fingerprint)}
      </div>
      <div className="app-muted mt-2 text-xs">
        conformance: {formatPublicStatus(dossier.conformance.status, locale)} ·
        current review:{' '}
        {formatPublicStatus(dossier.current_review.status, locale)}
      </div>
      {dossier.review_blockers.length ? (
        <ul className="app-error-text mt-2 grid gap-1 text-xs">
          {dossier.review_blockers.map((blocker) => (
            <li key={blocker}>{formatPublicStatus(blocker, locale)}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-[var(--app-success-text)]">
          {locale === 'zh'
            ? '服务端证据已就绪，可以创建三分钟离线签名 challenge。'
            : 'Server evidence is ready for a three-minute offline signing challenge.'}
        </p>
      )}
    </div>
  );
}

function ReleaseReviewSigning({
  controller,
  locale,
}: {
  controller: SignedBrokerAdapterReleaseReviewOperatorController;
  locale: Locale;
}) {
  const {
    acknowledged,
    approvalStatus,
    challenge,
    createChallenge,
    effectiveKeyId,
    eligibleIdentities,
    onAcknowledgedChange,
    onSelectedKeyIdChange,
    onSignatureChange,
    record,
    recordDecision,
    selectedIdentity,
    signature,
    verification,
    verifySignature,
  } = controller;
  return (
    <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] p-3">
      <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        {locale === 'zh' ? '可信签名身份' : 'Trusted signing identity'}
        <select
          aria-label="Adapter review signing identity"
          className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
          value={effectiveKeyId}
          onChange={(event) => onSelectedKeyIdChange(event.target.value)}
        >
          {eligibleIdentities.length === 0 ? (
            <option value="">
              {locale === 'zh'
                ? '无启用的可信身份'
                : 'No enabled trusted identity'}
            </option>
          ) : null}
          {eligibleIdentities.map((identity) => (
            <option key={identity.key_id} value={identity.key_id}>
              {identity.operator_id} · {identity.key_id}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!selectedIdentity || challenge.isPending}
        onClick={createChallenge}
      >
        {locale === 'zh'
          ? '创建三分钟离线签名 challenge'
          : 'Create 3-minute offline signing challenge'}
      </button>
      {challenge.data ? (
        <div className="mt-3 grid min-w-0 gap-2">
          <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            Signing payload Base64
            <input
              className="app-field min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
              readOnly
              value={challenge.data.signing_payload_base64}
            />
          </label>
          <pre className="app-muted min-w-0 overflow-x-auto whitespace-pre-wrap break-all rounded-xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] p-2 text-[length:var(--app-font-size-micro)] leading-5">
            {`printf '%s' '${challenge.data.signing_payload_base64}' | uv run python scripts/broker/operator_signer.py sign --private-key /secure/path/operator.pem --operator-id '${challenge.data.operator_id}' --key-id '${challenge.data.key_id}' --expected-action '${challenge.data.action}' --expected-artifact-type '${challenge.data.artifact_type}'`}
          </pre>
          <label className="grid min-w-0 gap-1.5 text-xs font-semibold text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '离线签名 Base64' : 'Offline signature Base64'}
            <input
              aria-label="Adapter review offline signature Base64"
              className="app-field min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
              value={signature}
              onChange={(event) => onSignatureChange(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="app-button-secondary min-h-9 w-fit rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!signature.trim() || verification.isPending}
            onClick={verifySignature}
          >
            {locale === 'zh' ? '核验离线签名' : 'Verify offline signature'}
          </button>
        </div>
      ) : null}
      {challenge.isError || approvalStatus.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(challenge.error || approvalStatus.error)}
        </div>
      ) : null}
      {verification.data ? (
        <div className="mt-3 grid min-w-0 gap-3">
          <p className="text-xs text-[var(--app-success-text)]">
            {locale === 'zh'
              ? `可信身份已核验：${verification.data.operator_id}`
              : `Trusted identity verified: ${verification.data.operator_id}`}
          </p>
          <label className="flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => onAcknowledgedChange(event.target.checked)}
            />
            <span>
              {locale === 'zh'
                ? '我确认该动作只追加精确 provider-neutral review；不会注册 adapter、联系券商或授予任何执行/资本权限。'
                : 'I confirm this appends only the exact provider-neutral review; it does not register an adapter, contact a broker, or grant execution/capital authority.'}
            </span>
          </label>
          <button
            type="button"
            className="app-button-primary min-h-9 w-fit rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!acknowledged || record.isPending}
            onClick={recordDecision}
          >
            {locale === 'zh'
              ? '记录签名式 Adapter 决策'
              : 'Record signed adapter decision'}
          </button>
        </div>
      ) : null}
      {verification.isError || record.isError ? (
        <div className="app-error-text mt-2 break-words text-xs" role="alert">
          {mutationError(verification.error || record.error)}
        </div>
      ) : null}
      {record.data ? (
        <div className="mt-3 rounded-xl border border-[var(--app-success-border)] p-3 text-xs text-[var(--app-success-text)]">
          {locale === 'zh' ? '已记录：' : 'Recorded: '}
          {record.data.decision} · {record.data.review_id} ·{' '}
          {shortenedIdentity(record.data.review_fingerprint)}
        </div>
      ) : null}
    </div>
  );
}

export function SignedBrokerAdapterReleaseReviewOperatorView({
  controller,
  locale,
}: {
  controller: SignedBrokerAdapterReleaseReviewOperatorController;
  locale: Locale;
}) {
  return (
    <section
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
      data-testid="signed-broker-adapter-release-review-panel"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <ReleaseReviewHeader controller={controller} locale={locale} />
        {controller.open ? (
          <div className="mt-4 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-4">
            <ReleaseReviewForm controller={controller} locale={locale} />
            {controller.preview.data ? (
              <ReleaseReviewEvidence
                dossier={controller.preview.data}
                locale={locale}
              />
            ) : null}
            {controller.preview.data?.review_ready ? (
              <ReleaseReviewSigning controller={controller} locale={locale} />
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
