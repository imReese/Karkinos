import { formatQuantity, formatTimestamp } from '../../../shared/format';
import {
  EvidenceIdentityDisclosure,
  EvidenceState as WorkbenchEvidenceState,
  MetricStrip as WorkbenchMetricStrip,
  WorkspaceHeader as WorkbenchWorkspaceHeader,
} from '../../../shared/ui/workbench';
import type { HoldingDetailModel } from './holding-detail-model';
import type { HoldingDetailTab } from './holding-detail-model-values';
import {
  HoldingEvidencePanel,
  HoldingPnlCostsPanel,
  HoldingPositionPanel,
  HoldingReconciliationPanel,
  HoldingRelatedActionsPanel,
  HoldingTransactionsPanel,
} from './holding-detail-panels';
import { HoldingDetailTabs } from './holding-detail-primitives';

export function HoldingDetailView({
  activeTab,
  model,
  onRefreshQuote,
  onRetryKline,
  onTabChange,
}: {
  activeTab: HoldingDetailTab;
  model: HoldingDetailModel;
  onRefreshQuote: () => void;
  onRetryKline: () => void;
  onTabChange: (tab: HoldingDetailTab) => void;
}) {
  const { copy, isHistoricalClosedPosition, labels, position, snapshot } =
    model.source;
  const {
    evidenceIdentityConsistent,
    evidenceReviewState,
    evidenceStateKind,
    nextManualStep,
    valuationSnapshotId,
  } = model.evidence;
  const { displayName, quoteNeedsReview, quoteTimestamp } = model.market;
  return (
    <section className="space-y-5 sm:space-y-6">
      <div data-testid="holding-detail-header">
        <WorkbenchWorkspaceHeader
          eyebrow={labels.kicker}
          title={`${displayName} · ${position.symbol}`}
          description={`${model.market.assetClassDisplay} · ${labels.quantity} ${formatQuantity(
            position.quantity,
          )}`}
          context={`${copy.common.valuationAsOf} ${formatTimestamp(
            snapshot.data?.valuation_as_of,
          )}`}
          actions={
            <>
              <a
                href="/portfolio"
                className="app-button-secondary inline-flex w-max rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                aria-label={labels.returnToPortfolio}
              >
                {labels.backToPortfolio}
              </a>
              {snapshot.data ? (
                <EvidenceIdentityDisclosure
                  triggerLabel={copy.common.viewEvidenceIdentity}
                  title={copy.common.evidenceIdentityTitle}
                  description={copy.common.evidenceIdentityDescription}
                  closeLabel={copy.common.closeEvidenceIdentity}
                  copyLabel={copy.common.copyEvidenceValue}
                  copiedLabel={copy.common.evidenceValueCopied}
                  fields={[
                    {
                      label: copy.common.valuationSnapshot,
                      value: valuationSnapshotId ?? '--',
                      mono: true,
                    },
                    {
                      label: copy.common.ledgerCutoff,
                      value: snapshot.data.ledger_cutoff_id ?? '--',
                      mono: true,
                    },
                    {
                      label: copy.common.valuationAsOf,
                      value: formatTimestamp(snapshot.data.valuation_as_of),
                      mono: true,
                    },
                    {
                      label: copy.common.valuationStatus,
                      value: evidenceReviewState,
                    },
                  ]}
                />
              ) : null}
            </>
          }
        />
      </div>

      <div
        data-testid="holding-detail-overview"
        className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(280px,0.75fr)] xl:items-stretch"
      >
        <WorkbenchEvidenceState
          kind={evidenceStateKind}
          statusLabel={
            isHistoricalClosedPosition
              ? labels.closedHistoryOnly
              : evidenceReviewState
          }
          title={
            quoteNeedsReview && evidenceIdentityConsistent
              ? labels.cacheNotice
              : labels.evidenceSummaryTitle
          }
          description={
            isHistoricalClosedPosition
              ? labels.closedNoCurrentExposure
              : nextManualStep
          }
          evidence={`${labels.valuationTimestamp} ${formatTimestamp(
            snapshot.data?.valuation_as_of,
          )} · ${labels.quoteTimestamp} ${formatTimestamp(quoteTimestamp)}`}
          className="order-2 xl:order-none xl:col-start-2 xl:row-start-1"
        />
        <section className="order-1 min-w-0 xl:order-none xl:col-start-1 xl:row-start-1">
          <div
            data-testid="holding-summary-header"
            className="sr-only"
            aria-hidden="true"
          >
            <span>{displayName}</span>
            <span data-testid="holding-summary-symbol">{position.symbol}</span>
          </div>
          <h2
            data-testid="holding-summary-title"
            className="app-type-section-title mb-2 text-[var(--app-text)]"
          >
            {labels.summary}
          </h2>
          <div data-testid="holding-summary-metrics">
            <WorkbenchMetricStrip
              ariaLabel={labels.summary}
              items={model.metrics.summaryMetrics.map((metric) => ({
                id: metric.label,
                label: metric.label,
                value: metric.value,
                detail: metric.detail,
                tone: metric.tone,
              }))}
              className="app-holding-summary-metrics sm:grid-flow-row sm:grid-cols-2 xl:grid-cols-4"
            />
          </div>
        </section>
      </div>

      <div className="space-y-5">
        <div className="min-w-0 space-y-5">
          <HoldingDetailTabs
            activeTab={activeTab}
            labels={model.metrics.tabLabels}
            onTabChange={onTabChange}
          />
          <HoldingPositionPanel
            activeTab={activeTab}
            model={model}
            onRetryKline={onRetryKline}
          />
          <HoldingPnlCostsPanel activeTab={activeTab} model={model} />
          <HoldingTransactionsPanel activeTab={activeTab} model={model} />
        </div>
        <aside className="min-w-0 space-y-5">
          <HoldingEvidencePanel
            activeTab={activeTab}
            model={model}
            onRefreshQuote={onRefreshQuote}
          />
          <HoldingReconciliationPanel activeTab={activeTab} model={model} />
          <HoldingRelatedActionsPanel model={model} />
        </aside>
      </div>
    </section>
  );
}
