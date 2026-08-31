import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  isCacheLikeMarketDataStatus,
  isUnconfirmedMarketDataStatus,
} from '../../../shared/market-data-status';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import { formatStrategyDisplayName } from '../../../shared/strategy-display';
import { buildAttributionReadinessItems } from '../portfolio-feature-boundary';
import type { LedgerEntry } from '../portfolio-feature-boundary';
import type { HoldingDetailModelSource } from './holding-detail-model-contracts';
import {
  buildHoldingMetricsModel,
  type HoldingMetricsModel,
} from './holding-detail-metrics-model';
import {
  buildAttributionNextAction,
  buildEvidenceRefItems,
  isFiniteNumber,
  normalizeSymbol,
  sameEvidenceIdentity,
} from './holding-detail-model-values';

export type { HoldingDetailModelSource } from './holding-detail-model-contracts';
export {
  buildHoldingMetricsModel,
  type HoldingMetricsModel,
} from './holding-detail-metrics-model';

export function buildHoldingMarketModel(source: HoldingDetailModelSource) {
  const {
    allocation,
    copy,
    isHistoricalClosedPosition,
    labels,
    liveHoldings,
    locale,
    marketHealth,
    normalizedSymbol,
    overview,
    position,
  } = source;
  const liveItem = (liveHoldings.data?.groups ?? [])
    .flatMap((group) => group.items)
    .find((item) => normalizeSymbol(item.symbol) === normalizedSymbol);
  const healthQuote = (marketHealth.data?.quotes ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
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
  const projectedQuotePrice =
    isFiniteNumber(position.latest_price) && position.latest_price !== null
      ? position.latest_price
      : isFiniteNumber(liveItem?.latest_price)
        ? liveItem.latest_price
        : null;
  const projectedTodayChange = isHistoricalClosedPosition
    ? null
    : (position.today_change ?? liveItem?.today_change ?? null);
  const projectedTodayChangePct = isHistoricalClosedPosition
    ? null
    : (position.today_change_pct ?? liveItem?.today_change_pct ?? null);
  const projectedBaselinePrice =
    position.baseline_price ?? liveItem?.baseline_price ?? null;
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
  return {
    liveItem,
    healthQuote,
    quoteStatus,
    quoteTimestamp,
    quoteSource,
    quoteSourceLabel,
    quoteAgeSeconds,
    staleReason,
    staleReasonLabel,
    refreshPolicy,
    quoteNeedsReview,
    quoteStatusLabel,
    projectedQuotePrice,
    projectedTodayChange,
    projectedTodayChangePct,
    projectedBaselinePrice,
    baselineSource,
    baselineSourceLabel,
    brokerDisplayedCostBasis,
    brokerDisplayedUnitCost,
    brokerCostBasisDifference,
    costBasisStatus,
    isBrokerConfirmedCostBasis,
    isProjectedLedgerCostBasis,
    hasBrokerCostBasisEvidence,
    needsCostBasisReview,
    displayName,
    assetClass,
    assetClassDisplay: formatAssetClassLabel(assetClass, copy.common),
  };
}

export type HoldingMarketModel = ReturnType<typeof buildHoldingMarketModel>;

export function buildHoldingStrategyModel(
  source: HoldingDetailModelSource,
  market: HoldingMarketModel,
) {
  const {
    accountStrategy,
    accountStrategyAttribution,
    accountStrategyContribution,
    copy,
    holdingStrategyAttribution,
    labels,
    locale,
    normalizedSymbol,
    position,
  } = source;
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
    assetClass: market.assetClass,
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
  return {
    strategyAssignment,
    strategyAttribution,
    strategyContribution,
    holdingAttribution,
    hasHoldingStrategyEvidence,
    hasAggregateSymbolStrategyEvidence,
    hasSymbolStrategyEvidence,
    strategyEvidenceFillCount,
    strategyEvidenceRefCount,
    strategyEvidenceItems,
    attributionReadinessItems,
    attributionReviewReady,
    attributionNextAction,
    strategyDisplayName,
    contributionStatusLabel,
    attributionStatusLabel,
  };
}

export type HoldingStrategyModel = ReturnType<typeof buildHoldingStrategyModel>;

export function buildHoldingEvidenceModel(
  source: HoldingDetailModelSource,
  market: HoldingMarketModel,
) {
  const {
    isHistoricalClosedPosition,
    kline,
    labels,
    liveHoldings,
    locale,
    marketHealth,
    overview,
    position,
    refreshQuote,
    snapshot,
    symbolLedgerEntries,
  } = source;
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
  const quotePrice = evidenceIdentityConsistent
    ? market.projectedQuotePrice
    : null;
  const todayChange = evidenceIdentityConsistent
    ? market.projectedTodayChange
    : null;
  const todayChangePct = evidenceIdentityConsistent
    ? market.projectedTodayChangePct
    : null;
  const baselinePrice = evidenceIdentityConsistent
    ? market.projectedBaselinePrice
    : null;
  const pnlPct =
    !isHistoricalClosedPosition && evidenceIdentityConsistent
      ? (market.liveItem?.since_buy_pnl_pct ?? null)
      : null;
  const evidenceReviewState = isHistoricalClosedPosition
    ? labels.evidenceStates.historicalClosed
    : !evidenceIdentityConsistent
      ? labels.evidenceStates.identityMismatch
      : market.needsCostBasisReview
        ? labels.evidenceStates.costBasisReview
        : market.quoteNeedsReview
          ? labels.evidenceStates.staleQuote
          : labels.evidenceStates.complete;
  const nextManualStep = isHistoricalClosedPosition
    ? labels.evidenceNextSteps.reviewHistory
    : !evidenceIdentityConsistent
      ? labels.evidenceNextSteps.reloadIdentity
      : market.needsCostBasisReview
        ? labels.evidenceNextSteps.reconcileCost
        : market.quoteNeedsReview
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
    ...(market.brokerDisplayedUnitCost !== null &&
    market.brokerCostBasisDifference !== null &&
    Math.abs(market.brokerCostBasisDifference) >= 0.005
      ? [
          {
            value: market.brokerDisplayedUnitCost,
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
      : market.needsCostBasisReview
        ? ('partial' as const)
        : market.quoteNeedsReview
          ? ('stale' as const)
          : ('ready' as const);
  return {
    lastLedgerEntry,
    snapshotIdentityMatchesOverview,
    snapshotIdentityMatchesLive,
    evidenceIdentityConsistent,
    quotePrice,
    todayChange,
    todayChangePct,
    baselinePrice,
    pnlPct,
    evidenceReviewState,
    nextManualStep,
    tradeMarkers,
    costReferenceLines,
    marketOpen,
    refreshPolicyLabel,
    refreshStatus,
    valuationSnapshotId,
    hasPersistedPriceStructure,
    evidenceStateKind,
  };
}

export type HoldingEvidenceModel = ReturnType<typeof buildHoldingEvidenceModel>;

export type HoldingDetailModel = {
  source: HoldingDetailModelSource;
  market: HoldingMarketModel;
  strategy: HoldingStrategyModel;
  evidence: HoldingEvidenceModel;
  metrics: HoldingMetricsModel;
  ledgerEntries: LedgerEntry[];
};

export function buildHoldingDetailModel(
  source: HoldingDetailModelSource,
): HoldingDetailModel {
  const market = buildHoldingMarketModel(source);
  const strategy = buildHoldingStrategyModel(source, market);
  const evidence = buildHoldingEvidenceModel(source, market);
  const metrics = buildHoldingMetricsModel(source, market, evidence);
  return {
    source,
    market,
    strategy,
    evidence,
    metrics,
    ledgerEntries: source.symbolLedgerEntries.slice(0, 12),
  };
}
