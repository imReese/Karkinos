import { ChevronDown } from 'lucide-react';

import { StatusBadge } from '../../../shared/ui/workbench';
import type { RiskPageController } from '../model/use-risk-page-controller';
import { RiskHistoryWorkspace } from './risk-history-workspace';

export function RiskHistoryDisclosure({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, locale } = controller;
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="risk-history-disclosure"
    >
      <summary className="flex min-h-16 cursor-pointer list-none flex-col gap-3 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:flex-row sm:items-center sm:justify-between sm:gap-5 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="app-product-mark">
            {locale === 'zh' ? '历史与归因' : 'History & attribution'}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {locale === 'zh'
              ? '净值与事件解释路径'
              : 'Equity and event explanation path'}
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {locale === 'zh'
              ? '按需查看净值桥、影响事件、持仓驱动和时间序列归因；当前风险与受控操作保持在上方。'
              : 'Expand for the equity bridge, impact events, position drivers, and timeline attribution. Current risk and controlled actions stay above.'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
          {controller.explainability.isLoading ? (
            <StatusBadge tone="neutral">{copy.states.loading}</StatusBadge>
          ) : (
            <>
              <StatusBadge tone="neutral">
                {locale === 'zh'
                  ? `${controller.riskHistoryImpactCount} 条影响事件`
                  : `${controller.riskHistoryImpactCount} impact ${controller.riskHistoryImpactCount === 1 ? 'event' : 'events'}`}
              </StatusBadge>
              <StatusBadge tone="neutral">
                {locale === 'zh'
                  ? `${controller.riskHistoryValuationDayCount} 个估值日`
                  : `${controller.riskHistoryValuationDayCount} valuation ${controller.riskHistoryValuationDayCount === 1 ? 'day' : 'days'}`}
              </StatusBadge>
            </>
          )}
          <span className="sr-only">
            {locale === 'zh' ? '按需展开' : 'Expand on demand'}
          </span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </div>
      </summary>
      <div className="border-t border-[var(--app-divider)] py-4 sm:py-5">
        <RiskHistoryWorkspace
          title={copy.riskPage.equityBridge}
          stateLabelRecent={copy.riskPage.recentDrivers}
          stateLabelPositions={copy.riskPage.positionDrivers}
          emptyLabel={copy.riskPage.emptyDrivers}
          explainability={controller.explainability.data}
          loading={controller.explainability.isLoading}
          instrumentNames={controller.instrumentNames}
          filters={<RiskHistoryFilters controller={controller} />}
        />
      </div>
    </details>
  );
}

function RiskHistoryFilters({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy } = controller;
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <label className="grid gap-2">
        <span className="text-sm font-medium">{copy.market.noteDateFrom}</span>
        <input
          type="date"
          value={controller.timelineFromDate}
          onChange={(event) =>
            controller.setTimelineFromDate(event.target.value)
          }
          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          aria-label={copy.market.noteDateFrom}
        />
      </label>
      <label className="grid gap-2">
        <span className="text-sm font-medium">{copy.market.noteDateTo}</span>
        <input
          type="date"
          value={controller.timelineToDate}
          onChange={(event) => controller.setTimelineToDate(event.target.value)}
          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          aria-label={copy.market.noteDateTo}
        />
      </label>
      <label className="grid gap-2">
        <span className="text-sm font-medium">
          {copy.explainability.timelineEventKind}
        </span>
        <select
          value={controller.timelineEventKind}
          onChange={(event) =>
            controller.setTimelineEventKind(event.target.value)
          }
          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
          aria-label={copy.explainability.timelineEventKind}
        >
          <option value="">{copy.explainability.allEvents}</option>
          <option value="cash_deposit">{copy.explainability.deposits}</option>
          <option value="cash_withdrawal">
            {copy.explainability.withdrawals}
          </option>
          <option value="dividend">{copy.explainability.dividends}</option>
          <option value="trade_buy">{copy.explainability.buys}</option>
          <option value="trade_sell">{copy.explainability.sells}</option>
          <option value="manual_adjustment">
            {copy.explainability.adjustments}
          </option>
        </select>
      </label>
    </div>
  );
}
