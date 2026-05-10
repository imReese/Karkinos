import { startTransition, useState, type CSSProperties } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
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
  realtimeUnrealizedPnlLabel: string;
  payload?: TooltipPayload[];
};

const SERIES_META: Array<{ key: SeriesKey; color: string; gradient: string }> =
  [
    { key: 'total', color: '#cba6f7', gradient: 'totalGradient' },
    { key: 'stocks', color: '#89b4fa', gradient: 'stocksGradient' },
    { key: 'funds', color: '#a6e3a1', gradient: 'fundsGradient' },
    { key: 'others', color: '#f9e2af', gradient: 'othersGradient' },
    { key: 'cash', color: '#94e2d5', gradient: 'cashGradient' },
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
}: {
  x?: number;
  y?: number;
  payload?: { value?: string | number | Date };
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
      {formatChartTimestamp(payload?.value ?? '')}
    </text>
  );
}

function toChartPoints(points: EquitySeriesPoint[]): ChartPoint[] {
  return points.map((point) => ({
    ...point,
    timestampMs: new Date(point.timestamp).getTime(),
  }));
}

function filterByRange(points: ChartPoint[], range: EquityCurveRange) {
  if (range === 'all' || points.length < 2) {
    return points;
  }

  const latest = new Date(
    points[points.length - 1]?.timestamp ?? Date.now(),
  ).getTime();
  const filtered = points.filter((point) => {
    const ageInDays =
      (latest - new Date(point.timestamp).getTime()) / 86_400_000;
    return ageInDays <= RANGE_DAYS[range];
  });
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

function CustomTooltip({
  active,
  payload,
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
    <div className="z-[90] rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_50%,transparent)] px-3 py-2.5 text-xs shadow-[0_14px_44px_rgba(17,17,27,0.22)] backdrop-blur-md tabular-nums">
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
          <div className="mt-2 flex min-w-36 items-center justify-between gap-5 border-t border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] pt-2">
            <span className="text-[var(--app-muted)]">
              {realtimeUnrealizedPnlLabel}
            </span>
            <span className="font-medium tabular-nums text-[var(--app-text)]">
              {formatWholeCurrency(point.unrealized_pnl)}
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
          <div className="h-5 w-44 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_86%,transparent)]" />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Array.from({ length: 5 }).map((_, index) => (
              <div
                key={index}
                className="h-6 w-16 rounded-full bg-[color-mix(in_srgb,var(--app-surface-0)_72%,transparent)]"
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
        <div className="absolute bottom-12 left-8 right-8 h-36 rounded-[55%_45%_50%_50%/60%_46%_54%_40%] border-t-2 border-[color-mix(in_srgb,var(--app-accent)_38%,transparent)] bg-gradient-to-t from-transparent to-[color-mix(in_srgb,var(--app-accent)_14%,transparent)]" />
      </div>
    </section>
  );
}

export function EquityCurveCard({
  points,
  onRangeChange,
}: {
  points: EquitySeriesPoint[];
  onRangeChange?: (range: EquityCurveRange) => void;
}) {
  const copy = useCopy();
  const labels = copy.overview.equityCurve;
  const [range, setRange] = useState<EquityCurveRange>('1m');
  const [visibleSeries, setVisibleSeries] = useState<
    Record<SeriesKey, boolean>
  >({
    total: true,
    stocks: true,
    funds: true,
    others: true,
    cash: true,
  });

  const chartPoints = filterByRange(toChartPoints(points), range);
  const hasUsableData = chartPoints.length >= 2;
  const xAxisTicks = resolveXAxisTicks(chartPoints, range);
  const xAxisDomain = resolveXAxisDomain(chartPoints, range);

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
      <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="app-card-title text-[var(--app-text)]">
            {labels.title}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
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
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-all duration-200 ${
                    active
                      ? 'bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] text-[var(--app-text)]'
                      : 'bg-transparent text-[var(--app-muted)] opacity-55 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_10%,transparent)] hover:opacity-100'
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

        <div className="relative inline-flex w-max rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_30%,transparent)] p-0.5 backdrop-blur-md">
          <div
            className="absolute bottom-0.5 top-0.5 w-[calc(100%/6)] rounded-full bg-[color-mix(in_srgb,var(--app-accent)_16%,transparent)] transition-transform duration-300 ease-out"
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
                  setRange(value);
                  onRangeChange?.(value);
                });
              }}
              className={`relative z-10 h-7 min-w-10 rounded-full px-2.5 text-[11px] font-semibold transition-colors duration-200 ${
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
        <div className="h-[320px] w-full overflow-hidden rounded-[20px] border-y border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] sm:h-[380px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartPoints}
              margin={{ left: 10, right: 30, top: 10, bottom: 0 }}
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
                      stopOpacity={series.key === 'total' ? 0.3 : 0.18}
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
                strokeOpacity={0.05}
                vertical={false}
              />
              <XAxis
                dataKey="timestampMs"
                type="number"
                scale="time"
                domain={xAxisDomain}
                ticks={xAxisTicks}
                tick={<TimeAxisTick />}
                axisLine={false}
                tickLine={false}
                tickCount={6}
                interval={0}
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
                domain={['auto', 'auto']}
                tick={{ fontSize: 12 }}
                stroke="var(--app-muted)"
              />
              <Tooltip
                content={
                  <CustomTooltip
                    realtimeUnrealizedPnlLabel={labels.realtimeUnrealizedPnl}
                  />
                }
                cursor={{
                  stroke: '#cba6f7',
                  strokeOpacity: 0.32,
                  strokeWidth: 1,
                }}
                wrapperStyle={{ zIndex: 90, outline: 'none' }}
              />
              <Legend
                verticalAlign="top"
                align="right"
                iconType="circle"
                wrapperStyle={{
                  color: 'var(--app-muted)',
                  fontSize: 11,
                  paddingBottom: 8,
                }}
              />
              {SERIES_META.map((series) => {
                const active = visibleSeries[series.key];
                return (
                  <Area
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={seriesLabels[series.key]}
                    stroke={series.color}
                    strokeWidth={series.key === 'total' ? 3 : 2}
                    strokeOpacity={active ? 1 : 0}
                    fill={`url(#${series.gradient})`}
                    fillOpacity={active ? 1 : 0}
                    animationDuration={520}
                    animationEasing="ease-out"
                    dot={false}
                    activeDot={{
                      r: series.key === 'total' ? 5 : 4,
                      stroke: '#1e1e2e',
                      strokeWidth: 2,
                      fill: series.color,
                    }}
                    isAnimationActive
                  />
                );
              })}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="flex h-[320px] items-center justify-center border-y border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-6 text-center sm:h-[380px]">
          <div>
            <div className="text-sm font-medium text-[var(--app-subtext-0)]">
              {labels.emptyPeriod}
            </div>
            <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
              {labels.emptyHint}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
