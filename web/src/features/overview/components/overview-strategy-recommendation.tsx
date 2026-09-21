import {
  formatDate,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  ExceptionBoundary,
  SectionHeader,
  StatusBadge,
} from '../../../shared/ui/workbench';
import type {
  AccountStateResponse,
  DailyTradingPlanResponse,
} from '../overview-feature-boundary';

type QueryState<T> = {
  data?: T;
  isLoading: boolean;
  isError: boolean;
};

type RecommendationAction = NonNullable<
  DailyTradingPlanResponse['account_action_recommendation']
>['actions'][number];

type PresentationLevel =
  | 'manual_review'
  | 'portfolio_preview'
  | 'signal'
  | 'no_action'
  | 'blocked'
  | 'unavailable';

function sideLabel(
  side: string | null,
  labels: Record<string, string>,
): string {
  if (!side) return '--';
  return labels[side] ?? side;
}

function fallbackPresentationLevel(
  recommendation:
    DailyTradingPlanResponse['account_action_recommendation'] | undefined,
): PresentationLevel {
  switch (recommendation?.status) {
    case 'manual_review_required':
      return 'manual_review';
    case 'no_action':
      return 'no_action';
    case 'blocked':
      return 'blocked';
    case 'paper_shadow_required':
      return 'signal';
    case 'unavailable':
    default:
      return 'unavailable';
  }
}

function recommendationHeading(
  plan: DailyTradingPlanResponse,
  copy: ReturnType<typeof useCopy>,
) {
  const recommendation = plan.account_action_recommendation;
  const dashboard = copy.overview.dashboard;
  if (!recommendation) return dashboard.accountRecommendationUnavailable;
  if (
    recommendation.presentation?.configuration_blockers.includes(
      'promoted_strategy_not_configured',
    )
  ) {
    return dashboard.strategyRecommendationConfigurationRequired;
  }
  switch (recommendation.status) {
    case 'no_action':
      return dashboard.accountRecommendationNoAction;
    case 'paper_shadow_required':
      return dashboard.accountRecommendationPaperShadow;
    case 'blocked':
      return dashboard.accountRecommendationBlocked;
    case 'manual_review_required':
      return dashboard.tradingPlanManualReady(recommendation.actions.length);
    case 'unavailable':
    default:
      return dashboard.accountRecommendationUnavailable;
  }
}

function actionName(
  action: RecommendationAction,
  positions: AccountStateResponse['snapshot']['positions'],
) {
  const symbol = action.symbol ?? '';
  const position = positions.find((item) => item.symbol === symbol);
  return (
    action.display_name ||
    action.name ||
    position?.display_name ||
    position?.name ||
    symbol ||
    '--'
  );
}

function currentWeight(
  symbol: string | null,
  positions: AccountStateResponse['snapshot']['positions'],
  currentWeightBySymbol: Record<string, number>,
) {
  if (!symbol) return null;
  const weight = currentWeightBySymbol[symbol];
  if (typeof weight === 'number' && Number.isFinite(weight)) {
    return weight;
  }
  return positions.some((item) => item.symbol === symbol) ? null : 0;
}

function quantityUnit(assetClass: string | null, locale: 'en' | 'zh') {
  if (locale === 'en') {
    return assetClass === 'stock' ? 'shares' : 'units';
  }
  return assetClass === 'stock' ? '股' : '份';
}

function statusLabel(
  level: PresentationLevel,
  dashboard: ReturnType<typeof useCopy>['overview']['dashboard'],
) {
  if (level === 'manual_review') return dashboard.strategyRecommendationReview;
  if (level === 'portfolio_preview') {
    return dashboard.strategyRecommendationPortfolioPreview;
  }
  return dashboard.strategyRecommendationSignal;
}

function statusTone(level: PresentationLevel) {
  if (level === 'manual_review') return 'warning' as const;
  if (level === 'portfolio_preview') return 'info' as const;
  return 'neutral' as const;
}

export function OverviewStrategyRecommendation({
  planQuery,
  positions,
  currentWeightBySymbol,
  className,
}: {
  planQuery: QueryState<DailyTradingPlanResponse>;
  positions: AccountStateResponse['snapshot']['positions'];
  currentWeightBySymbol: Record<string, number>;
  className?: string;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const dashboard = copy.overview.dashboard;
  const plan = planQuery.data;
  const recommendation = plan?.account_action_recommendation;
  const presentationLevel: PresentationLevel =
    recommendation?.presentation?.level ??
    fallbackPresentationLevel(recommendation);
  const recommendationDate = formatDate(
    plan?.plan_date ?? recommendation?.decision_date,
  );
  const presentationActions =
    presentationLevel === 'manual_review'
      ? (recommendation?.actions ?? [])
      : (recommendation?.presentation?.actions ?? []);
  const showDetailedActions =
    ['manual_review', 'portfolio_preview', 'signal'].includes(
      presentationLevel,
    ) && presentationActions.length > 0;
  const showPortfolioSizing =
    presentationLevel === 'manual_review' ||
    presentationLevel === 'portfolio_preview';

  return (
    <section
      data-testid="overview-strategy-recommendation"
      className={('min-w-0 ' + (className ?? '')).trim()}
      aria-label={dashboard.strategyRecommendationTitle}
    >
      <SectionHeader
        title={dashboard.strategyRecommendationTitle}
        meta={recommendationDate === '--' ? undefined : recommendationDate}
        className="overview-spotlight-heading"
        actions={
          <a
            href="/decision"
            className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
          >
            {dashboard.strategyRecommendationViewAll}
          </a>
        }
      />

      {planQuery.isLoading && !plan ? (
        <div className="mt-2 flex items-center gap-2.5 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-2.5 text-[var(--app-text-secondary)]">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--app-accent)] opacity-70" />
          <span className="app-type-compact font-medium">
            {locale === 'zh'
              ? '正在同步全市场最新策略与决策建议...'
              : 'Syncing latest strategy and decision recommendations...'}
          </span>
        </div>
      ) : planQuery.isError && !plan ? (
        <ExceptionBoundary
          tone="warning"
          title={dashboard.accountRecommendationUnavailable}
          className="mt-2"
        />
      ) : plan ? (
        showDetailedActions ? (
          <div className="mt-2 min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-accent-border)] bg-[var(--app-surface-raised)]/80 p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusBadge tone={statusTone(presentationLevel)}>
                {statusLabel(presentationLevel, dashboard)}
              </StatusBadge>
              <span className="app-type-label text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '只读' : 'Read only'}
              </span>
            </div>

            <ul className="mt-3 divide-y divide-[var(--app-divider)]">
              {presentationActions.map((action, index) => {
                const symbol = action.symbol ?? '';
                const name = actionName(action, positions);
                const weight = currentWeight(
                  symbol,
                  positions,
                  currentWeightBySymbol,
                );
                return (
                  <li
                    key={action.action_id ?? `${symbol || 'action'}-${index}`}
                    className="min-w-0 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="text-base font-semibold text-[var(--app-text)]">
                        {sideLabel(action.side, dashboard.decisionActionLabels)}
                      </span>
                      <span className="text-base font-semibold text-[var(--app-text)]">
                        {name}
                      </span>
                      {symbol && name !== symbol ? (
                        <span className="font-mono text-sm text-[var(--app-text-tertiary)]">
                          {symbol}
                        </span>
                      ) : null}
                    </div>

                    {showPortfolioSizing ? (
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        <div className="min-w-0">
                          <div className="app-type-label text-[var(--app-text-tertiary)]">
                            {locale === 'zh' ? '建议仓位' : 'Target allocation'}
                          </div>
                          <div className="mt-1 text-sm font-semibold tabular-nums text-[var(--app-text)]">
                            {weight == null ? '--' : formatPercent(weight)}
                            <span className="mx-1.5 text-[var(--app-text-tertiary)]">
                              →
                            </span>
                            <span className="text-[var(--app-accent)]">
                              {action.target_weight == null
                                ? '--'
                                : formatPercent(action.target_weight)}
                            </span>
                          </div>
                        </div>
                        {presentationLevel === 'manual_review' ? (
                          <div className="min-w-0">
                            <div className="app-type-label text-[var(--app-text-tertiary)]">
                              {dashboard.strategyRecommendationQuantity}
                            </div>
                            <div className="mt-1 text-sm font-semibold tabular-nums text-[var(--app-text)]">
                              {action.estimated_quantity == null
                                ? '--'
                                : `${formatQuantity(action.estimated_quantity)} ${quantityUnit(
                                    action.asset_class,
                                    locale,
                                  )}`}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>

            {presentationLevel !== 'manual_review' ? (
              <p className="app-type-compact mt-3 border-t border-[var(--app-divider)] pt-3 text-[var(--app-text-secondary)]">
                {presentationLevel === 'portfolio_preview'
                  ? dashboard.strategyRecommendationRefreshForReview
                  : dashboard.strategyRecommendationSignalOnly}
              </p>
            ) : null}

            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--app-divider)] pt-3">
              {presentationLevel === 'manual_review' ? (
                <a
                  href="/trading"
                  className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
                >
                  {dashboard.viewTrading}
                </a>
              ) : null}
              <a
                href="/decision"
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.viewDecision}
              </a>
            </div>
          </div>
        ) : (
          <div className="mt-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-2.5">
            <div className="flex items-center gap-2.5 min-w-0">
              <span className="inline-flex h-2 w-2 shrink-0 rounded-full bg-[var(--app-success-indicator)]" />
              <p className="app-type-body font-semibold text-[var(--app-text)]">
                {recommendationHeading(plan, copy)}
              </p>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <a
                href="/decision"
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.viewDecision}
              </a>
            </div>
          </div>
        )
      ) : null}
    </section>
  );
}
