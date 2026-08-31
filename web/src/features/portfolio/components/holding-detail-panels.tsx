import { formatTimestamp } from '../../../shared/format';
import {
  ControlledActionZone,
  EvidenceState as WorkbenchEvidenceState,
  MetricStrip as WorkbenchMetricStrip,
  StatusBadge as WorkbenchStatusBadge,
} from '../../../shared/ui/workbench';
import {
  PriceStructureChart,
  PriceStructureLoadingState,
} from '../portfolio-feature-boundary';
import type { HoldingDetailModel } from './holding-detail-model';
import {
  buildBacktestHandoffHref,
  formatAge,
  type HoldingDetailTab,
} from './holding-detail-model-values';
import {
  ActionLink,
  InfoRow,
  LedgerTrace,
  MetricGrid,
} from './holding-detail-primitives';

type HoldingPanelProps = {
  activeTab: HoldingDetailTab;
  model: HoldingDetailModel;
};

export function HoldingPositionPanel({
  activeTab,
  model,
  onRetryKline,
}: HoldingPanelProps & { onRetryKline: () => void }) {
  const { copy, kline, labels } = model.source;
  const { costReferenceLines, hasPersistedPriceStructure, tradeMarkers } =
    model.evidence;
  const { positionSizeMetrics } = model.metrics;
  return (
    <section
      id="holding-panel-position"
      role="tabpanel"
      aria-labelledby="holding-tab-position"
      hidden={activeTab !== 'position'}
      data-testid="holding-kline-panel"
      className="app-workbench-section min-w-0 overflow-hidden"
    >
      {hasPersistedPriceStructure ? (
        <>
          <div className="min-w-0">
            <PriceStructureChart
              bars={kline.data ?? []}
              emptyLabel={copy.market.noChart}
              titleLabel={copy.market.priceRangeKline}
              priceLabel={copy.market.priceLabel}
              rangeLabels={copy.market.klineRanges}
              axisLabels={copy.market.klineAxes}
              rangeAriaLabel={copy.market.showKlineRange}
              markers={tradeMarkers}
              referenceLines={costReferenceLines}
            />
          </div>
          <div data-testid="holding-position-size-metrics" className="mt-4">
            <WorkbenchMetricStrip
              ariaLabel={`${labels.quantity} · ${labels.availableFrozen}`}
              items={positionSizeMetrics.map((metric) => ({
                id: metric.label,
                label: metric.label,
                value: metric.value,
                detail: metric.detail,
                tone: metric.tone,
              }))}
            />
          </div>
        </>
      ) : (
        <div
          data-testid="holding-price-structure-fallback"
          className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.75fr)] lg:items-start"
        >
          <div
            data-testid="holding-position-size-metrics"
            className="order-1 min-w-0"
          >
            <div className="app-product-mark">{labels.positionFacts}</div>
            <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
              {labels.positionFactsDetail}
            </p>
            <WorkbenchMetricStrip
              ariaLabel={`${labels.quantity} · ${labels.availableFrozen}`}
              className="mt-3"
              items={positionSizeMetrics.map((metric) => ({
                id: metric.label,
                label: metric.label,
                value: metric.value,
                detail: metric.detail,
                tone: metric.tone,
              }))}
            />
          </div>
          <div
            data-testid="holding-price-structure-state"
            className="order-2 min-w-0 lg:border-l lg:border-[var(--app-divider)] lg:pl-4"
          >
            <div className="app-product-mark">
              {copy.market.priceRangeKline}
            </div>
            {kline.isLoading ? (
              <PriceStructureLoadingState
                title={copy.market.klineLoading}
                description={copy.market.klineLoadingDetail}
                className="mt-3"
                compact
              />
            ) : kline.isError ? (
              <WorkbenchEvidenceState
                kind="error"
                title={copy.market.klineError}
                description={copy.market.klineErrorDetail}
                className="mt-3"
                action={
                  <button
                    type="button"
                    className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
                    onClick={onRetryKline}
                  >
                    {copy.states.retry}
                  </button>
                }
              />
            ) : (
              <WorkbenchEvidenceState
                kind="missing"
                statusLabel={labels.priceStructureMissing}
                title={copy.market.noChart}
                description={labels.priceStructureMissingDetail}
                evidence={labels.persistedPriceBoundary}
                className="mt-3"
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export function HoldingPnlCostsPanel({ activeTab, model }: HoldingPanelProps) {
  const { labels } = model.source;
  return (
    <section
      id="holding-panel-pnl-costs"
      role="tabpanel"
      aria-labelledby="holding-tab-pnl-costs"
      hidden={activeTab !== 'pnl-costs'}
      data-testid="holding-pnl-costs-panel"
      className="app-workbench-section min-w-0"
    >
      <div className="flex flex-col gap-3">
        <div>
          <div className="app-product-mark">{labels.resultsEvidence}</div>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {labels.pnlCostsDetail}
          </p>
        </div>
        {!model.evidence.evidenceIdentityConsistent ? (
          <WorkbenchEvidenceState
            kind="missing"
            statusLabel={labels.evidenceStates.identityMismatch}
            title={labels.evidenceIdentityMismatch}
            description={labels.evidenceNextSteps.reloadIdentity}
          />
        ) : null}
        {model.market.needsCostBasisReview ? (
          <WorkbenchEvidenceState
            kind="partial"
            statusLabel={labels.evidenceStates.costBasisReview}
            title={labels.costBasisReviewNeeded}
            description={labels.costBasisReviewDetail}
          />
        ) : null}
        <MetricGrid metrics={model.metrics.valuationMetrics} />
      </div>
    </section>
  );
}

export function HoldingTransactionsPanel({
  activeTab,
  model,
}: HoldingPanelProps) {
  const { copy, labels, ledger } = model.source;
  return (
    <section
      id="holding-panel-transactions"
      role="tabpanel"
      aria-labelledby="holding-tab-transactions"
      hidden={activeTab !== 'transactions'}
      data-testid="holding-transactions-panel"
      className="app-workbench-section min-w-0"
    >
      <div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="app-product-mark">{labels.ledgerTrace}</div>
            <h2 className="app-card-title mt-1.5">
              {ledger.isLoading
                ? copy.states.loading
                : labels.ledgerCount(model.ledgerEntries.length)}
            </h2>
          </div>
          <WorkbenchStatusBadge tone="neutral">
            {labels.productionLedgerOnly}
          </WorkbenchStatusBadge>
          {ledger.isError ? (
            <div className="app-error-text text-sm">{copy.activity.error}</div>
          ) : null}
        </div>
        <LedgerTrace entries={model.ledgerEntries} loading={ledger.isLoading} />
      </div>
    </section>
  );
}

export function HoldingEvidencePanel({
  activeTab,
  model,
  onRefreshQuote,
}: HoldingPanelProps & { onRefreshQuote: () => void }) {
  const {
    isHistoricalClosedPosition,
    labels,
    overview,
    position,
    refreshQuote,
  } = model.source;
  const { marketOpen, refreshPolicyLabel, refreshStatus } = model.evidence;
  const {
    quoteAgeSeconds,
    quoteNeedsReview,
    quoteSourceLabel,
    quoteStatusLabel,
    quoteTimestamp,
    staleReason,
    staleReasonLabel,
  } = model.market;
  const {
    attributionNextAction,
    attributionReadinessItems,
    attributionReviewReady,
    attributionStatusLabel,
    hasSymbolStrategyEvidence,
    strategyDisplayName,
    strategyEvidenceFillCount,
    strategyEvidenceItems,
    strategyEvidenceRefCount,
  } = model.strategy;
  return (
    <div
      id="holding-panel-evidence"
      role="tabpanel"
      aria-labelledby="holding-tab-evidence"
      hidden={activeTab !== 'evidence'}
      className="min-w-0 space-y-5"
    >
      <section
        data-testid="holding-quote-status-panel"
        className="app-workbench-section min-w-0"
      >
        <div>
          <div className="app-product-mark">{labels.marketEvidence}</div>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {labels.marketEvidenceDetail}
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <InfoRow
              label={labels.quoteStatus}
              value={quoteNeedsReview ? labels.quoteStale : quoteStatusLabel}
              tone={quoteNeedsReview ? 'warning' : undefined}
            />
            <InfoRow
              label={labels.quoteTimestamp}
              value={formatTimestamp(quoteTimestamp)}
            />
            <InfoRow label={labels.quoteSource} value={quoteSourceLabel} />
            <InfoRow
              label={labels.quoteAge}
              value={formatAge(quoteAgeSeconds)}
            />
            <InfoRow
              label={labels.staleReason}
              value={staleReasonLabel}
              tone={staleReason ? 'warning' : undefined}
            />
            <InfoRow
              label={labels.valuationTimestamp}
              value={formatTimestamp(overview.data?.valuation_timestamp)}
            />
            <InfoRow label={labels.refreshPolicy} value={refreshPolicyLabel} />
            <InfoRow
              label={labels.marketOpen}
              value={
                marketOpen === undefined
                  ? '--'
                  : marketOpen
                    ? labels.marketOpen
                    : labels.marketClosed
              }
            />
          </div>
          {!isHistoricalClosedPosition ? (
            <ControlledActionZone
              title={labels.quoteRefreshTitle}
              description={labels.quoteRefreshDetail}
              evidence={`${labels.quoteRefreshBoundary} · ${labels.quoteTimestamp} ${formatTimestamp(
                quoteTimestamp,
              )}`}
              tone="info"
              className="mt-4"
            >
              <button
                type="button"
                className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55"
                disabled={refreshQuote.isPending}
                onClick={onRefreshQuote}
                aria-label={`${labels.refreshQuote}: ${position.symbol}`}
              >
                {refreshQuote.isPending
                  ? labels.refreshingQuote
                  : labels.refreshQuote}
              </button>
            </ControlledActionZone>
          ) : null}
          {refreshStatus ? (
            <div
              className={`mt-3 text-sm ${
                refreshQuote.isError
                  ? 'app-error-text'
                  : 'text-[var(--app-muted)]'
              }`}
              role="status"
              aria-live="polite"
            >
              {refreshStatus}
            </div>
          ) : null}
        </div>
      </section>

      {!isHistoricalClosedPosition ? (
        <section
          data-testid="holding-strategy-attribution-boundary"
          id="holding-strategy-attribution-boundary"
          className="app-workbench-section min-w-0 border-t border-[var(--app-divider)] pt-4"
        >
          <div>
            <div className="app-product-mark">
              {labels.strategyAttributionBoundary}
            </div>
            <WorkbenchEvidenceState
              kind={hasSymbolStrategyEvidence ? 'ready' : 'partial'}
              statusLabel={
                hasSymbolStrategyEvidence
                  ? labels.strategyAttributionLinkedEvidence
                  : labels.strategyAttributionNoLinkedFills
              }
              title={labels.strategyAttributionBoundary}
              description={
                hasSymbolStrategyEvidence
                  ? labels.strategyAttributionLinkedDetail
                  : labels.strategyAttributionDetail
              }
              className="mt-3"
            />
            {attributionReadinessItems.length > 0 ? (
              <div
                data-testid="holding-strategy-attribution-readiness"
                className="mt-4 border-y border-[var(--app-divider)] py-3"
              >
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <div className="app-product-mark">
                    {labels.strategyAttributionReviewReadiness}
                  </div>
                  <WorkbenchStatusBadge
                    tone={attributionReviewReady ? 'success' : 'warning'}
                  >
                    {attributionReviewReady
                      ? labels.strategyAttributionReviewReady
                      : labels.strategyAttributionReviewIncomplete}
                  </WorkbenchStatusBadge>
                </div>
                <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                  {attributionReadinessItems.map((item) => (
                    <li
                      key={item.label}
                      className="flex min-w-0 items-center gap-2 text-sm text-[var(--app-muted)]"
                    >
                      <span
                        className={`h-2 w-2 shrink-0 rounded-full ${
                          item.passed
                            ? 'bg-[var(--app-success-indicator)]'
                            : 'bg-[var(--app-warning-indicator)]'
                        }`}
                      />
                      <span className="min-w-0 break-words">{item.label}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-sm leading-6 text-[var(--app-muted)]">
                  {labels.strategyAttributionReviewBoundary}
                </p>
              </div>
            ) : null}
            {attributionNextAction ? (
              <div
                data-testid="holding-strategy-attribution-next-action"
                className="mt-4 border-l-2 border-[var(--app-accent-border)] pl-3"
              >
                <div className="app-product-mark">
                  {labels.strategyAttributionNextActionTitle}
                </div>
                <p className="mt-2 text-sm leading-6 text-[var(--app-muted)]">
                  {attributionNextAction.detail}
                </p>
                <div className="mt-3">
                  <ActionLink
                    href={attributionNextAction.href}
                    label={attributionNextAction.label}
                  />
                </div>
              </div>
            ) : null}
            {hasSymbolStrategyEvidence ? (
              <div className="mt-4 grid gap-2">
                <InfoRow
                  label={labels.strategyAttributionStrategy}
                  value={strategyDisplayName}
                />
                <InfoRow
                  label={labels.strategyAttributionEvidenceStatus}
                  value={attributionStatusLabel}
                />
                <InfoRow
                  label={labels.strategyAttributionLinkedFillsLabel}
                  value={labels.strategyAttributionLinkedFills(
                    strategyEvidenceFillCount,
                  )}
                />
                <InfoRow
                  label={labels.strategyAttributionEvidenceRefs}
                  value={String(strategyEvidenceRefCount)}
                />
                {strategyEvidenceItems.length > 0 ? (
                  <details
                    data-testid="holding-strategy-evidence-chain"
                    className="mt-3 border-y border-[var(--app-divider)] py-3"
                  >
                    <summary className="min-h-10 cursor-pointer py-2 text-xs font-semibold text-[var(--app-text-secondary)]">
                      {labels.strategyAttributionEvidenceChain}
                    </summary>
                    <ul className="divide-y divide-[var(--app-divider)]">
                      {strategyEvidenceItems.map((item, index) => (
                        <li
                          key={`${item.kind}-${item.auditRef}-${index}`}
                          className="min-w-0 py-2.5"
                        >
                          <div className="text-sm font-semibold text-[var(--app-text)]">
                            {item.label}
                          </div>
                          <div className="mt-1 break-all font-mono text-xs text-[var(--app-muted)]">
                            {labels.strategyAttributionEvidenceAuditRef(
                              item.auditRef,
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            ) : null}
            {!attributionNextAction ? (
              <div className="mt-4">
                <ActionLink
                  href={buildBacktestHandoffHref(
                    position.symbol,
                    model.market.assetClass,
                  )}
                  label={labels.actionStrategyEvidence}
                />
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function HoldingReconciliationPanel({
  activeTab,
  model,
}: HoldingPanelProps) {
  const { labels } = model.source;
  return (
    <section
      id="holding-panel-reconciliation"
      role="tabpanel"
      aria-labelledby="holding-tab-reconciliation"
      hidden={activeTab !== 'reconciliation'}
      data-testid="holding-reconciliation-panel"
      className="app-workbench-section min-w-0"
    >
      <div className="app-product-mark">{labels.reconciliationTitle}</div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {labels.reconciliationDetail}
      </p>
      <WorkbenchEvidenceState
        kind={model.evidence.evidenceStateKind}
        statusLabel={model.evidence.evidenceReviewState}
        title={labels.reconciliationStateTitle}
        description={model.evidence.nextManualStep}
        className="mt-3"
      />
      <MetricGrid metrics={model.metrics.reconciliationMetrics} />
      <div className="mt-4 flex flex-wrap gap-2">
        <ActionLink href="/account-truth" label={labels.actionAccountTruth} />
        <ActionLink href="/market" label={labels.actionMarket} />
      </div>
    </section>
  );
}

export function HoldingRelatedActionsPanel({
  model,
}: {
  model: HoldingDetailModel;
}) {
  const { isHistoricalClosedPosition, labels, position } = model.source;
  return (
    <section
      data-testid="holding-related-actions-panel"
      className="min-w-0 border-t border-[var(--app-divider)] pt-4"
    >
      <div>
        <div className="app-product-mark">{labels.relatedActions}</div>
        <nav
          aria-label={labels.relatedActions}
          className="mt-3 flex flex-wrap gap-2"
        >
          <ActionLink
            href={buildBacktestHandoffHref(
              position.symbol,
              model.market.assetClass,
            )}
            label={labels.actionStrategyResearch}
          />
          <ActionLink href="/portfolio" label={labels.actionPortfolio} />
          <ActionLink href="/market" label={labels.actionMarket} />
          {!isHistoricalClosedPosition ? (
            <ActionLink href="/trading" label={labels.actionTrading} />
          ) : null}
          <ActionLink
            href={`/activity?symbol=${encodeURIComponent(position.symbol)}`}
            label={
              isHistoricalClosedPosition
                ? labels.actionViewActivity
                : labels.actionActivity
            }
          />
        </nav>
      </div>
    </section>
  );
}
