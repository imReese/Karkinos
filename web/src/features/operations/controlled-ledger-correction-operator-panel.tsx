import { useMemo, useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledLedgerCorrectionApplyMutation,
  useControlledLedgerCorrectionApprovalChallengeMutation,
  useControlledLedgerCorrectionPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
  type ControlledLedgerCorrectionReason,
  type ControlledOrderJourney,
} from './api';

type Locale = 'en' | 'zh';

const correctionReasons: Array<{
  value: ControlledLedgerCorrectionReason;
  en: string;
  zh: string;
}> = [
  {
    value: 'broker_evidence_superseded',
    en: 'Broker evidence was superseded',
    zh: '券商证据已被更新证据取代',
  },
  {
    value: 'duplicate_controlled_posting',
    en: 'Controlled posting was duplicated',
    zh: '受控入账发生重复',
  },
  {
    value: 'operator_confirmed_mapping_error',
    en: 'Operator confirmed a mapping error',
    zh: '操作员确认映射错误',
  },
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

function reasonLabel(reason: ControlledLedgerCorrectionReason, locale: Locale) {
  const item = correctionReasons.find(
    (candidate) => candidate.value === reason,
  );
  return item?.[locale] ?? reason;
}

export function ControlledLedgerCorrectionOperatorPanel({
  journey,
  locale,
}: {
  journey: ControlledOrderJourney;
  locale: Locale;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ControlledLedgerCorrectionReason | ''>(
    '',
  );
  const [selectedKeyId, setSelectedKeyId] = useState('');
  const [signature, setSignature] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const postingStage = journey.stages.find(
    (stage) => stage.key === 'reconciled_ledger_posting',
  );
  const correctionStage = journey.stages.find(
    (stage) => stage.key === 'append_only_ledger_correction',
  );
  const postingId = postingStage?.evidence_id ?? '';
  const actionable = Boolean(
    postingId &&
    postingStage?.complete &&
    (postingStage.ledger_entry_count ?? 0) > 0 &&
    !correctionStage?.complete,
  );

  const approvalStatus = useOperatorApprovalStatusQuery(open && actionable);
  const preview = useControlledLedgerCorrectionPreviewMutation();
  const challenge = useControlledLedgerCorrectionApprovalChallengeMutation();
  const verification = useOperatorApprovalVerificationMutation();
  const applyCorrection = useControlledLedgerCorrectionApplyMutation();
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
    applyCorrection.reset();
    setSignature('');
    setAcknowledged(false);
  };

  const resetAfterInputs = () => {
    preview.reset();
    resetSignatureSteps();
  };

  const close = () => {
    setOpen(false);
    setReason('');
    setSelectedKeyId('');
    resetAfterInputs();
  };

  const loadPreview = () => {
    if (!reason || !selectedIdentity) {
      return;
    }
    resetAfterInputs();
    preview.mutate({
      postingId,
      reason_code: reason,
      operator_id: selectedIdentity.operator_id,
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
    applyCorrection.reset();
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
    applyCorrection.mutate({
      postingId,
      reason_code: preview.data.reason_code,
      operator_id: preview.data.operator_id,
      correction_fingerprint: preview.data.correction_fingerprint,
      operator_approval_id: verification.data.approval_id,
      operator_proof_signature_base64: signature.trim(),
      acknowledgement: 'apply_exact_compensating_ledger_correction_once',
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
            ? '发现入账错误？复核追加纠正'
            : 'Posting error? Review append-only correction'}
        </button>
      ) : (
        <section
          aria-label={
            locale === 'zh'
              ? '追加式账本纠正复核'
              : 'Append-only ledger correction review'
          }
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_6%,transparent)] p-3"
          data-testid="controlled-ledger-correction-review"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '已入账事实 → 追加补偿事件'
                  : 'Posted facts → compensating event'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '仅在人工确认原入账错误后使用。系统会从 canonical replay 推导唯一补偿，不删除历史，也不接受手填现金、数量或价格。'
                  : 'Use only after a human confirms the original posting is wrong. Canonical replay derives the exact compensation; history is preserved and cash, quantity, or price cannot be entered manually.'}
              </div>
            </div>
            <button
              type="button"
              className="app-button-secondary min-h-8 rounded-xl px-3 py-1.5 text-xs font-semibold"
              onClick={close}
            >
              {locale === 'zh' ? '关闭' : 'Close'}
            </button>
          </div>

          <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2">
            <div className="min-w-0 break-words">
              {locale === 'zh' ? '订单' : 'Order'}: {journey.order_id || '—'}
            </div>
            <div className="min-w-0 truncate font-mono" title={postingId}>
              posting: {shortenedIdentity(postingId)}
            </div>
          </div>

          <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
            <label className="block min-w-0 text-xs font-semibold text-[var(--app-text)]">
              {locale === 'zh' ? '确认的错误类型' : 'Confirmed error type'}
              <select
                aria-label={
                  locale === 'zh' ? '确认的错误类型' : 'Confirmed error type'
                }
                className="app-input mt-1 min-h-10 w-full rounded-xl px-3 py-2 text-sm"
                value={reason}
                onChange={(event) => {
                  setReason(
                    event.target.value as ControlledLedgerCorrectionReason | '',
                  );
                  resetAfterInputs();
                }}
              >
                <option value="">
                  {locale === 'zh' ? '请选择…' : 'Select…'}
                </option>
                {correctionReasons.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item[locale]}
                  </option>
                ))}
              </select>
            </label>

            <label className="block min-w-0 text-xs font-semibold text-[var(--app-text)]">
              {locale === 'zh' ? '可信操作员身份' : 'Trusted operator identity'}
              <select
                aria-label={
                  locale === 'zh'
                    ? '可信操作员身份'
                    : 'Trusted operator identity'
                }
                className="app-input mt-1 min-h-10 w-full rounded-xl px-3 py-2 text-sm disabled:opacity-50"
                disabled={!eligibleIdentities.length}
                value={effectiveKeyId}
                onChange={(event) => {
                  setSelectedKeyId(event.target.value);
                  resetAfterInputs();
                }}
              >
                {!eligibleIdentities.length ? (
                  <option value="">—</option>
                ) : null}
                {eligibleIdentities.map((identity) => (
                  <option
                    key={`${identity.operator_id}:${identity.key_id}`}
                    value={identity.key_id}
                  >
                    {identity.operator_id} · {identity.key_id}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {approvalStatus.isLoading ? (
            <div className="app-muted mt-2 text-xs">
              {locale === 'zh'
                ? '读取可信身份…'
                : 'Loading trusted identities…'}
            </div>
          ) : null}
          {approvalStatus.isError ? (
            <div
              role="alert"
              className="mt-2 break-words text-xs text-[var(--app-danger)]"
            >
              {mutationError(approvalStatus.error)}
            </div>
          ) : null}
          {!approvalStatus.isLoading && eligibleIdentities.length === 0 ? (
            <div
              role="status"
              className="mt-2 break-words text-xs text-[var(--app-warning)]"
            >
              {locale === 'zh'
                ? '没有已启用的 Ed25519 公钥；纠正预览与应用保持禁用。'
                : 'No enabled Ed25519 public key is configured; correction preview and apply remain disabled.'}
            </div>
          ) : null}

          <button
            type="button"
            className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!reason || !selectedIdentity || preview.isPending}
            onClick={loadPreview}
          >
            {preview.isPending
              ? locale === 'zh'
                ? '推导中'
                : 'Deriving'
              : locale === 'zh'
                ? '生成 canonical replay 纠正预览'
                : 'Generate canonical replay correction preview'}
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
                    ? '确定性补偿预览'
                    : 'Deterministic compensation preview'}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(preview.data.review_status, locale)}
                </span>
              </div>
              <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2 xl:grid-cols-3">
                <div>
                  {locale === 'zh' ? '原因' : 'Reason'}:{' '}
                  {reasonLabel(preview.data.reason_code, locale)}
                </div>
                <div className="font-mono tabular-nums">
                  ledger cutoff #{preview.data.pre_ledger_cutoff_id}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.pre_valuation_snapshot_id}
                >
                  valuation:{' '}
                  {shortenedIdentity(preview.data.pre_valuation_snapshot_id)}
                </div>
                <div className="font-mono tabular-nums">
                  {locale === 'zh' ? '原账本事件' : 'Original entries'}:{' '}
                  {preview.data.original_ledger_entry_ids.join(', ') || '—'}
                </div>
                <div
                  className="min-w-0 truncate"
                  title={preview.data.correction_fingerprint}
                >
                  fingerprint:{' '}
                  {shortenedIdentity(preview.data.correction_fingerprint)}
                </div>
                <div>{preview.data.generated_at}</div>
              </div>

              {preview.data.correction_plan?.symbol ? (
                <div className="mt-3 min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2">
                  <div className="font-semibold text-[var(--app-text)]">
                    {preview.data.correction_plan.symbol} ·{' '}
                    {formatPublicStatus(
                      preview.data.correction_plan.asset_class,
                      locale,
                    )}
                  </div>
                  <div className="mt-2 grid min-w-0 gap-1 font-mono text-[11px] tabular-nums sm:grid-cols-2 xl:grid-cols-3">
                    <div>
                      {locale === 'zh' ? '现金补偿' : 'Cash compensation'}:{' '}
                      {preview.data.correction_plan.cash_delta}
                    </div>
                    <div>
                      {locale === 'zh' ? '数量' : 'Quantity'}:{' '}
                      {preview.data.correction_plan.position_before.quantity} →{' '}
                      {preview.data.correction_plan.position_after.quantity}
                    </div>
                    <div>
                      {locale === 'zh' ? '可用数量' : 'Available'}:{' '}
                      {
                        preview.data.correction_plan.position_before
                          .available_qty
                      }{' '}
                      →{' '}
                      {
                        preview.data.correction_plan.position_after
                          .available_qty
                      }
                    </div>
                    <div>
                      {locale === 'zh' ? '移动成本' : 'Average cost'}:{' '}
                      {preview.data.correction_plan.position_before.avg_cost} →{' '}
                      {preview.data.correction_plan.position_after.avg_cost}
                    </div>
                    <div>
                      {locale === 'zh' ? '已实现盈亏' : 'Realized P/L'}:{' '}
                      {
                        preview.data.correction_plan.position_before
                          .realized_pnl
                      }{' '}
                      →{' '}
                      {preview.data.correction_plan.position_after.realized_pnl}
                    </div>
                    <div>
                      {locale === 'zh' ? '累计费用' : 'Accumulated fees'}:{' '}
                      {
                        preview.data.correction_plan.position_before
                          .commission_paid
                      }{' '}
                      →{' '}
                      {
                        preview.data.correction_plan.position_after
                          .commission_paid
                      }
                    </div>
                    <div>
                      {locale === 'zh' ? '入金变化' : 'Deposit delta'}: 0
                    </div>
                    <div className="sm:col-span-2">
                      {locale === 'zh' ? '生效时间' : 'Effective at'}:{' '}
                      {preview.data.correction_plan.effective_at}
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="app-muted mt-3 text-xs leading-5">
                {locale === 'zh'
                  ? '推导：排除精确原入账事件后的 canonical replay；不删除原历史，不联系 provider，不提交或撤单。'
                  : 'Derivation: canonical replay excluding the exact original posting entries. Original history is preserved; no provider contact, submission, or cancellation occurs.'}
              </div>
              {preview.data.blockers.length ? (
                <div
                  role="alert"
                  className="mt-3 break-words text-xs text-[var(--app-danger)]"
                >
                  {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
                  {preview.data.blockers
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ')}
                </div>
              ) : null}
            </div>
          ) : null}

          {preview.data?.review_ready ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '短时离线签名'
                  : 'Short-lived offline signature'}
              </div>
              <div className="app-muted mt-1 text-xs leading-5">
                {locale === 'zh'
                  ? '使用 scripts/operator_signer.py，expected action 为 reverse_controlled_submission_ledger_posting，artifact type 为 controlled_submission_ledger_correction。只粘贴 detached signature，绝不粘贴私钥。'
                  : 'Use scripts/operator_signer.py with expected action reverse_controlled_submission_ledger_posting and artifact type controlled_submission_ledger_correction. Paste only the detached signature, never the private key.'}
              </div>
              <button
                type="button"
                className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="mt-3 break-words text-xs text-[var(--app-danger)]"
                >
                  {mutationError(challenge.error)}
                </div>
              ) : null}

              {challenge.data ? (
                <div className="mt-3 min-w-0">
                  <label className="block text-xs font-semibold text-[var(--app-text)]">
                    {locale === 'zh'
                      ? '待签 payload（Base64）'
                      : 'Payload to sign (Base64)'}
                    <textarea
                      aria-label={
                        locale === 'zh'
                          ? '待签 payload Base64'
                          : 'Payload to sign Base64'
                      }
                      className="app-input mt-1 min-h-24 w-full resize-y rounded-xl px-3 py-2 font-mono text-xs"
                      readOnly
                      value={challenge.data.signing_payload_base64}
                    />
                  </label>
                  <div className="app-muted mt-1 text-xs">
                    {locale === 'zh' ? '到期' : 'Expires'}:{' '}
                    {challenge.data.expires_at}
                  </div>
                  <label className="mt-3 block text-xs font-semibold text-[var(--app-text)]">
                    Detached signature (Base64)
                    <input
                      aria-label="Detached signature Base64"
                      autoComplete="off"
                      className="app-input mt-1 min-h-10 w-full rounded-xl px-3 py-2 font-mono text-sm"
                      spellCheck={false}
                      type="password"
                      value={signature}
                      onChange={(event) => {
                        setSignature(event.target.value);
                        verification.reset();
                        applyCorrection.reset();
                        setAcknowledged(false);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      signature.trim().length < 80 || verification.isPending
                    }
                    onClick={verifySignature}
                  >
                    {verification.isPending
                      ? locale === 'zh'
                        ? '验证中'
                        : 'Verifying'
                      : locale === 'zh'
                        ? '验证签名'
                        : 'Verify signature'}
                  </button>
                  {verification.isError ? (
                    <div
                      role="alert"
                      className="mt-3 break-words text-xs text-[var(--app-danger)]"
                    >
                      {mutationError(verification.error)}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {verification.data ? (
            <div className="mt-3 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_42%,transparent)] p-3">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {locale === 'zh'
                  ? '最终纠正确认'
                  : 'Final correction confirmation'}
              </div>
              <div className="app-muted mt-1 text-xs leading-5">
                {locale === 'zh'
                  ? '应用时会在同一事务内重新核验原入账、canonical replay、Account Truth、valuation、ledger cutoff/fingerprint 与签名。成功后 Account Truth 必须重新导入复核。'
                  : 'Apply rechecks the original posting, canonical replay, Account Truth, valuation, ledger cutoff/fingerprint, and signature in one transaction. Account Truth must be re-imported and reviewed afterward.'}
              </div>
              <label className="mt-3 flex min-w-0 items-start gap-2 text-xs font-semibold text-[var(--app-text)]">
                <input
                  checked={acknowledged}
                  className="mt-0.5"
                  type="checkbox"
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                <span>
                  {locale === 'zh'
                    ? '我确认仅追加预览中的精确补偿事件一次；原始账本历史必须保留。'
                    : 'I confirm appending only the exact previewed compensation once; the original ledger history must remain.'}
                </span>
              </label>
              <button
                type="button"
                className="app-button-secondary mt-3 inline-flex min-h-9 items-center justify-center rounded-xl border-[var(--app-danger)] px-3 py-2 text-xs font-semibold text-[var(--app-danger)] disabled:cursor-not-allowed disabled:opacity-50"
                disabled={
                  !acknowledged ||
                  applyCorrection.isPending ||
                  applyCorrection.isSuccess
                }
                onClick={apply}
              >
                {applyCorrection.isPending
                  ? locale === 'zh'
                    ? '事务核验并追加中'
                    : 'Rechecking and appending'
                  : locale === 'zh'
                    ? '追加精确补偿事件'
                    : 'Append exact compensating event'}
              </button>
              {applyCorrection.isError ? (
                <div
                  role="alert"
                  className="mt-3 break-words text-xs text-[var(--app-danger)]"
                >
                  {mutationError(applyCorrection.error)}
                </div>
              ) : null}
              {applyCorrection.data ? (
                <div
                  role="status"
                  className="mt-3 break-words text-xs font-semibold text-[var(--app-success)]"
                >
                  {locale === 'zh'
                    ? `纠正已追加至 ledger cutoff #${applyCorrection.data.post_ledger_cutoff_id}；现在必须重新导入并复核 Account Truth。`
                    : `Correction appended at ledger cutoff #${applyCorrection.data.post_ledger_cutoff_id}; Account Truth must now be re-imported and reviewed.`}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
      )}
    </div>
  );
}
