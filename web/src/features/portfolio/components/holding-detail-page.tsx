import { useMemo } from 'react';

import { useAccountOverviewQuery } from '../../account/api';
import {
  useAccountStrategyAssignmentQuery,
  useAccountStrategyAttributionQuery,
  useAccountStrategyContributionQuery,
  useHoldingStrategyAttributionQuery,
} from '../../account-strategy/api';
import {
  buildAttributionReadinessItems,
  type AttributionReadinessItem,
} from '../../account-strategy/attribution-readiness';
import { useLedgerEntriesQuery, type LedgerEntry } from '../../activity/api';
import {
  formatLedgerActivitySummary,
  formatLedgerCostBasisMethodLabel,
  formatLedgerExecutionDetailLines,
  formatLedgerPublicNote,
} from '../../../shared/ledger-format';
import {
  useMarketDataHealthQuery,
  useKlineQuery,
  useRefreshMarketQuotesMutation,
} from '../../market/api';
import { PriceStructureChart } from '../../market/components/price-structure-chart';
import { useCopy } from '../../../app/copy';
import {
  MetricStrip as WorkbenchMetricStrip,
  WorkspaceHeader as WorkbenchWorkspaceHeader,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatReturnPercent,
  formatTimestamp,
} from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { formatStrategyDisplayName } from '../../../shared/strategy-display';
import {
  useLiveHoldingsQuery,
  usePortfolioSnapshotQuery,
  usePositionsQuery,
  type Position,
} from '../api';

type DetailMetric = {
  label: string;
  value: string;
  tone?: 'pnl-positive' | 'pnl-negative' | 'warning';
};

type EvidenceRefType =
  'signal' | 'action' | 'risk' | 'review' | 'order' | 'fill' | 'unknown';

type EvidenceRefItem = {
  kind: EvidenceRefType;
  label: string;
  auditRef: string;
};

type AttributionNextAction = {
  detail: string;
  href: string;
  label: string;
};

const EVIDENCE_REF_TYPES = new Set<EvidenceRefType>([
  'signal',
  'action',
  'risk',
  'review',
  'order',
  'fill',
]);

function normalizeSymbol(symbol: string) {
  return symbol.trim().toLowerCase();
}

function safeDecodeSymbol(symbol: string) {
  try {
    return decodeURIComponent(symbol);
  } catch {
    return symbol;
  }
}

function resolveQuotePrice(position: Position, livePrice: number | null) {
  if (
    typeof position.latest_price === 'number' &&
    Number.isFinite(position.latest_price)
  ) {
    return position.latest_price;
  }
  if (typeof livePrice === 'number' && Number.isFinite(livePrice)) {
    return livePrice;
  }
  return null;
}

function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(0, Math.round(seconds))}s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function sameEvidenceIdentity(
  snapshotId: string | null | undefined,
  ledgerCutoffId: number | undefined,
  comparisonSnapshotId: string | null | undefined,
  comparisonLedgerCutoffId: number | undefined,
) {
  return (
    Boolean(snapshotId) &&
    Boolean(comparisonSnapshotId) &&
    Number.isInteger(ledgerCutoffId) &&
    Number.isInteger(comparisonLedgerCutoffId) &&
    snapshotId === comparisonSnapshotId &&
    ledgerCutoffId === comparisonLedgerCutoffId
  );
}

function formatCostBasisMethod(
  method: string | null | undefined,
  locale: ReturnType<typeof usePreferences>['locale'],
) {
  return formatLedgerCostBasisMethodLabel(method, locale);
}

function buildBacktestHandoffHref(symbol: string, assetClass: string) {
  const params = new URLSearchParams();
  params.set('symbol', symbol);
  params.set('assetClass', assetClass);
  params.set('source', 'portfolio');
  return `/backtest?${params.toString()}`;
}

function buildEvidenceRefItems(
  refs: string[],
  labels: Record<EvidenceRefType, string>,
  locale: ReturnType<typeof usePreferences>['locale'],
) {
  return refs.map((ref): EvidenceRefItem => {
    const [rawKind, ...auditParts] = ref.split(':');
    const kind = EVIDENCE_REF_TYPES.has(rawKind as EvidenceRefType)
      ? (rawKind as EvidenceRefType)
      : 'unknown';
    const publicReference = formatPublicEvidenceReference(ref, locale);
    const [publicLabel, publicAuditRef] = publicReference.split(' · ');
    const auditRef =
      kind === 'unknown'
        ? publicAuditRef || publicReference
        : auditParts.join(':') || ref;
    return {
      kind,
      label:
        kind === 'unknown'
          ? publicLabel || labels.unknown
          : (labels[kind] ?? labels.unknown),
      auditRef,
    };
  });
}

function buildAttributionNextAction({
  missingItem,
  symbol,
  assetClass,
  labels,
  shouldStartResearchReview = false,
}: {
  missingItem: AttributionReadinessItem | null;
  symbol: string;
  assetClass: string;
  labels: ReturnType<typeof useCopy>['portfolio']['detail'];
  shouldStartResearchReview?: boolean;
}): AttributionNextAction | null {
  if (!missingItem) {
    if (shouldStartResearchReview) {
      return {
        detail: labels.strategyAttributionNextActionResearch,
        href: buildBacktestHandoffHref(symbol, assetClass),
        label: labels.actionStrategyEvidence,
      };
    }
    return null;
  }
  if (
    missingItem.key === 'strategy_signal' ||
    missingItem.key === 'candidate_action' ||
    missingItem.key === 'risk_gate'
  ) {
    return {
      detail: labels.strategyAttributionNextActionResearch,
      href: buildBacktestHandoffHref(symbol, assetClass),
      label: labels.actionStrategyEvidence,
    };
  }
  if (missingItem.key === 'manual_review') {
    return {
      detail: labels.strategyAttributionNextActionManualReview,
      href: '/decision',
      label: labels.strategyAttributionOpenDecisionReview,
    };
  }
  if (
    missingItem.key === 'order_evidence' ||
    missingItem.key === 'fill_evidence'
  ) {
    return {
      detail: labels.strategyAttributionNextActionExecution,
      href: '/trading',
      label: labels.strategyAttributionOpenExecutionReview,
    };
  }
  return {
    detail: labels.strategyAttributionNextActionGeneric,
    href: buildBacktestHandoffHref(symbol, assetClass),
    label: labels.actionStrategyEvidence,
  };
}

export function HoldingDetailPage({ symbol }: { symbol: string }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.portfolio.detail;
  const decodedSymbol = safeDecodeSymbol(symbol);
  const normalizedSymbol = normalizeSymbol(decodedSymbol);
  const positions = usePositionsQuery();
  const snapshot = usePortfolioSnapshotQuery();
  const liveHoldings = useLiveHoldingsQuery();
  const overview = useAccountOverviewQuery();
  const marketHealth = useMarketDataHealthQuery();
  const kline = useKlineQuery(decodedSymbol);
  const ledger = useLedgerEntriesQuery(200);
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const accountStrategyAttribution = useAccountStrategyAttributionQuery();
  const accountStrategyContribution = useAccountStrategyContributionQuery();
  const holdingStrategyAttribution =
    useHoldingStrategyAttributionQuery(decodedSymbol);
  const refreshQuote = useRefreshMarketQuotesMutation();

  const currentPositions = positions.data ?? snapshot.data?.positions ?? [];
  const currentPosition = currentPositions.find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const historicalPosition = (snapshot.data?.closed_positions ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const position = currentPosition ?? historicalPosition;
  const isHistoricalClosedPosition =
    !currentPosition && Boolean(historicalPosition);
  const allocation = (snapshot.data?.allocation ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const liveItem = (liveHoldings.data?.groups ?? [])
    .flatMap((group) => group.items)
    .find((item) => normalizeSymbol(item.symbol) === normalizedSymbol);
  const healthQuote = (marketHealth.data?.quotes ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );

  const symbolLedgerEntries = useMemo(
    () =>
      (ledger.data ?? []).filter(
        (entry) => normalizeSymbol(entry.symbol ?? '') === normalizedSymbol,
      ),
    [ledger.data, normalizedSymbol],
  );
  const ledgerEntries = symbolLedgerEntries.slice(0, 12);

  const coreLoading =
    !position &&
    (positions.isLoading ||
      snapshot.isLoading ||
      liveHoldings.isLoading ||
      overview.isLoading);
  const coreError = positions.isError && snapshot.isError;

  if (coreLoading) {
    return (
      <StatusPanel
        title={copy.states.loading}
        detail={labels.loading}
        tone="neutral"
      />
    );
  }

  if (coreError) {
    return (
      <StatusPanel
        title={copy.states.error}
        detail={labels.error}
        tone="danger"
      />
    );
  }

  if (!position) {
    return (
      <section className="space-y-5 sm:space-y-6">
        <a
          href="/portfolio"
          className="app-button-secondary inline-flex rounded-2xl px-4 py-2 text-sm font-semibold"
        >
          {labels.backToPortfolio}
        </a>
        <StatusPanel
          title={labels.notFoundTitle}
          detail={labels.notFoundDetail}
          tone="neutral"
        />
      </section>
    );
  }

  const quoteStatus =
    position.quote_status ??
    liveItem?.quote_status ??
    overview.data?.quote_status;
  const quoteTimestamp =
    position.quote_timestamp ??
    liveItem?.quote_timestamp ??
    healthQuote?.timestamp;
  const quoteSource =
    position.quote_source ??
    liveItem?.quote_source ??
    healthQuote?.quote_source ??
    null;
  const quoteSourceLabel = quoteSource ?? '--';
  const quoteAgeSeconds =
    position.quote_age_seconds ??
    liveItem?.quote_age_seconds ??
    healthQuote?.quote_age_seconds ??
    null;
  const staleReason =
    position.stale_reason ??
    liveItem?.stale_reason ??
    healthQuote?.stale_reason;
  const staleReasonLabel = formatStaleReason(
    staleReason,
    copy.common.staleReasons,
  );
  const isStale = quoteStatus === 'stale';
  const quoteStatusLabel = quoteStatus
    ? formatPublicStatus(quoteStatus, locale)
    : '--';
  const projectedQuotePrice = resolveQuotePrice(
    position,
    liveItem?.latest_price ?? null,
  );
  const projectedTodayChange = isHistoricalClosedPosition
    ? null
    : (position.today_change ?? liveItem?.today_change ?? null);
  const projectedTodayChangePct = isHistoricalClosedPosition
    ? null
    : (position.today_change_pct ?? liveItem?.today_change_pct ?? null);
  const projectedBaselinePrice =
    position.baseline_price ?? liveItem?.baseline_price;
  const baselineSource =
    position.baseline_source ?? liveItem?.baseline_source ?? 'unavailable';
  const baselineSourceLabel =
    {
      daily_close: labels.baselineSources.dailyClose,
      market_bar_close: labels.baselineSources.marketBarClose,
      previous_close: labels.baselineSources.previousClose,
      previous_quote: labels.baselineSources.previousQuote,
      intraday_trade_cost: labels.baselineSources.intradayTradeCost,
      fallback_close: labels.baselineSources.fallbackClose,
      unavailable: labels.baselineSources.unavailable,
    }[baselineSource] ?? baselineSource;
  const brokerDisplayedCostBasis =
    isFiniteNumber(position.broker_displayed_cost_basis) &&
    position.broker_displayed_cost_basis > 0
      ? position.broker_displayed_cost_basis
      : null;
  const brokerDisplayedUnitCost =
    isFiniteNumber(position.broker_displayed_unit_cost) &&
    position.broker_displayed_unit_cost > 0
      ? position.broker_displayed_unit_cost
      : null;
  const brokerCostBasisDifference = isFiniteNumber(
    position.broker_cost_basis_difference,
  )
    ? position.broker_cost_basis_difference
    : null;
  const costBasisStatus = position.broker_cost_basis_status ?? 'unavailable';
  const isBrokerConfirmedCostBasis = costBasisStatus === 'available';
  const isProjectedLedgerCostBasis =
    costBasisStatus === 'projected_from_ledger';
  const hasBrokerCostBasisEvidence =
    (isBrokerConfirmedCostBasis || isProjectedLedgerCostBasis) &&
    brokerDisplayedUnitCost !== null &&
    brokerDisplayedCostBasis !== null;
  const needsCostBasisReview =
    isBrokerConfirmedCostBasis &&
    hasBrokerCostBasisEvidence &&
    brokerCostBasisDifference !== null &&
    Math.abs(brokerCostBasisDifference) >= 0.005;
  const displayName =
    liveItem?.name ??
    allocation?.name ??
    position.display_name ??
    position.name ??
    position.symbol;
  const assetClass =
    liveItem?.asset_class ??
    allocation?.asset_class ??
    position.asset_class ??
    '--';
  const assetClassDisplay = formatAssetClassLabel(assetClass, copy.common);
  const strategyAssignment = accountStrategy.data ?? null;
  const strategyAttribution = accountStrategyAttribution.data ?? null;
  const strategyContribution = accountStrategyContribution.data ?? null;
  const holdingAttribution = holdingStrategyAttribution.data ?? null;
  const hasHoldingStrategyEvidence =
    holdingAttribution?.assignment_applies_to_symbol === true &&
    (holdingAttribution?.fill_count ?? 0) > 0 &&
    (holdingAttribution?.evidence_refs.length ?? 0) > 0;
  const hasAggregateSymbolStrategyEvidence =
    strategyAssignment?.scope === 'symbol' &&
    normalizeSymbol(strategyAssignment.symbol ?? '') === normalizedSymbol &&
    (strategyAttribution?.fill_count ?? 0) > 0 &&
    (strategyContribution?.linked_fill_count ?? 0) > 0 &&
    (strategyContribution?.evidence_refs.length ?? 0) > 0;
  const hasSymbolStrategyEvidence =
    hasHoldingStrategyEvidence ||
    (!holdingAttribution && hasAggregateSymbolStrategyEvidence);
  const strategyEvidenceFillCount = hasHoldingStrategyEvidence
    ? (holdingAttribution?.fill_count ?? 0)
    : (strategyContribution?.linked_fill_count ?? 0);
  const strategyEvidenceRefCount = hasHoldingStrategyEvidence
    ? (holdingAttribution?.evidence_refs.length ?? 0)
    : (strategyContribution?.evidence_refs.length ?? 0);
  const strategyEvidenceItems = hasHoldingStrategyEvidence
    ? buildEvidenceRefItems(
        holdingAttribution?.evidence_refs ?? [],
        labels.strategyAttributionEvidenceTypeLabels,
        locale,
      )
    : [];
  const attributionReadinessItems = holdingAttribution
    ? buildAttributionReadinessItems(
        {
          signal_count: holdingAttribution.signal_count,
          action_count: holdingAttribution.action_count,
          review_count: holdingAttribution.evidence_refs.filter((ref) =>
            ref.startsWith('review:'),
          ).length,
          risk_decision_count: holdingAttribution.risk_decision_count,
          order_count: holdingAttribution.order_count,
          fill_count: holdingAttribution.fill_count,
          review_prerequisites: holdingAttribution.review_prerequisites,
        },
        labels.strategyAttributionReadinessItems,
      )
    : [];
  const attributionReviewReady =
    attributionReadinessItems.length > 0 &&
    attributionReadinessItems.every((item) => item.passed);
  const attributionNextAction = buildAttributionNextAction({
    missingItem: attributionReadinessItems.find((item) => !item.passed) ?? null,
    symbol: position.symbol,
    assetClass,
    labels,
    shouldStartResearchReview: !hasSymbolStrategyEvidence,
  });
  const strategyDisplayName = formatStrategyDisplayName(
    holdingAttribution?.strategy_id ||
      strategyContribution?.strategy_id ||
      strategyAssignment?.strategy_id
      ? {
          strategy_id:
            holdingAttribution?.strategy_id ??
            strategyContribution?.strategy_id ??
            strategyAssignment?.strategy_id,
          name: strategyAssignment?.strategy_name,
        }
      : null,
    copy.backtest.page.strategyNames,
  );
  const contributionStatusLabel = strategyContribution?.contribution_status
    ? (copy.backtest.page.accountStrategyContributionStatusMap[
        strategyContribution.contribution_status as keyof typeof copy.backtest.page.accountStrategyContributionStatusMap
      ] ?? formatPublicCode(strategyContribution.contribution_status, locale))
    : '--';
  const attributionStatusLabel = holdingAttribution?.attribution_status
    ? formatPublicCode(holdingAttribution.attribution_status, locale)
    : contributionStatusLabel;
  const portfolioWeight = allocation?.weight ?? null;
  const lastLedgerEntry = symbolLedgerEntries[0] ?? null;
  const snapshotIdentityMatchesOverview = sameEvidenceIdentity(
    snapshot.data?.valuation_snapshot_id,
    snapshot.data?.ledger_cutoff_id,
    overview.data?.valuation_snapshot_id,
    overview.data?.ledger_cutoff_id,
  );
  const snapshotIdentityMatchesLive = isHistoricalClosedPosition
    ? true
    : sameEvidenceIdentity(
        snapshot.data?.valuation_snapshot_id,
        snapshot.data?.ledger_cutoff_id,
        liveHoldings.data?.valuation_snapshot_id,
        liveHoldings.data?.ledger_cutoff_id,
      );
  const evidenceIdentityConsistent =
    snapshotIdentityMatchesOverview && snapshotIdentityMatchesLive;
  const quotePrice = evidenceIdentityConsistent ? projectedQuotePrice : null;
  const todayChange = evidenceIdentityConsistent ? projectedTodayChange : null;
  const todayChangePct = evidenceIdentityConsistent
    ? projectedTodayChangePct
    : null;
  const baselinePrice = evidenceIdentityConsistent
    ? projectedBaselinePrice
    : null;
  const pnlPct =
    !isHistoricalClosedPosition && evidenceIdentityConsistent
      ? (liveItem?.since_buy_pnl_pct ?? null)
      : null;
  const evidenceReviewState = isHistoricalClosedPosition
    ? labels.evidenceStates.historicalClosed
    : !evidenceIdentityConsistent
      ? labels.evidenceStates.identityMismatch
      : needsCostBasisReview
        ? labels.evidenceStates.costBasisReview
        : isStale
          ? labels.evidenceStates.staleQuote
          : labels.evidenceStates.complete;
  const nextManualStep = isHistoricalClosedPosition
    ? labels.evidenceNextSteps.reviewHistory
    : !evidenceIdentityConsistent
      ? labels.evidenceNextSteps.reloadIdentity
      : needsCostBasisReview
        ? labels.evidenceNextSteps.reconcileCost
        : isStale
          ? labels.evidenceNextSteps.reviewQuote
          : labels.evidenceNextSteps.none;
  const tradeMarkers = symbolLedgerEntries.flatMap((entry) => {
    const direction = entry.direction?.toLowerCase();
    if (direction !== 'buy' && direction !== 'sell') {
      return [];
    }
    return [
      {
        timestamp: entry.timestamp,
        kind: direction,
        price: entry.price,
        label:
          direction === 'buy' ? labels.chartBuyMarker : labels.chartSellMarker,
      } as const,
    ];
  });
  const costReferenceLines = [
    ...(position.avg_cost > 0
      ? [
          {
            value: position.avg_cost,
            label: labels.chartLocalCostLine,
            tone: 'local' as const,
          },
        ]
      : []),
    ...(brokerDisplayedUnitCost !== null &&
    brokerCostBasisDifference !== null &&
    Math.abs(brokerCostBasisDifference) >= 0.005
      ? [
          {
            value: brokerDisplayedUnitCost,
            label: labels.chartEvidenceCostLine,
            tone: 'broker' as const,
          },
        ]
      : []),
  ];
  const marketOpen = marketHealth.data?.market_open;
  const refreshPolicy = marketHealth.data?.refresh_policy ?? '--';
  const refreshPolicyLabel = marketHealth.data?.refresh_policy
    ? formatPublicStatus(marketHealth.data.refresh_policy, locale)
    : '--';
  const refreshStatus = refreshQuote.isPending
    ? labels.refreshingQuote
    : refreshQuote.isError
      ? labels.refreshFailed
      : refreshQuote.isSuccess
        ? labels.refreshDone
        : null;

  const summaryMetrics: DetailMetric[] = [
    { label: labels.quantity, value: formatQuantity(position.quantity) },
    {
      label: labels.marketValue,
      value: formatCurrency(position.market_value),
    },
    {
      label: labels.availableFrozen,
      value: `${formatQuantity(position.available_qty)} / ${formatQuantity(
        position.frozen_qty,
      )}`,
    },
    {
      label: labels.portfolioWeight,
      value: isHistoricalClosedPosition ? '--' : formatPercent(portfolioWeight),
    },
    {
      label: labels.todayChange,
      value: formatCurrency(todayChange),
      tone:
        typeof todayChange === 'number' && todayChange !== 0
          ? todayChange > 0
            ? 'pnl-positive'
            : 'pnl-negative'
          : undefined,
    },
    {
      label: labels.todayChangePct,
      value: formatReturnPercent(todayChangePct),
      tone:
        typeof todayChange === 'number' && todayChange !== 0
          ? todayChange > 0
            ? 'pnl-positive'
            : 'pnl-negative'
          : undefined,
    },
    {
      label: labels.unrealizedPnl,
      value: formatCurrency(position.unrealized_pnl),
      tone:
        position.unrealized_pnl > 0
          ? 'pnl-positive'
          : position.unrealized_pnl < 0
            ? 'pnl-negative'
            : undefined,
    },
    { label: labels.pnlPct, value: formatReturnPercent(pnlPct) },
  ];

  const brokerCostBasisMetrics: DetailMetric[] = hasBrokerCostBasisEvidence
    ? [
        {
          label: isBrokerConfirmedCostBasis
            ? labels.brokerDisplayedCost
            : labels.ledgerProjectedUnitCost,
          value: formatPrice(brokerDisplayedUnitCost),
        },
        {
          label: isBrokerConfirmedCostBasis
            ? labels.brokerDisplayedCostBasis
            : labels.ledgerProjectedCostBasis,
          value: formatCurrency(brokerDisplayedCostBasis),
        },
        {
          label: labels.costBasisDifference,
          value: formatCurrency(brokerCostBasisDifference),
          tone:
            brokerCostBasisDifference === null ||
            Math.abs(brokerCostBasisDifference) < 0.005
              ? undefined
              : 'warning',
        },
        {
          label: labels.costBasisMethod,
          value: formatCostBasisMethod(
            position.broker_cost_basis_method,
            locale,
          ),
        },
        {
          label: labels.costBasisStatus,
          value:
            labels.costBasisStatuses[
              costBasisStatus as keyof typeof labels.costBasisStatuses
            ] ?? labels.costBasisStatuses.unavailable,
        },
      ]
    : [];

  const valuationMetrics: DetailMetric[] = [
    { label: labels.avgCost, value: formatPrice(position.avg_cost) },
    ...brokerCostBasisMetrics,
    { label: labels.quotePrice, value: formatPrice(quotePrice) },
    { label: labels.baselinePrice, value: formatPrice(baselinePrice) },
    { label: labels.baselineSource, value: baselineSourceLabel },
    { label: labels.realizedPnl, value: formatCurrency(position.realized_pnl) },
    {
      label: labels.commissionPaid,
      value: formatCurrency(position.commission_paid),
    },
    {
      label: labels.lastTradeAt,
      value: formatTimestamp(lastLedgerEntry?.timestamp),
    },
    {
      label: labels.valuationSnapshotId,
      value: snapshot.data?.valuation_snapshot_id ?? '--',
    },
    {
      label: labels.ledgerCutoffId,
      value: snapshot.data?.ledger_cutoff_id?.toString() ?? '--',
    },
    {
      label: labels.evidenceState,
      value: evidenceReviewState,
      tone: evidenceIdentityConsistent ? undefined : 'warning',
    },
    {
      label: labels.nextManualStep,
      value: nextManualStep,
      tone:
        evidenceIdentityConsistent && !needsCostBasisReview && !isStale
          ? undefined
          : 'warning',
    },
  ];

  return (
    <section className="space-y-5 sm:space-y-6">
      <div data-testid="holding-detail-header">
        <WorkbenchWorkspaceHeader
          eyebrow={labels.kicker}
          title={`${displayName} · ${position.symbol}`}
          description={assetClassDisplay}
          context={`${labels.valuationSnapshotId}: ${
            snapshot.data?.valuation_snapshot_id ?? '--'
          } · ${labels.ledgerCutoffId}: ${
            snapshot.data?.ledger_cutoff_id ?? '--'
          }`}
          actions={
            <>
              <a
                href="/portfolio"
                className="app-button-secondary inline-flex w-max rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                aria-label={labels.returnToPortfolio}
              >
                {labels.backToPortfolio}
              </a>
              {isHistoricalClosedPosition ? (
                <StatusBadge label={labels.closedHistoryOnly} tone="warning" />
              ) : null}
              <StatusBadge
                label={isStale ? labels.quoteStale : labels.quoteLive}
                tone={isStale ? 'warning' : 'success'}
              />
              {marketOpen === false ? (
                <StatusBadge label={labels.marketClosed} tone="warning" />
              ) : null}
              {refreshPolicy === 'cache_only' ? (
                <StatusBadge label={labels.cacheOnly} tone="warning" />
              ) : null}
              <div className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-muted)]">
                <span className="app-kicker mr-1 text-[10px] uppercase tracking-[0.14em]">
                  {labels.quoteTimestamp}
                </span>
                <span className="font-mono tabular-nums">
                  {formatTimestamp(quoteTimestamp)}
                </span>
              </div>
            </>
          }
        />
      </div>

      {isStale ? (
        <div className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
          <span className="truncate">{labels.cacheNotice}</span>
        </div>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.8fr)]">
        <div className="min-w-0 space-y-5">
          <section className="min-w-0">
            <div
              data-testid="holding-summary-header"
              className="sr-only"
              aria-hidden="true"
            >
              <span>{displayName}</span>
              <span data-testid="holding-summary-symbol">
                {position.symbol}
              </span>
            </div>
            <h2
              data-testid="holding-summary-title"
              className="mb-2 text-sm font-semibold text-[var(--app-text)]"
            >
              {labels.summary}
            </h2>
            <div data-testid="holding-summary-metrics">
              <WorkbenchMetricStrip
                ariaLabel={labels.summary}
                items={summaryMetrics.map((metric) => ({
                  id: metric.label,
                  label: metric.label,
                  value: metric.value,
                  tone: metric.tone,
                }))}
                className="sm:grid-flow-row sm:grid-cols-2 xl:grid-cols-4"
              />
            </div>
          </section>

          <section
            data-testid="holding-kline-panel"
            className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
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
          </section>

          <section className="app-terminal-panel rounded-[28px] p-[1px]">
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.resultsEvidence}</div>
              {!evidenceIdentityConsistent ? (
                <div
                  data-testid="holding-evidence-identity-warning"
                  className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-4 py-3 text-sm font-semibold text-[var(--app-warning)]"
                  role="status"
                >
                  {labels.evidenceIdentityMismatch}
                </div>
              ) : null}
              {needsCostBasisReview ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-4 py-3">
                  <div className="text-sm font-semibold text-[var(--app-warning)]">
                    {labels.costBasisReviewNeeded}
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[var(--app-muted)]">
                    {labels.costBasisReviewDetail}
                  </p>
                </div>
              ) : null}
              <MetricGrid metrics={valuationMetrics} />
            </div>
          </section>

          <section className="app-terminal-panel rounded-[28px] p-[1px]">
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <div className="app-product-mark">{labels.ledgerTrace}</div>
                  <h2 className="app-card-title mt-1.5">
                    {labels.ledgerCount(ledgerEntries.length)}
                  </h2>
                </div>
                <span className="w-max rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-muted)]">
                  {labels.productionLedgerOnly}
                </span>
                {ledger.isError ? (
                  <div className="app-error-text text-sm">
                    {copy.activity.error}
                  </div>
                ) : null}
              </div>
              <LedgerTrace entries={ledgerEntries} loading={ledger.isLoading} />
            </div>
          </section>
        </div>

        <aside className="min-w-0 space-y-5">
          <section
            data-testid="holding-quote-status-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.quoteStatus}</div>
              <div className="mt-4 grid gap-3">
                <InfoRow
                  label={labels.quoteStatus}
                  value={quoteStatusLabel}
                  tone={isStale ? 'warning' : undefined}
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
                <InfoRow
                  label={labels.refreshPolicy}
                  value={refreshPolicyLabel}
                />
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
                <button
                  type="button"
                  className="app-button-primary mt-4 w-full rounded-2xl px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55"
                  disabled={refreshQuote.isPending}
                  onClick={() =>
                    refreshQuote.mutate({
                      symbols: [position.symbol],
                      force: true,
                    })
                  }
                  aria-label={`${labels.refreshQuote}: ${position.symbol}`}
                >
                  {refreshQuote.isPending
                    ? labels.refreshingQuote
                    : labels.refreshQuote}
                </button>
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

          <section
            data-testid="holding-risk-exposure-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.riskExposure}</div>
              {isHistoricalClosedPosition ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-3 py-3 text-sm leading-6 text-[var(--app-muted)]">
                  {labels.closedNoCurrentExposure}
                </div>
              ) : (
                <div className="mt-4 grid gap-3">
                  <InfoRow
                    label={labels.portfolioWeight}
                    value={formatPercent(portfolioWeight)}
                  />
                  <InfoRow
                    label={labels.availableFrozen}
                    value={`${formatQuantity(position.available_qty)} / ${formatQuantity(
                      position.frozen_qty,
                    )}`}
                  />
                  <InfoRow
                    label={labels.unrealizedPnl}
                    value={formatCurrency(position.unrealized_pnl)}
                    tone={
                      position.unrealized_pnl > 0
                        ? 'pnl-positive'
                        : position.unrealized_pnl < 0
                          ? 'pnl-negative'
                          : undefined
                    }
                  />
                </div>
              )}
            </div>
          </section>

          {!isHistoricalClosedPosition ? (
            <section
              data-testid="holding-strategy-attribution-boundary"
              id="holding-strategy-attribution-boundary"
              className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
            >
              <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
                <div className="app-product-mark">
                  {labels.strategyAttributionBoundary}
                </div>
                <div className="mt-3 inline-flex max-w-full items-center rounded-full border border-[color-mix(in_srgb,var(--app-warning)_42%,var(--app-border))] bg-[var(--app-warning-bg)] px-3 py-1 text-xs font-semibold text-[var(--app-warning)]">
                  <span className="truncate">
                    {hasSymbolStrategyEvidence
                      ? labels.strategyAttributionLinkedEvidence
                      : labels.strategyAttributionNoLinkedFills}
                  </span>
                </div>
                <p className="app-muted mt-3 text-sm leading-6">
                  {hasSymbolStrategyEvidence
                    ? labels.strategyAttributionLinkedDetail
                    : labels.strategyAttributionDetail}
                </p>
                {attributionReadinessItems.length > 0 ? (
                  <div
                    data-testid="holding-strategy-attribution-readiness"
                    className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel)_36%,transparent)] p-3"
                  >
                    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                      <div className="app-product-mark">
                        {labels.strategyAttributionReviewReadiness}
                      </div>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                          attributionReviewReady
                            ? 'bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                            : 'bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
                        }`}
                      >
                        {attributionReviewReady
                          ? labels.strategyAttributionReviewReady
                          : labels.strategyAttributionReviewIncomplete}
                      </span>
                    </div>
                    <ul className="mt-3 grid gap-2">
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
                          <span className="min-w-0 break-words">
                            {item.label}
                          </span>
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
                    className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_24%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_8%,transparent)] p-3"
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
                      <div
                        data-testid="holding-strategy-evidence-chain"
                        className="mt-2 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel)_36%,transparent)] p-3"
                      >
                        <div className="app-product-mark">
                          {labels.strategyAttributionEvidenceChain}
                        </div>
                        <ul className="mt-3 grid gap-2">
                          {strategyEvidenceItems.map((item, index) => (
                            <li
                              key={`${item.kind}-${item.auditRef}-${index}`}
                              className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_24%,transparent)] px-3 py-2"
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
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {!attributionNextAction ? (
                  <div className="mt-4">
                    <ActionLink
                      href={buildBacktestHandoffHref(
                        position.symbol,
                        assetClass,
                      )}
                      label={labels.actionStrategyEvidence}
                    />
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          <section
            data-testid="holding-related-actions-panel"
            className="app-terminal-panel min-w-0 rounded-[28px] p-[1px]"
          >
            <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
              <div className="app-product-mark">{labels.relatedActions}</div>
              <div className="mt-4 grid gap-2">
                <ActionLink
                  href={buildBacktestHandoffHref(position.symbol, assetClass)}
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
              </div>
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}

function MetricGrid({
  metrics,
  testId,
  metricTestId,
}: {
  metrics: DetailMetric[];
  testId?: string;
  metricTestId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="mt-5 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      {metrics.map((metric) => (
        <div
          key={metric.label}
          data-testid={metricTestId}
          className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3"
        >
          <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
            {metric.label}
          </div>
          <div
            className={`mt-2 break-words font-mono text-sm font-semibold tabular-nums ${
              metric.tone === 'pnl-positive'
                ? 'text-[var(--app-pnl-positive)]'
                : metric.tone === 'pnl-negative'
                  ? 'text-[var(--app-pnl-negative)]'
                  : metric.tone === 'warning'
                    ? 'text-[var(--app-warning-text)]'
                    : 'text-[var(--app-text)]'
            }`}
          >
            {metric.value}
          </div>
        </div>
      ))}
    </div>
  );
}

function InfoRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'pnl-positive' | 'pnl-negative' | 'warning';
}) {
  return (
    <div
      data-testid="holding-info-row"
      className="grid min-w-0 grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-3 border-b border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] pb-2 text-sm last:border-b-0 last:pb-0"
    >
      <span className="app-muted min-w-0 break-words">{label}</span>
      <span
        data-testid="holding-info-row-value"
        className={`min-w-0 break-words text-right font-mono font-semibold tabular-nums ${
          tone === 'pnl-positive'
            ? 'text-[var(--app-pnl-positive)]'
            : tone === 'pnl-negative'
              ? 'text-[var(--app-pnl-negative)]'
              : tone === 'warning'
                ? 'text-[var(--app-warning-text)]'
                : 'text-[var(--app-text)]'
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: 'success' | 'warning' | 'danger';
}) {
  const colorClass =
    tone === 'success'
      ? 'bg-[var(--app-success-bg)] text-[var(--app-success-text)] ring-[var(--app-success-border)]'
      : tone === 'danger'
        ? 'bg-[var(--app-danger-bg)] text-[var(--app-danger-text)] ring-[var(--app-danger-border)]'
        : 'bg-[var(--app-warning-bg)] text-[var(--app-warning-text)] ring-[var(--app-warning-border)]';
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${colorClass}`}
    >
      {label}
    </span>
  );
}

function LedgerTrace({
  entries,
  loading,
}: {
  entries: LedgerEntry[];
  loading: boolean;
}) {
  const copy = useCopy();
  const labels = copy.portfolio.detail;
  const detailLabels = copy.activity.feed.detailFields;
  const { locale } = usePreferences();

  if (loading) {
    return <div className="app-muted mt-5 text-sm">{labels.loading}</div>;
  }
  if (entries.length === 0) {
    return (
      <div className="mt-5 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_36%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-5 text-sm text-[var(--app-muted)]">
        {labels.noLedger}
      </div>
    );
  }

  return (
    <div
      data-testid="holding-ledger-scroll"
      className="mt-5 min-w-0 max-w-full overflow-x-scroll overscroll-x-contain pb-2 [scrollbar-gutter:stable]"
    >
      <table
        data-testid="holding-ledger-table"
        className="app-data-table w-[880px] min-w-max text-left text-sm"
      >
        <thead className="app-kicker text-xs uppercase tracking-[0.16em]">
          <tr>
            <th className="px-4 py-3">{labels.entryType}</th>
            <th className="px-4 py-3">{labels.quantity}</th>
            <th className="px-4 py-3 text-right">{labels.price}</th>
            <th className="px-4 py-3 text-right">{labels.amount}</th>
            <th className="px-4 py-3">{labels.note}</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const activitySummary = formatLedgerActivitySummary(entry, locale);
            const detailLines = formatLedgerExecutionDetailLines(
              entry,
              detailLabels,
              locale,
            );
            return (
              <tr key={entry.id}>
                <td className="px-4 py-3.5">
                  <div className="font-semibold">{activitySummary.label}</div>
                  <div className="app-muted mt-1 text-xs tabular-nums">
                    {formatTimestamp(entry.timestamp)}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {activitySummary.cashImpactLabel}
                  </div>
                </td>
                <td className="px-4 py-3.5 font-mono tabular-nums">
                  {formatQuantity(entry.quantity)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  {formatPrice(entry.price)}
                </td>
                <td className="px-4 py-3.5 text-right font-mono tabular-nums">
                  <div>{activitySummary.amount}</div>
                  {detailLines.length > 0 ? (
                    <div className="app-muted mt-1 flex flex-col items-end gap-0.5 text-xs">
                      {detailLines.map((detail) => (
                        <span key={detail.label}>
                          {detail.label} {detail.value}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </td>
                <td className="max-w-[280px] px-4 py-3.5 text-[var(--app-muted)]">
                  <span className="line-clamp-2 break-words">
                    {formatLedgerPublicNote(entry, locale) ?? '--'}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ActionLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      data-testid="holding-related-action-link"
      className="app-button-secondary min-w-0 break-words rounded-2xl px-4 py-2.5 text-center text-sm font-semibold"
      aria-label={label}
    >
      {label}
    </a>
  );
}

function StatusPanel({
  title,
  detail,
  tone,
}: {
  title: string;
  detail: string;
  tone: 'neutral' | 'danger';
}) {
  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-5">
        <div
          className={`app-product-mark ${
            tone === 'danger' ? 'text-[var(--app-danger-text)]' : ''
          }`}
        >
          {title}
        </div>
        <p className="app-muted mt-2 text-sm">{detail}</p>
      </div>
    </section>
  );
}
