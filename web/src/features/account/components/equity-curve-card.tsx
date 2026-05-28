import { startTransition, useState, type CSSProperties } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useCopy } from '../../../app/copy';
import {
  formatCompactNumber,
  formatCurrency,
  formatDateTime,
} from '../../../shared/format';
import type { EquityCurveRange, EquitySeriesPoint } from '../api';

type SeriesKey = 'total' | 'stocks' | 'funds' | 'others' | 'cash';

type ChartPoint = EquitySeriesPoint & {
  timestampMs: number;
};

type TooltipPayload = {
  color?: string;
  dataKey?: string | number;
  name?: string | number;
  payload?: ChartPoint;
  value?: number | string;
};

type CustomTooltipProps = {
  active?: boolean;
  quoteStatusLabel: string;
  realtimeUnrealizedPnlLabel: string;
  payload?: TooltipPayload[];
};

const SERIES_META: Array<{ key: SeriesKey; color: string; gradient: string }> =
  [
    { key: 'total', color: 'var(--app-accent)', gradient: 'totalGradient' },
    {
      key: 'stocks',
      color: 'var(--app-accent-secondary)',
      gradient: 'stocksGradient',
    },
    { key: 'funds', color: 'var(--app-success)', gradient: 'fundsGradient' },
    { key: 'others', color: 'var(--app-warning)', gradient: 'othersGradient' },
    { key: 'cash', color: 'var(--app-teal)', gradient: 'cashGradient' },
  ];

const RANGE_DAYS: Record<EquityCurveRange, number> = {
  '1d': 1,
  '5d': 5,
  '1m': 31,
  '6m': 183,
  '1y': 366,
  all: Number.POSITIVE_INFINITY,
};

function formatAxisValue(value: number) {
  return formatCompactNumber(value);
}

function formatChartTimestamp(value: string | number | Date) {
  return formatDateTime(value);
}

function formatAxisTimestamp(
  value: string | number | Date,
  range: EquityCurveRange,
) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(
    typeof document !== 'undefined' &&
      document.documentElement.lang.startsWith('zh')
      ? 'zh-CN'
      : 'en-US',
    range === '1d'
      ? {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
          timeZone: 'Asia/Shanghai',
        }
      : {
          month: '2-digit',
          day: '2-digit',
          timeZone: 'Asia/Shanghai',
        },
  ).format(date);
}

function formatWholeCurrency(value: number) {
  return formatCurrency(value, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function TimeAxisTick({
  x = 0,
  y = 0,
  payload,
  range,
}: {
  x?: number;
  y?: number;
  payload?: { value?: string | number | Date };
  range: EquityCurveRange;
}) {
  return (
    <text
      x={x}
      y={y}
      dy={14}
      textAnchor="middle"
      fill="var(--app-subtext-0)"
      fontSize={10}
    >
      {formatAxisTimestamp(payload?.value ?? '', range)}
    </text>
  );
}

function toChartPoints(points: EquitySeriesPoint[]): ChartPoint[] {
  return points
    .map((point) => ({
      ...point,
      timestampMs: new Date(point.timestamp).getTime(),
    }))
    .filter((point) => Number.isFinite(point.timestampMs))
    .sort((a, b) => a.timestampMs - b.timestampMs);
}

function clonePointAtTimestamp(point: ChartPoint, timestampMs: number) {
  return {
    ...point,
    timestamp: new Date(timestampMs).toISOString(),
    timestampMs,
  };
}

function filterByRange(points: ChartPoint[], range: EquityCurveRange) {
  if (range === 'all' || points.length < 2) {
    return points;
  }

  const latest = points[points.length - 1]?.timestampMs ?? Date.now();
  const rangeStart = latest - RANGE_DAYS[range] * 86_400_000;
  const filtered = points.filter((point) => {
    return point.timestampMs >= rangeStart && point.timestampMs <= latest;
  });

  if (range === '1d') {
    return filtered;
  }

  const anchor = [...points]
    .reverse()
    .find((point) => point.timestampMs < rangeStart);
  if (anchor && filtered.length > 0) {
    return [clonePointAtTimestamp(anchor, rangeStart), ...filtered];
  }
  if (anchor && filtered.length === 0) {
    const latestPoint = points[points.length - 1];
    return [
      clonePointAtTimestamp(anchor, rangeStart),
      clonePointAtTimestamp(latestPoint, latest),
    ];
  }
  return filtered;
}

function buildTimeTicks(points: ChartPoint[], tickCount: number) {
  if (points.length === 0 || tickCount <= 1) {
    return [];
  }

  const start = points[0]?.timestampMs ?? 0;
  const end = points[points.length - 1]?.timestampMs ?? start;

  if (start === end) {
    return [start];
  }

  const step = (end - start) / (tickCount - 1);
  return Array.from({ length: tickCount }, (_, index) =>
    Math.round(start + step * index),
  );
}

function buildIntradaySessionTicks(points: ChartPoint[]) {
  const anchor = points[0]?.timestamp;
  if (!anchor) {
    return [];
  }
  const datePart = anchor.slice(0, 10);
  const buildTick = (hours: number, minutes: number) =>
    new Date(
      `${datePart}T${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:00+08:00`,
    ).getTime();
  return [
    buildTick(9, 30),
    buildTick(10, 30),
    buildTick(11, 30),
    buildTick(13, 0),
    buildTick(14, 0),
    buildTick(15, 0),
  ];
}

function resolveXAxisTicks(points: ChartPoint[], range: EquityCurveRange) {
  if (range === '1d') {
    return buildIntradaySessionTicks(points);
  }
  return buildTimeTicks(points, 6);
}

function resolveXAxisDomain(
  points: ChartPoint[],
  range: EquityCurveRange,
): [number, number] | ['dataMin', 'dataMax'] {
  if (range !== '1d') {
    return ['dataMin', 'dataMax'];
  }
  const intradayTicks = buildIntradaySessionTicks(points);
  if (intradayTicks.length >= 2) {
    return [intradayTicks[0], intradayTicks[intradayTicks.length - 1]];
  }
  return ['dataMin', 'dataMax'];
}

function resolveYAxisDomain(
  points: ChartPoint[],
  visibleSeries: Record<SeriesKey, boolean>,
) {
  const values = points.flatMap((point) =>
    SERIES_META.flatMap((series) => {
      if (!visibleSeries[series.key]) {
        return [];
      }
      const value = point[series.key];
      return typeof value === 'number' && Number.isFinite(value) ? [value] : [];
    }),
  );
  if (values.length === 0) {
    return ['auto', 'auto'] as const;
  }

  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const spread = maxValue - minValue;
  const padding = Math.max(spread * 0.18, maxValue * 0.01, 1);
  return [
    Math.max(0, Math.floor(minValue - padding)),
    Math.ceil(maxValue + padding),
  ] as const;
}

function CustomTooltip({
  active,
  payload,
  quoteStatusLabel,
  realtimeUnrealizedPnlLabel,
}: CustomTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) {
    return null;
  }

  return (
    <div className="z-[90] rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_92%,transparent)] px-3 py-2.5 text-xs shadow-[0_18px_54px_color-mix(in_srgb,var(--app-mantle)_54%,transparent),inset_0_1px_0_color-mix(in_srgb,var(--app-text)_6%,transparent)] backdrop-blur-md tabular-nums">
      <div className="mb-2 font-medium text-[var(--app-text)]">
        {formatChartTimestamp(point.timestamp)}
      </div>
      <div className="space-y-1.5">
        {payload.map((item) => {
          if (typeof item.value !== 'number') {
            return null;
          }
          return (
            <div
              key={String(item.dataKey)}
              className="flex min-w-36 items-center justify-between gap-5"
            >
              <span className="flex items-center gap-2 text-[var(--app-muted)]">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                {item.name}
              </span>
              <span className="font-medium tabular-nums text-[var(--app-text)]">
                {formatWholeCurrency(item.value)}
              </span>
            </div>
          );
        })}
        {typeof point.unrealized_pnl === 'number' ? (
          <div className="mt-2 flex min-w-36 items-center justify-between gap-5 border-t border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] pt-2">
            <span className="text-[var(--app-muted)]">
              {realtimeUnrealizedPnlLabel}
            </span>
            <span className="font-medium tabular-nums text-[var(--app-text)]">
              {formatWholeCurrency(point.unrealized_pnl)}
            </span>
          </div>
        ) : null}
        {point.quote_status ? (
          <div className="mt-2 flex min-w-36 items-center justify-between gap-5 border-t border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] pt-2">
            <span className="text-[var(--app-muted)]">{quoteStatusLabel}</span>
            <span className="font-mono text-[var(--app-text)]">
              {point.quote_status}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function EquityCurveSkeleton() {
  return (
    <section
      data-testid="equity-curve-skeleton"
      aria-hidden="true"
      className="w-full animate-pulse bg-[color-mix(in_srgb,var(--app-surface-0)_0%,transparent)] px-0 py-1"
    >
      <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="h-5 w-44 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_48%,transparent)]" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="h-6 w-16 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_38%,transparent)]"
              />
            ))}
          </div>
        </div>
        <div className="h-8 w-60 max-w-full rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_82%,transparent)]" />
      </div>

      <div className="relative h-[320px] overflow-hidden bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] sm:h-[380px]">
        <div className="absolute inset-x-8 top-12 space-y-12">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              className="h-px bg-[color-mix(in_srgb,var(--app-surface-0)_68%,transparent)]"
            />
          ))}
        </div>
        <div className="absolute bottom-12 left-8 right-8 h-36 rounded-[55%_45%_50%_50%/60%_46%_54%_40%] border-t-2 border-[color-mix(in_srgb,var(--app-accent)_48%,transparent)] bg-gradient-to-t from-transparent to-[color-mix(in_srgb,var(--app-accent)_14%,transparent)]" />
      </div>
    </section>
  );
}

export function EquityCurveCard({
  points,
  range: controlledRange,
  onRangeChange,
}: {
  points: EquitySeriesPoint[];
  range?: EquityCurveRange;
  onRangeChange?: (range: EquityCurveRange) => void;
}) {
  const copy = useCopy();
  const labels = copy.overview.equityCurve;
  const [uncontrolledRange, setUncontrolledRange] =
    useState<EquityCurveRange>('1m');
  const range = controlledRange ?? uncontrolledRange;
  const [visibleSeries, setVisibleSeries] = useState<
    Record<SeriesKey, boolean>
  >({
    total: true,
    stocks: false,
    funds: false,
    others: false,
    cash: false,
  });

  const chartPoints = filterByRange(toChartPoints(points), range);
  const hasUsableData = chartPoints.length >= 2;
  const xAxisTicks = resolveXAxisTicks(chartPoints, range);
  const xAxisDomain = resolveXAxisDomain(chartPoints, range);
  const yAxisDomain = resolveYAxisDomain(chartPoints, visibleSeries);
  const latestPoint = chartPoints[chartPoints.length - 1];
  const isStale = latestPoint?.quote_status === 'stale';

  const rangeOptions: Array<[EquityCurveRange, string]> = [
    ['1d', labels.oneDay],
    ['5d', labels.fiveDays],
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  const activeRangeIndex = rangeOptions.findIndex(([value]) => value === range);
  const seriesLabels: Record<SeriesKey, string> = {
    total: labels.total,
    stocks: labels.stocks,
    funds: labels.funds,
    others: labels.others,
    cash: labels.cash,
  };

  return (
    <section className="w-full px-0 py-1">
      <div className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">
            {copy.overview.dashboard.equityPanel}
          </div>
          <div className="app-card-title mt-1.5 text-xl text-[var(--app-text)]">
            {labels.title}
          </div>
          {isStale ? (
            <div className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-2.5 py-1 text-[11px] font-semibold text-[var(--app-warning)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
              <span className="truncate">{labels.cachedValuation}</span>
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {SERIES_META.map((series) => {
              const active = visibleSeries[series.key];
              return (
                <button
                  key={series.key}
                  type="button"
                  aria-pressed={active}
                  aria-label={seriesLabels[series.key]}
                  onClick={() =>
                    setVisibleSeries((current) => ({
                      ...current,
                      [series.key]: !current[series.key],
                    }))
                  }
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-[background-color,border-color,color,opacity,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.98] ${
                    active
                      ? 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-text)]'
                      : 'border-transparent bg-transparent text-[var(--app-muted)] opacity-55 hover:border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] hover:opacity-100'
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: series.color }}
                  />
                  {seriesLabels[series.key]}
                </button>
              );
            })}
          </div>
        </div>

        <div className="relative inline-flex w-max rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_30%,transparent)] p-1 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)]">
          <div
            className="absolute bottom-1 top-1 w-[calc(100%/6)] rounded-full bg-[color-mix(in_srgb,var(--app-accent)_18%,transparent)] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_7%,transparent)] transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
            style={
              {
                transform: `translateX(${Math.max(activeRangeIndex, 0) * 100}%)`,
              } as CSSProperties
            }
            aria-hidden="true"
          />
          {rangeOptions.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-label={`${labels.range}: ${label}`}
              aria-pressed={range === value}
              onClick={() => {
                startTransition(() => {
                  if (controlledRange === undefined) {
                    setUncontrolledRange(value);
                  }
                  onRangeChange?.(value);
                });
              }}
              className={`relative z-10 h-7 min-w-10 rounded-full px-2.5 font-mono text-[11px] font-semibold transition-colors duration-300 ${
                range === value
                  ? 'text-[var(--app-accent)]'
                  : 'text-[var(--app-muted)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {hasUsableData ? (
        <div className="h-[340px] w-full overflow-hidden rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[linear-gradient(color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),linear-gradient(90deg,color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),color-mix(in_srgb,var(--app-panel-strong)_26%,transparent)] bg-[length:44px_44px,44px_44px,auto] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] sm:h-[410px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartPoints}
              margin={{ left: 10, right: 30, top: 18, bottom: 34 }}
            >
              <defs>
                {SERIES_META.map((series) => (
                  <linearGradient
                    key={series.gradient}
                    id={series.gradient}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop
                      offset="0%"
                      stopColor={series.color}
                      stopOpacity={series.key === 'total' ? 0.18 : 0}
                    />
                    <stop
                      offset="100%"
                      stopColor={series.color}
                      stopOpacity={0}
                    />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid
                stroke="var(--app-border)"
                strokeOpacity={0.12}
                vertical={false}
              />
              <XAxis
                dataKey="timestampMs"
                type="number"
                scale="time"
                domain={xAxisDomain}
                ticks={xAxisTicks}
                tick={<TimeAxisTick range={range} />}
                axisLine={false}
                tickLine={false}
                tickCount={6}
                interval={0}
                height={46}
                tickMargin={14}
                minTickGap={range === '1d' ? 18 : 24}
                stroke="var(--app-subtext-0)"
              />
              <YAxis
                width={60}
                axisLine={false}
                tickLine={false}
                tickMargin={12}
                tickFormatter={formatAxisValue}
                domain={yAxisDomain}
                tick={{ fontSize: 12 }}
                stroke="var(--app-muted)"
              />
              <Tooltip
                content={
                  <CustomTooltip
                    quoteStatusLabel={labels.quoteStatus}
                    realtimeUnrealizedPnlLabel={labels.realtimeUnrealizedPnl}
                  />
                }
                cursor={{
                  stroke: 'var(--app-accent)',
                  strokeOpacity: 0.32,
                  strokeWidth: 1,
                }}
                wrapperStyle={{ zIndex: 90, outline: 'none' }}
              />
              {SERIES_META.map((series) => {
                const active = visibleSeries[series.key];
                if (!active) {
                  return null;
                }
                const isPrimarySeries = series.key === 'total';
                return (
                  <Line
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={seriesLabels[series.key]}
                    stroke={series.color}
                    strokeWidth={isPrimarySeries ? 3.5 : 2}
                    strokeOpacity={isPrimarySeries ? 1 : 0.86}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    animationDuration={520}
                    animationEasing="ease-out"
                    dot={false}
                    activeDot={{
                      r: series.key === 'total' ? 5 : 4,
                      stroke: 'var(--app-mantle)',
                      strokeWidth: 2,
                      fill: series.color,
                    }}
                    isAnimationActive
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="flex h-[340px] items-center justify-center rounded-[26px] border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-6 text-center sm:h-[410px]">
          <div>
            <div className="text-sm font-medium text-[var(--app-subtext-0)]">
              {chartPoints.length > 0
                ? labels.insufficientData
                : labels.emptyPeriod}
            </div>
            <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
              {labels.emptyHint}
            </div>
            {latestPoint ? (
              <div className="mt-4 inline-flex flex-wrap items-center justify-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] px-3 py-1.5 text-xs text-[var(--app-soft)]">
                <span>{labels.currentPoint}</span>
                <span className="font-mono tabular-nums">
                  {formatChartTimestamp(latestPoint.timestamp)}
                </span>
                {latestPoint.quote_status ? (
                  <span className="font-mono">{latestPoint.quote_status}</span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
