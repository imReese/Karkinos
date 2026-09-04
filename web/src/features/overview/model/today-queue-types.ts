import type {
  AccountOverview,
  AccountStrategyContributionReport,
  CurrentHoldingMarketEvidenceReview,
  DailyTradingPlanResponse,
  DecisionResponse,
  ManualOrder,
  MarketDataHealthResponse,
  OperationsTodayResponse,
  PortfolioSnapshot,
  QuoteDiagnosticItem,
} from '../overview-feature-boundary';

export type TodayQueueTone = 'success' | 'warning' | 'danger' | 'neutral';
export type TodayQueuePriority = 'first' | 'watch' | 'normal';

export type TodayQueueItem = {
  key: 'operations' | 'data' | 'decision' | 'research' | 'orders' | 'strategy';
  title: string;
  detail: string;
  meta: string;
  href: string;
  actionLabel: string;
  tone: TodayQueueTone;
  priority: TodayQueuePriority;
  alwaysVisible?: boolean;
  resolution?: string;
};

export type DashboardTodayQueueProps = {
  overview: AccountOverview;
  marketHealth?: MarketDataHealthResponse;
  portfolioSnapshot: PortfolioSnapshot;
  marketEvidenceReview?: CurrentHoldingMarketEvidenceReview | null;
  marketEvidenceReviewLoading: boolean;
  marketEvidenceReviewError: boolean;
  quoteDiagnostics: QuoteDiagnosticItem[];
  pendingOrders: ManualOrder[];
  pendingOrdersLoading: boolean;
  pendingOrdersError: boolean;
  strategyContribution?: AccountStrategyContributionReport | null;
  strategyContributionLoading: boolean;
  strategyContributionError: boolean;
  todayDecision?: DecisionResponse | null;
  todayDecisionLoading: boolean;
  todayDecisionError: boolean;
  tradingPlan?: DailyTradingPlanResponse | null;
  tradingPlanLoading: boolean;
  tradingPlanError: boolean;
  operationsToday?: OperationsTodayResponse | null;
  operationsTodayLoading: boolean;
  operationsTodayError: boolean;
};

export const TODAY_QUEUE_PRIORITY_ORDER: TodayQueuePriority[] = [
  'first',
  'watch',
  'normal',
];
