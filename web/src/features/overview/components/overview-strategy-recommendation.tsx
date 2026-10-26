import { formatDate } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  ExceptionBoundary,
  SectionHeader,
  StatusBadge,
} from '../../../shared/ui/workbench';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import type {
  AccountStateResponse,
  DailyTradingPlanResponse,
  DecisionResponse,
} from '../overview-feature-boundary';
import { OverviewResearchSimulationPreview } from './overview-research-simulation-preview';
import {
  RecommendationActionItem,
  type PresentationLevel,
} from './overview-recommendation-action';
import {
  SavedHistoricalComparison,
  forwardObservationLabel,
} from './overview-research-comparison';

type QueryState<T> = {
  data?: T;
  isLoading: boolean;
  isError: boolean;
};

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

function isMissingPromotedStrategy(
  recommendation:
    DailyTradingPlanResponse['account_action_recommendation'] | undefined,
): boolean {
  if (!recommendation) return false;
  return Boolean(
    recommendation.presentation?.configuration_blockers?.includes(
      'promoted_strategy_not_configured',
    ) ||
    recommendation.presentation?.configuration_blockers?.includes(
      'promoted_daily_candidate_strategy_missing',
    ) ||
    recommendation.reason_codes.includes(
      'promoted_daily_candidate_strategy_missing',
    ),
  );
}

function indicatorTone(
  plan: DailyTradingPlanResponse,
): 'success' | 'warning' | 'info' | 'neutral' {
  const recommendation = plan.account_action_recommendation;
  if (!recommendation) return 'neutral';
  if (isMissingPromotedStrategy(recommendation)) {
    return 'neutral';
  }
  switch (recommendation.status) {
    case 'no_action':
      return 'success';
    case 'paper_shadow_required':
      return 'info';
    case 'manual_review_required':
      return 'warning';
    case 'blocked':
    case 'unavailable':
    default:
      return 'neutral';
  }
}

function indicatorDotClass(tone: 'success' | 'warning' | 'info' | 'neutral') {
  switch (tone) {
    case 'success':
      return 'bg-[var(--app-success-indicator)]';
    case 'warning':
      return 'bg-[var(--app-warning-indicator)]';
    case 'info':
      return 'bg-[var(--app-info-indicator)]';
    case 'neutral':
    default:
      return 'bg-[var(--app-text-tertiary)]';
  }
}

function recommendationHeading(
  plan: DailyTradingPlanResponse,
  copy: ReturnType<typeof useCopy>,
) {
  const recommendation = plan.account_action_recommendation;
  const dashboard = copy.overview.dashboard;
  if (!recommendation) return dashboard.accountRecommendationUnavailable;
  if (isMissingPromotedStrategy(recommendation)) {
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
  marketClosed,
  nextTradingDate,
  planQuery,
  todayQuery,
  positions,
  currentWeightBySymbol,
  className,
}: {
  marketClosed: boolean;
  nextTradingDate?: string | null;
  planQuery: QueryState<DailyTradingPlanResponse>;
  todayQuery: QueryState<DecisionResponse>;
  positions: AccountStateResponse['snapshot']['positions'];
  currentWeightBySymbol: Record<string, number>;
  className?: string;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const dashboard = copy.overview.dashboard;

  const plan = planQuery.data;
  const recommendation = plan?.account_action_recommendation;
  const generation = todayQuery.data?.generation;
  const currentGeneration =
    plan &&
    todayQuery.data?.decision_date === plan.plan_date &&
    generation?.run_date === plan.plan_date
      ? generation
      : null;
  const quoteTooOldForReview = recommendation?.reason_codes.includes(
    'market_quote_too_old_for_decision',
  );
  const blockedReasons =
    recommendation?.status === 'blocked' ||
    recommendation?.status === 'unavailable'
      ? [...new Set(recommendation.reason_codes)].filter(
          (code) => code !== 'market_quote_too_old_for_decision',
        )
      : [];
  const reasonLabels = dashboard.decisionReasonLabels as Record<string, string>;
  const blockedReasonSummary = [
    ...new Set(
      blockedReasons.map(
        (code) =>
          reasonLabels[code] ??
          (locale === 'zh'
            ? '其他账户证据待核验，请查看决策证据'
            : 'Other account evidence needs verification; review decision evidence'),
      ),
    ),
  ].join(locale === 'zh' ? '；' : '; ');
  const presentationLevel: PresentationLevel =
    recommendation?.presentation?.level ??
    fallbackPresentationLevel(recommendation);
  const presentationActions =
    presentationLevel === 'manual_review'
      ? (recommendation?.actions ?? [])
      : (recommendation?.presentation?.actions ?? []);
  const showDetailedActions =
    ['manual_review', 'portfolio_preview', 'signal'].includes(
      presentationLevel,
    ) && presentationActions.length > 0;

  const effectivePlan = plan;
  const showPortfolioSizing =
    presentationLevel === 'manual_review' ||
    presentationLevel === 'portfolio_preview';
  const recommendationDate = formatDate(
    effectivePlan?.plan_date ?? recommendation?.decision_date,
  );

  return (
    <section
      data-testid="overview-strategy-recommendation"
      className={('flex flex-col min-w-0 ' + (className ?? '')).trim()}
      aria-label={dashboard.strategyRecommendationTitle}
    >
      <div className="mb-2 flex min-h-9 shrink-0 items-center border-b border-[var(--app-divider)]">
        <SectionHeader
          title={dashboard.strategyRecommendationTitle}
          meta={
            marketClosed
              ? undefined
              : recommendationDate === '--'
                ? undefined
                : recommendationDate
          }
          className="overview-spotlight-heading w-full flex-row items-center justify-between sm:items-center"
          actions={
            <div className="flex items-center gap-3">
              <a
                href="/decision"
                onClick={(e) => handleClientNavigation(e, '/decision')}
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.strategyRecommendationViewAll}
              </a>
            </div>
          }
        />
      </div>

      {marketClosed ? (
        <div
          data-testid="overview-recommendation-market-closed"
          className="space-y-3 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-3"
        >
          <p
            role="status"
            className="app-type-subsection-title text-[var(--app-text)]"
          >
            {dashboard.strategyRecommendationMarketClosed}
          </p>
          <p className="app-type-compact text-[var(--app-text-secondary)]">
            {dashboard.strategyRecommendationClosedResearch}
          </p>
          {nextTradingDate ? (
            <p className="app-type-compact text-[var(--app-text-secondary)]">
              {dashboard.strategyRecommendationNextSession(
                formatDate(nextTradingDate),
              )}
            </p>
          ) : null}
          <a
            href="/ai-research"
            onClick={(e) => handleClientNavigation(e, '/ai-research')}
            className="app-type-compact inline-flex min-h-11 items-center font-semibold text-[var(--app-accent)] hover:underline"
          >
            {dashboard.strategyRecommendationResearchAction}
          </a>
        </div>
      ) : plan && showDetailedActions ? (
        <div className="flex flex-1 min-w-0 flex-col rounded-[var(--app-radius-control)] border border-[var(--app-accent-border)] bg-[var(--app-surface-raised)]/80 p-4 shadow-sm">
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
            <StatusBadge tone={statusTone(presentationLevel)}>
              {statusLabel(presentationLevel, dashboard)}
            </StatusBadge>
            <div className="flex items-center gap-2">
              <span className="app-type-label text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '只读建议' : 'Read only'}
              </span>
            </div>
          </div>

          <ul className="mt-3 flex-1 divide-y divide-[var(--app-divider)] overflow-y-auto overscroll-y-contain pr-1 max-h-[30rem]">
            {presentationActions.map((action, index) => (
              <RecommendationActionItem
                key={
                  action.action_id ?? `${action.symbol || 'action'}-${index}`
                }
                action={action}
                index={index}
                plan={plan}
                positions={positions}
                currentWeightBySymbol={currentWeightBySymbol}
                dashboard={dashboard}
                locale={locale}
                presentationLevel={presentationLevel}
                showPortfolioSizing={showPortfolioSizing}
              />
            ))}
          </ul>

          {presentationLevel !== 'manual_review' ? (
            <p className="app-type-compact mt-3 shrink-0 border-t border-[var(--app-divider)] pt-3 text-[var(--app-text-secondary)]">
              {presentationLevel === 'portfolio_preview'
                ? dashboard.strategyRecommendationRefreshForReview
                : dashboard.strategyRecommendationSignalOnly}
            </p>
          ) : null}

          <div className="mt-4 flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-[var(--app-divider)] pt-3">
            {presentationLevel === 'manual_review' ? (
              <a
                href="/trading"
                onClick={(e) => handleClientNavigation(e, '/trading')}
                className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
              >
                {dashboard.viewTrading}
              </a>
            ) : null}
            <a
              href="/decision"
              onClick={(e) => handleClientNavigation(e, '/decision')}
              className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
            >
              {dashboard.viewDecision}
            </a>
          </div>
        </div>
      ) : planQuery.isLoading && !plan ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-2.5 text-[var(--app-text-secondary)]">
          <span className="inline-block h-2 w-2 rounded-full bg-[var(--app-accent)] opacity-70" />
          <span className="app-type-compact font-medium">
            {locale === 'zh'
              ? '正在读取账户级推荐...'
              : 'Loading account recommendations...'}
          </span>
        </div>
      ) : planQuery.isError && !plan ? (
        <ExceptionBoundary
          tone="warning"
          title={dashboard.accountRecommendationUnavailable}
        />
      ) : plan ? (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-2.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className={(
                'inline-flex h-2 w-2 shrink-0 rounded-full ' +
                indicatorDotClass(indicatorTone(plan))
              ).trim()}
            />
            <p className="app-type-body font-semibold text-[var(--app-text)]">
              {recommendationHeading(plan, copy)}
            </p>
          </div>
          <a
            href="/decision"
            onClick={(e) => handleClientNavigation(e, '/decision')}
            className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline shrink-0"
          >
            {dashboard.viewDecision}
          </a>
        </div>
      ) : null}

      {plan?.research_simulation_preview ? (
        <OverviewResearchSimulationPreview
          preview={plan.research_simulation_preview}
        />
      ) : null}

      {plan?.historical_research_comparison ? (
        <details
          data-testid="overview-historical-research-comparison"
          className="mt-3 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/40 px-4 py-3 app-type-compact text-[var(--app-text-secondary)]"
        >
          <summary className="cursor-pointer font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '历史研究对比 · Gen7 与候选策略'
              : 'Historical research · Gen7 and candidate'}
          </summary>
          <div className="mt-3 space-y-2">
            <p>
              {locale === 'zh'
                ? '已保存的研究事实；账户建议资格、前向观测和人工确认分别核验。'
                : 'Saved research facts; account recommendation eligibility, forward observation and human confirmation are assessed separately.'}
            </p>
            <SavedHistoricalComparison
              comparison={plan.historical_research_comparison}
              locale={locale}
              testId="overview-historical-research-results"
            />
            <a
              href={`/backtest?id=${plan.historical_research_comparison.source_result_id}`}
              onClick={(event) =>
                handleClientNavigation(
                  event,
                  `/backtest?id=${plan.historical_research_comparison!.source_result_id}`,
                )
              }
              className="inline-block font-semibold text-[var(--app-accent)] hover:underline"
            >
              {locale === 'zh' ? '公式来源' : 'Formula source'} #
              {plan.historical_research_comparison.source_result_id}
            </a>
            <div
              data-testid="overview-historical-forward-state"
              className="space-y-1"
            >
              <p className="font-semibold">
                {locale === 'zh'
                  ? '前向观测（独立）'
                  : 'Forward observation (separate)'}
              </p>
              {(
                [
                  [
                    'Gen7',
                    plan.historical_research_comparison.forward.baseline,
                  ],
                  [
                    locale === 'zh' ? '候选策略' : 'Candidate',
                    plan.historical_research_comparison.forward.candidate,
                  ],
                ] as const
              ).map(([label, forward]) => (
                <p key={label}>
                  {label} #{forward.source_backtest_result_id}：
                  {forwardObservationLabel(forward, locale)}
                </p>
              ))}
            </div>
          </div>
        </details>
      ) : null}

      {!marketClosed &&
      plan &&
      (currentGeneration ||
        !todayQuery.isLoading ||
        quoteTooOldForReview ||
        blockedReasons.length > 0) ? (
        <div
          data-testid="overview-recommendation-evidence"
          className="mt-2 shrink-0 space-y-1 app-type-compact text-[var(--app-text-secondary)]"
        >
          {currentGeneration || !todayQuery.isLoading ? (
            <p>
              {currentGeneration
                ? dashboard.strategyDailyGeneration[currentGeneration.status]
                : dashboard.strategyDailyGenerationUnavailable}
            </p>
          ) : null}
          {blockedReasons.length > 0 ? (
            <p
              data-testid="overview-account-recommendation-blockers"
              title={blockedReasons.join('\n')}
            >
              {dashboard.accountRecommendationReason(blockedReasonSummary)}
            </p>
          ) : null}
          {quoteTooOldForReview ? (
            <p>{dashboard.strategyReviewQuoteTooOld}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
