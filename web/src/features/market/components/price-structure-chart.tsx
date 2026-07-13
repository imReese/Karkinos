import { useMemo, useState } from 'react';

import { formatCurrency, formatPercent } from '../../../shared/format';

export type PriceStructureBar = {
  timestamp?: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
};

type KlineRangeKey =
  'oneMonth' | 'threeMonths' | 'sixMonths' | 'oneYear' | 'all';

export type KlineRangeLabels = Record<KlineRangeKey, string>;

export type KlineAxisLabels = {
  price: string;
  date: string;
};

const DEFAULT_RANGE_LABELS: KlineRangeLabels = {
  oneMonth: '1M',
  threeMonths: '3M',
  sixMonths: '6M',
  oneYear: '1Y',
  all: 'All',
};

const KLINE_RANGES: Array<{
  key: KlineRangeKey;
  days: number | null;
}> = [
  { key: 'oneMonth', days: 31 },
  { key: 'threeMonths', days: 93 },
  { key: 'sixMonths', days: 186 },
  { key: 'oneYear', days: 366 },
  { key: 'all', days: null },
];

function toFiniteNumber(value: number | null | undefined) {
  return Number.isFinite(value ?? NaN) ? Number(value) : null;
}

function parseBarTime(bar: PriceStructureBar) {
  if (!bar.timestamp) {
    return null;
  }
  const time = Date.parse(bar.timestamp);
  return Number.isFinite(time) ? time : null;
}

function formatDateTick(timestamp: string | undefined, fallback: number) {
  if (!timestamp) {
    return `${fallback + 1}`;
  }
  const match = timestamp.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) {
    return `${match[1]}-${match[2]}-${match[3]}`;
  }
  return timestamp.slice(0, 10);
}

function filterBarsByRange(
  bars: PriceStructureBar[],
  selectedRange: KlineRangeKey,
) {
  const range = KLINE_RANGES.find((item) => item.key === selectedRange);
  if (!range?.days) {
    return bars;
  }

  const latestTime = bars.reduce<number | null>((latest, bar) => {
    const time = parseBarTime(bar);
    if (time === null) {
      return latest;
    }
    return latest === null ? time : Math.max(latest, time);
  }, null);

  if (latestTime === null) {
    return bars.slice(Math.max(0, bars.length - range.days));
  }

  const startTime = latestTime - range.days * 24 * 60 * 60 * 1000;
  return bars.filter((bar) => {
    const time = parseBarTime(bar);
    return time === null || time >= startTime;
  });
}

export function PriceStructureChart({
  bars,
  emptyLabel,
  titleLabel,
  priceLabel,
  rangeLabels = DEFAULT_RANGE_LABELS,
  axisLabels = { price: 'Price axis', date: 'Date axis' },
  rangeAriaLabel = (label) => `Show ${label} K-line range`,
}: {
  bars: PriceStructureBar[];
  emptyLabel: string;
  titleLabel: string;
  priceLabel: string;
  rangeLabels?: KlineRangeLabels;
  axisLabels?: KlineAxisLabels;
  rangeAriaLabel?: (label: string) => string;
}) {
  const [selectedRange, setSelectedRange] = useState<KlineRangeKey>('all');
  const validBars = useMemo(
    () =>
      bars
        .filter((bar) => Number.isFinite(bar.close))
        .sort((left, right) => {
          const leftTime = parseBarTime(left);
          const rightTime = parseBarTime(right);
          if (leftTime === null || rightTime === null) {
            return 0;
          }
          return leftTime - rightTime;
        }),
    [bars],
  );
  const visibleBars = useMemo(
    () => filterBarsByRange(validBars, selectedRange),
    [selectedRange, validBars],
  );

  if (validBars.length === 0) {
    return (
      <div
        className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] p-4"
        aria-label={titleLabel}
      >
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {titleLabel}
        </div>
        <div className="mt-3 flex h-48 items-center justify-center rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] text-sm text-[var(--app-muted)] sm:h-56">
          {emptyLabel}
        </div>
      </div>
    );
  }

  const plottedBars = visibleBars.length > 0 ? visibleBars : validBars;
  const closes = plottedBars.map((bar) => bar.close);
  const lows = plottedBars.map((bar) => toFiniteNumber(bar.low) ?? bar.close);
  const highs = plottedBars.map((bar) => toFiniteNumber(bar.high) ?? bar.close);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const latest = closes[closes.length - 1] ?? 0;
  const first = closes[0] ?? latest;
  const change = latest - first;
  const changePercent = first === 0 ? 0 : change / first;
  const latestTone =
    change >= 0 ? 'text-[var(--app-success)]' : 'text-[var(--app-danger)]';
  const plot = {
    left: 64,
    right: 620,
    top: 18,
    bottom: 198,
  };
  const plotWidth = plot.right - plot.left;
  const plotHeight = plot.bottom - plot.top;
  const plotY = (value: number) =>
    plot.bottom - ((value - min) / range) * plotHeight;
  const step = plotWidth / Math.max(plottedBars.length, 1);
  const candleWidth = Math.max(Math.min(step * 0.48, 14), 4);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = min + range * ratio;
    return {
      value,
      y: plotY(value),
    };
  });
  const xTickIndexes = Array.from(
    new Set([
      0,
      Math.max(0, Math.floor((plottedBars.length - 1) / 2)),
      Math.max(0, plottedBars.length - 1),
    ]),
  );

  return (
    <div
      className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] p-4"
      aria-label={titleLabel}
    >
      <div className="mb-4 flex min-w-0 flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
            {titleLabel}
          </div>
          <div className="mt-1 break-words font-mono text-2xl font-semibold tabular-nums text-[var(--app-text)]">
            {formatCurrency(latest)}
          </div>
        </div>
        <div
          className={`shrink-0 font-mono text-sm font-semibold ${latestTone}`}
        >
          {change >= 0 ? '+' : ''}
          {formatCurrency(change)} · {formatPercent(changePercent)}
        </div>
      </div>
      <div className="mb-4 flex min-w-0 flex-wrap gap-2">
        {KLINE_RANGES.map((rangeOption) => {
          const label = rangeLabels[rangeOption.key];
          const selected = selectedRange === rangeOption.key;
          return (
            <button
              key={rangeOption.key}
              type="button"
              className={`rounded-full border px-3 py-1.5 font-mono text-[11px] font-semibold transition-colors ${
                selected
                  ? 'border-[color-mix(in_srgb,var(--app-accent)_58%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_16%,transparent)] text-[var(--app-text)]'
                  : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] text-[var(--app-muted)] hover:border-[color-mix(in_srgb,var(--app-accent)_34%,transparent)] hover:text-[var(--app-soft)]'
              }`}
              aria-pressed={selected}
              aria-label={rangeAriaLabel(label)}
              onClick={() => {
                setSelectedRange(rangeOption.key);
              }}
            >
              {label}
            </button>
          );
        })}
      </div>
      <div
        data-testid="price-structure-chart-scroll"
        className="min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2"
      >
        <div
          data-testid="price-structure-chart-canvas"
          className="min-w-[640px]"
        >
          <svg
            viewBox="0 0 640 244"
            className="h-60 w-full overflow-visible text-[var(--app-soft)] sm:h-72"
            role="img"
            aria-label={`${titleLabel} ${priceLabel}`}
          >
            <text x={plot.left} y="10" className="fill-current text-[10px]">
              {axisLabels.price}
            </text>
            <text
              x={(plot.left + plot.right) / 2}
              y="240"
              textAnchor="middle"
              className="fill-current text-[10px]"
            >
              {axisLabels.date}
            </text>
            <line
              x1={plot.left}
              x2={plot.left}
              y1={plot.top}
              y2={plot.bottom}
              stroke="currentColor"
              strokeOpacity="0.22"
            />
            <line
              x1={plot.left}
              x2={plot.right}
              y1={plot.bottom}
              y2={plot.bottom}
              stroke="currentColor"
              strokeOpacity="0.22"
            />
            {yTicks.map((tick) => (
              <g key={tick.value}>
                <line
                  x1={plot.left}
                  x2={plot.right}
                  y1={tick.y}
                  y2={tick.y}
                  stroke="currentColor"
                  strokeOpacity="0.08"
                />
                <text
                  x={plot.left - 8}
                  y={tick.y + 4}
                  textAnchor="end"
                  className="fill-current font-mono text-[10px]"
                >
                  {formatCurrency(tick.value)}
                </text>
              </g>
            ))}
            {xTickIndexes.map((index) => {
              const bar = plottedBars[index];
              const x = plot.left + step * index + step / 2;
              return (
                <g key={`${bar.timestamp ?? index}-tick`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={plot.bottom}
                    y2={plot.bottom + 5}
                    stroke="currentColor"
                    strokeOpacity="0.22"
                  />
                  <text
                    x={x}
                    y={plot.bottom + 20}
                    textAnchor="middle"
                    className="fill-current font-mono text-[10px]"
                  >
                    {formatDateTick(bar.timestamp, index)}
                  </text>
                </g>
              );
            })}
            {plottedBars.map((bar, index) => {
              const open = toFiniteNumber(bar.open) ?? bar.close;
              const high =
                toFiniteNumber(bar.high) ?? Math.max(open, bar.close);
              const low = toFiniteNumber(bar.low) ?? Math.min(open, bar.close);
              const x = plot.left + step * index + step / 2;
              const openY = plotY(open);
              const closeY = plotY(bar.close);
              const topY = Math.min(openY, closeY);
              const height = Math.max(Math.abs(openY - closeY), 2);
              const tone =
                bar.close >= open ? 'var(--app-success)' : 'var(--app-danger)';

              return (
                <g
                  key={`${bar.timestamp ?? index}-${bar.close}`}
                  data-testid="kline-candle"
                >
                  <line
                    x1={x}
                    x2={x}
                    y1={plotY(high)}
                    y2={plotY(low)}
                    stroke={tone}
                    strokeOpacity="0.9"
                    strokeWidth="1.4"
                  />
                  <rect
                    x={x - candleWidth / 2}
                    y={topY}
                    width={candleWidth}
                    height={height}
                    rx="1"
                    fill={tone}
                    fillOpacity={bar.close >= open ? '0.18' : '0.34'}
                    stroke={tone}
                    strokeWidth="1.5"
                  />
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-col gap-1 font-mono text-[11px] text-[var(--app-muted)] sm:flex-row sm:items-center sm:justify-between">
            <span>
              {formatDateTick(plottedBars[0]?.timestamp, 0)} -{' '}
              {formatDateTick(
                plottedBars[plottedBars.length - 1]?.timestamp,
                plottedBars.length - 1,
              )}
            </span>
            <span>
              {formatCurrency(min)} - {formatCurrency(max)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
