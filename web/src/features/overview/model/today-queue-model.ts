import { formatCurrency as formatCurrencyValue } from '../../../shared/format';
import type { AppCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import type { AccountStrategyContributionReport } from '../overview-feature-boundary';
import { buildMarketEvidenceQueueItem } from './today-queue-market-evidence';
import {
  buildOperationsQueueItem,
  decisionQueueResolution,
} from './today-queue-operations';
import { buildDecisionQueueItem } from './today-queue-trading-plan';
import type {
  DashboardTodayQueueProps,
  TodayQueueItem,
} from './today-queue-types';

function canUseStrategyContribution(
  report?: AccountStrategyContributionReport | null,
) {
  return Boolean(
    report &&
    report.schema_version === 'karkinos.account_strategy_contribution.v2' &&
    report.contribution_status === 'evidence_bound_from_posted_fills' &&
    report.evidence_binding_status === 'bound' &&
    report.linked_fill_count > 0 &&
    report.ledger_posted_fill_count === report.linked_fill_count &&
    report.unposted_linked_fill_count === 0 &&
    Boolean(report.valuation_snapshot_id) &&
    (report.ledger_cutoff_id ?? 0) > 0 &&
    Boolean(report.contribution_fingerprint) &&
    report.evidence_refs.length > 0 &&
    report.missing_valuation_symbols.length === 0 &&
    report.persisted_facts_only === true &&
    report.provider_contacted === false &&
    report.database_writes_performed === false &&
    report.authorizes_execution === false,
  );
}

function strategyContributionReviewHref(
  report?: AccountStrategyContributionReport | null,
) {
  const status = report?.contribution_status ?? '';
  if (status.startsWith('valuation_')) {
    return '/market';
  }
  if (status.startsWith('ledger_')) {
    return '/operations';
  }
  return '/backtest';
}

function buildStrategyQueueItem(
  props: DashboardTodayQueueProps,
  copy: AppCopy,
  locale: Locale,
): TodayQueueItem {
  const labels = copy.overview.dashboard;
  const contribution = props.strategyContribution;
  const ready = canUseStrategyContribution(contribution);
  const hasNoLinkedFills =
    contribution?.contribution_status === 'no_linked_fills' &&
    contribution.linked_fill_count === 0 &&
    (contribution.unattributed_fill_count ?? 0) === 0;
  const status = contribution?.contribution_status
    ? (copy.backtest.page.accountStrategyContributionStatusMap[
        contribution.contribution_status as keyof typeof copy.backtest.page.accountStrategyContributionStatusMap
      ] ?? formatPublicStatus(contribution.contribution_status, locale))
    : copy.backtest.page.accountStrategyContributionStatusMap.no_linked_fills;
  const nextAction = contribution?.next_manual_action
    ? (copy.backtest.page.accountStrategyNextActionMap[
        contribution.next_manual_action as keyof typeof copy.backtest.page.accountStrategyNextActionMap
      ] ?? formatPublicStatus(contribution.next_manual_action, locale))
    : copy.backtest.page.accountStrategyContributionHiddenUntilEvidence;
  const href = strategyContributionReviewHref(contribution);
  const actionLabel = href.startsWith('/market')
    ? labels.viewData
    : href.startsWith('/operations')
      ? labels.viewOperations
      : labels.viewStrategy;
  return {
    key: 'strategy',
    title: props.strategyContributionLoading
      ? copy.backtest.page.accountStrategyContributionLoading
      : props.strategyContributionError
        ? labels.strategyUnavailable
        : ready
          ? labels.strategyEvidenceLinked
          : hasNoLinkedFills
            ? labels.strategyNoLinkedFills
            : labels.strategyEvidenceRequired,
    detail: props.strategyContributionLoading
      ? copy.backtest.page.accountStrategyContributionLoading
      : ready && contribution
        ? `${copy.backtest.page.accountStrategyNetContribution}: ${formatCurrencyValue(
            contribution.net_contribution,
          )}`
        : nextAction,
    meta: props.strategyContributionLoading ? copy.states.loading : status,
    href,
    actionLabel,
    tone: props.strategyContributionError
      ? 'danger'
      : props.strategyContributionLoading
        ? 'neutral'
        : ready || hasNoLinkedFills
          ? 'success'
          : 'warning',
    priority: props.strategyContributionError
      ? 'watch'
      : props.strategyContributionLoading
        ? 'normal'
        : ready || hasNoLinkedFills
          ? 'normal'
          : 'watch',
    resolution: props.strategyContributionLoading
      ? undefined
      : hasNoLinkedFills
        ? labels.strategyNoLinkedFillsResolution
        : ready
          ? undefined
          : labels.strategyEvidenceResolution,
  };
}

function buildOrdersQueueItem(
  props: DashboardTodayQueueProps,
  copy: AppCopy,
): TodayQueueItem {
  const labels = copy.overview.dashboard;
  return {
    key: 'orders',
    title: props.pendingOrdersError
      ? copy.trading.orders.loadFailed
      : props.pendingOrders.length > 0
        ? labels.pendingOrdersReady
        : labels.pendingOrdersClear,
    detail: props.pendingOrdersLoading
      ? copy.trading.orders.loading
      : props.pendingOrders.length > 0
        ? labels.pendingCount(props.pendingOrders.length)
        : labels.pendingEmptyDetail,
    meta: props.pendingOrdersLoading
      ? copy.states.loading
      : labels.pendingCount(props.pendingOrders.length),
    href: '/trading',
    actionLabel: labels.viewTrading,
    tone: props.pendingOrdersError
      ? 'danger'
      : props.pendingOrders.length > 0
        ? 'warning'
        : 'success',
    priority:
      props.pendingOrdersError || props.pendingOrders.length > 0
        ? 'first'
        : 'normal',
  };
}

export function buildTodayQueueModel(
  props: DashboardTodayQueueProps,
  copy: AppCopy,
  locale: Locale,
) {
  const market = buildMarketEvidenceQueueItem({
    overview: props.overview,
    portfolioSnapshot: props.portfolioSnapshot,
    marketEvidenceReview: props.marketEvidenceReview,
    marketEvidenceReviewLoading: props.marketEvidenceReviewLoading,
    marketEvidenceReviewError: props.marketEvidenceReviewError,
    copy,
  });
  const operations = buildOperationsQueueItem({
    operations: props.operationsToday,
    loading: props.operationsTodayLoading,
    error: props.operationsTodayError,
    tradingPlan: props.tradingPlan,
    copy,
    locale,
  });
  const decision = buildDecisionQueueItem({
    todayDecision: props.todayDecision,
    todayDecisionLoading: props.todayDecisionLoading,
    todayDecisionError: props.todayDecisionError,
    tradingPlan: props.tradingPlan,
    tradingPlanLoading: props.tradingPlanLoading,
    tradingPlanError: props.tradingPlanError,
    instrumentDiagnostics: [
      ...props.quoteDiagnostics,
      ...(props.marketHealth?.quotes ?? []),
    ],
    resolution: decisionQueueResolution(props.operationsToday, copy, locale),
    copy,
    locale,
  });
  const hideDuplicateOperationsReview =
    (market.needsReview && operations.primaryTarget === 'market') ||
    operations.duplicatesTradingPlanReview;
  const allItems: TodayQueueItem[] = [
    operations.item,
    market.item,
    decision,
    buildOrdersQueueItem(props, copy),
    buildStrategyQueueItem(props, copy, locale),
  ];
  return {
    items: allItems.filter(
      (item) => !(hideDuplicateOperationsReview && item.key === 'operations'),
    ),
    dataRefreshSymbols: market.refreshSymbols,
  };
}
