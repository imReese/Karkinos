import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import type {
  AccountStateResponse,
  DailyTradingPlanResponse,
} from '../overview-feature-boundary';
import {
  SavedHistoricalComparison,
  forwardObservationLabel,
} from './overview-research-comparison';

type RecommendationAction = NonNullable<
  DailyTradingPlanResponse['account_action_recommendation']
>['actions'][number];

export type PresentationLevel =
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

export function RecommendationActionItem({
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
  const strategyContext = action.strategy_id
    ? plan.account_action_recommendation?.strategy_context?.[action.strategy_id]
    : undefined;
  const triggerCondition =
    action.side === 'buy'
      ? strategyContext?.entry_conditions
      : action.side === 'sell'
        ? strategyContext?.exit_conditions
        : null;
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

      <div className="mt-3 grid gap-3 grid-cols-2 sm:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
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

      {strategyContext ? (
        <div
          className="mt-3 space-y-1.5 border-t border-[var(--app-divider)] pt-2.5 text-sm text-[var(--app-text-secondary)]"
          data-testid="overview-account-strategy-evidence"
        >
          {strategyContext.strategy_stage === 'paper_shadow' ? (
            <p className="app-type-label text-[var(--app-warning-text)]">
              {locale === 'zh'
                ? presentationLevel === 'signal'
                  ? '研究／模拟策略 · 只读信号 · 尚未形成账户配置'
                  : '研究／模拟策略 · 账户级建议 · 待人工确认'
                : presentationLevel === 'signal'
                  ? 'Research / simulation strategy · Read-only signal · Account sizing pending'
                  : 'Research / simulation strategy · Account recommendation · Human confirmation required'}
            </p>
          ) : null}
          <p>
            <span className="font-semibold">
              {locale === 'zh' ? '触发条件：' : 'Condition: '}
            </span>
            {triggerCondition ||
              (locale === 'zh'
                ? '条件证据不可用'
                : 'Condition evidence unavailable')}
          </p>
          <p>
            <span className="font-semibold">
              {locale === 'zh'
                ? '策略假设（冻结文本）：'
                : 'Strategy hypothesis (saved text): '}
            </span>
            {strategyContext.economic_hypothesis ||
              (locale === 'zh'
                ? '理由证据不可用'
                : 'Rationale evidence unavailable')}
          </p>
          <p>
            <span className="font-semibold">
              {locale === 'zh'
                ? '风险说明（冻结文本）：'
                : 'Risk explanation (saved text): '}
            </span>
            {strategyContext.risk_impact ||
              (locale === 'zh'
                ? '风险说明不可用'
                : 'Risk explanation unavailable')}
          </p>
          {strategyContext.failure_conditions.length > 0 ? (
            <details>
              <summary className="cursor-pointer app-type-compact">
                {locale === 'zh' ? '失效条件' : 'Invalidation conditions'}
              </summary>
              <ul className="mt-1 list-disc space-y-1 pl-4">
                {strategyContext.failure_conditions.map((condition) => (
                  <li key={condition}>{condition}</li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 app-type-compact">
            {action.frozen_market_date ? (
              <span>
                {locale === 'zh' ? '已核验行情：' : 'Verified market date: '}
                {formatDate(action.frozen_market_date)}
              </span>
            ) : null}
            {Number.isSafeInteger(strategyContext.saved_backtest_id) &&
            strategyContext.saved_backtest_id! > 0 ? (
              <a
                href={`/backtest?id=${strategyContext.saved_backtest_id}`}
                onClick={(e) =>
                  handleClientNavigation(
                    e,
                    `/backtest?id=${strategyContext.saved_backtest_id}`,
                  )
                }
                className="font-semibold text-[var(--app-accent)] hover:underline"
              >
                {locale === 'zh' ? '查看真实回测' : 'View saved backtest'} #
                {strategyContext.saved_backtest_id}
              </a>
            ) : null}
          </div>
          {strategyContext.historical_comparison ? (
            <SavedHistoricalComparison
              comparison={strategyContext.historical_comparison}
              locale={locale}
              testId="overview-account-historical-comparison"
            />
          ) : null}
          <p data-testid="overview-account-forward-state">
            {locale === 'zh'
              ? '前向观测（独立）：'
              : 'Forward observation (separate): '}
            {forwardObservationLabel(strategyContext.forward, locale)}
          </p>
        </div>
      ) : null}

      {netCash != null ||
      fee != null ||
      positionEffect != null ||
      constraintChecks.length > 0 ? (
        <div className="mt-3 rounded-lg border border-[var(--app-divider)] bg-[var(--app-surface-overlay)]/40 p-2.5">
          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
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
