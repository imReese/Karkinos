import type { Locale } from '../../../shared/preferences/context';
import { formatDateTime } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../shared/ui/workbench';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import {
  formatCode,
  formatReconciliationValue,
  statusTone,
} from './account-truth-review-format';
import {
  ReconciliationItemList,
  ReviewItemCard,
} from './account-truth-reconciliation-review';
import { AccountTruthReconciliationLanes } from './account-truth-reconciliation-lanes';
import {
  reportFilters,
  type AccountTruthReviewState,
} from './account-truth-review-state';

export function AccountTruthReconciliationWorkspace({
  locale,
  state,
}: {
  locale: Locale;
  state: AccountTruthReviewState;
}) {
  const text = labels[locale];
  const {
    attentionItems,
    changeFilter,
    detail,
    filter,
    indexedItems,
    recordReview,
    reportHistory,
    reports,
    reviewMutation,
    savedReviewStatus,
    scoreData,
    selectItem,
    selectedItem,
    selectedReport,
    selectReport,
    showMatchedItems,
    toggleMatchedItems,
    visibleItems,
  } = state;

  return (
    <div className="flex min-w-0 flex-col gap-5 sm:gap-6">
      <section
        className="app-workbench-section order-1 min-w-0 px-1 py-4 sm:order-2 sm:px-4"
        data-testid="account-truth-review-workspace"
        id="account-truth-review-workspace"
      >
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{text.reports}</div>
            <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
              {text.reviewWorkspace}
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
              {text.reviewWorkspaceDetail}
            </p>
          </div>
          <span className="shrink-0 text-xs text-[var(--app-text-tertiary)]">
            {detail.isLoading || (!selectedReport && reports.isLoading)
              ? text.loading
              : text.itemCount(detail.data?.items.length ?? 0)}
          </span>
        </div>

        <div
          aria-label={text.reportListLabel}
          className="app-account-truth-filter-rail app-horizontal-scroll-cue mt-4 flex max-w-full gap-1.5 overflow-x-auto overscroll-x-contain border-y border-[var(--app-divider)] py-2 sm:gap-2"
        >
          {reportFilters.map((option) => (
            <button
              key={option.value}
              aria-pressed={filter === option.value}
              type="button"
              className={`min-h-10 shrink-0 rounded-[var(--app-radius-control)] border px-2.5 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:px-3 ${
                filter === option.value
                  ? 'border-[var(--app-accent)] bg-[var(--app-accent-bg)] text-[var(--app-text)]'
                  : 'border-[var(--app-divider)] text-[var(--app-text-secondary)]'
              }`}
              onClick={() => changeFilter(option.value)}
            >
              {option[locale]}
            </button>
          ))}
        </div>

        {selectedReport ? (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(230px,0.55fr)_minmax(0,1.45fr)]">
            <div className="min-w-0">
              <div className="app-type-overline text-[var(--app-text-tertiary)]">
                {text.currentReport}
              </div>
              <div
                className="mt-2 border-l-2 border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] px-3 py-3"
                data-testid="account-truth-current-report"
              >
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <StatusBadge tone={statusTone(selectedReport.status)}>
                    {formatCode(selectedReport.status, locale, 'status')}
                  </StatusBadge>
                  <span className="text-xs font-medium text-[var(--app-text-secondary)]">
                    {selectedReport.unresolved_count} {text.unresolved}
                  </span>
                </div>
                <div className="mt-2 truncate text-sm font-semibold text-[var(--app-text)]">
                  {selectedReport.source_name}
                </div>
                <div className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {text.cashDifference}{' '}
                  {formatReconciliationValue(
                    'cash',
                    selectedReport.cash_difference,
                    locale,
                  )}{' '}
                  · {text.feeDifference}{' '}
                  {formatReconciliationValue(
                    'fee',
                    selectedReport.fee_difference,
                    locale,
                  )}{' '}
                  · {text.taxDifference}{' '}
                  {formatReconciliationValue(
                    'tax',
                    selectedReport.tax_difference,
                    locale,
                  )}
                </div>
                <div className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                  {formatDateTime(selectedReport.created_at)}
                </div>
              </div>

              <AccountTruthReconciliationLanes
                locale={locale}
                report={
                  detail.data?.import_run_id === selectedReport.import_run_id
                    ? detail.data
                    : null
                }
              />

              {reportHistory.length > 0 ? (
                <details
                  className="mt-3 border-y border-[var(--app-divider)]"
                  data-testid="account-truth-report-history-disclosure"
                >
                  <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
                    <span>{text.reportHistoryCount(reportHistory.length)}</span>
                    <span aria-hidden="true">+</span>
                  </summary>
                  <div className="divide-y divide-[var(--app-divider)] border-t border-[var(--app-divider)]">
                    {reportHistory.map((report) => (
                      <button
                        key={report.import_run_id}
                        type="button"
                        className="grid min-h-12 w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                        onClick={() => selectReport(report.import_run_id)}
                      >
                        <StatusBadge tone={statusTone(report.status)}>
                          {formatCode(report.status, locale, 'status')}
                        </StatusBadge>
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-semibold text-[var(--app-text)]">
                            {report.source_name}
                          </span>
                          <span className="app-type-micro block text-[var(--app-text-tertiary)]">
                            {formatDateTime(report.created_at)} ·{' '}
                            {report.unresolved_count} {text.unresolved}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>

            <div className="min-w-0">
              <div className="flex min-w-0 items-center justify-between gap-3 border-b border-[var(--app-divider)] pb-2">
                <h3 className="app-type-subsection-title truncate text-[var(--app-text)]">
                  {attentionItems.length > 0
                    ? text.attentionItems
                    : text.reconciliationItems}
                </h3>
                <StatusBadge
                  tone={attentionItems.length > 0 ? 'warning' : 'success'}
                >
                  {text.itemCount(
                    attentionItems.length > 0
                      ? attentionItems.length
                      : indexedItems.length,
                  )}
                </StatusBadge>
              </div>

              {attentionItems.length === 0 && indexedItems.length > 0 ? (
                <EvidenceState
                  kind="ready"
                  statusLabel={formatCode('pass', locale, 'status')}
                  title={text.matchedItems}
                  description={text.matchedItemsQuiet(indexedItems.length)}
                  action={
                    <button
                      type="button"
                      aria-expanded={showMatchedItems}
                      className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
                      onClick={toggleMatchedItems}
                    >
                      {showMatchedItems
                        ? text.hideMatchedItems
                        : text.showMatchedItems(indexedItems.length)}
                    </button>
                  }
                />
              ) : null}

              {detail.isLoading ? (
                <div
                  className="mt-3"
                  data-testid="account-truth-report-detail-loading"
                >
                  <EvidenceState kind="loading" title={text.loading} />
                </div>
              ) : detail.isError ? (
                <EvidenceState
                  className="mt-3"
                  kind="error"
                  title={text.error}
                />
              ) : visibleItems.length > 0 && detail.data ? (
                <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(220px,0.62fr)_minmax(0,1.38fr)]">
                  <ReconciliationItemList
                    ariaLabel={text.itemListLabel}
                    entries={visibleItems}
                    locale={locale}
                    selectedIdentity={selectedItem?.id ?? null}
                    onSelect={selectItem}
                  />
                  {selectedItem ? (
                    <ReviewItemCard
                      item={selectedItem.item}
                      importRunId={detail.data.import_run_id}
                      locale={locale}
                      reviewPending={reviewMutation.isPending}
                      onReview={recordReview}
                    />
                  ) : null}
                </div>
              ) : indexedItems.length === 0 ? (
                <EvidenceState kind="empty" title={text.noItems} />
              ) : null}

              {savedReviewStatus ? (
                <EvidenceState
                  className="mt-3"
                  kind="ready"
                  title={`${text.reviewSaved}: ${formatPublicStatus(
                    savedReviewStatus,
                    locale,
                  )}`}
                />
              ) : null}
              {reviewMutation.isError ? (
                <EvidenceState
                  className="mt-3"
                  kind="error"
                  title={text.reviewFailed}
                />
              ) : null}
            </div>
          </div>
        ) : reports.isLoading ? (
          <div className="mt-4" data-testid="account-truth-reports-loading">
            <EvidenceState kind="loading" title={text.loading} />
          </div>
        ) : reports.isError ? (
          <EvidenceState className="mt-4" kind="error" title={text.error} />
        ) : (
          <EvidenceState className="mt-4" kind="empty" title={text.noReports} />
        )}
      </section>

      <div className="order-2 min-w-0 sm:order-1">
        <MetricStrip
          ariaLabel={text.score}
          items={[
            {
              id: 'score',
              label: text.score,
              value: scoreData?.score ?? text.scorePending,
              detail: `${text.gate}: ${formatCode(
                scoreData?.gate_status ?? '--',
                locale,
                'status',
              )}`,
              tone:
                scoreData?.gate_status === 'blocked' ? 'warning' : 'neutral',
            },
            {
              id: 'unresolved',
              label: text.unresolved,
              value: String(scoreData?.unresolved_mismatch_count ?? '--'),
            },
            {
              id: 'resolved',
              label: text.resolved,
              value: String(scoreData?.resolved_review_count ?? '--'),
            },
            {
              id: 'freshness',
              label: text.freshness,
              value: formatCode(
                scoreData?.data_freshness_status ?? '--',
                locale,
                'status',
              ),
            },
          ]}
        />
      </div>
    </div>
  );
}
