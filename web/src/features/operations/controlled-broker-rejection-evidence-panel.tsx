import { useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useControlledBrokerRejectionEvidenceExportMutation,
  useControlledBrokerRejectionEvidencePreviewMutation,
  useControlledBrokerRejectionReviewMutation,
  type ControlledOrderJourney,
} from './api';

type Locale = 'en' | 'zh';

function mutationError(error: unknown) {
  return error instanceof Error
    ? error.message
    : String(error || 'unknown_error');
}

function shortenedIdentity(value: string) {
  if (value.length <= 28) {
    return value || '—';
  }
  return `${value.slice(0, 14)}…${value.slice(-10)}`;
}

function rejectionClassificationLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    local_pre_gateway_rejection: {
      en: 'Blocked before gateway call',
      zh: '网关调用前已阻断',
    },
    definitive_gateway_rejection: {
      en: 'Definitive gateway rejection',
      zh: '网关明确拒绝',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function rejectionBlockerLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    controlled_broker_rejection_evidence_not_required: {
      en: 'The submission is not in the rejected state',
      zh: '该提交并非 rejected 状态',
    },
    controlled_broker_rejection_result_not_definitive: {
      en: 'Persisted rejection evidence is not definitive',
      zh: '持久化拒绝证据并不明确',
    },
    controlled_broker_rejection_order_contract_changed: {
      en: 'The canonical OMS order contract changed',
      zh: '规范 OMS 订单契约已变化',
    },
  };
  return labels[value]?.[locale] ?? formatPublicCode(value, locale);
}

export function ControlledBrokerRejectionEvidencePanel({
  journey,
  locale,
}: {
  journey: ControlledOrderJourney;
  locale: Locale;
}) {
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);
  const [reviewerId, setReviewerId] = useState('');
  const preview = useControlledBrokerRejectionEvidencePreviewMutation();
  const exportEvidence = useControlledBrokerRejectionEvidenceExportMutation();
  const recordReview = useControlledBrokerRejectionReviewMutation();
  const actionable =
    journey.next_operator_action ===
      'review_rejection_evidence_without_retry' &&
    Boolean(journey.submit_intent_id);

  if (!actionable) {
    return null;
  }

  const close = () => {
    setOpen(false);
    setAcknowledged(false);
    setCopied(false);
    setReviewerId('');
    preview.reset();
    exportEvidence.reset();
    recordReview.reset();
  };

  const loadPreview = () => {
    setOpen(true);
    setAcknowledged(false);
    setCopied(false);
    setReviewerId('');
    exportEvidence.reset();
    recordReview.reset();
    preview.mutate({ submitIntentId: journey.submit_intent_id });
  };

  const createExport = () => {
    if (!preview.data?.ready || !acknowledged) {
      return;
    }
    setCopied(false);
    exportEvidence.mutate({
      submitIntentId: journey.submit_intent_id,
      review_fingerprint: preview.data.review_fingerprint,
      acknowledgement:
        'export_exact_rejection_evidence_without_retry_or_authority_change',
    });
  };

  const copyExport = async () => {
    const content = exportEvidence.data?.content;
    if (!content || !navigator.clipboard) {
      return;
    }
    await navigator.clipboard.writeText(content);
    setCopied(true);
  };

  const submitReview = () => {
    const reviewer = reviewerId.trim();
    if (!preview.data?.ready || !acknowledged || !reviewer) {
      return;
    }
    recordReview.mutate({
      submitIntentId: journey.submit_intent_id,
      review_fingerprint: preview.data.review_fingerprint,
      reviewer_id: reviewer,
      disposition: 'acknowledged_no_retry',
      acknowledgement:
        'record_exact_rejection_review_without_retry_or_authority_change',
    });
  };

  return (
    <div
      data-testid="controlled-broker-rejection-evidence-panel"
      className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_6%,transparent)] p-3"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '受控提交拒绝证据'
              : 'Controlled submission rejection evidence'}
          </div>
          <p className="app-muted mt-1 text-xs leading-5">
            {locale === 'zh'
              ? '只读取已净化并持久化的拒绝结果；不会联系券商，也不会重试原订单。'
              : 'Reads only sanitized persisted rejection facts; it never contacts a broker or retries the order.'}
          </p>
        </div>
        <button
          className="app-button-secondary"
          type="button"
          onClick={loadPreview}
        >
          {locale === 'zh' ? '复核拒绝证据' : 'Review rejection evidence'}
        </button>
      </div>

      {open ? (
        <div className="mt-3 border-t border-[var(--app-border)] pt-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-semibold text-[var(--app-text)]">
              {locale === 'zh' ? '证据预览' : 'Evidence preview'}
            </span>
            <button className="app-link text-xs" type="button" onClick={close}>
              {locale === 'zh' ? '关闭' : 'Close'}
            </button>
          </div>

          {preview.isPending ? (
            <p className="app-muted mt-2 text-xs">
              {locale === 'zh'
                ? '读取持久化拒绝事实…'
                : 'Reading persisted rejection facts…'}
            </p>
          ) : null}
          {preview.isError ? (
            <p className="mt-2 text-xs text-[var(--app-danger)]" role="alert">
              {locale === 'zh' ? '预览失败：' : 'Preview failed: '}
              {mutationError(preview.error)}
            </p>
          ) : null}

          {preview.data ? (
            <>
              <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">
                    {locale === 'zh' ? '拒绝分类' : 'Classification'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {rejectionClassificationLabel(
                      preview.data.rejection_evidence.classification,
                      locale,
                    )}
                  </div>
                </div>
                <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">
                    {locale === 'zh' ? '结果 / 明确性' : 'Result / definitive'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {formatPublicStatus(
                      preview.data.rejection_evidence.result_status,
                      locale,
                    )}{' '}
                    ·{' '}
                    {preview.data.rejection_evidence.definitive
                      ? locale === 'zh'
                        ? '明确'
                        : 'definitive'
                      : locale === 'zh'
                        ? '本地阻断'
                        : 'local block'}
                  </div>
                </div>
                <div className="min-w-0 rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">gateway_id</div>
                  <div
                    className="mt-1 truncate font-mono text-[var(--app-text)]"
                    title={preview.data.identity.gateway_id}
                  >
                    {shortenedIdentity(preview.data.identity.gateway_id)}
                  </div>
                </div>
                <div className="min-w-0 rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">client_order_id</div>
                  <div
                    className="mt-1 truncate font-mono text-[var(--app-text)]"
                    title={preview.data.identity.client_order_id}
                  >
                    {shortenedIdentity(preview.data.identity.client_order_id)}
                  </div>
                </div>
              </div>

              <div className="app-muted mt-2 break-words text-[11px] leading-5">
                {preview.data.order.symbol} · {preview.data.order.side} ·{' '}
                {preview.data.order.quantity} ·{' '}
                {locale === 'zh' ? '证据时间：' : 'Evidence as of: '}
                {preview.data.rejection_evidence.evidence_as_of || '—'}
              </div>
              {preview.data.rejection_evidence.reason_codes.length ? (
                <div className="app-muted mt-1 break-words text-[11px] leading-5">
                  {locale === 'zh' ? '原因：' : 'Reasons: '}
                  {preview.data.rejection_evidence.reason_codes
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ')}
                </div>
              ) : null}

              {preview.data.blockers.length ? (
                <div
                  className="mt-2 text-xs text-[var(--app-danger)]"
                  role="alert"
                >
                  {locale === 'zh' ? '阻断项：' : 'Blockers: '}
                  {preview.data.blockers
                    .map((item) => rejectionBlockerLabel(item, locale))
                    .join(' · ')}
                </div>
              ) : (
                <div className="mt-3 grid gap-3">
                  <label className="flex items-start gap-2 text-xs leading-5 text-[var(--app-text)]">
                    <input
                      checked={acknowledged}
                      className="mt-1"
                      type="checkbox"
                      onChange={(event) =>
                        setAcknowledged(event.target.checked)
                      }
                    />
                    <span>
                      {locale === 'zh'
                        ? '我理解：原 submit intent 与 client order id 不得重试；若仍需交易，必须从新的 Decision、账户事实、风控、逐单确认与授权证据重新开始。'
                        : 'I understand the persisted submit intent and client order id must not be retried. Any later order starts again from a new Decision, Account Truth, risk, per-order confirmation, and authority review.'}
                    </span>
                  </label>
                  <label
                    className="grid max-w-sm gap-1 text-xs text-[var(--app-text)]"
                    htmlFor="controlled-rejection-reviewer-id"
                  >
                    <span>{locale === 'zh' ? '复核人 ID' : 'Reviewer ID'}</span>
                    <input
                      id="controlled-rejection-reviewer-id"
                      autoComplete="off"
                      className="app-input"
                      maxLength={128}
                      pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
                      placeholder="local-operator"
                      value={reviewerId}
                      onChange={(event) => setReviewerId(event.target.value)}
                    />
                  </label>
                </div>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  className="app-button-secondary"
                  type="button"
                  disabled={
                    !preview.data.ready ||
                    !acknowledged ||
                    exportEvidence.isPending
                  }
                  onClick={createExport}
                >
                  {exportEvidence.isPending
                    ? locale === 'zh'
                      ? '生成中…'
                      : 'Preparing…'
                    : locale === 'zh'
                      ? '生成可复制复核资料'
                      : 'Create copyable review package'}
                </button>
                <button
                  className="app-button-primary"
                  type="button"
                  disabled={
                    !preview.data.ready ||
                    !acknowledged ||
                    !reviewerId.trim() ||
                    recordReview.isPending
                  }
                  onClick={submitReview}
                >
                  {recordReview.isPending
                    ? locale === 'zh'
                      ? '记录中…'
                      : 'Recording…'
                    : locale === 'zh'
                      ? '记录不得重试复核'
                      : 'Record no-retry review'}
                </button>
                <span className="app-muted text-[11px]">
                  {locale === 'zh'
                    ? '无查询、重试、提交、撤单、账本或权限副作用'
                    : 'No query, retry, submit, cancel, ledger, or authority side effects'}
                </span>
              </div>
            </>
          ) : null}

          {exportEvidence.isError ? (
            <p className="mt-2 text-xs text-[var(--app-danger)]" role="alert">
              {locale === 'zh' ? '导出被阻断：' : 'Export blocked: '}
              {mutationError(exportEvidence.error)}
            </p>
          ) : null}
          {recordReview.isError ? (
            <p className="mt-2 text-xs text-[var(--app-danger)]" role="alert">
              {locale === 'zh' ? '复核记录被阻断：' : 'Review record blocked: '}
              {mutationError(recordReview.error)}
            </p>
          ) : null}
          {recordReview.data ? (
            <div
              className="mt-3 rounded-xl border border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)] px-3 py-2 text-xs text-[var(--app-text)]"
              role="status"
            >
              <div className="font-semibold">
                {locale === 'zh'
                  ? '拒绝已复核并记录；不得重试原 intent。'
                  : 'Rejection review recorded; the original intent must not be retried.'}
              </div>
              <div className="app-muted mt-1 break-all font-mono text-[11px]">
                {shortenedIdentity(recordReview.data.review_id)} ·{' '}
                {recordReview.data.reviewer_id} ·{' '}
                {recordReview.data.recorded_at}
              </div>
              <div className="app-muted mt-1 text-[11px]">
                {locale === 'zh'
                  ? '如仍需交易，请新建 Decision 并重新通过账户事实、风控、逐单确认和授权门禁。'
                  : 'If the trade is still needed, create a new Decision and pass Account Truth, risk, per-order confirmation, and authority gates again.'}
              </div>
            </div>
          ) : null}
          {exportEvidence.data ? (
            <div className="mt-3">
              <label
                className="text-xs font-semibold text-[var(--app-text)]"
                htmlFor="controlled-rejection-evidence-content"
              >
                {locale === 'zh' ? '拒绝证据 JSON' : 'Rejection evidence JSON'}
              </label>
              <textarea
                id="controlled-rejection-evidence-content"
                className="app-input mt-2 min-h-40 w-full resize-y font-mono text-[11px]"
                readOnly
                value={exportEvidence.data.content}
              />
              <button
                className="app-button-secondary mt-2"
                type="button"
                onClick={copyExport}
              >
                {copied
                  ? locale === 'zh'
                    ? '已复制'
                    : 'Copied'
                  : locale === 'zh'
                    ? '复制拒绝证据'
                    : 'Copy rejection evidence'}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
