import { ChevronDown } from 'lucide-react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import type { ManualOrderStatus } from '../api';
import { ManualTicketExportPanel } from './manual-ticket-export-panel';
import { OrderQueue } from './order-queue';
import {
  getErrorMessage,
  STATUS_OPTIONS,
  statusLabel,
  type SideFilter,
} from './trading-execution-format';
import type { TradingPageController } from './use-trading-page-controller';

export function TradingReviewQueue({
  controller,
}: {
  controller: TradingPageController;
}) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const {
    status,
    setStatus,
    symbolFilter,
    setSymbolFilter,
    sideFilter,
    setSideFilter,
    rows,
    orders,
    busy,
    rejectReasons,
    setRejectReasons,
    confirmingRejectId,
    handleConfirm,
    handleReject,
    handleExportTicket,
    exportingOrderId,
    instrumentNames,
    manualTicketExport,
    manualExecutionPreviewResult,
    manualExecutionRecordResult,
    manualExecutionPreview,
    manualExecutionRecord,
    handlePreviewManualExecution,
    handleRecordManualExecution,
    rowError,
    confirmOrder,
    rejectOrder,
  } = controller;

  return (
    <section
      className="app-workbench-section order-1 min-w-0 overflow-hidden"
      data-testid="trading-review-queue"
    >
      <div className="min-w-0 px-1 py-4 sm:px-3">
        <div className="flex min-w-0 flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.filterTitle}</div>
            <h2 className="app-card-title mt-1.5">{labels.ordersTitle}</h2>
            <p className="app-muted mt-2 break-words text-sm">
              {labels.filteredCount(rows.length)}
            </p>
          </div>
          <div className="grid min-w-0 w-full gap-3 sm:grid-cols-[minmax(180px,220px)_minmax(0,1fr)] xl:max-w-[440px] xl:grid-cols-[minmax(150px,180px)_minmax(0,1fr)] 2xl:max-w-[680px] 2xl:grid-cols-[minmax(180px,220px)_minmax(0,1fr)]">
            <label className="grid gap-2 text-sm font-medium">
              {labels.statusFilter}
              <select
                className="app-field rounded-[var(--app-radius-control)] px-4 py-3 text-sm"
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as ManualOrderStatus)
                }
                aria-label={labels.statusFilter}
              >
                {STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option === 'all'
                      ? labels.allStatuses
                      : statusLabel(option, labels, locale)}
                  </option>
                ))}
              </select>
            </label>
            <details
              className="group min-w-0 border-y border-[var(--app-divider)] sm:border-y-0"
              data-testid="trading-secondary-filters"
            >
              <summary
                aria-controls="trading-secondary-filter-fields"
                className="app-button-ghost flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--app-radius-control)] px-3 text-left text-sm font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:min-h-11 [&::-webkit-details-marker]:hidden"
              >
                <span className="min-w-0">
                  <span className="block">{labels.moreFilters}</span>
                  <span className="mt-0.5 block text-xs font-normal text-[var(--app-text-tertiary)]">
                    {labels.moreFiltersDetail}
                  </span>
                </span>
                <ChevronDown
                  aria-hidden="true"
                  className="size-4 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
                  data-testid="trading-secondary-filters-chevron"
                />
              </summary>
              <div
                className="hidden min-w-0 gap-3 pb-3 pt-2 group-open:grid sm:grid-cols-2 sm:pb-0"
                id="trading-secondary-filter-fields"
              >
                <label className="grid gap-2 text-sm font-medium">
                  {labels.symbolFilter}
                  <input
                    name="trading-symbol-filter"
                    autoComplete="off"
                    className="app-field rounded-[var(--app-radius-control)] px-4 py-3 text-sm"
                    value={symbolFilter}
                    onChange={(event) => setSymbolFilter(event.target.value)}
                    placeholder={labels.symbolPlaceholder}
                    aria-label={labels.symbolFilter}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.sideFilter}
                  <select
                    className="app-field rounded-[var(--app-radius-control)] px-4 py-3 text-sm"
                    value={sideFilter}
                    onChange={(event) =>
                      setSideFilter(event.target.value as SideFilter)
                    }
                    aria-label={labels.sideFilter}
                  >
                    <option value="all">{labels.allSides}</option>
                    <option value="buy">{labels.buy}</option>
                    <option value="sell">{labels.sell}</option>
                  </select>
                </label>
              </div>
            </details>
          </div>
        </div>

        <OrderQueue
          orders={rows}
          loading={orders.isLoading}
          error={orders.isError}
          busy={busy}
          rejectReasons={rejectReasons}
          confirmingRejectId={confirmingRejectId}
          onConfirm={handleConfirm}
          onReject={handleReject}
          onExportTicket={handleExportTicket}
          exportingOrderId={exportingOrderId}
          onRejectReasonChange={(orderId, value) =>
            setRejectReasons((current) => ({
              ...current,
              [orderId]: value,
            }))
          }
          instrumentNames={instrumentNames}
        />

        <ManualTicketExportPanel
          result={manualTicketExport.data ?? null}
          executionPreview={manualExecutionPreviewResult}
          executionRecord={manualExecutionRecordResult}
          previewPending={manualExecutionPreview.isPending}
          previewError={
            manualExecutionPreview.isError
              ? getErrorMessage(manualExecutionPreview.error)
              : ''
          }
          recordPending={manualExecutionRecord.isPending}
          recordError={
            manualExecutionRecord.isError
              ? getErrorMessage(manualExecutionRecord.error)
              : ''
          }
          onPreviewExecution={handlePreviewManualExecution}
          onRecordExecution={handleRecordManualExecution}
        />

        {rowError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {rowError}
          </div>
        ) : null}
        {confirmOrder.isError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {getErrorMessage(confirmOrder.error)}
          </div>
        ) : null}
        {rejectOrder.isError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {getErrorMessage(rejectOrder.error)}
          </div>
        ) : null}
        {manualTicketExport.isError ? (
          <div className="app-error-text mt-3 text-sm" role="alert">
            {getErrorMessage(manualTicketExport.error)}
          </div>
        ) : null}
      </div>
    </section>
  );
}
