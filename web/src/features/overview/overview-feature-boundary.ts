/**
 * The Overview route composes read models owned by several features. Keep those
 * dependencies at this single adapter boundary so Overview's models and views
 * do not grow private cross-feature imports of their own.
 */

export {
  useAccountOverviewQuery,
  useEquityCurveSeriesQuery,
  useExplainabilityQuery,
} from '../account/api';
export type { AccountOverview, EquityCurveRange } from '../account/api';
export {
  EquityCurveCard,
  EquityCurveSkeleton,
} from '../account/components/equity-curve-card';
export {
  OverviewCards,
  OverviewSnapshotFallbackCards,
} from '../account/components/overview-cards';
export { PortfolioExposureSummary } from '../account/components/portfolio-exposure-summary';
export { ReturnCalendarCard } from '../account/components/return-calendar-card';
export type { QuoteDiagnosticItem } from '../account/components/dashboard-quick-actions';

export { useAccountStrategyContributionQuery } from '../account-strategy/api';
export type { AccountStrategyContributionReport } from '../account-strategy/api';
export { StrategyContributionGateCard } from '../account-strategy/components/strategy-contribution-gate-card';

export { useLedgerEntriesQuery } from '../activity/api';
export type { LedgerEntry } from '../activity/api';

export {
  useDailyTradingPlanQuery,
  useTodayDecisionQuery,
} from '../decision/api';
export type {
  DailyTradingPlanResponse,
  DecisionCandidate,
  DecisionResponse,
} from '../decision/api';

export {
  useMarketCalendarQuery,
  useMarketDataHealthQuery,
} from '../market/api';
export type {
  MarketCalendarSnapshot,
  MarketDataHealthResponse,
  MarketHealthQuote,
} from '../market/api';
export { MarketRefreshButton } from '../market/components/market-refresh-button';

export { useOperationsTodayQuery } from '../operations/api';
export type { OperationsTodayResponse } from '../operations/api';
export {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsTargetHref,
} from '../operations/presentation';

export {
  useCurrentHoldingMarketEvidenceReviewQuery,
  usePortfolioSnapshotQuery,
} from '../portfolio/api';
export type {
  CurrentHoldingMarketEvidenceReview,
  PortfolioSnapshot,
} from '../portfolio/api';
export { PositionsTable } from '../portfolio/components/positions-table';

export { usePendingManualOrdersQuery } from '../trading/api';
export type { ManualOrder } from '../trading/api';
