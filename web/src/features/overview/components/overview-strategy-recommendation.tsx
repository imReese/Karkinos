import {
  formatCurrency,
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
  DecisionResponse,
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

function actionName(
  action: RecommendationAction,
  positions: AccountStateResponse['snapshot']['positions'],
) {
  const symbol = action.symbol ?? '';
  const position = positions.find((item) => item.symbol === symbol);
  return (
    action.display_name ||
    action.symbol_name ||
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

function resolveActionPrice(
  action: RecommendationAction,
  intent: DailyTradingPlanResponse['order_intents'][number] | undefined,
  positions: AccountStateResponse['snapshot']['positions'],
): number | null {
  for (const candidate of [
    intent?.estimated_price,
    action.target_price,
    action.estimated_execution_price,
    action.estimated_price,
    action.limit_price,
  ]) {
    if (typeof candidate === 'number' && Number.isFinite(candidate)) {
      return candidate;
    }
  }
  const pos = positions.find((item) => item.symbol === action.symbol);
  if (
    pos &&
    typeof pos.latest_price === 'number' &&
    Number.isFinite(pos.latest_price)
  ) {
    return pos.latest_price;
  }
  return null;
}

function actionPriceLabel(
  side: string | null,
  dashboard: ReturnType<typeof useCopy>['overview']['dashboard'],
): string {
  if (side === 'buy') return dashboard.strategyRecommendationBuyPrice;
  if (side === 'sell') return dashboard.strategyRecommendationSellPrice;
  return dashboard.strategyRecommendationReferencePrice;
}

function resolveGrossAmount(
  action: RecommendationAction,
  intent: DailyTradingPlanResponse['order_intents'][number] | undefined,
  price: number | null,
): number | null {
  for (const candidate of [
    intent?.estimated_gross_amount,
    action.target_amount,
    action.estimated_gross_amount,
  ]) {
    if (typeof candidate === 'number' && Number.isFinite(candidate)) {
      return candidate;
    }
  }
  const qty =
    action.target_quantity ??
    action.estimated_quantity ??
    intent?.estimated_quantity;
  if (price != null && qty != null) {
    return price * qty;
  }
  return null;
}

function sideBadgeClass(side: string | null) {
  if (side === 'buy') {
    return 'bg-[color-mix(in_srgb,var(--app-success)_15%,transparent)] text-[var(--app-success-text)] border-[color-mix(in_srgb,var(--app-success)_35%,transparent)]';
  }
  if (side === 'sell') {
    return 'bg-[color-mix(in_srgb,var(--app-warning)_15%,transparent)] text-[var(--app-warning-text)] border-[color-mix(in_srgb,var(--app-warning)_35%,transparent)]';
  }
  return 'bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)] border-[var(--app-divider)]';
}

type RecommendationActionItemProps = {
  action: RecommendationAction;
  index: number;
  plan: DailyTradingPlanResponse;
  positions: AccountStateResponse['snapshot']['positions'];
  currentWeightBySymbol: Record<string, number>;
  dashboard: ReturnType<typeof useCopy>['overview']['dashboard'];
  locale: 'en' | 'zh';
  presentationLevel: PresentationLevel;
  showPortfolioSizing: boolean;
};

function RecommendationActionItem({
  action,
  index,
  plan,
  positions,
  currentWeightBySymbol,
  dashboard,
  locale,
  presentationLevel,
  showPortfolioSizing,
}: RecommendationActionItemProps) {
  const symbol = action.symbol ?? '';
  const name = actionName(action, positions);
  const weight = currentWeight(symbol, positions, currentWeightBySymbol);
  const intent = plan.order_intents?.find(
    (item) =>
      (action.action_id != null && item.action_id === action.action_id) ||
      (symbol && item.symbol === symbol),
  );
  const price = resolveActionPrice(action, intent, positions);
  const grossAmount = resolveGrossAmount(action, intent, price);
  const fee = intent?.estimated_total_fee ?? action.estimated_total_fee ?? null;
  const netCash =
    intent?.estimated_net_cash_impact ??
    action.estimated_net_cash_impact ??
    null;
  const positionEffect = intent?.position_effect ?? null;
  const constraintChecks = intent?.constraint_checks ?? [];
  const isBuy = action.side === 'buy';
  const isSell = action.side === 'sell';

  return (
    <li
      key={action.action_id ?? `${symbol || 'action'}-${index}`}
      className="min-w-0 py-3.5 first:pt-0 last:pb-0"
      data-testid={`overview-recommendation-item-${symbol || index}`}
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
          <span
            className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-bold border ${sideBadgeClass(action.side)}`}
          >
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
        {action.submission_status ? (
          <span className="app-type-micro rounded-full bg-[var(--app-surface-overlay)] px-2 py-0.5 font-medium text-[var(--app-text-tertiary)] border border-[var(--app-divider)]">
            {action.submission_status === 'manual_confirmation_required'
              ? dashboard.strategyRecommendationReview
              : action.submission_status === 'read_only_signal'
                ? dashboard.strategyRecommendationSignal
                : action.submission_status}
          </span>
        ) : null}
      </div>

      <div className="mt-3 grid gap-3 grid-cols-2 sm:grid-cols-4">
        <div className="min-w-0">
          <div className="app-type-label text-[var(--app-text-tertiary)]">
            {actionPriceLabel(action.side, dashboard)}
          </div>
          <div
            className="mt-1 text-sm font-semibold font-mono tabular-nums text-[var(--app-text)]"
            data-testid="recommendation-price"
          >
            {price != null ? formatCurrency(price) : '--'}
          </div>
        </div>

        {showPortfolioSizing ? (
          <div className="min-w-0">
            <div className="app-type-label text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '建议仓位' : 'Target allocation'}
            </div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-[var(--app-text)]">
              {weight == null ? '--' : formatPercent(weight)}
              <span className="mx-1 text-[var(--app-text-tertiary)]">→</span>
              <span className="text-[var(--app-accent)]">
                {(action.target_allocation ?? action.target_weight) == null
                  ? '--'
                  : formatPercent(
                      (action.target_allocation ?? action.target_weight)!,
                    )}
              </span>
            </div>
          </div>
        ) : null}

        {presentationLevel === 'manual_review' ||
        (action.target_quantity ??
          action.estimated_quantity ??
          intent?.estimated_quantity) != null ? (
          <div className="min-w-0">
            <div className="app-type-label text-[var(--app-text-tertiary)]">
              {dashboard.strategyRecommendationQuantity}
            </div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-[var(--app-text)]">
              {(action.target_quantity ??
                action.estimated_quantity ??
                intent?.estimated_quantity) == null
                ? '--'
                : `${formatQuantity(
                    (action.target_quantity ??
                      action.estimated_quantity ??
                      intent?.estimated_quantity)!,
                  )} ${quantityUnit(action.asset_class ?? null, locale)}`}
            </div>
          </div>
        ) : null}

        {presentationLevel === 'manual_review' || grossAmount != null ? (
          <div className="min-w-0">
            <div className="app-type-label text-[var(--app-text-tertiary)]">
              {dashboard.strategyRecommendationAmount}
            </div>
            <div className="mt-1 text-sm font-semibold font-mono tabular-nums text-[var(--app-text)]">
              {grossAmount != null ? formatCurrency(grossAmount) : '--'}
            </div>
          </div>
        ) : null}
      </div>

      {netCash != null ||
      fee != null ||
      positionEffect != null ||
      constraintChecks.length > 0 ? (
        <div className="mt-3 rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-overlay)]/40 p-2.5">
          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
            {netCash != null ? (
              <div>
                <span className="text-[var(--app-text-tertiary)]">
                  {dashboard.strategyRecommendationNetCash}:{' '}
                </span>
                <span
                  className={`font-mono font-medium tabular-nums ${isBuy ? 'text-[var(--app-warning-text)]' : isSell ? 'text-[var(--app-success-text)]' : 'text-[var(--app-text)]'}`}
                >
                  {netCash > 0
                    ? `+${formatCurrency(netCash)}`
                    : formatCurrency(netCash)}
                </span>
              </div>
            ) : null}
            {fee != null ? (
              <div>
                <span className="text-[var(--app-text-tertiary)]">
                  {dashboard.strategyRecommendationFee}:{' '}
                </span>
                <span className="font-mono font-medium tabular-nums text-[var(--app-text)]">
                  {formatCurrency(fee)}
                </span>
              </div>
            ) : null}
            {positionEffect ? (
              <div>
                <span className="text-[var(--app-text-tertiary)]">
                  {dashboard.strategyRecommendationPositionAfter}:{' '}
                </span>
                <span className="font-mono font-medium tabular-nums text-[var(--app-text)]">
                  {formatQuantity(positionEffect.current_quantity)}
                  {' → '}
                  {formatQuantity(positionEffect.estimated_quantity_after)}{' '}
                  {quantityUnit(action.asset_class ?? null, locale)}
                </span>
              </div>
            ) : null}
            {positionEffect ? (
              <div>
                <span className="text-[var(--app-text-tertiary)]">
                  {dashboard.strategyRecommendationAvgCostAfter}:{' '}
                </span>
                <span className="font-mono font-medium tabular-nums text-[var(--app-text)]">
                  {positionEffect.current_avg_cost == null
                    ? dashboard.strategyRecommendationPositionNew
                    : positionEffect.estimated_avg_cost_after == null
                      ? '--'
                      : `${formatCurrency(positionEffect.current_avg_cost)} → ${formatCurrency(positionEffect.estimated_avg_cost_after)}`}
                </span>
              </div>
            ) : null}
          </div>

          {constraintChecks.length > 0 ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-[var(--app-divider)]/40 pt-2">
              <span className="app-type-micro text-[var(--app-text-tertiary)] font-medium">
                {dashboard.strategyRecommendationRiskPassed}:
              </span>
              {constraintChecks.map((check) => {
                const isPassed = check.status === 'passed';
                return (
                  <span
                    key={check.id}
                    className={`inline-flex items-center rounded px-1.5 py-0.5 app-type-micro font-medium border ${
                      isPassed
                        ? 'border-[color-mix(in_srgb,var(--app-success)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] text-[var(--app-success-text)]'
                        : 'border-[color-mix(in_srgb,var(--app-danger)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-danger)_10%,transparent)] text-[var(--app-danger-text)]'
                    }`}
                  >
                    {check.id === 'cash_buffer'
                      ? isPassed
                        ? dashboard.strategyRecommendationCashBufferSufficient
                        : dashboard.strategyRecommendationCashBufferBreached
                      : check.id === 'single_symbol_weight'
                        ? locale === 'zh'
                          ? '单标的限额'
                          : 'Single asset limit'
                        : check.id}
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function OverviewStrategyRecommendation({
  planQuery,
  todayQuery,
  positions,
  currentWeightBySymbol,
  className,
}: {
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
      className={('min-w-0 ' + (className ?? '')).trim()}
      aria-label={dashboard.strategyRecommendationTitle}
    >
      <SectionHeader
        title={dashboard.strategyRecommendationTitle}
        meta={recommendationDate === '--' ? undefined : recommendationDate}
        className="overview-spotlight-heading"
        actions={
          <div className="flex items-center gap-3">
            <a
              href="/decision"
              className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
            >
              {dashboard.strategyRecommendationViewAll}
            </a>
          </div>
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
              <div className="flex items-center gap-2">
                <span className="app-type-label text-[var(--app-text-tertiary)]">
                  {locale === 'zh' ? '只读建议' : 'Read only'}
                </span>
              </div>
            </div>

            <ul className="mt-3 divide-y divide-[var(--app-divider)]">
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
              className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline shrink-0"
            >
              {dashboard.viewDecision}
            </a>
          </div>
        )
      ) : null}

      {plan &&
      (currentGeneration || !todayQuery.isLoading || quoteTooOldForReview) ? (
        <div
          data-testid="overview-recommendation-evidence"
          className="mt-2 space-y-1 app-type-compact text-[var(--app-text-secondary)]"
        >
          {currentGeneration || !todayQuery.isLoading ? (
            <p>
              {currentGeneration
                ? dashboard.strategyDailyGeneration[currentGeneration.status]
                : dashboard.strategyDailyGenerationUnavailable}
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
