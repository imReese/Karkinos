import { useMemo, useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledSubmissionClearanceApplyMutation,
  useControlledSubmissionClearanceApprovalChallengeMutation,
  useControlledSubmissionClearancePreviewMutation,
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

export function ControlledTerminalClearanceOperatorPanel({
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
  const reconciliationRunId =
    journey.stages.find((stage) => stage.key === 'execution_reconciliation')
      ?.evidence_id ?? '';
  const actionable =
    journey.next_operator_action === 'preview_terminal_clearance' &&
    Boolean(journey.submit_intent_id) &&
    Boolean(reconciliationRunId);

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledSubmissionClearancePreviewMutation();
  const challenge = useControlledSubmissionClearanceApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyClearance = useControlledSubmissionClearanceApplyMutation();
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
    applyClearance.reset();
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
    preview.mutate({
      submitIntentId: journey.submit_intent_id,
      reconciliation_run_id: reconciliationRunId,
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

  const verifySignature = () => {
    if (!challenge.data || !signature.trim()) {
      return;
    }
    verification.reset();
    applyClearance.reset();
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
    applyClearance.mutate({
      submitIntentId: journey.submit_intent_id,
      reconciliation_run_id: reconciliationRunId,
      clearance_fingerprint: preview.data.clearance_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement:
        'clear_exact_terminal_outcome_without_automatic_ledger_mutation',
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
            ? '复核签名式终态确认'
            : 'Review signed terminal clearance'}
        </button>
      ) : (
        <section
          aria-label={
            locale === 'zh'
              ? '签名式受控订单终态确认'
              : 'Signed controlled-order terminal clearance'
          }
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] p-3"
        >
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '对账证据 → 精确终态确认'
                  : 'Reconciled evidence → exact terminal clearance'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '只确认已持久化的完整成交、零成交撤单或部分成交后撤单；不会写生产账本、联系券商或授予权限。'
                  : 'Confirm only persisted full-fill, no-fill cancel, or partial-fill-then-cancel evidence. This does not post the production ledger, contact a broker, or grant authority.'}
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
            <div className="min-w-0 truncate" title={journey.submit_intent_id}>
              submit intent: {shortenedIdentity(journey.submit_intent_id)}
            </div>
            <div className="min-w-0 truncate" title={reconciliationRunId}>
              reconciliation: {shortenedIdentity(reconciliationRunId)}
            </div>
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
                ? '生成只读终态预览'
                : 'Generate read-only terminal preview'}
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
                  {locale === 'zh'
                    ? '确定性终态证据'
                    : 'Deterministic terminal evidence'}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(preview.data.review_status, locale)}
                </span>
              </div>
              <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
                <div>
                  {locale === 'zh' ? '终态' : 'Terminal'}:{' '}
                  {formatPublicStatus(preview.data.terminal_status, locale)}
                </div>
                <div className="font-mono tabular-nums">
                  {locale === 'zh' ? '成交数量' : 'Filled quantity'}:{' '}
                  {preview.data.fill_quantity}
                </div>
                <div className="font-mono tabular-nums">
                  {locale === 'zh' ? '撤单数量' : 'Cancelled quantity'}:{' '}
                  {preview.data.cancelled_quantity}
                </div>
                <div className="font-mono tabular-nums">
                  {locale === 'zh' ? '成交笔数' : 'Fills'}:{' '}
                  {preview.data.fill_count}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.account_truth_import_run_id}
                >
                  Account Truth:{' '}
                  {shortenedIdentity(preview.data.account_truth_import_run_id)}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.lifecycle_evidence_fingerprint}
                >
                  lifecycle:{' '}
                  {shortenedIdentity(
                    preview.data.lifecycle_evidence_fingerprint,
                  )}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.broker_evidence_fingerprint}
                >
                  broker evidence:{' '}
                  {shortenedIdentity(preview.data.broker_evidence_fingerprint)}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.clearance_fingerprint}
                >
                  clearance:{' '}
                  {shortenedIdentity(preview.data.clearance_fingerprint)}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.broker_order_id}
                >
                  broker order: {preview.data.broker_order_id || '—'}
                </div>
              </div>

              {preview.data.fills.length ? (
                <div className="mt-3 grid min-w-0 gap-2">
                  {preview.data.fills.map((fill) => (
                    <div
                      className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2"
                      key={fill.fill_id}
                    >
                      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                        <div className="font-semibold text-[var(--app-text)]">
                          {fill.symbol} ·{' '}
                          {formatPublicStatus(fill.side, locale)}
                        </div>
                        <span className="app-chip">
                          {formatPublicStatus(fill.asset_class, locale)}
                        </span>
                      </div>
                      <div className="app-muted mt-1 flex min-w-0 flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] tabular-nums">
                        <span>
                          {locale === 'zh' ? '数量' : 'Quantity'}{' '}
                          {fill.fill_quantity}
                        </span>
                        <span>
                          {locale === 'zh' ? '价格' : 'Price'} {fill.fill_price}
                        </span>
                        <span>
                          {locale === 'zh' ? '费用' : 'Fee'} {fill.fee}
                        </span>
                        <span>
                          {locale === 'zh' ? '税费' : 'Tax'} {fill.tax}
                        </span>
                        <span>
                          {locale === 'zh' ? '过户费' : 'Transfer fee'}{' '}
                          {fill.transfer_fee}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="app-muted mt-3 text-xs">
                  {locale === 'zh'
                    ? '零成交撤单：本次终态确认不会记录成交，也不会写入账本。'
                    : 'No-fill cancel: this clearance records no fill and posts no ledger entry.'}
                </div>
              )}

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
                    ? '没有与订单操作员匹配且启用的 Ed25519 公钥；终态确认保持禁用。'
                    : 'No enabled Ed25519 public key matches the order operator; clearance remains disabled.'}
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
                    {locale === 'zh' ? '有效至：' : 'Expires: '}
                    {challenge.data.expires_at}
                    <br />
                    {locale === 'zh'
                      ? '使用 scripts/operator_signer.py，expected action 为 clear_controlled_submission_reconciliation，artifact type 为 controlled_submission_reconciliation_clearance。只粘贴 payload，不要粘贴私钥。'
                      : 'Use scripts/operator_signer.py with expected action clear_controlled_submission_reconciliation and artifact type controlled_submission_reconciliation_clearance. Paste only the payload, never the private key.'}
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
                        applyClearance.reset();
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
                {locale === 'zh' ? '最终确认' : 'Final clearance confirmation'}
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
                    ? `我确认只记录预览中的 ${preview.data?.fill_count ?? 0} 笔实际成交和精确终态，并解除该订单互锁；本步骤不会写生产账本。`
                    : `I confirm recording only the ${preview.data?.fill_count ?? 0} previewed actual fill(s) and exact terminal outcome, then releasing this order interlock; this step does not post the production ledger.`}
                </span>
              </label>
              <button
                type="button"
                className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold"
                disabled={!acknowledged || applyClearance.isPending}
                onClick={apply}
              >
                {applyClearance.isPending
                  ? locale === 'zh'
                    ? '记录中'
                    : 'Recording'
                  : locale === 'zh'
                    ? '记录精确终态一次'
                    : 'Record exact terminal outcome once'}
              </button>
              {applyClearance.isError ? (
                <div
                  role="alert"
                  className="mt-2 break-words text-xs text-[var(--app-danger)]"
                >
                  {mutationError(applyClearance.error)}
                </div>
              ) : null}
              {applyClearance.data ? (
                <div
                  role="status"
                  className="mt-2 break-words text-xs text-[var(--app-success)]"
                >
                  {locale === 'zh'
                    ? `终态 ${formatPublicStatus(applyClearance.data.terminal_status, locale)} 已记录；下一步复核签名式账本入账。`
                    : `Terminal ${formatPublicStatus(applyClearance.data.terminal_status, locale)} recorded; review signed ledger posting next.`}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
