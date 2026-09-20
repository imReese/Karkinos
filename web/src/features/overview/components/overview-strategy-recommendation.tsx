import { formatPercent } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import {
  ExceptionBoundary,
  Register,
  RegisterRow,
  SectionHeader,
} from '../../../shared/ui/workbench';
import type {
  DailyTradingPlanResponse,
  DecisionResponse,
} from '../overview-feature-boundary';

type QueryState<T> = {
  data?: T;
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
    case 'unavailable':
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
    case 'unavailable':
    default:
      return dashboard.accountRecommendationUnavailableDetail;
  }
}

function readableCode(code: string, labels: Record<string, string>): string {
  return labels[code] ?? code.split('_').join(' ');
}

export function OverviewStrategyRecommendation({
  planQuery,
  decisionQuery,
  className,
}: {
  planQuery: QueryState<DailyTradingPlanResponse>;
  decisionQuery: QueryState<DecisionResponse>;
  className?: string;
}) {
  const copy = useCopy();
  const dashboard = copy.overview.dashboard;
  const plan = planQuery.data;
  const decision = decisionQuery.data;
  const recommendation = plan?.account_action_recommendation;
  const blockedTasks =
    decision?.summary.workflow_tasks?.filter(
      (task) => task.status === 'blocked',
    ) ?? [];
  const reasonCodes = recommendation?.reason_codes ?? [];
  const strategyReadinessReason = reasonCodes.find((reason) =>
    [
      'promoted_strategy_not_configured',
      'promoted_strategy_scan_missing',
    ].includes(reason),
  );
  const decisionTaskLabels = dashboard.decisionTaskLabels as Record<
    string,
    string
  >;
  const decisionReasonLabels = dashboard.decisionReasonLabels as Record<
    string,
    string
  >;
  const decisionActionLabels = dashboard.decisionRequiredActionLabels as Record<
    string,
    string
  >;
  const isBlocked =
    recommendation?.status === 'blocked' ||
    recommendation?.status === 'unavailable' ||
    blockedTasks.length > 0;

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
        meta={plan?.plan_date ?? decision?.decision_date}
      />

      {planQuery.isLoading && !plan ? (
        <p className="app-type-compact mt-2 text-[var(--app-text-secondary)]">
          {dashboard.tradingPlanLoading}
        </p>
      ) : planQuery.isError && !plan ? (
        <ExceptionBoundary
          tone="warning"
          title={dashboard.accountRecommendationUnavailable}
          description={dashboard.accountRecommendationUnavailableDetail}
          className="mt-3"
        />
      ) : plan ? (
        <>
          <p className="app-type-body mt-2 font-medium text-[var(--app-text)]">
            {recommendationHeading(plan, copy)}
          </p>
          <p className="app-type-compact mt-1 text-[var(--app-text-secondary)]">
            {recommendationDetail(plan, copy)}
          </p>

          {recommendation?.actions.length ? (
            <ul
              className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
              data-testid="overview-decision-actions"
            >
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

          {isBlocked ? (
            <div className="mt-3" data-testid="overview-decision-blockers">
              <SectionHeader
                title={dashboard.decisionBlockers}
                meta={
                  blockedTasks.length + (strategyReadinessReason ? 1 : 0) ||
                  reasonCodes.length
                }
                className="mb-2"
              />
              <Register ariaLabel={dashboard.decisionBlockers}>
                {blockedTasks.map((task) => (
                  <RegisterRow
                    key={task.id}
                    label={
                      decisionTaskLabels[task.id] ??
                      task.title ??
                      readableCode(task.id, decisionTaskLabels)
                    }
                    value={dashboard.decisionBlocked}
                    detail={
                      task.required_actions?.length
                        ? task.required_actions
                            .map((action) =>
                              readableCode(action, decisionActionLabels),
                            )
                            .join(' · ')
                        : task.blocking_reasons
                            ?.map((reason) =>
                              readableCode(reason, decisionReasonLabels),
                            )
                            .join(' · ') || task.description
                    }
                    tone="warning"
                  />
                ))}
                {strategyReadinessReason ? (
                  <RegisterRow
                    label={dashboard.decisionStrategyResearch}
                    value={dashboard.decisionStrategyNotReady}
                    detail={
                      <span>
                        {readableCode(
                          strategyReadinessReason,
                          decisionReasonLabels,
                        )}
                        {' · '}
                        <a
                          href="/ai-research"
                          className="font-semibold text-[var(--app-accent)] hover:underline"
                        >
                          {dashboard.decisionStrategyNextStep}
                        </a>
                      </span>
                    }
                    tone="warning"
                  />
                ) : null}
                {!blockedTasks.length
                  ? reasonCodes
                      .filter((reason) => reason !== strategyReadinessReason)
                      .slice(0, strategyReadinessReason ? 5 : 6)
                      .map((reason) => (
                        <RegisterRow
                          key={reason}
                          label={dashboard.decisionEvidence}
                          value={readableCode(reason, decisionReasonLabels)}
                          tone="warning"
                        />
                      ))
                  : null}
              </Register>
            </div>
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
