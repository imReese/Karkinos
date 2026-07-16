import { useMemo, useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledBrokerRecoveryApplyMutation,
  useControlledBrokerRecoveryApprovalChallengeMutation,
  useControlledBrokerRecoveryPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type ControlledOrderJourney,
} from './api';

type Locale = 'en' | 'zh';

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

export function ControlledBrokerRecoveryOperatorPanel({
  journey,
  locale,
}: {
  journey: ControlledOrderJourney;
  locale: Locale;
}) {
  const [open, setOpen] = useState(false);
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const actionable =
    [
      'query_submission_outcome_without_resubmit',
      'query_prepared_submission_outcome_without_resubmit',
    ].includes(journey.next_operator_action) &&
    Boolean(journey.submit_intent_id);

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledBrokerRecoveryPreviewMutation();
  const challenge = useControlledBrokerRecoveryApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyRecovery = useControlledBrokerRecoveryApplyMutation();
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

  if (!actionable) {
    return null;
  }

  const resetSignatureSteps = () => {
    challenge.reset();
    verification.reset();
    applyRecovery.reset();
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
    preview.mutate({ submitIntentId: journey.submit_intent_id });
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
    applyRecovery.reset();
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
    applyRecovery.mutate({
      submitIntentId: journey.submit_intent_id,
      recovery_fingerprint: preview.data.recovery_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement: 'query_exact_unknown_submission_once_without_resubmit',
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
            ? '签名查询未知订单结果'
            : 'Sign and query unknown order outcome'}
        </button>
      ) : (
        <section
          aria-label={
            locale === 'zh'
              ? '签名式未知订单查询恢复'
              : 'Signed unknown-order query recovery'
          }
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] p-3"
        >
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '未知提交结果 → 精确只读查询'
                  : 'Unknown submission → exact read-only query'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '只按已持久化的 client order id 查询一次。不会创建或重提订单、撤单、写账本或改变任何资本/执行权限；仅在获得确定证据后收敛既有 OMS 订单状态。'
                  : 'Query exactly once by the persisted client order id. This cannot create or resubmit an order, cancel, post the ledger, or change capital/execution authority; definitive evidence may only resolve the existing OMS order status.'}
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
                ? '生成查询证据预览'
                : 'Generate query evidence preview'}
          </button>

          {preview.isError ? (
            <div
              role="alert"
              className="mt-3 break-words text-xs text-[var(--app-danger)]"
            >
              {mutationError(preview.error)}
            </div>
          ) : null}

          {preview.data ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-[var(--app-text)]">
                  {locale === 'zh' ? '绑定证据' : 'Bound evidence'}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(preview.data.review_status, locale)}
                </span>
              </div>
              <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
                <div>
                  {locale === 'zh' ? '来源状态' : 'Source status'}:{' '}
                  {formatPublicStatus(preview.data.source_status, locale)}
                </div>
                <div className="min-w-0 truncate" title={preview.data.order_id}>
                  {locale === 'zh' ? '订单' : 'Order'}:{' '}
                  {preview.data.order_id || '—'}
                </div>
                <div
                  className="min-w-0 truncate font-mono"
                  title={preview.data.client_order_id}
                >
                  client order:{' '}
                  {shortenedIdentity(preview.data.client_order_id)}
                </div>
                <div
                  className="min-w-0 truncate font-mono"
                  title={preview.data.source_result_fingerprint}
                >
                  source:{' '}
                  {shortenedIdentity(preview.data.source_result_fingerprint)}
                </div>
                <div
                  className="min-w-0 truncate font-mono"
                  title={preview.data.recovery_fingerprint}
                >
                  recovery:{' '}
                  {shortenedIdentity(preview.data.recovery_fingerprint)}
                </div>
                <div>
                  {locale === 'zh' ? '查询能力' : 'Query capability'}:{' '}
                  {preview.data.gateway_query_capability
                    ? locale === 'zh'
                      ? '已声明'
                      : 'declared'
                    : locale === 'zh'
                      ? '不可用'
                      : 'unavailable'}
                </div>
              </div>
              <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                {[
                  locale === 'zh' ? '只读精确查询' : 'Exact read-only query',
                  locale === 'zh' ? '禁止重提' : 'No resubmit',
                  locale === 'zh' ? '禁止撤单' : 'No cancel',
                  locale === 'zh' ? '不写账本' : 'No ledger write',
                  locale === 'zh' ? '不改权限' : 'No authority change',
                ].map((label) => (
                  <span className="app-chip" key={label}>
                    {label}
                  </span>
                ))}
              </div>
              {!preview.data.review_ready || preview.data.blockers.length ? (
                <div
                  role="alert"
                  className="mt-3 break-words text-xs text-[var(--app-danger)]"
                >
                  {locale === 'zh' ? '阻断项：' : 'Blockers: '}
                  {preview.data.blockers
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ') ||
                    (locale === 'zh'
                      ? '预览未达到可签名状态'
                      : 'Preview is not ready for signature')}
                  {preview.data.recovery_wait_remaining_seconds > 0
                    ? ` · ${preview.data.recovery_wait_remaining_seconds}s`
                    : ''}
                </div>
              ) : null}
            </div>
          ) : null}

          {preview.data?.review_ready &&
          preview.data.required_operator_approval ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh' ? '离线签名' : 'Offline signature'}
              </div>
              {approvalStatus.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger)]"
                >
                  {mutationError(approvalStatus.error)}
                </div>
              ) : null}
              {approvalStatus.isSuccess && !eligibleIdentities.length ? (
                <div className="app-muted mt-2 text-xs leading-5">
                  {locale === 'zh'
                    ? '没有与订单操作员匹配且启用的 Ed25519 公钥；查询保持禁用。'
                    : 'No enabled Ed25519 key matches the order operator; the query remains disabled.'}
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
                  className="mt-2 break-words text-xs text-[var(--app-danger)]"
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
                    {locale === 'zh'
                      ? '使用 scripts/operator_signer.py；expected action 为 query_unknown_controlled_broker_submission，artifact type 为 controlled_broker_submission_recovery。只粘贴 payload，不要把私钥放进浏览器。'
                      : 'Use scripts/operator_signer.py with expected action query_unknown_controlled_broker_submission and artifact type controlled_broker_submission_recovery. Paste only the payload; never put the private key in the browser.'}
                  </div>
                  <label className="block min-w-0 text-xs text-[var(--app-text)]">
                    <span className="app-muted block pb-1">
                      Detached signature（Base64）
                    </span>
                    <textarea
                      aria-label="Detached signature Base64"
                      className="app-input min-h-20 w-full resize-y break-all font-mono text-[11px]"
                      value={signature}
                      onChange={(event) => {
                        setSignature(event.target.value);
                        verification.reset();
                        applyRecovery.reset();
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
                      className="break-words text-xs text-[var(--app-danger)]"
                    >
                      {mutationError(verification.error)}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {verification.data ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_38%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh' ? '最终确认' : 'Final query confirmation'}
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
                    ? '我确认只查询预览绑定的 client order id 一次；不得重提、撤单、写账本或改变权限。'
                    : 'I confirm one query for the preview-bound client order id only; no resubmit, cancel, ledger write, or authority change is allowed.'}
                </span>
              </label>
              <button
                type="button"
                className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
                disabled={!acknowledged || applyRecovery.isPending}
                onClick={apply}
              >
                {applyRecovery.isPending
                  ? locale === 'zh'
                    ? '查询中'
                    : 'Querying'
                  : locale === 'zh'
                    ? '执行精确只读查询一次'
                    : 'Run one exact read-only query'}
              </button>
              {applyRecovery.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger)]"
                >
                  {mutationError(applyRecovery.error)}
                </div>
              ) : null}
              {applyRecovery.data ? (
                <div
                  role="status"
                  className="mt-2 break-words text-xs text-[var(--app-success)]"
                >
                  {locale === 'zh'
                    ? `只读查询已审计，结果：${formatPublicStatus(applyRecovery.data.status, locale)}；未重提、未撤单、未写账本。`
                    : `Read-only query audited: ${formatPublicStatus(applyRecovery.data.status, locale)}; no resubmit, cancel, or ledger write occurred.`}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
