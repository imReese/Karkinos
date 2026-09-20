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
  const manualReview = recommendation?.status === 'manual_review_required';

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
        <div className="mt-3 h-28 rounded-[var(--app-radius-control)] bg-[var(--app-surface-raised)]" />
      ) : planQuery.isError && !plan ? (
        <ExceptionBoundary
          tone="warning"
          title={dashboard.accountRecommendationUnavailable}
          className="mt-3"
        />
      ) : plan ? (
        manualReview && actions.length ? (
          <div
            className="mt-3 min-w-0 rounded-[calc(var(--app-radius-control)*1.25)] border border-[var(--app-accent-border)] p-4"
            style={{
              background:
                'linear-gradient(140deg, color-mix(in srgb, var(--app-accent) 10%, var(--app-surface)) 0%, color-mix(in srgb, var(--app-accent) 4%, var(--app-surface)) 100%)',
            }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusBadge tone="warning">
                {dashboard.strategyRecommendationReview}
              </StatusBadge>
              <span className="app-type-label text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '策略信号' : 'Strategy signal'}
              </span>
            </div>

            <ul className="mt-3 divide-y divide-[var(--app-divider)]">
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
                    </div>
                  </li>
                );
              })}
            </ul>

            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--app-divider)] pt-3">
              <a
                href="/trading"
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.viewTrading}
              </a>
              <a
                href="/decision"
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.viewDecision}
              </a>
            </div>
          </div>
        ) : (
          <div
            className="mt-3 flex min-h-36 items-center rounded-[calc(var(--app-radius-control)*1.25)] border border-[var(--app-divider)] px-4 py-5"
            style={{
              background:
                'linear-gradient(140deg, color-mix(in srgb, var(--app-accent) 5%, var(--app-surface)) 0%, color-mix(in srgb, var(--app-accent) 2%, var(--app-surface)) 100%)',
            }}
          >
            <p className="app-type-body font-semibold text-[var(--app-text)]">
              {recommendationHeading(plan, copy)}
            </p>
          </div>
        )
      ) : null}
    </section>
  );
}
