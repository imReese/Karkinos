import { useMemo, useState } from 'react';

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
import {
  PriceStructureChart,
  PriceStructureLoadingState,
} from '../../market/components/price-structure-chart';
import { useCopy } from '../../../app/copy';
import {
  ControlledActionZone,
  EvidenceLoadingLayout as WorkbenchEvidenceLoadingLayout,
  EvidenceState as WorkbenchEvidenceState,
  EvidenceIdentityDisclosure,
  MetricStrip as WorkbenchMetricStrip,
  StatusBadge as WorkbenchStatusBadge,
  WorkspaceHeader as WorkbenchWorkspaceHeader,
} from '../../../shared/ui/workbench';
import { usePreferences } from '../../../shared/preferences/context';
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
  isCacheLikeMarketDataStatus,
  isUnconfirmedMarketDataStatus,
} from '../../../shared/market-data-status';
import {
  useLiveHoldingsQuery,
  usePortfolioSnapshotQuery,
  type Position,
} from '../api';

type DetailMetric = {
  detail?: string;
  label: string;
  value: string;
  tone?: 'pnl-positive' | 'pnl-negative' | 'warning';
};

type HoldingDetailTab =
  'position' | 'pnl-costs' | 'transactions' | 'evidence' | 'reconciliation';

const HOLDING_DETAIL_TABS: HoldingDetailTab[] = [
  'position',
  'pnl-costs',
  'transactions',
  'evidence',
  'reconciliation',
];

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
  const snapshot = usePortfolioSnapshotQuery();
  const currentPositions = snapshot.data?.positions ?? [];
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
  const kline = useKlineQuery(decodedSymbol);
  const secondaryQueriesEnabled = Boolean(
    position && (snapshot.data !== undefined || snapshot.isError),
  );
  const liveHoldings = useLiveHoldingsQuery(secondaryQueriesEnabled);
  const overview = useAccountOverviewQuery(secondaryQueriesEnabled);
  const marketHealth = useMarketDataHealthQuery(secondaryQueriesEnabled);
  const ledger = useLedgerEntriesQuery(200, secondaryQueriesEnabled);
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const accountStrategyAttribution = useAccountStrategyAttributionQuery();
  const accountStrategyContribution = useAccountStrategyContributionQuery(
    secondaryQueriesEnabled,
  );
  const holdingStrategyAttribution = useHoldingStrategyAttributionQuery(
    secondaryQueriesEnabled ? decodedSymbol : '',
  );
  const refreshQuote = useRefreshMarketQuotesMutation();
  const [activeTab, setActiveTab] = useState<HoldingDetailTab>('position');
  const stateHeader = (
    <div data-testid="holding-detail-header">
      <WorkbenchWorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title(decodedSymbol)}
        description={labels.subtitle}
        actions={
          <a
            href="/portfolio"
            className="app-button-secondary app-type-compact inline-flex min-h-11 items-center rounded-[var(--app-radius-control)] px-3 py-2 font-semibold"
            aria-label={labels.returnToPortfolio}
          >
            {labels.backToPortfolio}
          </a>
        }
      />
    </div>
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

  const hasSnapshotProjection = snapshot.data !== undefined;
  const coreLoading = !position && !hasSnapshotProjection && snapshot.isLoading;
  const coreError = snapshot.isError;

  if (coreLoading) {
    return (
      <section className="space-y-5 sm:space-y-6">
        {stateHeader}
        <WorkbenchEvidenceLoadingLayout
          title={copy.states.loading}
          description={labels.loading}
          metricCount={4}
          rowCount={4}
        />
      </section>
    );
  }

  if (coreError) {
    return (
      <section className="space-y-5 sm:space-y-6">
        {stateHeader}
        <StatusPanel
          title={copy.states.error}
          detail={labels.error}
          kind="error"
        />
      </section>
    );
  }

  if (!position) {
    return (
      <section className="space-y-5 sm:space-y-6">
        {stateHeader}
        <StatusPanel
          title={labels.notFoundTitle}
          detail={labels.notFoundDetail}
          kind="empty"
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
  const quoteSourceLabel =
    quoteSource === 'market_bar_close'
      ? labels.baselineSources.marketBarClose
      : (quoteSource ?? '--');
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
  const refreshPolicy = marketHealth.data?.refresh_policy ?? '--';
  const quoteNeedsReview =
    isUnconfirmedMarketDataStatus(quoteStatus) ||
    isCacheLikeMarketDataStatus(refreshPolicy);
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
        : quoteNeedsReview
          ? labels.evidenceStates.staleQuote
          : labels.evidenceStates.complete;
  const nextManualStep = isHistoricalClosedPosition
    ? labels.evidenceNextSteps.reviewHistory
    : !evidenceIdentityConsistent
      ? labels.evidenceNextSteps.reloadIdentity
      : needsCostBasisReview
        ? labels.evidenceNextSteps.reconcileCost
        : quoteNeedsReview
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
  const valuationSnapshotId = snapshot.data?.valuation_snapshot_id ?? null;
  const hasPersistedPriceStructure = (kline.data ?? []).some((bar) =>
    Number.isFinite(bar.close),
  );
  const evidenceStateKind = isHistoricalClosedPosition
    ? ('empty' as const)
    : !evidenceIdentityConsistent
      ? ('missing' as const)
      : needsCostBasisReview
        ? ('partial' as const)
        : quoteNeedsReview
          ? ('stale' as const)
          : ('ready' as const);

  const positionSizeMetrics: DetailMetric[] = [
    { label: labels.quantity, value: formatQuantity(position.quantity) },
    {
      label: labels.availableFrozen,
      value: `${formatQuantity(position.available_qty)} / ${formatQuantity(
        position.frozen_qty,
      )}`,
    },
  ];
  const summaryMetrics: DetailMetric[] = [
    {
      label: labels.marketValue,
      value: formatCurrency(position.market_value),
    },
    {
      label: labels.portfolioWeight,
      value: isHistoricalClosedPosition ? '--' : formatPercent(portfolioWeight),
    },
    {
      label: labels.todayChange,
      value: formatCurrency(todayChange),
      detail: `${labels.todayChangePct} ${formatReturnPercent(todayChangePct)}`,
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
      detail: `${labels.pnlPct} ${formatReturnPercent(
        pnlPct,
      )}\n${labels.realizedPnl} ${formatCurrency(position.realized_pnl)}`,
      tone:
        position.unrealized_pnl > 0
          ? 'pnl-positive'
          : position.unrealized_pnl < 0
            ? 'pnl-negative'
            : undefined,
    },
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
  ];

  const reconciliationMetrics: DetailMetric[] = [
    {
      label: labels.evidenceState,
      value: evidenceReviewState,
      tone: evidenceIdentityConsistent ? undefined : 'warning',
    },
    {
      label: labels.nextManualStep,
      value: nextManualStep,
      tone:
        evidenceIdentityConsistent && !needsCostBasisReview && !quoteNeedsReview
          ? undefined
          : 'warning',
    },
    {
      label: labels.costBasisStatus,
      value:
        labels.costBasisStatuses[
          costBasisStatus as keyof typeof labels.costBasisStatuses
        ] ?? labels.costBasisStatuses.unavailable,
    },
    {
      label: labels.valuationTimestamp,
      value: formatTimestamp(snapshot.data?.valuation_as_of),
    },
    {
      label: labels.quoteTimestamp,
      value: formatTimestamp(quoteTimestamp),
    },
  ];
  const tabLabels: Record<HoldingDetailTab, string> = {
    position: labels.tabPosition,
    'pnl-costs': labels.tabPnlCosts,
    transactions: labels.tabTransactions,
    evidence: labels.tabEvidence,
    reconciliation: labels.tabReconciliation,
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <div data-testid="holding-detail-header">
        <WorkbenchWorkspaceHeader
          eyebrow={labels.kicker}
          title={`${displayName} · ${position.symbol}`}
          description={`${assetClassDisplay} · ${labels.quantity} ${formatQuantity(
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
              items={summaryMetrics.map((metric) => ({
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
          <div className="min-w-0">
            <div
              className="app-type-micro mb-1.5 text-right font-medium text-[var(--app-text-tertiary)] sm:hidden"
              data-testid="holding-tabs-scroll-hint"
              id="holding-tabs-scroll-hint"
            >
              {labels.tabScrollHint}
            </div>
            <div
              role="tablist"
              aria-label={labels.tabListLabel}
              aria-describedby="holding-tabs-scroll-hint"
              data-testid="holding-detail-tabs"
              className="app-horizontal-scroll-cue flex min-w-0 gap-1 overflow-x-auto border-b border-[var(--app-divider)] pb-px"
            >
              {HOLDING_DETAIL_TABS.map((tab) => {
                const selected = activeTab === tab;
                return (
                  <button
                    key={tab}
                    id={`holding-tab-${tab}`}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    aria-controls={`holding-panel-${tab}`}
                    tabIndex={selected ? 0 : -1}
                    className={`min-h-10 shrink-0 border-b-2 px-3 py-2 text-xs font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                      selected
                        ? 'border-[var(--app-accent)] text-[var(--app-text)]'
                        : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                    }`}
                    onClick={() => setActiveTab(tab)}
                    onKeyDown={(event) => {
                      if (
                        !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(
                          event.key,
                        )
                      ) {
                        return;
                      }
                      event.preventDefault();
                      const currentIndex = HOLDING_DETAIL_TABS.indexOf(tab);
                      const nextIndex =
                        event.key === 'Home'
                          ? 0
                          : event.key === 'End'
                            ? HOLDING_DETAIL_TABS.length - 1
                            : event.key === 'ArrowRight'
                              ? (currentIndex + 1) % HOLDING_DETAIL_TABS.length
                              : (currentIndex -
                                  1 +
                                  HOLDING_DETAIL_TABS.length) %
                                HOLDING_DETAIL_TABS.length;
                      const nextTab = HOLDING_DETAIL_TABS[nextIndex];
                      setActiveTab(nextTab);
                      event.currentTarget.parentElement
                        ?.querySelector<HTMLButtonElement>(
                          `#holding-tab-${nextTab}`,
                        )
                        ?.focus();
                    }}
                  >
                    {tabLabels[tab]}
                  </button>
                );
              })}
            </div>
          </div>

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
                <div
                  data-testid="holding-position-size-metrics"
                  className="mt-4"
                >
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
                          onClick={() => void kline.refetch()}
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
              {!evidenceIdentityConsistent ? (
                <WorkbenchEvidenceState
                  kind="missing"
                  statusLabel={labels.evidenceStates.identityMismatch}
                  title={labels.evidenceIdentityMismatch}
                  description={labels.evidenceNextSteps.reloadIdentity}
                />
              ) : null}
              {needsCostBasisReview ? (
                <WorkbenchEvidenceState
                  kind="partial"
                  statusLabel={labels.evidenceStates.costBasisReview}
                  title={labels.costBasisReviewNeeded}
                  description={labels.costBasisReviewDetail}
                />
              ) : null}
              <MetricGrid metrics={valuationMetrics} />
            </div>
          </section>

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
                      : labels.ledgerCount(ledgerEntries.length)}
                  </h2>
                </div>
                <WorkbenchStatusBadge tone="neutral">
                  {labels.productionLedgerOnly}
                </WorkbenchStatusBadge>
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
                    value={
                      quoteNeedsReview ? labels.quoteStale : quoteStatusLabel
                    }
                    tone={quoteNeedsReview ? 'warning' : undefined}
                  />
                  <InfoRow
                    label={labels.quoteTimestamp}
                    value={formatTimestamp(quoteTimestamp)}
                  />
                  <InfoRow
                    label={labels.quoteSource}
                    value={quoteSourceLabel}
                  />
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
                          assetClass,
                        )}
                        label={labels.actionStrategyEvidence}
                      />
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}
          </div>

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
              kind={evidenceStateKind}
              statusLabel={evidenceReviewState}
              title={labels.reconciliationStateTitle}
              description={nextManualStep}
              className="mt-3"
            />
            <MetricGrid metrics={reconciliationMetrics} />
            <div className="mt-4 flex flex-wrap gap-2">
              <ActionLink
                href="/account-truth"
                label={labels.actionAccountTruth}
              />
              <ActionLink href="/market" label={labels.actionMarket} />
            </div>
          </section>

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
              </nav>
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
    <dl
      data-testid={testId}
      className="mt-3 grid min-w-0 grid-cols-1 border-y border-[var(--app-divider)] sm:grid-cols-2 xl:grid-cols-3"
    >
      {metrics.map((metric) => (
        <div
          key={metric.label}
          data-testid={metricTestId}
          className="min-w-0 border-b border-[var(--app-divider)] px-3 py-2.5 sm:border-r sm:[&:nth-child(2n)]:border-r-0 xl:[&:nth-child(2n)]:border-r xl:[&:nth-child(3n)]:border-r-0"
        >
          <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
            {metric.label}
          </dt>
          <dd
            className={`mt-0.5 break-words text-sm font-semibold tabular-nums ${
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
          </dd>
          {metric.detail ? (
            <div className="app-type-micro mt-0.5 text-[var(--app-text-tertiary)]">
              {metric.detail}
            </div>
          ) : null}
        </div>
      ))}
    </dl>
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
      className="grid min-w-0 grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-start gap-3 border-b border-[var(--app-divider)] pb-2 text-sm last:border-b-0 last:pb-0"
    >
      <span className="min-w-0 break-words text-[var(--app-text-secondary)]">
        {label}
      </span>
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
      <div className="mt-4 border-y border-dashed border-[var(--app-divider)] px-3 py-4 text-sm text-[var(--app-text-secondary)]">
        {labels.noLedger}
      </div>
    );
  }

  return (
    <div
      data-testid="holding-ledger-scroll"
      className="mt-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2 [scrollbar-gutter:stable]"
    >
      <table
        data-testid="holding-ledger-table"
        className="app-data-table w-full min-w-[760px] text-left text-sm"
      >
        <thead className="app-kicker app-type-overline">
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
            const publicNote = formatLedgerPublicNote(entry, locale) ?? '--';
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
                  <span
                    className="line-clamp-2 break-words focus:line-clamp-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                    data-testid="holding-ledger-note"
                    tabIndex={0}
                    title={publicNote}
                  >
                    {publicNote}
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
      className="app-button-secondary inline-flex min-h-10 min-w-0 items-center break-words rounded-[var(--app-radius-control)] px-3 py-2 text-center text-sm font-semibold"
      aria-label={label}
    >
      {label}
    </a>
  );
}

function StatusPanel({
  title,
  detail,
  kind,
}: {
  title: string;
  detail: string;
  kind: 'loading' | 'empty' | 'error';
}) {
  return (
    <WorkbenchEvidenceState kind={kind} title={title} description={detail} />
  );
}
