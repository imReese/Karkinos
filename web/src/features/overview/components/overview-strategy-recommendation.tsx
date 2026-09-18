import { formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import type { DailyTradingPlanResponse } from '../overview-feature-boundary';

type QueryState = {
  data?: DailyTradingPlanResponse;
  isLoading: boolean;
  isError: boolean;
};

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
    default:
      return dashboard.accountRecommendationUnavailable;
  }
}

function recommendationDetail(
  plan: DailyTradingPlanResponse,
  copy: ReturnType<typeof useCopy>,
) {
  const recommendation = plan.account_action_recommendation;
  const dashboard = copy.overview.dashboard;
  if (!recommendation) return dashboard.accountRecommendationReason('');
  switch (recommendation.status) {
    case 'no_action':
      return dashboard.accountRecommendationNoActionDetail;
    case 'manual_review_required':
      return dashboard.tradingPlanManualReadyDetail(
        recommendation.actions.length,
      );
    case 'paper_shadow_required':
      return dashboard.accountRecommendationPaperShadowDetail;
    case 'blocked':
      return dashboard.tradingPlanBlockedDetail(plan.blocked_count);
    default:
      return dashboard.accountRecommendationReason('');
  }
}

export function OverviewStrategyRecommendation({
  query,
}: {
  query: QueryState;
}) {
  const copy = useCopy();
  const dashboard = copy.overview.dashboard;
  const plan = query.data;
  const recommendation = plan?.account_action_recommendation;

  return (
    <section
      data-testid="overview-strategy-recommendation"
      className="min-w-0 border-b border-[var(--app-divider)] py-4 lg:border-b-0"
      aria-label={dashboard.strategyRecommendationTitle}
    >
      <SectionHeader
        title={dashboard.strategyRecommendationTitle}
        meta={plan?.plan_date}
      />

      {query.isLoading && !plan ? (
        <p className="app-type-compact mt-2 text-[var(--app-text-secondary)]">
          {dashboard.tradingPlanLoading}
        </p>
      ) : query.isError && !plan ? (
        <p className="app-type-compact mt-2 text-[var(--app-warning-text)]">
          {dashboard.accountRecommendationUnavailable}
        </p>
      ) : plan ? (
        <>
          <p className="app-type-body mt-2 font-medium text-[var(--app-text)]">
            {recommendationHeading(plan, copy)}
          </p>
          <p className="app-type-compact mt-1 text-[var(--app-text-secondary)]">
            {recommendationDetail(plan, copy)}
          </p>

          {recommendation?.actions.length ? (
            <ul className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {recommendation.actions.map((action, index) => (
                <li
                  key={
                    action.action_id ?? `${action.symbol ?? 'action'}-${index}`
                  }
                  className="app-type-compact grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 py-2"
                >
                  <div className="min-w-0">
                    <span className="font-medium text-[var(--app-text)]">
                      {sideLabel(action.side, dashboard.decisionActionLabels)}
                    </span>
                    <span className="ml-2 font-mono text-[var(--app-text-secondary)]">
                      {action.symbol ?? '--'}
                    </span>
                  </div>
                  <div className="text-right tabular-nums text-[var(--app-text-secondary)]">
                    {action.target_weight == null
                      ? null
                      : formatPercent(action.target_weight)}
                    {action.target_weight != null &&
                    action.estimated_quantity != null
                      ? ' · '
                      : null}
                    {action.estimated_quantity == null
                      ? null
                      : `${dashboard.strategyRecommendationQuantity} ${action.estimated_quantity}`}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}

          <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
            {dashboard.strategyRecommendationReadOnly}
          </p>
          <a
            href="/decision"
            className="app-type-compact mt-2 inline-block font-semibold text-[var(--app-accent)] hover:underline"
          >
            {dashboard.viewDecision}
          </a>
        </>
      ) : null}
    </section>
  );
}
