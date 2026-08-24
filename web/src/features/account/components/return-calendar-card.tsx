import { useMemo, useState, type ReactNode } from 'react';
import {
  BarChart3,
  CalendarDays,
  CircleDollarSign,
  Percent,
  Table2,
} from 'lucide-react';

import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import {
  formatCurrency as formatCurrencyValue,
  formatPercent as formatPercentValue,
} from '../../../shared/format';
import {
  MARKET_CALENDAR_SCHEMA_VERSION,
  explainMarketCalendarDate,
  type MarketCalendarDay,
  type MarketCalendarDayType,
} from '../../../shared/market-calendar';

type ReturnCalendarPeriod = 'day' | 'week' | 'month' | 'year';

export type ReturnCalendarBreakdownItem = {
  key: string;
  label: string;
  value: number;
};

type ReturnCalendarRow = {
  label: string;
  delta: number;
  externalFlow: number;
  marketPnl: number;
  percentChange: number;
  valuationStatus: string;
  missingPriceSymbols: string[];
  marketBreakdown: ReturnCalendarBreakdownItem[];
  externalFlowBreakdown: ReturnCalendarBreakdownItem[];
};

type ReturnCalendarPosition = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
};

export type ReturnCalendarMarketCalendar = {
  status: string;
  days: Array<{
    schema_version: string;
    date: string;
    day_type: MarketCalendarDayType;
    reason_code: MarketCalendarDay['reasonCode'];
    reason: string;
    is_trading_day: boolean;
  }>;
};

export function ReturnCalendarCard({
  timeline,
  positions = [],
  marketCalendar,
  compact = false,
}: {
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
    valuation_status?: string;
    missing_price_symbols?: string[];
    market_breakdown?: ReturnCalendarBreakdownItem[];
    external_flow_breakdown?: ReturnCalendarBreakdownItem[];
  }>;
  positions?: ReturnCalendarPosition[];
  marketCalendar?: ReturnCalendarMarketCalendar | null;
  compact?: boolean;
}) {
  const copy = useCopy();
  const dailyRows = aggregateReturnTimeline(timeline, 'day');
  const weeklyRows = aggregateReturnTimeline(timeline, 'week');
  const monthlyRows = aggregateReturnTimeline(timeline, 'month');
  const yearlyRows = aggregateReturnTimeline(timeline, 'year');
  const monthOptions = Array.from(
    new Set(dailyRows.map((row) => row.label.slice(0, 7))),
  ).sort();
  const yearOptions = Array.from(
    new Set(monthlyRows.map((row) => row.label.slice(0, 4))),
  ).sort();
  const initialMonth = monthOptions[monthOptions.length - 1] ?? '';
  const initialYear = yearOptions[yearOptions.length - 1] ?? '';
  const [viewMode, setViewMode] = useState<'calendar' | 'table' | 'curve'>(
    'calendar',
  );
  const [period, setPeriod] = useState<ReturnCalendarPeriod>('day');
  const [metric, setMetric] = useState<'amount' | 'percent'>('amount');
  const [selectedMonth, setSelectedMonth] = useState(initialMonth);
  const [selectedYear, setSelectedYear] = useState(initialYear);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);

  const activeMonth = monthOptions.includes(selectedMonth)
    ? selectedMonth
    : initialMonth;
  const activeYear = yearOptions.includes(selectedYear)
    ? selectedYear
    : initialYear;

  const aggregated =
    period === 'day'
      ? dailyRows.filter((row) => row.label.startsWith(activeMonth))
      : period === 'week'
        ? weeklyRows.filter((row) => row.label.startsWith(activeYear))
        : period === 'month'
          ? monthlyRows.filter((row) => row.label.startsWith(activeYear))
          : yearlyRows;
  const selectedRow =
    aggregated.find((row) => row.label === selectedLabel) ??
    aggregated[aggregated.length - 1] ??
    null;
  const marketCalendarDays = useMemo(
    () => buildMarketCalendarDayMap(marketCalendar),
    [marketCalendar],
  );
  const panelClass = compact ? 'p-4' : 'app-panel rounded-2xl p-4 sm:p-5';
  const contentGridClass =
    period === 'week'
      ? compact
        ? 'return-calendar-layout-week mt-3 grid gap-3 2xl:grid-cols-1'
        : 'return-calendar-layout-week mt-4 grid gap-4 xl:grid-cols-1'
      : compact
        ? 'mt-3 grid gap-3 2xl:grid-cols-[minmax(0,1fr)_260px]'
        : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';
  const hasTimeline = timeline.length > 0;
  const valuationStatus = summarizeReturnCalendarStatus(aggregated);

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
      {hasTimeline ? (
        <div className={`${compact ? 'mt-3' : 'mt-4'} min-w-0`}>
          <div
            className="grid min-w-0 items-center gap-3 rounded-2xl bg-[color-mix(in_srgb,var(--app-surface-1)_62%,transparent)] p-1.5 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-border)_36%,transparent)] sm:grid-cols-[auto_minmax(14rem,1fr)_auto] sm:rounded-full"
            data-testid="return-calendar-toolbar"
          >
            <ReturnCalendarSegmentedControl
              compactMode="icon"
              label={copy.explainability.viewMode}
              options={[
                {
                  value: 'calendar',
                  label: copy.explainability.calendarView,
                  icon: <CalendarDays aria-hidden="true" size={18} />,
                },
                {
                  value: 'curve',
                  label: copy.explainability.curveView,
                  icon: <BarChart3 aria-hidden="true" size={18} />,
                },
                {
                  value: 'table',
                  label: copy.explainability.tableView,
                  icon: <Table2 aria-hidden="true" size={17} />,
                },
              ]}
              value={viewMode}
              onChange={(value) =>
                setViewMode(value as 'calendar' | 'table' | 'curve')
              }
            />
            <ReturnCalendarSegmentedControl
              compactMode="period"
              label={copy.explainability.periodMode}
              options={[
                { value: 'day', label: copy.explainability.day },
                { value: 'week', label: copy.explainability.week },
                { value: 'month', label: copy.explainability.month },
                { value: 'year', label: copy.explainability.year },
              ]}
              value={period}
              onChange={(value) => {
                setPeriod(value as ReturnCalendarPeriod);
                setSelectedLabel(null);
              }}
            />
            <ReturnCalendarSegmentedControl
              compactMode="metric"
              label={copy.explainability.metricMode}
              options={[
                {
                  value: 'amount',
                  label: copy.explainability.amountMetric,
                  icon: <CircleDollarSign aria-hidden="true" size={18} />,
                },
                {
                  value: 'percent',
                  label: copy.explainability.percentMetric,
                  icon: <Percent aria-hidden="true" size={18} />,
                },
              ]}
              value={metric}
              onChange={(value) => setMetric(value as 'amount' | 'percent')}
            />
          </div>
          <div className="mt-2 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            {period === 'day' ? (
              <select
                aria-label={copy.explainability.month}
                data-testid="return-calendar-period-select"
                value={activeMonth}
                onChange={(event) => {
                  setSelectedMonth(event.target.value);
                  setSelectedLabel(null);
                }}
                className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-40"
              >
                {monthOptions.map((month) => (
                  <option key={month} value={month}>
                    {month}
                  </option>
                ))}
              </select>
            ) : period === 'week' || period === 'month' ? (
              <select
                aria-label={copy.explainability.year}
                data-testid="return-calendar-period-select"
                value={activeYear}
                onChange={(event) => {
                  setSelectedYear(event.target.value);
                  setSelectedLabel(null);
                }}
                className="app-field h-9 min-w-0 rounded-full px-3 text-sm sm:w-32"
              >
                {yearOptions.map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            ) : (
              <div className="hidden sm:block" aria-hidden="true" />
            )}
            <ReturnCalendarDataStatus
              status={valuationStatus}
              copy={copy}
              compact={compact}
            />
          </div>
        </div>
      ) : null}

      {aggregated.length === 0 ? (
        <ReturnCalendarEmptyState
          positions={positions}
          copy={copy}
          compact={compact}
        />
      ) : viewMode === 'calendar' ? (
        <div className={contentGridClass} data-testid="return-calendar-layout">
          <ReturnCalendarGrid
            rows={aggregated}
            period={period}
            activeMonth={activeMonth}
            activeYear={activeYear}
            metric={metric}
            copy={copy}
            compact={compact}
            selectedLabel={selectedRow?.label ?? null}
            onSelect={setSelectedLabel}
            marketCalendarDays={marketCalendarDays}
          />
          <ReturnCalendarDetail
            row={selectedRow}
            period={period}
            metric={metric}
            copy={copy}
            compact={compact}
          />
        </div>
      ) : viewMode === 'table' ? (
        <div className="mt-4 min-w-0 max-w-full overflow-x-auto overscroll-x-contain">
          <table className="min-w-full text-left text-sm">
            <thead className="app-kicker app-type-overline">
              <tr>
                <th className="px-3 py-2">{copy.explainability.bucketLabel}</th>
                <th className="px-3 py-2">{copy.explainability.netChange}</th>
                <th className="px-3 py-2">
                  {copy.explainability.externalFlow}
                </th>
                <th className="px-3 py-2">{copy.explainability.marketPnl}</th>
              </tr>
            </thead>
            <tbody>
              {aggregated
                .slice()
                .reverse()
                .map((row) => {
                  const hasMissingValuation = row.valuationStatus === 'missing';
                  const returnValue = hasMissingValuation
                    ? copy.explainability.missingValuationShort
                    : metric === 'amount'
                      ? formatCurrency(row.delta)
                      : formatPercent(row.percentChange);
                  const marketValue = hasMissingValuation
                    ? copy.explainability.missingValuationShort
                    : formatCurrency(row.marketPnl);
                  return (
                    <tr
                      key={row.label}
                      className="border-t border-[var(--app-border)]"
                    >
                      <td className="px-3 py-3 font-medium">{row.label}</td>
                      <td className="px-3 py-3">{returnValue}</td>
                      <td className="px-3 py-3">
                        {formatCurrency(row.externalFlow)}
                      </td>
                      <td className="px-3 py-3">{marketValue}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-4">
          <ReturnCurveChart
            points={aggregated.map((row) => ({
              label: row.label,
              value: metric === 'amount' ? row.marketPnl : row.percentChange,
            }))}
          />
        </div>
      )}
    </div>
  );
}

function ReturnCalendarSegmentedControl({
  compactMode = 'period',
  label,
  options,
  value,
  onChange,
}: {
  compactMode?: 'icon' | 'period' | 'metric';
  label: string;
  options: Array<{ value: string; label: string; icon?: ReactNode }>;
  value: string;
  onChange: (value: string) => void;
}) {
  const groupClass =
    compactMode === 'period'
      ? 'inline-flex w-full min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1 sm:justify-between'
      : 'inline-flex w-fit min-w-0 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_70%,transparent)] p-1';
  const buttonClass =
    compactMode === 'period'
      ? 'min-h-8 min-w-12 rounded-full px-4 py-1 text-base font-semibold transition sm:flex-1'
      : 'grid min-h-8 min-w-9 place-items-center rounded-full px-2 py-1 text-xs font-semibold transition';

  return (
    <div
      aria-label={label}
      className={`${groupClass} ${compactMode === 'metric' ? 'sm:justify-self-end' : ''}`}
      data-compact={compactMode}
      role="group"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            aria-label={option.label}
            onClick={() => onChange(option.value)}
            className={`${buttonClass} ${
              active
                ? 'bg-[var(--app-button)] text-[var(--app-button-text)] shadow-sm'
                : 'text-[color-mix(in_srgb,var(--app-muted)_78%,transparent)] hover:text-[var(--app-text)]'
            }`}
          >
            {option.icon ?? option.label}
            {option.icon ? (
              <span className="sr-only">{option.label}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

function ReturnCalendarDataStatus({
  status,
  copy,
  compact,
}: {
  status: string;
  copy: AppCopy;
  compact: boolean;
}) {
  const detail =
    status === 'missing'
      ? copy.explainability.missingValuation
      : status === 'partial'
        ? copy.explainability.partialValuation
        : copy.explainability.confirmedValuation;
  const tone =
    status === 'missing'
      ? 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
      : status === 'partial'
        ? 'border-[color-mix(in_srgb,var(--app-accent-secondary)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-accent-secondary)_10%,transparent)] text-[var(--app-accent-secondary)]'
        : 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]';

  return (
    <div
      className={`${compact ? 'px-3 py-1.5' : 'px-3 py-2'} flex min-w-0 items-center gap-2 rounded-full border ${tone}`}
      data-testid="return-calendar-status-chip"
    >
      <div className="app-type-overline shrink-0">
        {copy.explainability.dataStatus}
      </div>
      <div className="min-w-0 truncate text-xs font-semibold">{detail}</div>
    </div>
  );
}

function summarizeReturnCalendarStatus(rows: ReturnCalendarRow[]) {
  if (rows.some((row) => row.valuationStatus === 'missing')) {
    return 'missing';
  }
  if (rows.some((row) => row.valuationStatus === 'partial')) {
    return 'partial';
  }
  return 'complete';
}

function ReturnCalendarEmptyState({
  positions,
  copy,
  compact,
}: {
  positions: ReturnCalendarPosition[];
  copy: AppCopy;
  compact: boolean;
}) {
  const totalUnrealizedPnl = positions.reduce(
    (total, position) => total + position.unrealized_pnl,
    0,
  );
  const totalRealizedPnl = positions.reduce(
    (total, position) => total + position.realized_pnl,
    0,
  );
  const totalMarketValue = positions.reduce(
    (total, position) => total + position.market_value,
    0,
  );
  const totalPnl = totalUnrealizedPnl + totalRealizedPnl;
  const rankedPositions = positions
    .slice()
    .sort(
      (left, right) =>
        Math.abs(right.unrealized_pnl + right.realized_pnl) -
        Math.abs(left.unrealized_pnl + left.realized_pnl),
    )
    .slice(0, 4);
  const wrapperClass = compact
    ? 'mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_240px]'
    : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';

  return (
    <div className={wrapperClass} data-testid="return-calendar-empty-state">
      <div className="min-w-0 rounded-md border border-dashed border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3">
        <div className="app-kicker app-type-overline">
          {copy.explainability.currentPositionPnl}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <CalendarFallbackMetric
            label={copy.explainability.netChange}
            value={formatCurrency(totalPnl)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.marketValue}
            value={formatCurrency(totalMarketValue)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.unrealizedPnl}
            value={formatCurrency(totalUnrealizedPnl)}
          />
        </div>
        {rankedPositions.length > 0 ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {rankedPositions.map((position) => {
              const positionPnl =
                position.unrealized_pnl + position.realized_pnl;
              const displayName =
                position.display_name || position.name || position.symbol;
              const assetClass = position.asset_class || '--';
              const assetClassDisplay = formatAssetClassLabel(
                assetClass,
                copy.common,
              );
              return (
                <div
                  key={position.symbol}
                  className="rounded-md border border-[var(--app-border)] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate font-semibold">
                      {displayName}
                    </span>
                    <span
                      className={
                        positionPnl > 0
                          ? 'text-[var(--app-pnl-positive)]'
                          : positionPnl < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : 'text-[var(--app-pnl-neutral)]'
                      }
                    >
                      {formatCurrency(positionPnl)}
                    </span>
                  </div>
                  <div className="app-muted app-type-micro mt-1 flex items-center gap-2 uppercase">
                    <span>{position.symbol}</span>
                    <span aria-hidden="true">/</span>
                    <span>{assetClassDisplay}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] p-3">
        <div className="app-kicker app-type-overline">
          {copy.explainability.returnCalendarWarmingUp}
        </div>
        <div className="app-muted mt-2 text-sm">
          {copy.explainability.returnCalendarEmptyDetail}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="/activity"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.addActivity}
          </a>
          <a
            href="/market"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.checkDataSource}
          </a>
        </div>
      </div>
    </div>
  );
}

function CalendarFallbackMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] px-3 py-2">
      <div className="app-muted app-type-micro">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

function ReturnCurveChart({
  points,
}: {
  points: Array<{ label: string; value: number }>;
}) {
  const copy = useCopy();
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (points.length === 0) {
    return null;
  }
  const width = 820;
  const height = 420;
  const left = 96;
  const right = 36;
  const top = 30;
  const bottom = 68;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const values = points.map((point) => point.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const positionForPoint = (point: { value: number }, index: number) => {
    const x = left + (index / Math.max(points.length - 1, 1)) * chartWidth;
    const y = top + chartHeight - ((point.value - min) / range) * chartHeight;
    return { x, y };
  };
  const positionedPoints = points.map((point, index) => ({
    ...point,
    ...positionForPoint(point, index),
  }));
  const line = positionedPoints
    .map((point) => `${point.x},${point.y}`)
    .join(' ');
  const ticks = Array.from(new Set(max === min ? [max] : [max, 0, min]));
  const zeroY = top + chartHeight - ((0 - min) / range) * chartHeight;
  const firstLabel = points[0]?.label ?? '';
  const lastLabel = points[points.length - 1]?.label ?? firstLabel;
  const activePoint =
    activeIndex === null ? null : (positionedPoints[activeIndex] ?? null);
  const tooltipX = activePoint
    ? Math.min(Math.max(activePoint.x + 12, left), width - 184)
    : 0;
  const tooltipY = activePoint ? Math.max(top + 6, activePoint.y - 54) : 0;

  return (
    <div
      aria-label={copy.explainability.curveView}
      className="max-w-full overflow-x-auto overscroll-x-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
      data-testid="return-curve-chart-scroll"
      role="region"
      tabIndex={0}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="block h-[360px] w-full min-w-[720px] sm:h-[420px] sm:min-w-0"
        data-testid="return-curve-chart"
      >
        <line
          data-testid="return-curve-y-axis"
          x1={left}
          y1={top}
          x2={left}
          y2={top + chartHeight}
          stroke="currentColor"
          strokeOpacity="0.48"
          strokeWidth="1.2"
        />
        <line
          data-testid="return-curve-x-axis"
          x1={left}
          y1={top + chartHeight}
          x2={left + chartWidth}
          y2={top + chartHeight}
          stroke="currentColor"
          strokeOpacity="0.48"
          strokeWidth="1.2"
        />
        <line
          data-testid="return-curve-zero-axis"
          x1={left}
          y1={zeroY}
          x2={left + chartWidth}
          y2={zeroY}
          stroke="currentColor"
          strokeDasharray="4 5"
          strokeOpacity="0.34"
          strokeWidth="1.2"
        />
        {ticks.map((tick) => {
          const y = top + chartHeight - ((tick - min) / range) * chartHeight;
          return (
            <g key={tick}>
              <line
                x1={left}
                y1={y}
                x2={left + chartWidth}
                y2={y}
                stroke="currentColor"
                strokeOpacity="0.16"
              />
              <text
                x={left - 10}
                y={y + 5}
                textAnchor="end"
                className="app-type-compact fill-current font-semibold opacity-85"
              >
                {formatCurrency(tick)}
              </text>
            </g>
          );
        })}
        <text
          x={left}
          y={height - 16}
          textAnchor="start"
          className="app-type-compact fill-current font-semibold opacity-85"
        >
          {firstLabel}
        </text>
        <text
          x={left + chartWidth}
          y={height - 16}
          textAnchor="end"
          className="app-type-compact fill-current font-semibold opacity-85"
        >
          {lastLabel}
        </text>
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="4"
          points={line}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {positionedPoints.map((point, index) => (
          <circle
            key={point.label}
            cx={point.x}
            cy={point.y}
            r={activeIndex === index ? 6 : 4}
            tabIndex={0}
            role="img"
            aria-label={`${point.label} · ${formatCurrency(point.value)}`}
            data-testid={`return-curve-point-${index}`}
            fill="var(--app-text)"
            stroke="var(--app-mantle)"
            strokeWidth="2.4"
            opacity={activeIndex === null || activeIndex === index ? 1 : 0.56}
            onClick={() => setActiveIndex(index)}
            onFocus={() => setActiveIndex(index)}
            onBlur={() => setActiveIndex(null)}
            onPointerEnter={() => setActiveIndex(index)}
            onPointerMove={() => setActiveIndex(index)}
            onPointerLeave={() => setActiveIndex(null)}
            onMouseEnter={() => setActiveIndex(index)}
            onMouseLeave={() => setActiveIndex(null)}
          />
        ))}
        {activePoint ? (
          <g data-testid="return-curve-tooltip">
            <rect
              x={tooltipX}
              y={tooltipY}
              width="162"
              height="46"
              rx="10"
              fill="var(--app-panel-strong)"
              stroke="var(--app-border)"
              opacity="0.98"
            />
            <text
              x={tooltipX + 12}
              y={tooltipY + 18}
              className="app-type-label fill-current font-semibold"
            >
              {activePoint.label}
            </text>
            <text
              x={tooltipX + 12}
              y={tooltipY + 36}
              className="app-type-compact fill-current font-bold"
            >
              {formatCurrency(activePoint.value)}
            </text>
          </g>
        ) : null}
      </svg>
    </div>
  );
}

function aggregateReturnTimeline(
  timeline: Array<{
    date: string;
    equity: number;
    delta: number;
    external_flow: number;
    market_pnl: number;
    valuation_status?: string;
    missing_price_symbols?: string[];
    market_breakdown?: ReturnCalendarBreakdownItem[];
    external_flow_breakdown?: ReturnCalendarBreakdownItem[];
  }>,
  bucket: 'day' | 'week' | 'month' | 'year',
) {
  const groups = new Map<
    string,
    {
      label: string;
      delta: number;
      externalFlow: number;
      marketPnl: number;
      startEquity: number;
      endEquity: number;
      valuationStatus: string;
      missingPriceSymbols: Set<string>;
      marketBreakdown: Map<string, ReturnCalendarBreakdownItem>;
      externalFlowBreakdown: Map<string, ReturnCalendarBreakdownItem>;
    }
  >();

  timeline.forEach((point) => {
    const label = toReturnBucket(point.date, bucket);
    const existing = groups.get(label);
    const previousEquity = point.equity - point.delta;
    const missingPriceSymbols = point.missing_price_symbols ?? [];
    const valuationStatus =
      missingPriceSymbols.length > 0
        ? 'missing'
        : normalizeValuationStatus(point.valuation_status);
    if (existing) {
      existing.delta += point.delta;
      existing.externalFlow += point.external_flow;
      existing.marketPnl += point.market_pnl;
      existing.endEquity = point.equity;
      existing.valuationStatus = combineValuationStatus(
        existing.valuationStatus,
        valuationStatus,
      );
      mergeBreakdownItems(existing.marketBreakdown, point.market_breakdown);
      mergeBreakdownItems(
        existing.externalFlowBreakdown,
        point.external_flow_breakdown,
      );
      missingPriceSymbols.forEach((symbol) =>
        existing.missingPriceSymbols.add(symbol),
      );
      return;
    }
    groups.set(label, {
      label,
      delta: point.delta,
      externalFlow: point.external_flow,
      marketPnl: point.market_pnl,
      startEquity: previousEquity,
      endEquity: point.equity,
      valuationStatus,
      missingPriceSymbols: new Set(missingPriceSymbols),
      marketBreakdown: buildBreakdownMap(point.market_breakdown),
      externalFlowBreakdown: buildBreakdownMap(point.external_flow_breakdown),
    });
  });

  return Array.from(groups.values()).map((row) => ({
    ...row,
    missingPriceSymbols: Array.from(row.missingPriceSymbols).sort(),
    marketBreakdown: Array.from(row.marketBreakdown.values()).filter(
      (item) => Math.abs(item.value) > 0.000001,
    ),
    externalFlowBreakdown: Array.from(
      row.externalFlowBreakdown.values(),
    ).filter((item) => Math.abs(item.value) > 0.000001),
    percentChange:
      row.startEquity === 0 ? 0 : row.marketPnl / Math.abs(row.startEquity),
  }));
}

function buildBreakdownMap(items: ReturnCalendarBreakdownItem[] | undefined) {
  const map = new Map<string, ReturnCalendarBreakdownItem>();
  mergeBreakdownItems(map, items);
  return map;
}

function mergeBreakdownItems(
  target: Map<string, ReturnCalendarBreakdownItem>,
  items: ReturnCalendarBreakdownItem[] | undefined,
) {
  (items ?? []).forEach((item) => {
    const existing = target.get(item.key);
    if (existing) {
      target.set(item.key, {
        ...existing,
        value: existing.value + item.value,
      });
      return;
    }
    target.set(item.key, { ...item });
  });
}

function normalizeValuationStatus(status: string | undefined) {
  const normalized =
    status
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '';
  if (
    ['missing', 'unavailable', 'missing_price_symbols'].includes(normalized)
  ) {
    return 'missing';
  }
  if (
    [
      'partial',
      'cache',
      'cached',
      'cache_only',
      'estimated',
      'estimate',
      'stale',
      'quote_older_than_expected_session',
      'confirmed_nav_missing',
      'confirmed_fund_nav_missing_estimate_only',
    ].includes(normalized)
  ) {
    return 'partial';
  }
  return 'complete';
}

function combineValuationStatus(left: string, right: string) {
  if (left === 'missing' || right === 'missing') {
    return 'missing';
  }
  if (left === 'partial' || right === 'partial') {
    return 'partial';
  }
  return 'complete';
}

function toReturnBucket(
  dateText: string,
  bucket: 'day' | 'week' | 'month' | 'year',
) {
  if (bucket === 'day') {
    return dateText;
  }
  const date = new Date(`${dateText}T00:00:00`);
  if (bucket === 'month') {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
  }
  if (bucket === 'year') {
    return `${date.getFullYear()}`;
  }
  return toReturnWeekBucket(date);
}

function toReturnWeekBucket(date: Date) {
  const year = date.getFullYear();
  const slot = buildReturnWeekSlots(String(year)).find(
    (item) => date >= item.startDate && date <= item.endDate,
  );
  return slot?.label ?? `${year}-W01`;
}

function buildReturnWeekSlots(yearText: string) {
  const year = Number(yearText);
  if (!Number.isFinite(year)) {
    return [];
  }

  const slots: Array<{
    label: string;
    weekNumber: number;
    startDate: Date;
    endDate: Date;
    rangeLabel: string;
  }> = [];
  const yearEnd = new Date(year, 11, 31);
  const cursor = new Date(year, 0, 1);
  let weekNumber = 1;

  while (cursor <= yearEnd) {
    const startDate = new Date(cursor);
    const endDate = new Date(cursor);
    endDate.setDate(endDate.getDate() + (6 - startDate.getDay()));
    if (endDate > yearEnd) {
      endDate.setTime(yearEnd.getTime());
    }

    slots.push({
      label: `${year}-W${String(weekNumber).padStart(2, '0')}`,
      weekNumber,
      startDate,
      endDate,
      rangeLabel: `${formatReturnMonthDay(startDate)}-${formatReturnMonthDay(
        endDate,
      )}`,
    });

    cursor.setTime(endDate.getTime());
    cursor.setDate(cursor.getDate() + 1);
    weekNumber += 1;
  }

  return slots;
}

function formatReturnWeekHeading(weekNumber: number, copy: AppCopy) {
  if (copy.explainability.week === '周') {
    return `第${weekNumber}周`;
  }
  return `${copy.explainability.week} ${weekNumber}`;
}

function formatReturnCalendarDetailTitle(
  row: ReturnCalendarRow,
  period: ReturnCalendarPeriod,
  copy: AppCopy,
) {
  if (period !== 'week') {
    return row.label;
  }

  const match = /^(\d{4})-W(\d{2})$/.exec(row.label);
  const slot = match
    ? buildReturnWeekSlots(match[1]).find(
        (item) => item.weekNumber === Number(match[2]),
      )
    : null;
  if (!slot) {
    return row.label;
  }

  return `${formatReturnWeekHeading(slot.weekNumber, copy)} · ${
    slot.rangeLabel
  }`;
}

function formatReturnMonthDay(date: Date) {
  return `${String(date.getMonth() + 1).padStart(2, '0')}/${String(
    date.getDate(),
  ).padStart(2, '0')}`;
}

function formatPercent(value: number) {
  return formatPercentValue(value, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 2,
  });
}

function formatCurrency(value: number) {
  return formatCurrencyValue(value);
}

function formatCompactReturnCurrency(value: number) {
  if (value === 0) {
    return '0';
  }
  const sign = value > 0 ? '+' : '-';
  const absoluteValue = Math.abs(value);
  if (absoluteValue < 10) {
    return `${sign}${absoluteValue.toFixed(1)}`;
  }
  if (absoluteValue < 1_000) {
    return `${sign}${Math.round(absoluteValue)}`;
  }

  const { divisor, suffix } =
    absoluteValue >= 1_000_000_000
      ? { divisor: 1_000_000_000, suffix: 'b' }
      : absoluteValue >= 1_000_000
        ? { divisor: 1_000_000, suffix: 'm' }
        : { divisor: 1_000, suffix: 'k' };
  const scaledValue = absoluteValue / divisor;
  const compactValue = scaledValue
    .toFixed(scaledValue < 10 ? 1 : 0)
    .replace(/\.0$/, '');
  return `${sign}${compactValue}${suffix}`;
}
function ReturnCalendarGrid({
  rows,
  period,
  activeMonth,
  activeYear,
  metric,
  copy,
  compact,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  period: ReturnCalendarPeriod;
  activeMonth: string;
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const maxMagnitude = Math.max(
    ...rows.map((row) =>
      Math.abs(metric === 'amount' ? row.marketPnl : row.percentChange),
    ),
    0.0001,
  );

  if (period === 'day') {
    return (
      <ReturnMonthGrid
        rows={rows}
        activeMonth={activeMonth}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
        marketCalendarDays={marketCalendarDays}
      />
    );
  }

  if (period === 'week') {
    return (
      <ReturnWeekGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  if (period === 'month') {
    return (
      <ReturnYearGrid
        rows={rows}
        activeYear={activeYear}
        metric={metric}
        copy={copy}
        compact={compact}
        maxMagnitude={maxMagnitude}
        selectedLabel={selectedLabel}
        onSelect={onSelect}
      />
    );
  }

  return (
    <ReturnYearsGrid
      rows={rows}
      metric={metric}
      compact={compact}
      maxMagnitude={maxMagnitude}
      selectedLabel={selectedLabel}
      onSelect={onSelect}
    />
  );
}

function ReturnMonthGrid({
  rows,
  activeMonth,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
  marketCalendarDays,
}: {
  rows: ReturnCalendarRow[];
  activeMonth: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
  marketCalendarDays: Map<string, MarketCalendarDay>;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const firstDay = new Date(`${activeMonth}-01T00:00:00`);
  const month = firstDay.getMonth();
  const year = firstDay.getFullYear();
  const leadingBlanks = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];
  const gapClass = compact ? 'gap-1.5' : 'gap-2';
  const blankClass = compact
    ? 'min-h-[4.25rem] rounded-md'
    : 'min-h-[5.75rem] rounded-lg';

  return (
    <div className="min-w-0">
      <div
        className={`app-kicker app-type-overline grid grid-cols-7 ${gapClass} text-center`}
      >
        {copy.explainability.weekdays.map((day) => (
          <div key={day} data-testid="return-calendar-weekday">
            {day}
          </div>
        ))}
      </div>
      <div
        className={`mt-2 grid grid-cols-7 ${gapClass}`}
        data-testid="return-calendar-month-grid"
      >
        {cells.map((day, index) => {
          if (day === null) {
            return (
              <div
                key={`blank-${index}`}
                className={`${blankClass} border border-dashed border-[color-mix(in_srgb,var(--app-border)_44%,transparent)]`}
              />
            );
          }
          const label = `${activeMonth}-${String(day).padStart(2, '0')}`;
          const row = rowsByLabel.get(label);
          const calendarDay =
            marketCalendarDays.get(label) ?? explainMarketCalendarDate(label);
          return (
            <ReturnCalendarCell
              key={label}
              label={label}
              heading={String(day)}
              row={row}
              calendarDay={calendarDay}
              metric={metric}
              maxMagnitude={maxMagnitude}
              selected={selectedLabel === label}
              onSelect={onSelect}
              compact={compact}
            />
          );
        })}
      </div>
    </div>
  );
}

function ReturnWeekGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  const slots = buildReturnWeekSlots(activeYear);

  return (
    <div
      className={`grid ${compact ? 'max-h-[34rem] gap-1.5' : 'max-h-[38rem] gap-2'} overflow-y-auto overscroll-contain pr-1 sm:grid-cols-2 md:grid-cols-3`}
      data-testid="return-calendar-week-grid"
    >
      {slots.map((slot) => (
        <ReturnCalendarCell
          key={slot.label}
          label={slot.label}
          heading={formatReturnWeekHeading(slot.weekNumber, copy)}
          sublabel={slot.rangeLabel}
          row={rowsByLabel.get(slot.label)}
          metric={metric}
          maxMagnitude={maxMagnitude}
          selected={selectedLabel === slot.label}
          onSelect={onSelect}
          compact={compact}
        />
      ))}
    </div>
  );
}

function ReturnYearGrid({
  rows,
  activeYear,
  metric,
  copy,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  activeYear: string;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  const rowsByLabel = new Map(rows.map((row) => [row.label, row]));
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-3 xl:grid-cols-4`}
      data-testid="return-calendar-year-grid"
    >
      {Array.from({ length: 12 }, (_, index) => {
        const label = `${activeYear}-${String(index + 1).padStart(2, '0')}`;
        return (
          <ReturnCalendarCell
            key={label}
            label={label}
            heading={label.slice(5)}
            row={rowsByLabel.get(label)}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === label}
            onSelect={onSelect}
            sublabel={copy.explainability.month}
            compact={compact}
          />
        );
      })}
    </div>
  );
}

function ReturnYearsGrid({
  rows,
  metric,
  compact,
  maxMagnitude,
  selectedLabel,
  onSelect,
}: {
  rows: ReturnCalendarRow[];
  metric: 'amount' | 'percent';
  compact: boolean;
  maxMagnitude: number;
  selectedLabel: string | null;
  onSelect: (label: string) => void;
}) {
  return (
    <div
      className={`grid ${compact ? 'gap-1.5' : 'gap-2'} sm:grid-cols-2 xl:grid-cols-3`}
      data-testid="return-calendar-years-grid"
    >
      {rows
        .slice()
        .reverse()
        .map((row) => (
          <ReturnCalendarCell
            key={row.label}
            label={row.label}
            heading={row.label}
            row={row}
            metric={metric}
            maxMagnitude={maxMagnitude}
            selected={selectedLabel === row.label}
            onSelect={onSelect}
            compact={compact}
          />
        ))}
    </div>
  );
}

function formatReturnCalendarCellHeading(heading: string, sublabel?: string) {
  if (!sublabel) {
    return { headingText: heading, sublabelText: null };
  }
  if (/^\d{2}$/.test(heading)) {
    return {
      headingText:
        sublabel === '月' ? `${heading}${sublabel}` : `${heading} ${sublabel}`,
      sublabelText: null,
    };
  }
  return { headingText: heading, sublabelText: sublabel };
}

function ReturnCalendarCell({
  label,
  heading,
  row,
  calendarDay,
  metric,
  maxMagnitude,
  selected,
  onSelect,
  sublabel,
  compact,
}: {
  label: string;
  heading: string;
  row: ReturnCalendarRow | undefined;
  calendarDay?: MarketCalendarDay;
  metric: 'amount' | 'percent';
  maxMagnitude: number;
  selected: boolean;
  onSelect: (label: string) => void;
  sublabel?: string;
  compact: boolean;
}) {
  const copy = useCopy();
  const hasMissingValuation =
    row !== undefined && row.valuationStatus === 'missing';
  const hasUnconfirmedValuation =
    row !== undefined && row.valuationStatus === 'partial';
  const value = row
    ? metric === 'amount'
      ? row.marketPnl
      : row.percentChange
    : 0;
  const displayValue = row
    ? hasMissingValuation
      ? copy.explainability.missingValuationShort
      : metric === 'amount'
        ? formatCurrency(row.marketPnl)
        : formatPercent(row.percentChange)
    : '--';
  const nonTradingLabel =
    !row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const rowNonTradingLabel =
    row && calendarDay && !calendarDay.isTradingDay
      ? formatMarketCalendarClosedLabel(calendarDay, copy)
      : null;
  const cellDisplayValue =
    rowNonTradingLabel ??
    (compact && row && !hasMissingValuation && metric === 'amount'
      ? formatCompactReturnCurrency(row.marketPnl)
      : (nonTradingLabel ?? displayValue));
  const cellAccessibleValue =
    rowNonTradingLabel ?? nonTradingLabel ?? displayValue;
  const tone = row
    ? hasMissingValuation
      ? 'border-dashed border-[color-mix(in_srgb,var(--app-border)_72%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_64%,transparent)] text-[var(--app-muted)]'
      : getHeatmapTone(value, maxMagnitude)
    : 'border-[color-mix(in_srgb,var(--app-border)_54%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_42%,transparent)] text-[var(--app-muted)]';
  const cellClass = compact
    ? 'flex min-h-[4.25rem] min-w-0 flex-col overflow-hidden rounded-md px-1.5 py-2'
    : 'flex min-h-[5.75rem] min-w-0 flex-col overflow-hidden rounded-lg px-3 py-3';
  const valueClass = compact
    ? 'app-type-micro mt-auto self-end whitespace-nowrap text-right font-semibold'
    : 'mt-auto max-w-full self-end break-words text-right text-base font-semibold leading-tight';
  const metaClass = compact
    ? 'app-type-micro mt-1 self-end text-right opacity-80'
    : 'app-type-micro mt-2 self-end text-right opacity-80';
  const { headingText, sublabelText } = formatReturnCalendarCellHeading(
    heading,
    sublabel,
  );

  if (!row) {
    return (
      <div className={`${cellClass} border ${tone}`}>
        <div
          className="text-xs font-semibold"
          data-testid="return-calendar-cell-heading"
        >
          {headingText}
        </div>
        {sublabelText ? (
          <div className="app-muted app-type-micro mt-1">{sublabelText}</div>
        ) : null}
        <div className={valueClass} data-testid="return-calendar-cell-value">
          {cellDisplayValue}
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${label} · ${cellAccessibleValue}`}
      data-motion="stable-fact"
      onClick={() => onSelect(label)}
      className={`${cellClass} border text-left transition-colors focus:outline-none focus:ring-2 focus:ring-[color-mix(in_srgb,var(--app-accent)_58%,transparent)] ${
        selected ? 'ring-2 ring-[var(--app-accent)]' : ''
      } ${tone}`}
    >
      <div
        className="text-xs font-semibold"
        data-testid="return-calendar-cell-heading"
      >
        {headingText}
      </div>
      {sublabelText ? (
        <div className="app-type-micro mt-1 opacity-70">{sublabelText}</div>
      ) : null}
      <div className={valueClass} data-testid="return-calendar-cell-value">
        {cellDisplayValue}
      </div>
      {hasMissingValuation && row.missingPriceSymbols.length > 0 ? (
        <div className={metaClass}>
          {row.missingPriceSymbols.slice(0, 2).join(', ')}
        </div>
      ) : null}
      {hasUnconfirmedValuation ? (
        <div className={metaClass}>
          {copy.explainability.unconfirmedValuationShort}
        </div>
      ) : null}
    </button>
  );
}

function ReturnCalendarDetail({
  row,
  period,
  metric,
  copy,
  compact,
}: {
  row: ReturnCalendarRow | null;
  period: ReturnCalendarPeriod;
  metric: 'amount' | 'percent';
  copy: AppCopy;
  compact: boolean;
}) {
  const detailClass = compact
    ? 'rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3'
    : 'rounded-lg border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-4';

  if (row === null) {
    return (
      <div
        className={`${compact ? 'rounded-md p-3' : 'rounded-lg p-4'} border border-dashed border-[var(--app-border)] text-sm text-[var(--app-muted)]`}
      >
        {copy.explainability.timelineEmpty}
      </div>
    );
  }

  const hasMissingValuation = row.valuationStatus === 'missing';
  const hasUnconfirmedValuation = row.valuationStatus === 'partial';
  const returnValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : metric === 'amount'
      ? formatCurrency(row.delta)
      : formatPercent(row.percentChange);
  const marketValue = hasMissingValuation
    ? copy.explainability.missingValuationShort
    : formatCurrency(row.marketPnl);
  const detailTitle = formatReturnCalendarDetailTitle(row, period, copy);
  const netChangeLabel =
    period === 'day'
      ? copy.explainability.netChangeDaily
      : period === 'week'
        ? copy.explainability.netChangeWeekly
        : period === 'month'
          ? copy.explainability.netChangeMonthly
          : copy.explainability.netChangeAnnual;

  return (
    <div className={detailClass}>
      <div className="app-kicker app-type-overline">
        {copy.explainability.selectedPeriod}
      </div>
      <div
        className={`${compact ? 'mt-1 text-base' : 'mt-2 text-lg'} font-semibold`}
      >
        {detailTitle}
      </div>
      <div
        className={`${compact ? 'mt-3 space-y-2' : 'mt-4 space-y-3'} text-sm`}
      >
        <CalendarDetailMetric label={netChangeLabel} value={returnValue} />
        <CalendarDetailMetric
          label={copy.explainability.marketPnl}
          value={marketValue}
        />
        {row.marketBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.marketBreakdown}
            labelForKey={(item) =>
              copy.explainability.marketBreakdownLabels[
                item.key as keyof typeof copy.explainability.marketBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        <CalendarDetailMetric
          label={copy.explainability.externalFlow}
          value={formatCurrency(row.externalFlow)}
        />
        {row.externalFlowBreakdown.length > 0 ? (
          <CalendarDetailBreakdown
            items={row.externalFlowBreakdown}
            labelForKey={(item) =>
              copy.explainability.externalFlowBreakdownLabels[
                item.key as keyof typeof copy.explainability.externalFlowBreakdownLabels
              ] ?? item.label
            }
          />
        ) : null}
        {hasMissingValuation || hasUnconfirmedValuation ? (
          <CalendarDetailMetric
            label={copy.explainability.valuationCoverage}
            value={
              hasMissingValuation && row.missingPriceSymbols.length > 0
                ? `${copy.explainability.missingHistoricalPrices}: ${row.missingPriceSymbols.join(', ')}`
                : copy.explainability.partialValuation
            }
          />
        ) : null}
      </div>
    </div>
  );
}

function buildMarketCalendarDayMap(
  marketCalendar?: ReturnCalendarMarketCalendar | null,
) {
  const days =
    marketCalendar?.status === 'missing' ? [] : (marketCalendar?.days ?? []);
  return new Map(
    days.map((day) => [
      day.date,
      {
        schemaVersion: MARKET_CALENDAR_SCHEMA_VERSION,
        date: day.date,
        dayType: day.day_type,
        reasonCode: day.reason_code,
        reason: day.reason,
        isTradingDay: day.is_trading_day,
      } satisfies MarketCalendarDay,
    ]),
  );
}

function formatMarketCalendarClosedLabel(
  day: MarketCalendarDay,
  copy: AppCopy,
) {
  if (day.dayType === 'holiday') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketHolidayShort
      : day.reason;
  }
  if (day.dayType === 'weekend') {
    return isGenericMarketCalendarReason(day.reason)
      ? copy.explainability.marketWeekendShort
      : day.reason;
  }
  return isGenericMarketCalendarReason(day.reason)
    ? copy.explainability.marketClosedShort
    : day.reason;
}

function isGenericMarketCalendarReason(reason: string | null | undefined) {
  const normalized = (reason ?? '').trim().toLowerCase();
  return (
    normalized === '' ||
    normalized === 'weekend' ||
    normalized === 'exchange closed'
  );
}

function CalendarDetailMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[var(--app-border)] pt-3 first:border-t-0 first:pt-0">
      <span className="app-muted">{label}</span>
      <span className="text-right font-semibold">{value}</span>
    </div>
  );
}

function CalendarDetailBreakdown({
  items,
  labelForKey,
}: {
  items: ReturnCalendarBreakdownItem[];
  labelForKey: (item: ReturnCalendarBreakdownItem) => string;
}) {
  return (
    <div className="space-y-2 border-t border-[var(--app-border)] pt-3">
      {items.map((item) => (
        <div
          key={item.key}
          className="flex items-center justify-between gap-3 text-xs"
        >
          <span className="app-muted">{labelForKey(item)}</span>
          <span className="text-right font-semibold">
            {formatCurrency(item.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function getHeatmapTone(value: number, maxMagnitude: number) {
  const intensity = Math.min(Math.abs(value) / maxMagnitude, 1);

  if (value > 0) {
    if (intensity > 0.66) {
      return 'app-heat-positive-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-positive-medium';
    }
    return 'app-heat-positive-soft';
  }

  if (value < 0) {
    if (intensity > 0.66) {
      return 'app-heat-negative-strong';
    }
    if (intensity > 0.33) {
      return 'app-heat-negative-medium';
    }
    return 'app-heat-negative-soft';
  }

  return 'border-[var(--app-border)] bg-[var(--app-panel-strong)] text-[var(--app-foreground)]';
}
