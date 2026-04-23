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
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_58%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_82%,transparent)] px-4 py-3 text-xs shadow-[0_18px_60px_rgba(17,17,27,0.28)] backdrop-blur-xl">
      <div className="mb-2 font-semibold text-[var(--app-text)]">
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
              <span className="font-medium text-[var(--app-text)]">
                {formatCurrency(item.value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
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
      <section className="w-full px-0 py-2">
        <div className="mb-5">
          <div className="text-xl font-bold tracking-[-0.02em] text-[var(--app-text)]">
            {labels.title}
          </div>
        </div>
        <div className="rounded-2xl bg-[color-mix(in_srgb,var(--app-panel)_42%,transparent)] p-4 sm:p-5">
          <div className="text-base font-semibold">{labels.emptyTitle}</div>
          <div className="app-muted mt-2 text-sm leading-6">{labels.emptyDetail}</div>
          <div className="app-kicker mt-3 text-[11px] uppercase tracking-[0.16em]">
            {labels.emptyHint}
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
    <section className="w-full px-0 py-2">
      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="text-xl font-bold tracking-[-0.02em] text-[var(--app-text)] sm:text-2xl">
            {labels.title}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
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
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-300 ${
                    active
                      ? "border-[color-mix(in_srgb,var(--app-border)_62%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_52%,transparent)] text-[var(--app-text)] shadow-[inset_0_1px_0_color-mix(in_srgb,white_6%,transparent)]"
                      : "border-transparent bg-transparent text-[var(--app-muted)] opacity-55 hover:opacity-100"
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

        <div className="relative inline-flex w-max rounded-full border border-[color-mix(in_srgb,var(--app-border)_54%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_48%,transparent)] p-1 backdrop-blur-md">
          <div
            className="absolute bottom-1 top-1 w-[calc(100%/6)] rounded-full bg-[color-mix(in_srgb,var(--app-accent)_22%,transparent)] transition-transform duration-300 ease-out"
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
              className={`relative z-10 h-8 min-w-11 rounded-full px-3 text-xs font-semibold transition-colors duration-200 ${
                range === value ? "text-[var(--app-accent)]" : "text-[var(--app-muted)]"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-[320px] w-full sm:h-[380px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartPoints} margin={{ top: 18, right: 8, left: 0, bottom: 8 }}>
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
