import { useMemo, useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledSessionRevocationApprovalChallengeMutation,
  useControlledSessionRevocationMutation,
  useControlledSessionRevocationPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type ControlledExecutionOperatorSession,
  type ControlledSessionRevocationReason,
} from './api';

type Locale = 'en' | 'zh';

const REVOCATION_REASONS: ControlledSessionRevocationReason[] = [
  'manual_operator_stop',
  'end_of_strategy_window',
  'operational_concern',
  'risk_review',
  'account_or_reconciliation_concern',
];

function mutationError(error: unknown) {
  return error instanceof Error
    ? error.message
    : String(error || 'unknown_error');
}

function shortenedIdentity(value: string) {
  if (value.length <= 20) {
    return value || '—';
  }
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function reasonLabel(
  reason: ControlledSessionRevocationReason,
  locale: Locale,
) {
  const labels: Record<
    ControlledSessionRevocationReason,
    { en: string; zh: string }
  > = {
    manual_operator_stop: {
      en: 'Manual operator stop',
      zh: '操作员主动停止',
    },
    end_of_strategy_window: {
      en: 'End of strategy window',
      zh: '策略窗口结束',
    },
    operational_concern: {
      en: 'Operational concern',
      zh: '运行问题',
    },
    risk_review: { en: 'Risk review', zh: '风险复核' },
    account_or_reconciliation_concern: {
      en: 'Account or reconciliation concern',
      zh: '账户或对账问题',
    },
  };
  return labels[reason][locale];
}

export function ControlledSessionRevocationOperatorPanel({
  session,
  locale,
}: {
  session: ControlledExecutionOperatorSession;
  locale: Locale;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ControlledSessionRevocationReason>(
    'manual_operator_stop',
  );
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const actionable =
    session.persisted_status === 'enabled' &&
    ['current_clear_evidence', 'blocked', 'paused', 'scheduled'].includes(
      session.status,
    );

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledSessionRevocationPreviewMutation();
  const challenge = useControlledSessionRevocationApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const revoke = useControlledSessionRevocationMutation();
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

  if (!actionable) {
    return null;
  }

  const resetSignatureSteps = () => {
    challenge.reset();
    verification.reset();
    revoke.reset();
    setSignature('');
    setAcknowledged(false);
  };

  const close = () => {
    setOpen(false);
    setReason('manual_operator_stop');
    setSelectedKeyId('');
    preview.reset();
    resetSignatureSteps();
  };

  const loadPreview = () => {
    preview.reset();
    resetSignatureSteps();
    preview.mutate({ sessionId: session.session_id, reason_code: reason });
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
    revoke.reset();
    setAcknowledged(false);
    verification.mutate({
      challenge_id: challenge.data.challenge_id,
      signature_base64: signature.trim(),
    });
  };

  const applyRevocation = () => {
    if (!preview.data || !verification.data || !acknowledged) {
      return;
    }
    revoke.mutate({
      sessionId: session.session_id,
      reason_code: reason,
      revocation_fingerprint: preview.data.revocation_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement: 'revoke_exact_controlled_session_no_auto_resume',
    });
  };

  return (
    <div className="mt-3 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-3">
      {!open ? (
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold"
          onClick={() => setOpen(true)}
        >
          {locale === 'zh'
            ? '复核并撤销该会话授权'
            : 'Review and revoke this session authority'}
        </button>
      ) : (
        <section
          aria-label={
            locale === 'zh'
              ? '签名式受控会话撤销'
              : 'Signed controlled-session revocation'
          }
          className="min-w-0 rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] p-3"
        >
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '永久撤销精确会话授权'
                  : 'Permanently revoke exact session authority'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '撤销后该会话不能自动恢复、续期或继续通过运行时准入。本步骤不会提交或撤销券商订单，也不会替代未结订单的生命周期处置。'
                  : 'After revocation this session cannot auto-resume, renew, or pass runtime admission. This step cannot submit or cancel a broker order and does not replace lifecycle handling for an open order.'}
              </div>
            </div>
            <button
              type="button"
              className="app-button-secondary min-h-8 rounded-xl px-3 py-1.5 text-xs"
              onClick={close}
            >
              {locale === 'zh' ? '关闭' : 'Close'}
            </button>
          </div>

          <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2">
            <div className="min-w-0 truncate" title={session.session_id}>
              session: {shortenedIdentity(session.session_id)}
            </div>
            <div className="min-w-0 break-words">
              {locale === 'zh' ? '账户 / 策略' : 'Account / strategy'}:{' '}
              {session.account_alias || '—'} / {session.strategy_id || '—'}
            </div>
            <div className="min-w-0 truncate" title={session.authorization_id}>
              authorization: {shortenedIdentity(session.authorization_id)}
            </div>
            <div className="min-w-0 break-words">
              {locale === 'zh' ? '到期时间' : 'Expiry'}:{' '}
              {session.expires_at || '—'}
            </div>
          </div>

          <label className="mt-3 block text-xs text-[var(--app-text)]">
            <span className="app-muted block pb-1">
              {locale === 'zh' ? '撤销原因' : 'Revocation reason'}
            </span>
            <select
              aria-label={locale === 'zh' ? '撤销原因' : 'Revocation reason'}
              className="app-input min-h-10 w-full"
              value={reason}
              onChange={(event) => {
                setReason(
                  event.target.value as ControlledSessionRevocationReason,
                );
                preview.reset();
                resetSignatureSteps();
              }}
            >
              {REVOCATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {reasonLabel(value, locale)}
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

          {preview.isError ? (
            <div
              role="alert"
              className="mt-2 break-words text-xs text-[var(--app-danger-text)]"
            >
              {mutationError(preview.error)}
            </div>
          ) : null}

          {preview.data ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-[var(--app-text)]">
                  {locale === 'zh'
                    ? '确定性撤销证据'
                    : 'Deterministic revocation evidence'}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(preview.data.status, locale)}
                </span>
              </div>
              <div className="mt-2 grid min-w-0 gap-2 font-mono text-[11px] sm:grid-cols-2">
                <div
                  className="min-w-0 truncate"
                  title={preview.data.revocation_id}
                >
                  revocation: {shortenedIdentity(preview.data.revocation_id)}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.revocation_fingerprint}
                >
                  fingerprint:{' '}
                  {shortenedIdentity(preview.data.revocation_fingerprint)}
                </div>
              </div>
              {!preview.data.ready || preview.data.blockers.length ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger-text)]"
                >
                  {locale === 'zh' ? '阻断项：' : 'Blockers: '}
                  {preview.data.blockers
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ') ||
                    (locale === 'zh'
                      ? '预览未达到可签名状态'
                      : 'Preview is not ready for signature')}
                </div>
              ) : null}
            </div>
          ) : null}

          {preview.data?.ready ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh' ? '离线签名' : 'Offline signature'}
              </div>
              {approvalStatus.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger-text)]"
                >
                  {mutationError(approvalStatus.error)}
                </div>
              ) : null}
              {approvalStatus.isSuccess && !eligibleIdentities.length ? (
                <div className="app-muted mt-2 text-xs leading-5">
                  {locale === 'zh'
                    ? '没有已启用的可信 Ed25519 公钥；撤销保持禁用。'
                    : 'No enabled trusted Ed25519 public key is configured; revocation remains disabled.'}
                </div>
              ) : null}
              {eligibleIdentities.length ? (
                <label className="mt-3 block text-xs text-[var(--app-text)]">
                  <span className="app-muted block pb-1">
                    {locale === 'zh'
                      ? '可信操作员身份'
                      : 'Trusted operator identity'}
                  </span>
                  <select
                    aria-label={
                      locale === 'zh'
                        ? '可信操作员身份'
                        : 'Trusted operator identity'
                    }
                    className="app-input min-h-10 w-full"
                    value={effectiveKeyId}
                    onChange={(event) => {
                      setSelectedKeyId(event.target.value);
                      resetSignatureSteps();
                    }}
                  >
                    {eligibleIdentities.map((identity) => (
                      <option key={identity.key_id} value={identity.key_id}>
                        {identity.operator_id} · {identity.key_id}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}

              <button
                type="button"
                className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
                disabled={!selectedIdentity || challenge.isPending}
                onClick={createChallenge}
              >
                {challenge.isPending
                  ? locale === 'zh'
                    ? '创建中'
                    : 'Creating'
                  : locale === 'zh'
                    ? '创建 3 分钟签名挑战'
                    : 'Create 3-minute signing challenge'}
              </button>
              {challenge.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger-text)]"
                >
                  {mutationError(challenge.error)}
                </div>
              ) : null}

              {challenge.data ? (
                <div className="mt-3 grid min-w-0 gap-3">
                  <label className="block min-w-0 text-xs text-[var(--app-text)]">
                    <span className="app-muted block pb-1">
                      {locale === 'zh'
                        ? '待签名 Payload（Base64）'
                        : 'Payload to sign Base64'}
                    </span>
                    <textarea
                      aria-label={
                        locale === 'zh'
                          ? '待签名 Payload Base64'
                          : 'Payload to sign Base64'
                      }
                      className="app-input min-h-24 w-full resize-y break-all font-mono text-[11px]"
                      readOnly
                      value={challenge.data.signing_payload_base64}
                    />
                  </label>
                  <div className="app-muted break-words text-xs leading-5">
                    {locale === 'zh' ? '有效至：' : 'Expires: '}
                    {challenge.data.expires_at}
                    <br />
                    {locale === 'zh'
                      ? '使用 scripts/operator_signer.py，expected action 为 revoke_controlled_session，artifact type 为 controlled_session_revocation。只粘贴 payload，私钥不得进入 Karkinos。'
                      : 'Use scripts/operator_signer.py with expected action revoke_controlled_session and artifact type controlled_session_revocation. Paste only the payload; the private key must never enter Karkinos.'}
                  </div>
                  <label className="block min-w-0 text-xs text-[var(--app-text)]">
                    <span className="app-muted block pb-1">
                      {locale === 'zh'
                        ? 'Detached signature（Base64）'
                        : 'Detached signature Base64'}
                    </span>
                    <textarea
                      aria-label={
                        locale === 'zh'
                          ? 'Detached signature Base64'
                          : 'Detached signature Base64'
                      }
                      className="app-input min-h-20 w-full resize-y break-all font-mono text-[11px]"
                      value={signature}
                      onChange={(event) => {
                        setSignature(event.target.value);
                        verification.reset();
                        revoke.reset();
                        setAcknowledged(false);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="app-button-secondary min-h-9 justify-self-start rounded-xl px-3 py-2 text-xs font-semibold"
                    disabled={!signature.trim() || verification.isPending}
                    onClick={verifySignature}
                  >
                    {verification.isPending
                      ? locale === 'zh'
                        ? '核验中'
                        : 'Verifying'
                      : locale === 'zh'
                        ? '核验签名'
                        : 'Verify signature'}
                  </button>
                  {verification.isError ? (
                    <div
                      role="alert"
                      className="break-words text-xs text-[var(--app-danger-text)]"
                    >
                      {mutationError(verification.error)}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {verification.data ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[var(--app-danger-border)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '最终撤销确认'
                  : 'Final revocation confirmation'}
              </div>
              <label className="mt-3 flex min-w-0 items-start gap-2 text-xs leading-5 text-[var(--app-text)]">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={acknowledged}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                <span>
                  {locale === 'zh'
                    ? '我确认永久撤销这一精确会话；它不会自动恢复、续期或扩大。本步骤不会撤销任何未结券商订单。'
                    : 'I confirm permanently revoking this exact session. It will not auto-resume, renew, or widen. This step does not cancel any open broker order.'}
                </span>
              </label>
              <button
                type="button"
                className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
                disabled={!acknowledged || revoke.isPending}
                onClick={applyRevocation}
              >
                {revoke.isPending
                  ? locale === 'zh'
                    ? '撤销中'
                    : 'Revoking'
                  : locale === 'zh'
                    ? '永久撤销该会话一次'
                    : 'Permanently revoke this session once'}
              </button>
              {revoke.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger-text)]"
                >
                  {mutationError(revoke.error)}
                </div>
              ) : null}
              {revoke.data ? (
                <div
                  role="status"
                  className="mt-2 break-words text-xs text-[var(--app-success-text)]"
                >
                  {locale === 'zh'
                    ? `会话已撤销（${reasonLabel(revoke.data.reason_code, locale)}）；运行时准入已永久关闭。`
                    : `Session revoked (${reasonLabel(revoke.data.reason_code, locale)}); runtime admission is permanently closed.`}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
