import { ChevronDown } from 'lucide-react';

import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  ExceptionList,
  type ExceptionItem,
} from '../../../shared/ui/workbench';
import { buildTodayQueueModel } from '../model/today-queue-model';
import { buildDecisionQueueItem } from '../model/today-queue-trading-plan';
import {
  TODAY_QUEUE_PRIORITY_ORDER,
  type DashboardTodayQueueProps,
  type TodayQueuePriority,
} from '../model/today-queue-types';
import {
  ConfirmedFundNavRefreshButton,
  MarketRefreshButton,
} from '../overview-feature-boundary';

function todayQueuePriorityLabel(
  priority: TodayQueuePriority,
  labels: AppCopy['overview']['dashboard'],
) {
  if (priority === 'first') {
    return labels.queuePriorityFirst;
  }
  if (priority === 'watch') {
    return labels.queuePriorityWatch;
  }
  return labels.queuePriorityNormal;
}

function exceptionLabels(locale: 'en' | 'zh') {
  return locale === 'zh'
    ? {
        reason: '阻断原因',
        unblockCondition: '解除条件',
        nextAction: '安全下一步',
        evidence: '证据',
      }
    : {
        reason: 'Reason',
        unblockCondition: 'Unblock condition',
        nextAction: 'Safe next step',
        evidence: 'Evidence',
      };
}

/** Keep today's account-recommendation status visible without portfolio views. */
export function DashboardDecisionQueueFallback({
  todayDecision,
  todayDecisionLoading,
  todayDecisionError,
  tradingPlan,
  tradingPlanLoading,
  tradingPlanError,
}: Pick<
  DashboardTodayQueueProps,
  | 'todayDecision'
  | 'todayDecisionLoading'
  | 'todayDecisionError'
  | 'tradingPlan'
  | 'tradingPlanLoading'
  | 'tradingPlanError'
>) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const item = buildDecisionQueueItem({
    todayDecision,
    todayDecisionLoading,
    todayDecisionError,
    tradingPlan,
    tradingPlanLoading,
    tradingPlanError,
    instrumentDiagnostics: [],
    copy,
    locale,
  });
  return (
    <section className="min-w-0" data-testid="overview-decision-queue-fallback">
      <div className="mb-2">
        <div className="app-type-overline text-[var(--app-text-tertiary)]">
          {labels.dailyWorkbench}
        </div>
        <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
          {labels.todayToReview}
        </h2>
      </div>
      <ExceptionList
        ariaLabel={labels.todayToReview}
        emptyState={labels.noActionItems}
        density="compact"
        labels={exceptionLabels(locale)}
        items={[
          {
            id: item.key,
            severity:
              item.tone === 'danger'
                ? 'danger'
                : item.tone === 'warning'
                  ? 'warning'
                  : 'info',
            statusLabel: todayQueuePriorityLabel(item.priority, labels),
            title: item.title,
            reason: item.detail,
            unblockCondition: item.resolution,
            nextAction: (
              <a
                href={item.href}
                className="font-semibold text-[var(--app-accent)] hover:underline"
              >
                {item.actionLabel}
              </a>
            ),
            evidence: item.meta,
          },
        ]}
      />
    </section>
  );
}

export function DashboardTodayQueue(props: DashboardTodayQueueProps) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const { items, dataQuoteRefreshSymbols, dataConfirmedFundNavRefreshSymbols } =
    buildTodayQueueModel(props, copy, locale);
  const actionableCount = items.filter(
    (item) => item.priority !== 'normal',
  ).length;
  const exceptionItems: (ExceptionItem & { alwaysVisible: boolean })[] = items
    .filter((item) => item.priority !== 'normal' || item.alwaysVisible === true)
    .sort(
      (left, right) =>
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(left.priority) -
        TODAY_QUEUE_PRIORITY_ORDER.indexOf(right.priority),
    )
    .map((item) => ({
      id: item.key,
      severity:
        item.tone === 'danger'
          ? 'danger'
          : item.tone === 'warning'
            ? 'warning'
            : 'info',
      statusLabel: todayQueuePriorityLabel(item.priority, labels),
      title: item.title,
      reason: item.detail,
      unblockCondition: item.resolution,
      nextAction:
        item.key === 'data' &&
        (dataQuoteRefreshSymbols.length > 0 ||
          dataConfirmedFundNavRefreshSymbols.length > 0) ? (
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
            {dataConfirmedFundNavRefreshSymbols.length > 0 ? (
              <ConfirmedFundNavRefreshButton
                compact
                symbols={dataConfirmedFundNavRefreshSymbols}
              />
            ) : null}
            {dataQuoteRefreshSymbols.length > 0 ? (
              <MarketRefreshButton compact symbols={dataQuoteRefreshSymbols} />
            ) : null}
            <a
              href={item.href}
              className="inline-flex min-h-8 items-center font-semibold text-[var(--app-accent)] hover:underline"
            >
              {item.actionLabel}
            </a>
          </div>
        ) : (
          <a
            href={item.href}
            className="font-semibold text-[var(--app-accent)] hover:underline"
          >
            {item.actionLabel}
          </a>
        ),
      evidence: item.meta,
      alwaysVisible: item.alwaysVisible === true,
    }));
  const normalCount = items.length - actionableCount;
  const primaryExceptionItems = [
    ...exceptionItems.slice(0, 1),
    ...exceptionItems.slice(1).filter((item) => item.alwaysVisible),
  ];
  const additionalExceptionItems = exceptionItems
    .slice(1)
    .filter((item) => !item.alwaysVisible);
  return (
    <section className="min-w-0" data-testid="overview-today-queue">
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {labels.dailyWorkbench}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {labels.todayToReview}
          </h2>
        </div>
        <span className="text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]">
          {actionableCount}
        </span>
      </div>
      <ExceptionList
        items={primaryExceptionItems}
        ariaLabel={labels.todayToReview}
        emptyState={labels.noActionItems}
        density="compact"
        className="app-overview-primary-exception"
        labels={exceptionLabels(locale)}
      />
      {additionalExceptionItems.length > 0 ? (
        <details
          data-testid="overview-today-queue-more"
          className="group border-b border-[var(--app-divider)]"
        >
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span>
              {labels.additionalReviewItems(additionalExceptionItems.length)}
            </span>
            <ChevronDown
              className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
              aria-hidden="true"
            />
          </summary>
          <ExceptionList
            items={additionalExceptionItems}
            ariaLabel={labels.additionalReviewItems(
              additionalExceptionItems.length,
            )}
            emptyState={labels.noActionItems}
            density="compact"
            className="border-b-0"
            labels={exceptionLabels(locale)}
          />
        </details>
      ) : null}
      {normalCount > 0 ? (
        <div
          data-testid="overview-today-queue-normal"
          className="mt-2 border-y border-[var(--app-divider)] px-3 py-2 text-xs text-[var(--app-text-tertiary)]"
        >
          {todayQueuePriorityLabel('normal', labels)} · {normalCount}
        </div>
      ) : null}
    </section>
  );
}
