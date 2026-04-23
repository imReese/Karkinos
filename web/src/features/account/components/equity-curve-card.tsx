import { startTransition, useState, type CSSProperties } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useCopy } from "../../../app/copy";
import type { EquitySeriesPoint } from "../api";

type SeriesKey = "total" | "stocks" | "funds" | "others" | "cash";
type RangeKey = "1d" | "5d" | "1m" | "6m" | "1y" | "all";

type ChartPoint = EquitySeriesPoint & {
  dateLabel: string;
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
  payload?: TooltipPayload[];
};

const SERIES_META: Array<{ key: SeriesKey; color: string; gradient: string }> = [
  { key: "total", color: "#cba6f7", gradient: "totalGradient" },
  { key: "stocks", color: "#89b4fa", gradient: "stocksGradient" },
  { key: "funds", color: "#a6e3a1", gradient: "fundsGradient" },
  { key: "others", color: "#f9e2af", gradient: "othersGradient" },
  { key: "cash", color: "#94e2d5", gradient: "cashGradient" },
];

const RANGE_DAYS: Record<RangeKey, number> = {
  "1d": 1,
  "5d": 5,
  "1m": 31,
  "6m": 183,
  "1y": 366,
  all: Number.POSITIVE_INFINITY,
};

function formatCurrency(value: number) {
  return `¥${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatAxisDate(timestamp: string) {
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function toChartPoints(points: EquitySeriesPoint[]): ChartPoint[] {
  return points.map((point) => ({
    ...point,
    dateLabel: formatAxisDate(point.timestamp),
  }));
}

function filterByRange(points: ChartPoint[], range: RangeKey) {
  if (range === "all" || points.length < 2) {
    return points;
  }

  const latest = new Date(points[points.length - 1]?.timestamp ?? Date.now()).getTime();
  const filtered = points.filter((point) => {
    const ageInDays = (latest - new Date(point.timestamp).getTime()) / 86_400_000;
    return ageInDays <= RANGE_DAYS[range];
  });
  return filtered.length >= 2 ? filtered : points;
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) {
    return null;
  }

  return (
    <div className="z-[90] rounded-xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_50%,transparent)] px-3 py-2.5 text-xs shadow-[0_14px_44px_rgba(17,17,27,0.22)] backdrop-blur-md tabular-nums">
      <div className="mb-2 font-medium text-[var(--app-text)]">
        {new Date(point.timestamp).toLocaleDateString()}
      </div>
      <div className="space-y-1.5">
        {payload.map((item) => {
          if (typeof item.value !== "number") {
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
                {formatCurrency(item.value)}
              </span>
            </div>
          );
        })}
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

export function EquityCurveCard({ points }: { points: EquitySeriesPoint[] }) {
  const copy = useCopy();
  const labels = copy.overview.equityCurve;
  const [range, setRange] = useState<RangeKey>("all");
  const [visibleSeries, setVisibleSeries] = useState<Record<SeriesKey, boolean>>({
    total: true,
    stocks: true,
    funds: true,
    others: true,
    cash: true,
  });

  if (points.length === 0) {
    return (
      <section className="w-full px-0 py-1">
        <div className="mb-3">
          <div className="text-base font-semibold tracking-[-0.02em] text-[var(--app-text)]">
            {labels.title}
          </div>
        </div>
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
      </section>
    );
  }

  const chartPoints = filterByRange(toChartPoints(points), range);
  const rangeOptions: Array<[RangeKey, string]> = [
    ["1d", labels.oneDay],
    ["5d", labels.fiveDays],
    ["1m", labels.oneMonth],
    ["6m", labels.sixMonths],
    ["1y", labels.oneYear],
    ["all", labels.all],
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
          <div className="text-base font-semibold tracking-[-0.02em] text-[var(--app-text)]">
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
                      ? "bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] text-[var(--app-text)]"
                      : "bg-transparent text-[var(--app-muted)] opacity-55 hover:bg-[color-mix(in_srgb,var(--app-surface-1)_10%,transparent)] hover:opacity-100"
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
                startTransition(() => setRange(value));
              }}
              className={`relative z-10 h-7 min-w-10 rounded-full px-2.5 text-[11px] font-semibold transition-colors duration-200 ${
                range === value ? "text-[var(--app-accent)]" : "text-[var(--app-muted)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="-mx-4 h-[320px] w-[calc(100%+2rem)] border-y border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] sm:h-[380px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartPoints} margin={{ top: 18, right: 4, left: -14, bottom: 8 }}>
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
                    stopOpacity={series.key === "total" ? 0.3 : 0.18}
                  />
                  <stop offset="100%" stopColor={series.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke="var(--app-border)" strokeOpacity={0.05} vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatAxisDate}
              axisLine={false}
              tickLine={false}
              tickMargin={14}
              minTickGap={32}
              className="text-xs"
              stroke="var(--app-muted)"
            />
            <YAxis
              width={72}
              axisLine={false}
              tickLine={false}
              tickMargin={12}
              tickFormatter={formatCurrency}
              className="text-xs"
              stroke="var(--app-muted)"
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: "#cba6f7", strokeOpacity: 0.32, strokeWidth: 1 }}
              wrapperStyle={{ zIndex: 90, outline: "none" }}
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
                  strokeWidth={series.key === "total" ? 3 : 2}
                  strokeOpacity={active ? 1 : 0}
                  fill={`url(#${series.gradient})`}
                  fillOpacity={active ? 1 : 0}
                  animationDuration={520}
                  animationEasing="ease-out"
                  dot={false}
                  activeDot={{
                    r: series.key === "total" ? 5 : 4,
                    stroke: "#1e1e2e",
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
    </section>
  );
}
