import {
  formatDate,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { ExceptionBoundary, SectionHeader } from '../../../shared/ui/workbench';
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

function sideLabel(
  side: string | null,
  labels: Record<string, string>,
): string {
  if (!side) return '--';
  return labels[side] ?? side;
}

function recommendationHeading(
  plan: DailyTradingPlanResponse,
  copy: ReturnType<typeof useCopy>,
) {
  const recommendation = plan.account_action_recommendation;
  const dashboard = copy.overview.dashboard;
  if (!recommendation) return dashboard.accountRecommendationUnavailable;
  switch (recommendation.status) {
    case 'no_action':
      return dashboard.accountRecommendationNoAction;
    case 'manual_review_required':
      return dashboard.tradingPlanManualReady(recommendation.actions.length);
    case 'paper_shadow_required':
      return dashboard.accountRecommendationPaperShadow;
    case 'blocked':
      return dashboard.accountRecommendationBlocked;
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
  const recommendationDate = formatDate(
    plan?.plan_date ?? recommendation?.decision_date,
  );
  const actions =
    recommendation?.status === 'manual_review_required'
      ? recommendation.actions
      : [];

  return (
    <section
      data-testid="overview-strategy-recommendation"
      className={(
        'min-w-0 border-b border-[var(--app-divider)] py-3.5 ' +
        (className ?? '')
      ).trim()}
      aria-label={dashboard.strategyRecommendationTitle}
    >
      <SectionHeader
        title={dashboard.strategyRecommendationTitle}
        meta={recommendationDate === '--' ? undefined : recommendationDate}
      />

      {planQuery.isLoading && !plan ? (
        <p className="app-type-compact mt-2 text-[var(--app-text-secondary)]">
          {dashboard.tradingPlanLoading}
        </p>
      ) : planQuery.isError && !plan ? (
        <ExceptionBoundary
          tone="warning"
          title={dashboard.accountRecommendationUnavailable}
          className="mt-3"
        />
      ) : plan ? (
        <>
          <p className="app-type-body mt-2 font-medium text-[var(--app-text)]">
            {recommendationHeading(plan, copy)}
          </p>

          {actions.length ? (
            <ul
              className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
              data-testid="overview-decision-actions"
            >
              {actions.map((action, index) => {
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
                    className="grid min-w-0 gap-1 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-x-5"
                  >
                    <div className="min-w-0">
                      <span className="font-semibold text-[var(--app-text)]">
                        {sideLabel(action.side, dashboard.decisionActionLabels)}
                      </span>
                      <span className="ml-2 font-medium text-[var(--app-text)]">
                        {name}
                      </span>
                      {symbol && name !== symbol ? (
                        <span className="ml-2 font-mono text-[var(--app-text-tertiary)]">
                          {symbol}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[var(--app-text-secondary)] sm:justify-end">
                      <span className="whitespace-nowrap tabular-nums">
                        {dashboard.strategyRecommendationCurrentWeight}{' '}
                        {weight == null ? '--' : formatPercent(weight)}
                        {' → '}
                        {dashboard.strategyRecommendationTargetWeight}{' '}
                        {action.target_weight == null
                          ? '--'
                          : formatPercent(action.target_weight)}
                      </span>
                      {action.estimated_quantity == null ? null : (
                        <span className="whitespace-nowrap tabular-nums">
                          {dashboard.strategyRecommendationQuantity}{' '}
                          {formatQuantity(action.estimated_quantity)}{' '}
                          {quantityUnit(action.asset_class, locale)}
                        </span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : null}

          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
            {recommendation?.status === 'manual_review_required' ? (
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
        </>
      ) : null}
    </section>
  );
}
