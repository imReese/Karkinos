import { formatCurrency } from '../../../shared/format';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import type { PortfolioCopy } from '../copy';
import type { DailyTradingPlanResponse } from '../portfolio-feature-boundary';

export function RebalanceAlertBanner({
  copy,
  tradingPlan,
}: {
  copy: PortfolioCopy;
  tradingPlan?: DailyTradingPlanResponse | null;
}) {
  const intents = tradingPlan?.order_intents ?? [];
  const totalActions =
    intents.length > 0
      ? intents.length
      : (tradingPlan?.order_intent_count ?? 0);

  if (totalActions <= 0) {
    return null;
  }

  const buyCount = intents.filter(
    (intent) => intent.side?.toLowerCase() === 'buy',
  ).length;
  const sellCount = intents.filter(
    (intent) => intent.side?.toLowerCase() === 'sell',
  ).length;
  const requiresApproval =
    tradingPlan?.manual_ready_count ??
    intents.filter(
      (intent) =>
        intent.manual_confirmation_status === 'pending_confirmation' ||
        intent.manual_confirmation_status === 'requires_confirmation',
    ).length;
  const blockedCount =
    tradingPlan?.blocked_count ?? tradingPlan?.blockers?.length ?? 0;
  const turnover = intents.reduce(
    (sum, intent) => sum + (intent.estimated_gross_amount || 0),
    0,
  );

  return (
    <div
      data-testid="portfolio-rebalance-alert-banner"
      role="region"
      aria-label={copy.rebalanceAlert.title}
      className="flex flex-col gap-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-accent)_38%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] p-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3 sm:items-center">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[color-mix(in_srgb,var(--app-accent)_20%,transparent)] text-xs text-[var(--app-accent)] font-bold">
          ⚡
        </div>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
            <span className="text-xs sm:text-sm font-semibold text-[var(--app-text)]">
              {copy.rebalanceAlert.rebalancePending(totalActions)}
            </span>
            <span className="app-type-micro rounded-full border border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] px-2 py-0.5 font-medium text-[var(--app-accent-text)]">
              {copy.rebalanceAlert.buySellSummary(buyCount, sellCount)}
            </span>
            {requiresApproval > 0 ? (
              <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-warning-indicator)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-warning-indicator)_10%,transparent)] px-2 py-0.5 font-medium text-[var(--app-warning-indicator)]">
                {copy.rebalanceAlert.requiresApproval(requiresApproval)}
              </span>
            ) : null}
            {blockedCount > 0 ? (
              <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-danger-indicator)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-danger-indicator)_10%,transparent)] px-2 py-0.5 font-medium text-[var(--app-danger-indicator)]">
                {copy.rebalanceAlert.blockedActions(blockedCount)}
              </span>
            ) : null}
          </div>
          {turnover > 0 ? (
            <div className="app-muted app-type-micro mt-0.5 font-mono">
              {copy.rebalanceAlert.estimatedTurnover}:{' '}
              {formatCurrency(turnover)}
            </div>
          ) : null}
        </div>
      </div>
      <div className="shrink-0">
        <a
          href="/decision"
          onClick={(e) => handleClientNavigation(e, '/decision')}
          data-testid="rebalance-alert-decision-link"
          className="app-button-secondary inline-flex items-center gap-1 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] hover:text-[var(--app-text)]"
        >
          <span>{copy.rebalanceAlert.goToDecision}</span>
          <span aria-hidden="true">&rarr;</span>
        </a>
      </div>
    </div>
  );
}
