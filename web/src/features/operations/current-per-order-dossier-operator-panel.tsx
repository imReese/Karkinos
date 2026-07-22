import { useMemo, useState } from 'react';

import {
  formatPublicOperationalNote,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useCurrentPerOrderConfirmationMutation,
  useCurrentPerOrderDossierApprovalChallengeMutation,
  useCurrentPerOrderDossierCandidatesQuery,
  useCurrentPerOrderDossierPreviewMutation,
  useOperatorApprovalStatusQuery,
  useOperatorApprovalVerificationMutation,
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

function adapterReadOnlyStatusLabel(status: string, locale: Locale) {
  if (status === 'observing_readonly') {
    return locale === 'zh' ? '只读观测中' : 'Read-only observation active';
  }
  return formatPublicStatus(status, locale);
}

export function CurrentPerOrderDossierOperatorPanel({
  locale,
}: {
  locale: Locale;
}) {
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

  return (
    <section
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
      data-testid="current-per-order-dossier-panel"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {locale === 'zh'
                ? '受控执行证据'
                : 'Controlled execution evidence'}
            </div>
            <h2 className="app-card-title mt-1.5">
              {locale === 'zh'
                ? '逐单证据复核（非提交）'
                : 'Per-order evidence review (non-submitting)'}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {locale === 'zh'
                ? '从持久化资本评估自动解析当前订单、前序批次与网关验证指纹，并绑定当前已审查的只读适配器 release。签名只记录 append-only 复核事实，不修改 OMS、账本、风控、kill switch 或资本授权。'
                : 'Resolve current order, prior-batch, and gateway-verification fingerprints from persisted capital evidence, then bind the current reviewed read-only adapter release. The signature records only an append-only review fact and changes no OMS, ledger, risk, kill switch, or capital authority.'}
            </p>
          </div>
          <button
            type="button"
            className="app-button-secondary min-h-9 shrink-0 rounded-xl px-3 py-2 text-xs font-semibold"
            onClick={() => (open ? close() : setOpen(true))}
          >
            {open
              ? locale === 'zh'
                ? '关闭'
                : 'Close'
              : locale === 'zh'
                ? '打开逐单复核'
                : 'Open per-order review'}
          </button>
        </div>

        <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-xs">
          <span className="app-chip">persisted facts only</span>
          <span className="app-chip">broker submit: disabled</span>
          <span className="app-chip">broker cancel: disabled</span>
        </div>

        {open ? (
          <div className="mt-4 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] pt-4">
            {candidates.isLoading ? (
              <div className="app-muted text-sm">
                {locale === 'zh'
                  ? '读取持久化候选订单…'
                  : 'Loading persisted candidates…'}
              </div>
            ) : candidates.isError ? (
              <div className="app-error-text text-sm" role="alert">
                {mutationError(candidates.error)}
              </div>
            ) : candidateRows.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] px-4 py-4 text-sm text-[var(--app-soft)]">
                {locale === 'zh'
                  ? '当前没有 canonical manually_confirmed OMS 订单。系统保持默认关闭，不会创建示例订单或联系券商。'
                  : 'No canonical manually_confirmed OMS order is available. The system stays default-closed and creates no sample order or broker contact.'}
              </div>
            ) : (
              <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                <label className="grid min-w-0 gap-2 text-xs font-semibold text-[var(--app-soft)]">
                  {locale === 'zh'
                    ? `当前逐单候选（${candidateRows.length}）`
                    : `Current candidates (${candidateRows.length})`}
                  <select
                    aria-label={
                      locale === 'zh'
                        ? '选择逐单复核订单'
                        : 'Select order to review'
                    }
                    className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
                    value={effectiveOrderId}
                    onChange={(event) => {
                      setSelectedOrderId(event.target.value);
                      resetPreview();
                    }}
                  >
                    {candidateRows.map((candidate) => (
                      <option
                        key={candidate.order_id}
                        value={candidate.order_id}
                      >
                        {candidate.symbol} · {candidate.side}{' '}
                        {candidate.quantity} · {candidate.order_id}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="app-button-secondary min-h-10 rounded-xl px-4 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!effectiveOrderId || preview.isPending}
                  onClick={loadPreview}
                >
                  {preview.isPending
                    ? locale === 'zh'
                      ? '解析中'
                      : 'Resolving'
                    : locale === 'zh'
                      ? '解析当前精确证据'
                      : 'Resolve current exact evidence'}
                </button>
              </div>
            )}

            {candidates.data?.truncated ? (
              <div className="app-muted mt-2 text-xs">
                {locale === 'zh'
                  ? '候选列表已达到只读查询上限；不会自动扩大扫描范围。'
                  : 'The candidate list reached its read-only limit; the scan is not expanded automatically.'}
              </div>
            ) : null}

            {preview.isError ? (
              <div
                className="app-error-text mt-3 break-words text-sm"
                role="alert"
              >
                {mutationError(preview.error)}
              </div>
            ) : null}

            {preview.data ? (
              <div className="mt-4 min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] p-3 sm:p-4">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-[var(--app-text)]">
                    {preview.data.order.symbol} ·{' '}
                    {formatPublicStatus(preview.data.order.side, locale)}{' '}
                    {preview.data.order.quantity}
                  </div>
                  <span className="app-chip">
                    {formatPublicStatus(preview.data.review_status, locale)}
                  </span>
                </div>
                <div className="mt-3 grid min-w-0 gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
                  <EvidenceMetric
                    label={locale === 'zh' ? '订单' : 'Order'}
                    value={preview.data.order.order_id}
                  />
                  <EvidenceMetric
                    label={locale === 'zh' ? '资本评估' : 'Capital evaluation'}
                    value={shortenedIdentity(
                      preview.data.evidence_resolution
                        .capital_evaluation_input_fingerprint,
                    )}
                  />
                  <EvidenceMetric
                    label={locale === 'zh' ? '前序批次对账' : 'Prior batch'}
                    value={shortenedIdentity(
                      preview.data.evidence_resolution
                        .prior_batch_reconciliation_fingerprint,
                    )}
                  />
                  <EvidenceMetric
                    label={
                      locale === 'zh' ? '网关验证' : 'Gateway verification'
                    }
                    value={shortenedIdentity(
                      preview.data.evidence_resolution
                        .execution_gateway_verification_fingerprint,
                    )}
                  />
                  <EvidenceMetric
                    label={locale === 'zh' ? '策略' : 'Strategy'}
                    value={
                      preview.data.capital_evaluation.scope.strategy_id || '—'
                    }
                  />
                  <EvidenceMetric
                    label={locale === 'zh' ? '账户别名' : 'Account alias'}
                    value={
                      preview.data.capital_evaluation.scope.account_alias || '—'
                    }
                  />
                  <EvidenceMetric
                    label={
                      locale === 'zh' ? '适配器发布证据' : 'Adapter release'
                    }
                    value={shortenedIdentity(
                      preview.data.broker_adapter_release.release
                        ?.release_evidence_ref || '—',
                    )}
                  />
                  <EvidenceMetric
                    label={
                      locale === 'zh'
                        ? '适配器只读状态'
                        : 'Adapter read-only status'
                    }
                    value={adapterReadOnlyStatusLabel(
                      preview.data.broker_adapter_release.release?.status ||
                        preview.data.broker_adapter_release.status,
                      locale,
                    )}
                  />
                  <EvidenceMetric
                    label="kill switch"
                    value={formatPublicStatus(
                      preview.data.kill_switch.status,
                      locale,
                    )}
                  />
                  <EvidenceMetric
                    label="dossier fingerprint"
                    value={shortenedIdentity(preview.data.dossier_fingerprint)}
                  />
                </div>

                {preview.data.review_blockers.length ? (
                  <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-3">
                    <div className="text-xs font-semibold text-[var(--app-text)]">
                      {locale === 'zh'
                        ? '当前证据不足，不能签名'
                        : 'Current evidence is insufficient for signing'}
                    </div>
                    <ul className="mt-2 grid gap-1 pl-5 text-xs text-[var(--app-soft)]">
                      {preview.data.review_blockers.map((blocker) => (
                        <li className="list-disc break-words" key={blocker}>
                          {formatPublicOperationalNote(blocker, locale)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_25%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_5%,transparent)] px-3 py-3 text-xs text-[var(--app-soft)]">
                  {locale === 'zh'
                    ? `提交状态固定为 blocked；仍有 ${preview.data.hard_submission_blockers.length} 个硬门禁。本步骤不会移除这些门禁。`
                    : `Submission remains blocked with ${preview.data.hard_submission_blockers.length} hard gates. This review removes none of them.`}
                </div>

                {preview.data.review_ready ? (
                  <div className="mt-4 min-w-0 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] pt-4">
                    {approvalStatus.isLoading ? (
                      <div className="app-muted text-xs">
                        {locale === 'zh'
                          ? '读取可信操作员身份…'
                          : 'Loading trusted operator identities…'}
                      </div>
                    ) : approvalStatus.isError ? (
                      <div className="app-error-text text-xs" role="alert">
                        {mutationError(approvalStatus.error)}
                      </div>
                    ) : eligibleIdentities.length === 0 ? (
                      <div className="rounded-xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] px-3 py-3 text-xs text-[var(--app-soft)]">
                        {locale === 'zh'
                          ? '未配置启用的 Ed25519 可信操作员公钥，签名步骤保持禁用。'
                          : 'No enabled trusted Ed25519 operator public key is configured; signing stays disabled.'}
                      </div>
                    ) : (
                      <>
                        <label className="grid min-w-0 gap-2 text-xs font-semibold text-[var(--app-soft)] sm:max-w-xl">
                          {locale === 'zh'
                            ? '可信操作员身份'
                            : 'Trusted operator identity'}
                          <select
                            className="app-field min-w-0 rounded-xl px-3 py-2 text-sm"
                            value={effectiveKeyId}
                            onChange={(event) => {
                              setSelectedKeyId(event.target.value);
                              resetSignatureSteps();
                            }}
                          >
                            {eligibleIdentities.map((identity) => (
                              <option
                                key={identity.key_id}
                                value={identity.key_id}
                              >
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
                          {challenge.isPending
                            ? locale === 'zh'
                              ? '创建中'
                              : 'Creating'
                            : locale === 'zh'
                              ? '创建 3 分钟离线签名挑战'
                              : 'Create 3-minute offline signing challenge'}
                        </button>
                      </>
                    )}
                    {challenge.isError ? (
                      <div className="app-error-text mt-3 text-xs" role="alert">
                        {mutationError(challenge.error)}
                      </div>
                    ) : null}
                    {challenge.data ? (
                      <div className="mt-3 min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_25%,transparent)] p-3">
                        <label className="grid min-w-0 gap-2 text-xs font-semibold text-[var(--app-soft)]">
                          {locale === 'zh'
                            ? '离线签名 payload（base64）'
                            : 'Offline signing payload (base64)'}
                          <textarea
                            className="app-field min-h-20 min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
                            readOnly
                            value={challenge.data.signing_payload_base64}
                          />
                        </label>
                        <label className="mt-3 grid min-w-0 gap-2 text-xs font-semibold text-[var(--app-soft)]">
                          {locale === 'zh'
                            ? '粘贴 detached signature（base64）'
                            : 'Paste detached signature (base64)'}
                          <input
                            autoComplete="off"
                            className="app-field min-w-0 rounded-xl px-3 py-2 font-mono text-xs"
                            type="password"
                            value={signature}
                            onChange={(event) => {
                              setSignature(event.target.value);
                              verification.reset();
                              confirmation.reset();
                              setAcknowledged(false);
                            }}
                          />
                        </label>
                        <button
                          type="button"
                          className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={
                            signature.trim().length < 80 ||
                            verification.isPending
                          }
                          onClick={verifySignature}
                        >
                          {verification.isPending
                            ? locale === 'zh'
                              ? '验证中'
                              : 'Verifying'
                            : locale === 'zh'
                              ? '验证离线签名'
                              : 'Verify offline signature'}
                        </button>
                        {verification.isError ? (
                          <div
                            className="app-error-text mt-3 text-xs"
                            role="alert"
                          >
                            {mutationError(verification.error)}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}

            {verification.data ? (
              <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] p-3">
                <label className="flex min-w-0 items-start gap-2 text-xs font-semibold text-[var(--app-text)]">
                  <input
                    checked={acknowledged}
                    className="mt-0.5"
                    type="checkbox"
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  <span>
                    {locale === 'zh'
                      ? '我确认只记录当前精确 dossier 的非授权复核事实；它不是券商指令，也不会恢复或扩大任何权限。'
                      : 'I confirm this records only a non-authorizing review of the exact current dossier. It is not a broker instruction and cannot restore or expand authority.'}
                  </span>
                </label>
                <button
                  type="button"
                  className="app-button-secondary mt-3 min-h-9 rounded-xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!acknowledged || confirmation.isPending}
                  onClick={recordConfirmation}
                >
                  {confirmation.isPending
                    ? locale === 'zh'
                      ? '记录中'
                      : 'Recording'
                    : locale === 'zh'
                      ? '记录非授权逐单复核'
                      : 'Record non-authorizing per-order review'}
                </button>
                {confirmation.isError ? (
                  <div
                    className="app-error-text mt-3 break-words text-xs"
                    role="alert"
                  >
                    {mutationError(confirmation.error)}
                  </div>
                ) : null}
              </div>
            ) : null}

            {confirmation.data ? (
              <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-success)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)] px-3 py-3 text-sm text-[var(--app-success)]">
                {locale === 'zh'
                  ? '逐单复核事实已记录。券商提交、撤单和资本授权仍保持关闭。'
                  : 'The per-order review fact is recorded. Broker submit, cancel, and capital authority remain disabled.'}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function EvidenceMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] px-3 py-2">
      <div className="app-muted text-[11px]">{label}</div>
      <div
        className="mt-1 min-w-0 truncate font-mono text-xs text-[var(--app-text)]"
        title={value}
      >
        {value || '—'}
      </div>
    </div>
  );
}
