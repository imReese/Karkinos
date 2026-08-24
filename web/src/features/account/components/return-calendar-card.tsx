import { useCopy } from '../../../shared/i18n/context';
import { ReturnCalendarDetail } from './return-calendar-detail';
import { ReturnCalendarGrid } from './return-calendar-grid';
import {
  formatReturnCurrency,
  formatReturnPercent,
  type ReturnCalendarMarketCalendar,
  type ReturnCalendarPosition,
  type ReturnCalendarTimelinePoint,
} from './return-calendar-model';
import {
  ReturnCalendarEmptyState,
  ReturnCurveChart,
} from './return-calendar-supporting-views';
import { ReturnCalendarToolbar } from './return-calendar-toolbar';
import { useReturnCalendarController } from './use-return-calendar-controller';

export type {
  ReturnCalendarBreakdownItem,
  ReturnCalendarMarketCalendar,
} from './return-calendar-model';

export function ReturnCalendarCard({
  timeline,
  positions = [],
  marketCalendar,
  compact = false,
}: {
  timeline: ReturnCalendarTimelinePoint[];
  positions?: ReturnCalendarPosition[];
  marketCalendar?: ReturnCalendarMarketCalendar | null;
  compact?: boolean;
}) {
  const copy = useCopy();
  const controller = useReturnCalendarController(timeline, marketCalendar);
  const contentGridClass =
    controller.period === 'week'
      ? compact
        ? 'return-calendar-layout-week mt-3 grid gap-3 2xl:grid-cols-1'
        : 'return-calendar-layout-week mt-4 grid gap-4 xl:grid-cols-1'
      : compact
        ? 'mt-3 grid gap-3 2xl:grid-cols-[minmax(0,1fr)_260px]'
        : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';
  const panelClass = compact ? 'p-4' : 'app-panel rounded-2xl p-4 sm:p-5';

  return (
    <div className={panelClass} data-testid="return-calendar-card">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {copy.explainability.returnCalendar}
          </div>
          <div className="app-muted mt-2 max-w-2xl text-sm">
            {copy.explainability.returnCalendarDetail}
          </div>
        </div>
      </div>
      {controller.hasTimeline ? (
        <ReturnCalendarToolbar
          copy={copy}
          compact={compact}
          viewMode={controller.viewMode}
          period={controller.period}
          metric={controller.metric}
          activeMonth={controller.activeMonth}
          activeYear={controller.activeYear}
          monthOptions={controller.monthOptions}
          yearOptions={controller.yearOptions}
          valuationStatus={controller.valuationStatus}
          onViewModeChange={controller.selectViewMode}
          onPeriodChange={controller.selectPeriod}
          onMetricChange={controller.selectMetric}
          onMonthChange={controller.selectMonth}
          onYearChange={controller.selectYear}
        />
      ) : null}

      {controller.aggregated.length === 0 ? (
        <ReturnCalendarEmptyState
          positions={positions}
          copy={copy}
          compact={compact}
        />
      ) : controller.viewMode === 'calendar' ? (
        <div className={contentGridClass} data-testid="return-calendar-layout">
          <ReturnCalendarGrid
            rows={controller.aggregated}
            period={controller.period}
            activeMonth={controller.activeMonth}
            activeYear={controller.activeYear}
            metric={controller.metric}
            copy={copy}
            compact={compact}
            selectedLabel={controller.selectedRow?.label ?? null}
            onSelect={controller.selectLabel}
            marketCalendarDays={controller.marketCalendarDays}
          />
          <ReturnCalendarDetail
            row={controller.selectedRow}
            period={controller.period}
            metric={controller.metric}
            copy={copy}
            compact={compact}
          />
        </div>
      ) : controller.viewMode === 'table' ? (
        <ReturnCalendarTable
          rows={controller.aggregated}
          metric={controller.metric}
        />
      ) : (
        <div className="mt-4">
          <ReturnCurveChart
            points={controller.aggregated.map((row) => ({
              label: row.label,
              value:
                controller.metric === 'amount'
                  ? row.marketPnl
                  : row.percentChange,
            }))}
          />
        </div>
      )}
    </div>
  );
}

function ReturnCalendarTable({
  rows,
  metric,
}: {
  rows: ReturnType<typeof useReturnCalendarController>['aggregated'];
  metric: ReturnType<typeof useReturnCalendarController>['metric'];
}) {
  const copy = useCopy();
  return (
    <div className="mt-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
      <table className="min-w-full text-left text-sm">
        <thead className="app-kicker app-type-overline">
          <tr>
            <th className="px-3 py-2">{copy.explainability.bucketLabel}</th>
            <th className="px-3 py-2">{copy.explainability.netChange}</th>
            <th className="px-3 py-2">{copy.explainability.externalFlow}</th>
            <th className="px-3 py-2">{copy.explainability.marketPnl}</th>
          </tr>
        </thead>
        <tbody>
          {rows
            .slice()
            .reverse()
            .map((row) => {
              const hasMissingValuation = row.valuationStatus === 'missing';
              const returnValue = hasMissingValuation
                ? copy.explainability.missingValuationShort
                : metric === 'amount'
                  ? formatReturnCurrency(row.delta)
                  : formatReturnPercent(row.percentChange);
              const marketValue = hasMissingValuation
                ? copy.explainability.missingValuationShort
                : formatReturnCurrency(row.marketPnl);
              return (
                <tr
                  key={row.label}
                  className="border-t border-[var(--app-border)]"
                >
                  <td className="px-3 py-3 font-medium">{row.label}</td>
                  <td className="px-3 py-3">{returnValue}</td>
                  <td className="px-3 py-3">
                    {formatReturnCurrency(row.externalFlow)}
                  </td>
                  <td className="px-3 py-3">{marketValue}</td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
