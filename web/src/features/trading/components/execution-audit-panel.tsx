import { ChevronDown } from 'lucide-react';

import { formatTimestamp } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge as WorkbenchStatusBadge,
} from '../../../shared/ui/workbench';
import type { PaperShadowRunReviewResponse } from '../operations-boundary';
import type { FillFact, OrderFact } from '../api';
import {
  formatFillDetail,
  formatOrderFactDetail,
  formatOrderFactTitle,
  instrumentDisplayLabel,
  sideLabel,
  type InstrumentNameLookup,
} from './trading-execution-format';
import {
  latestPaperShadowRunEvidenceItems,
  paperShadowAcceptedReviewEvidenceItems,
  paperShadowRunNeedsReview,
  type PaperShadowRunSummary,
} from './trading-paper-shadow-evidence';

export function ExecutionAuditPanel({
  orders,
  fills,
  loading,
  error,
  instrumentNames,
  shadowRunPending,
  shadowRunResult,
  paperShadowRun,
  reviewPending,
  reviewResult,
  reviewError,
  onRunShadowReview,
  onAcceptSimulationReview,
}: {
  orders: OrderFact[];
  fills: FillFact[];
  loading: boolean;
  error: boolean;
  instrumentNames: InstrumentNameLookup;
  shadowRunPending: boolean;
  shadowRunResult: { processed_count: number; reused_count: number } | null;
  paperShadowRun: PaperShadowRunSummary | null;
  reviewPending: boolean;
  reviewResult: PaperShadowRunReviewResponse | null;
  reviewError: string;
  onRunShadowReview: () => void;
  onAcceptSimulationReview: () => void;
}) {
  const copy = useCopy();
  const labels = copy.trading.page;
  const ledgerDetailLabels = copy.activity.feed.detailFields;
  const { locale } = usePreferences();
  const latestOrders = orders.slice(0, 4);
  const latestFills = fills.slice(0, 4);
  const reviewAccepted =
    reviewResult?.review_status === 'accepted_for_manual_confirmation' ||
    paperShadowRun?.review_status === 'accepted_for_manual_confirmation';
  const needsSimulationReview =
    paperShadowRunNeedsReview(paperShadowRun) && !reviewAccepted;
  const canRecordSimulationReview = needsSimulationReview;
  const latestPaperShadowEvidenceItems = paperShadowRun?.run_id
    ? latestPaperShadowRunEvidenceItems(paperShadowRun, locale)
    : [];
  const acceptedReviewEvidenceItems = reviewAccepted
    ? paperShadowAcceptedReviewEvidenceItems(
        reviewResult,
        paperShadowRun,
        locale,
      )
    : [];
  const evidenceCountLabel =
    locale === 'zh'
      ? `${orders.length} 条订单事实 · ${fills.length} 条成交事实`
      : `${orders.length} order fact${orders.length === 1 ? '' : 's'} · ${fills.length} fill fact${fills.length === 1 ? '' : 's'}`;
  const disclosureStatus = loading
    ? labels.auditLoading
    : error
      ? labels.auditLoadFailed
      : needsSimulationReview
        ? labels.simulationReviewNeedsAttention
        : reviewAccepted
          ? labels.simulationReviewAccepted
          : paperShadowRun?.status
            ? formatPublicStatus(paperShadowRun.status, locale)
            : evidenceCountLabel;
  const disclosureTone = error
    ? 'danger'
    : needsSimulationReview
      ? 'warning'
      : reviewAccepted
        ? 'success'
        : 'neutral';

  return (
    <details
      className="group app-workbench-section min-w-0"
      data-testid="trading-execution-audit-disclosure"
    >
      <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 px-1 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:px-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-product-mark block">
            {labels.executionAudit}
          </span>
          <span className="app-card-title mt-1.5 block">
            {labels.executionAuditTitle}
          </span>
          <span className="app-muted mt-1 block text-sm">
            {evidenceCountLabel}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <WorkbenchStatusBadge tone={disclosureTone}>
            {disclosureStatus}
          </WorkbenchStatusBadge>
          <span className="hidden text-xs font-semibold text-[var(--app-text-secondary)] sm:inline">
            {labels.expandOnDemand}
          </span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 text-[var(--app-text-secondary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </span>
      </summary>

      <div className="min-w-0 border-t border-[var(--app-divider)] px-1 py-4 sm:px-3">
        <p className="app-muted max-w-3xl break-words text-sm leading-6">
          {labels.executionAuditDetail}
        </p>

        <ControlledActionZone
          className="mt-4"
          tone="info"
          title={labels.simulationReviewAction}
          description={labels.simulationReviewActionDetail}
          evidence={
            paperShadowRun?.status
              ? formatPublicStatus(paperShadowRun.status, locale)
              : undefined
          }
        >
          <button
            type="button"
            className="app-button-secondary shrink-0 rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={shadowRunPending}
            onClick={onRunShadowReview}
          >
            {shadowRunPending
              ? labels.runningShadowReview
              : labels.runShadowReview}
          </button>
          {canRecordSimulationReview ? (
            <button
              type="button"
              className="app-button-primary shrink-0 rounded-[var(--app-radius-control)] px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              disabled={reviewPending}
              onClick={onAcceptSimulationReview}
            >
              {reviewPending
                ? labels.recordingSimulationReview
                : labels.recordSimulationReview}
            </button>
          ) : null}
        </ControlledActionZone>

        {shadowRunResult ? (
          <EvidenceState
            className="mt-3"
            kind="ready"
            statusLabel={labels.executionAudit}
            title={labels.shadowRunResult(
              shadowRunResult.processed_count,
              shadowRunResult.reused_count,
            )}
          />
        ) : null}

        {latestPaperShadowEvidenceItems.length > 0 ? (
          <div className="mt-3 border-y border-[var(--app-divider)] px-3 py-3 text-sm">
            <div className="font-semibold text-[var(--app-text)]">
              {locale === 'zh'
                ? '最新模拟与影子运行'
                : 'Latest paper/shadow run'}
            </div>
            <div className="mt-2 grid min-w-0 gap-1 sm:grid-cols-2">
              {latestPaperShadowEvidenceItems.map((item) => (
                <div
                  className="min-w-0 break-words text-[var(--app-soft)]"
                  key={item}
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {needsSimulationReview ? (
          <p className="mt-3 text-sm text-[var(--app-warning-text)]">
            {labels.simulationReviewNeedsAttentionDetail}
          </p>
        ) : null}

        {reviewAccepted && acceptedReviewEvidenceItems.length > 0 ? (
          <div
            className="mt-3 grid gap-1 border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-soft)]"
            data-testid="trading-simulation-review-evidence"
          >
            {acceptedReviewEvidenceItems.map((item) => (
              <div className="min-w-0 break-words" key={item}>
                {item}
              </div>
            ))}
          </div>
        ) : null}

        {reviewError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {labels.simulationReviewFailed} {reviewError}
          </div>
        ) : null}

        {loading ? (
          <EvidenceState
            className="mt-4"
            kind="loading"
            statusLabel={labels.executionAudit}
            title={labels.auditLoading}
          />
        ) : error ? (
          <EvidenceState
            className="mt-4"
            kind="error"
            statusLabel={labels.executionAudit}
            title={labels.auditLoadFailed}
          />
        ) : (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-2">
            <AuditFactList
              title={labels.orderFacts}
              empty={labels.noOrderFacts}
              rows={latestOrders.map((order) => ({
                id: order.order_id,
                title: formatOrderFactTitle(order, locale, instrumentNames),
                detail: formatOrderFactDetail(
                  order,
                  labels,
                  ledgerDetailLabels,
                  locale,
                  instrumentNames,
                ),
                timestamp: order.timestamp,
              }))}
            />
            <AuditFactList
              title={labels.fills}
              empty={labels.noFills}
              rows={latestFills.map((fill) => ({
                id: fill.fill_id ?? fill.order_id,
                title: `${instrumentDisplayLabel(
                  fill,
                  instrumentNames,
                )} · ${sideLabel(fill.side, locale)}`,
                detail: formatFillDetail(
                  fill,
                  labels,
                  ledgerDetailLabels,
                  locale,
                  instrumentNames,
                ),
                timestamp: fill.timestamp,
              }))}
            />
          </div>
        )}
      </div>
    </details>
  );
}

function AuditFactList({
  title,
  empty,
  rows,
}: {
  title: string;
  empty: string;
  rows: Array<{ id: string; title: string; detail: string; timestamp: string }>;
}) {
  return (
    <section className="min-w-0 border-t border-[var(--app-divider)] py-3">
      <div className="app-product-mark">{title}</div>
      {rows.length === 0 ? (
        <div className="app-muted mt-3 text-sm">{empty}</div>
      ) : (
        <div className="mt-2 grid divide-y divide-[var(--app-divider)]">
          {rows.map((row) => (
            <div key={row.id} className="px-1 py-3 text-sm">
              <div className="font-semibold text-[var(--app-text)]">
                {row.title}
              </div>
              <div className="app-muted mt-1 break-words text-xs">
                {row.detail}
              </div>
              <div className="app-muted mt-1 font-mono text-xs tabular-nums">
                {formatTimestamp(row.timestamp)}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
