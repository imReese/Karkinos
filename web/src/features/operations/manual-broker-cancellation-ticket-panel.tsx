import { useState } from 'react';

import {
  formatPublicCode,
  formatPublicStatus,
} from '../../shared/public-labels';
import {
  useManualBrokerCancellationTicketExportMutation,
  useManualBrokerCancellationTicketPreviewMutation,
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

function lifecycleStatusLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    submitted: { en: 'Submitted', zh: '已提交' },
    open: { en: 'Open', zh: '未终态' },
    partially_filled: { en: 'Partially filled', zh: '部分成交' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function cancellationBlockerLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    manual_broker_cancel_lifecycle_collector_unhealthy: {
      en: 'Lifecycle collector evidence is unhealthy',
      zh: '生命周期采集证据不健康',
    },
    manual_broker_cancel_exact_lifecycle_evidence_unavailable: {
      en: 'Exact lifecycle evidence is unavailable',
      zh: '缺少精确生命周期证据',
    },
    manual_broker_cancel_lifecycle_not_cancellable: {
      en: 'Latest lifecycle status is not cancellable',
      zh: '最新生命周期状态不可撤',
    },
  };
  return labels[value]?.[locale] ?? formatPublicCode(value, locale);
}

export function ManualBrokerCancellationTicketPanel({
  journey,
  locale,
}: {
  journey: ControlledOrderJourney;
  locale: Locale;
}) {
  const [open, setOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);
  const preview = useManualBrokerCancellationTicketPreviewMutation();
  const exportTicket = useManualBrokerCancellationTicketExportMutation();
  const actionable =
    journey.next_operator_action ===
      'review_open_order_or_prepare_manual_cancel_ticket' &&
    Boolean(journey.submit_intent_id);

  if (!actionable) {
    return null;
  }

  const close = () => {
    setOpen(false);
    setAcknowledged(false);
    setCopied(false);
    preview.reset();
    exportTicket.reset();
  };

  const loadPreview = () => {
    setOpen(true);
    setAcknowledged(false);
    setCopied(false);
    exportTicket.reset();
    preview.mutate({ submitIntentId: journey.submit_intent_id });
  };

  const createExport = () => {
    if (!preview.data?.ready || !acknowledged) {
      return;
    }
    setCopied(false);
    exportTicket.mutate({
      submitIntentId: journey.submit_intent_id,
      ticket_fingerprint: preview.data.ticket_fingerprint,
      acknowledgement:
        'prepare_manual_broker_cancellation_ticket_without_broker_contact',
    });
  };

  const copyExport = async () => {
    const content = exportTicket.data?.content;
    if (!content || !navigator.clipboard) {
      return;
    }
    await navigator.clipboard.writeText(content);
    setCopied(true);
  };

  return (
    <div
      data-testid="manual-broker-cancellation-ticket-panel"
      className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] p-3"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '人工券商撤单证据包'
              : 'Manual broker cancellation evidence package'}
          </div>
          <p className="app-muted mt-1 text-xs leading-5">
            {locale === 'zh'
              ? '仅整理已持久化订单与生命周期证据；不会联系券商，也不会改变 OMS。'
              : 'Uses persisted order and lifecycle evidence only; it never contacts a broker or changes OMS.'}
          </p>
        </div>
        <button
          className="app-button-secondary"
          type="button"
          onClick={loadPreview}
        >
          {locale === 'zh' ? '准备撤单资料' : 'Prepare cancellation package'}
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
                ? '读取持久化证据…'
                : 'Reading persisted evidence…'}
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
                    {locale === 'zh' ? '生命周期' : 'Lifecycle'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {lifecycleStatusLabel(
                      preview.data.order.lifecycle_status,
                      locale,
                    )}
                  </div>
                </div>
                <div className="rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">
                    {locale === 'zh' ? '已成交 / 剩余' : 'Filled / remaining'}
                  </div>
                  <div className="mt-1 font-semibold tabular-nums text-[var(--app-text)]">
                    {preview.data.order.filled_quantity} /{' '}
                    {preview.data.order.remaining_quantity}
                  </div>
                </div>
                <div className="min-w-0 rounded-xl border border-[var(--app-border)] px-3 py-2">
                  <div className="app-muted">broker_order_id</div>
                  <div
                    className="mt-1 truncate font-mono text-[var(--app-text)]"
                    title={preview.data.identity.broker_order_id}
                  >
                    {shortenedIdentity(preview.data.identity.broker_order_id)}
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
                {locale === 'zh' ? '证据：' : 'Evidence: '}
                {preview.data.provider || '—'} ·{' '}
                {shortenedIdentity(
                  preview.data.lifecycle_evidence.observation_id,
                )}{' '}
                · {preview.data.lifecycle_evidence.captured_at || '—'}
              </div>

              {preview.data.blockers.length ? (
                <div
                  className="mt-2 text-xs text-[var(--app-danger)]"
                  role="alert"
                >
                  {locale === 'zh' ? '阻断项：' : 'Blockers: '}
                  {preview.data.blockers
                    .map((item) => cancellationBlockerLabel(item, locale))
                    .join(' · ')}
                </div>
              ) : (
                <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-text)]">
                  <input
                    checked={acknowledged}
                    className="mt-1"
                    type="checkbox"
                    onChange={(event) => setAcknowledged(event.target.checked)}
                  />
                  <span>
                    {locale === 'zh'
                      ? '我理解：这只是人工操作资料，不会执行撤单；必须在独立券商界面复核双重订单 ID，之后重新导入生命周期证据。'
                      : 'I understand this is preparation only. I must verify both order IDs in the separate broker interface and ingest newer lifecycle evidence afterward.'}
                  </span>
                </label>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <button
                  className="app-button-primary"
                  type="button"
                  disabled={
                    !preview.data.ready ||
                    !acknowledged ||
                    exportTicket.isPending
                  }
                  onClick={createExport}
                >
                  {exportTicket.isPending
                    ? locale === 'zh'
                      ? '生成中…'
                      : 'Preparing…'
                    : locale === 'zh'
                      ? '生成可复制证据包'
                      : 'Create copyable evidence package'}
                </button>
                <span className="app-muted text-[11px]">
                  {locale === 'zh'
                    ? '无提交、撤单、权限或账本副作用'
                    : 'No submit, cancel, authority, or ledger side effects'}
                </span>
              </div>
            </>
          ) : null}

          {exportTicket.isError ? (
            <p className="mt-2 text-xs text-[var(--app-danger)]" role="alert">
              {locale === 'zh' ? '导出被阻断：' : 'Export blocked: '}
              {mutationError(exportTicket.error)}
            </p>
          ) : null}
          {exportTicket.data ? (
            <div className="mt-3">
              <label
                className="text-xs font-semibold text-[var(--app-text)]"
                htmlFor="manual-cancel-ticket-content"
              >
                {locale === 'zh' ? '证据包 JSON' : 'Evidence package JSON'}
              </label>
              <textarea
                id="manual-cancel-ticket-content"
                className="app-input mt-2 min-h-40 w-full resize-y font-mono text-[11px]"
                readOnly
                value={exportTicket.data.content}
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
                    ? '复制证据包'
                    : 'Copy evidence package'}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
