import {
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatReturnPercent,
  formatTimestamp,
} from '../../../shared/format';
import { formatLedgerCostBasisMethodLabel } from '../../../shared/ledger-format';
import type { LedgerEntry } from '../portfolio-feature-boundary';
import type { HoldingDetailModelSource } from './holding-detail-model-contracts';
import type {
  DetailMetric,
  HoldingDetailTab,
} from './holding-detail-model-values';

type HoldingMetricsSource = Pick<
  HoldingDetailModelSource,
  | 'allocation'
  | 'isHistoricalClosedPosition'
  | 'labels'
  | 'locale'
  | 'position'
  | 'snapshot'
>;

type HoldingMetricsMarket = {
  baselineSourceLabel: string;
  brokerCostBasisDifference: number | null;
  brokerDisplayedCostBasis: number | null;
  brokerDisplayedUnitCost: number | null;
  costBasisStatus: string;
  hasBrokerCostBasisEvidence: boolean;
  isBrokerConfirmedCostBasis: boolean;
  needsCostBasisReview: boolean;
  quoteNeedsReview: boolean;
  quoteTimestamp: string | null | undefined;
};

type HoldingMetricsEvidence = {
  baselinePrice: number | null;
  evidenceIdentityConsistent: boolean;
  evidenceReviewState: string;
  lastLedgerEntry: LedgerEntry | null;
  nextManualStep: string;
  pnlPct: number | null;
  quotePrice: number | null;
  todayChange: number | null;
  todayChangePct: number | null;
};

export function buildHoldingMetricsModel(
  source: HoldingMetricsSource,
  market: HoldingMetricsMarket,
  evidence: HoldingMetricsEvidence,
) {
  const {
    allocation,
    isHistoricalClosedPosition,
    labels,
    locale,
    position,
    snapshot,
  } = source;
  const portfolioWeight = allocation?.weight ?? null;
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
      value: formatCurrency(evidence.todayChange),
      detail: `${labels.todayChangePct} ${formatReturnPercent(
        evidence.todayChangePct,
      )}`,
      tone:
        typeof evidence.todayChange === 'number' && evidence.todayChange !== 0
          ? evidence.todayChange > 0
            ? 'pnl-positive'
            : 'pnl-negative'
          : undefined,
    },
    {
      label: labels.unrealizedPnl,
      value: formatCurrency(position.unrealized_pnl),
      detail: `${labels.pnlPct} ${formatReturnPercent(
        evidence.pnlPct,
      )}\n${labels.realizedPnl} ${formatCurrency(position.realized_pnl)}`,
      tone:
        position.unrealized_pnl > 0
          ? 'pnl-positive'
          : position.unrealized_pnl < 0
            ? 'pnl-negative'
            : undefined,
    },
  ];
  const brokerCostBasisMetrics: DetailMetric[] =
    market.hasBrokerCostBasisEvidence
      ? [
          {
            label: market.isBrokerConfirmedCostBasis
              ? labels.brokerDisplayedCost
              : labels.ledgerProjectedUnitCost,
            value: formatPrice(market.brokerDisplayedUnitCost),
          },
          {
            label: market.isBrokerConfirmedCostBasis
              ? labels.brokerDisplayedCostBasis
              : labels.ledgerProjectedCostBasis,
            value: formatCurrency(market.brokerDisplayedCostBasis),
          },
          {
            label: labels.costBasisDifference,
            value: formatCurrency(market.brokerCostBasisDifference),
            tone:
              market.brokerCostBasisDifference === null ||
              Math.abs(market.brokerCostBasisDifference) < 0.005
                ? undefined
                : 'warning',
          },
          {
            label: labels.costBasisMethod,
            value: formatLedgerCostBasisMethodLabel(
              position.broker_cost_basis_method,
              locale,
            ),
          },
          {
            label: labels.costBasisStatus,
            value:
              labels.costBasisStatuses[
                market.costBasisStatus as keyof typeof labels.costBasisStatuses
              ] ?? labels.costBasisStatuses.unavailable,
          },
        ]
      : [];
  const valuationMetrics: DetailMetric[] = [
    { label: labels.avgCost, value: formatPrice(position.avg_cost) },
    ...brokerCostBasisMetrics,
    { label: labels.quotePrice, value: formatPrice(evidence.quotePrice) },
    { label: labels.baselinePrice, value: formatPrice(evidence.baselinePrice) },
    { label: labels.baselineSource, value: market.baselineSourceLabel },
    { label: labels.realizedPnl, value: formatCurrency(position.realized_pnl) },
    {
      label: labels.commissionPaid,
      value: formatCurrency(position.commission_paid),
    },
    {
      label: labels.lastTradeAt,
      value: formatTimestamp(evidence.lastLedgerEntry?.timestamp),
    },
  ];
  const reconciliationMetrics: DetailMetric[] = [
    {
      label: labels.evidenceState,
      value: evidence.evidenceReviewState,
      tone: evidence.evidenceIdentityConsistent ? undefined : 'warning',
    },
    {
      label: labels.nextManualStep,
      value: evidence.nextManualStep,
      tone:
        evidence.evidenceIdentityConsistent &&
        !market.needsCostBasisReview &&
        !market.quoteNeedsReview
          ? undefined
          : 'warning',
    },
    {
      label: labels.costBasisStatus,
      value:
        labels.costBasisStatuses[
          market.costBasisStatus as keyof typeof labels.costBasisStatuses
        ] ?? labels.costBasisStatuses.unavailable,
    },
    {
      label: labels.valuationTimestamp,
      value: formatTimestamp(snapshot.data?.valuation_as_of),
    },
    {
      label: labels.quoteTimestamp,
      value: formatTimestamp(market.quoteTimestamp),
    },
  ];
  const tabLabels: Record<HoldingDetailTab, string> = {
    position: labels.tabPosition,
    'pnl-costs': labels.tabPnlCosts,
    transactions: labels.tabTransactions,
    evidence: labels.tabEvidence,
    reconciliation: labels.tabReconciliation,
  };
  return {
    portfolioWeight,
    positionSizeMetrics,
    summaryMetrics,
    brokerCostBasisMetrics,
    valuationMetrics,
    reconciliationMetrics,
    tabLabels,
  };
}

export type HoldingMetricsModel = ReturnType<typeof buildHoldingMetricsModel>;
