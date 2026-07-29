import { useEffect, useMemo, useRef, useState } from 'react';

import { EvidenceState } from '../../../app/components/workbench';
import { formatCurrency } from '../../../shared/format';

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
  volume?: string;
};

export type PriceStructureMarker = {
  timestamp: string;
  kind: 'buy' | 'sell';
  price?: number | null;
  label: string;
};

export type PriceStructureReferenceLine = {
  value: number;
  label: string;
  tone?: 'local' | 'broker';
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
  markers = [],
  referenceLines = [],
}: {
  bars: PriceStructureBar[];
  emptyLabel: string;
  titleLabel: string;
  priceLabel: string;
  rangeLabels?: KlineRangeLabels;
  axisLabels?: KlineAxisLabels;
  rangeAriaLabel?: (label: string) => string;
  markers?: PriceStructureMarker[];
  referenceLines?: PriceStructureReferenceLine[];
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
  const plottedBars = visibleBars.length > 0 ? visibleBars : validBars;
  const chartScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const scrollToLatest = () => {
      const container = chartScrollRef.current;
      if (!container) {
        return;
      }
      container.scrollLeft = Math.max(
        0,
        container.scrollWidth - container.clientWidth,
      );
    };
    const frame = window.requestAnimationFrame(scrollToLatest);
    window.addEventListener('resize', scrollToLatest);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', scrollToLatest);
    };
  }, [plottedBars.length, selectedRange]);

  if (validBars.length === 0) {
    return (
      <div
        className="border-y border-[var(--app-divider)] py-3"
        aria-label={titleLabel}
      >
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {titleLabel}
        </div>
        <EvidenceState className="mt-3" kind="empty" title={emptyLabel} />
      </div>
    );
  }

  const lows = plottedBars.map((bar) => toFiniteNumber(bar.low) ?? bar.close);
  const highs = plottedBars.map((bar) => toFiniteNumber(bar.high) ?? bar.close);
  const volumes = plottedBars.map((bar) =>
    Math.max(0, toFiniteNumber(bar.volume) ?? 0),
  );
  const maxVolume = Math.max(...volumes, 0);
  const hasVolume = maxVolume > 0;
  const plottedTimes = plottedBars.map((bar) => parseBarTime(bar));
  const finitePlottedTimes = plottedTimes.filter(
    (value): value is number => value !== null,
  );
  const plottedStart =
    finitePlottedTimes.length > 0 ? Math.min(...finitePlottedTimes) : null;
  const plottedEnd =
    finitePlottedTimes.length > 0 ? Math.max(...finitePlottedTimes) : null;
  const plottedMarkers = markers.flatMap((marker) => {
    const markerTime = Date.parse(marker.timestamp);
    if (
      !Number.isFinite(markerTime) ||
      (plottedStart !== null && markerTime < plottedStart) ||
      (plottedEnd !== null && markerTime > plottedEnd)
    ) {
      return [];
    }
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    plottedTimes.forEach((barTime, index) => {
      if (barTime === null) {
        return;
      }
      const distance = Math.abs(barTime - markerTime);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    const bar = plottedBars[nearestIndex];
    const price = toFiniteNumber(marker.price) ?? bar?.close;
    if (!bar || price === undefined) {
      return [];
    }
    return [{ ...marker, price, barIndex: nearestIndex }];
  });
  const finiteReferenceValues = referenceLines
    .map((line) => toFiniteNumber(line.value))
    .filter((value): value is number => value !== null);
  const finiteMarkerValues = plottedMarkers
    .map((marker) => toFiniteNumber(marker.price))
    .filter((value): value is number => value !== null);
  const min = Math.min(
    ...lows,
    ...finiteReferenceValues,
    ...finiteMarkerValues,
  );
  const max = Math.max(
    ...highs,
    ...finiteReferenceValues,
    ...finiteMarkerValues,
  );
  const range = max - min || 1;
  const plot = {
    left: 64,
    right: 620,
    top: 10,
    bottom: hasVolume ? 174 : 218,
  };
  const volumePlot = {
    top: 190,
    bottom: 218,
  };
  const xAxisY = hasVolume ? volumePlot.bottom : plot.bottom;
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
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
      aria-label={titleLabel}
    >
      <div className="mb-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {titleLabel}
        </div>
        <div
          className="flex min-w-0 flex-wrap gap-2"
          role="group"
          aria-label={titleLabel}
        >
          {KLINE_RANGES.map((rangeOption) => {
            const label = rangeLabels[rangeOption.key];
            const selected = selectedRange === rangeOption.key;
            return (
              <button
                key={rangeOption.key}
                type="button"
                className={`rounded-[var(--app-radius-control)] border px-3 py-1.5 text-[11px] font-semibold transition-colors ${
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
      </div>
      <div
        ref={chartScrollRef}
        data-testid="price-structure-chart-scroll"
        className="app-horizontal-scroll-cue min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2"
      >
        <div
          data-testid="price-structure-chart-canvas"
          className="min-w-[720px]"
        >
          <svg
            viewBox="0 0 640 246"
            className="h-64 w-full overflow-visible text-[var(--app-soft)] sm:h-80 xl:h-[21rem]"
            role="img"
            aria-label={`${titleLabel} · ${axisLabels.price} · ${axisLabels.date}`}
          >
            <desc>
              {`${priceLabel} · ${axisLabels.price} · ${axisLabels.date}${
                hasVolume ? ` · ${axisLabels.volume ?? 'Volume'}` : ''
              }`}
            </desc>
            <line
              x1={plot.left}
              x2={plot.left}
              y1={plot.top}
              y2={xAxisY}
              stroke="currentColor"
              strokeOpacity="0.22"
            />
            <line
              x1={plot.left}
              x2={plot.right}
              y1={xAxisY}
              y2={xAxisY}
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
                  className="fill-current text-[length:var(--app-font-size-micro)] tabular-nums"
                >
                  {formatCurrency(tick.value)}
                </text>
              </g>
            ))}
            {referenceLines.map((line) => {
              const tone =
                line.tone === 'broker'
                  ? 'var(--app-warning)'
                  : 'var(--app-accent)';
              return (
                <g
                  key={`${line.label}-${line.value}`}
                  data-testid="kline-reference-line"
                >
                  <title>{line.label}</title>
                  <line
                    x1={plot.left}
                    x2={plot.right}
                    y1={plotY(line.value)}
                    y2={plotY(line.value)}
                    stroke={tone}
                    strokeDasharray={line.tone === 'broker' ? '3 3' : '7 4'}
                    strokeOpacity="0.8"
                    strokeWidth="1.2"
                  />
                </g>
              );
            })}
            {xTickIndexes.map((index) => {
              const bar = plottedBars[index];
              const x = plot.left + step * index + step / 2;
              const textAnchor =
                index === 0
                  ? 'start'
                  : index === plottedBars.length - 1
                    ? 'end'
                    : 'middle';
              return (
                <g key={`${bar.timestamp ?? index}-tick`}>
                  <line
                    x1={x}
                    x2={x}
                    y1={xAxisY}
                    y2={xAxisY + 5}
                    stroke="currentColor"
                    strokeOpacity="0.22"
                  />
                  <text
                    x={x}
                    y={xAxisY + 20}
                    textAnchor={textAnchor}
                    className="fill-current text-[length:var(--app-font-size-micro)] tabular-nums"
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
                bar.close >= open
                  ? 'var(--app-pnl-positive)'
                  : 'var(--app-pnl-negative)';

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
            {hasVolume ? (
              <g data-testid="kline-volume-series">
                <line
                  x1={plot.left}
                  x2={plot.right}
                  y1={volumePlot.top - 7}
                  y2={volumePlot.top - 7}
                  stroke="currentColor"
                  strokeOpacity="0.08"
                />
                <text
                  x={plot.right}
                  y={volumePlot.top - 7}
                  textAnchor="end"
                  className="fill-current text-[length:var(--app-font-size-micro)]"
                >
                  {axisLabels.volume ?? 'Volume'}
                </text>
                {volumes.map((volume, index) => {
                  if (volume <= 0) {
                    return null;
                  }
                  const x = plot.left + step * index + step / 2;
                  const height = Math.max(
                    1,
                    (volume / maxVolume) * (volumePlot.bottom - volumePlot.top),
                  );
                  return (
                    <rect
                      key={`${plottedBars[index]?.timestamp ?? index}-volume`}
                      data-testid="kline-volume-bar"
                      x={x - candleWidth / 2}
                      y={volumePlot.bottom - height}
                      width={candleWidth}
                      height={height}
                      rx="0.75"
                      fill="var(--app-chart-label)"
                      fillOpacity="0.24"
                    />
                  );
                })}
              </g>
            ) : null}
            {plottedMarkers.map((marker, index) => {
              const x = plot.left + step * marker.barIndex + step / 2;
              const y = plotY(marker.price);
              const isBuy = marker.kind === 'buy';
              const tone = isBuy
                ? 'var(--app-chart-buy)'
                : 'var(--app-chart-sell)';
              return (
                <g
                  key={`${marker.timestamp}-${marker.kind}-${index}`}
                  data-testid={`kline-trade-marker-${marker.kind}`}
                >
                  <title>{marker.label}</title>
                  <circle
                    cx={x}
                    cy={y}
                    r="5.5"
                    fill="var(--app-panel-strong)"
                    stroke={tone}
                    strokeWidth="2"
                  />
                  <text
                    x={x}
                    y={y + 3}
                    textAnchor="middle"
                    fill={tone}
                    className="text-[length:var(--app-font-size-micro)] font-bold"
                  >
                    {isBuy ? 'B' : 'S'}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="mt-2 flex flex-col gap-1 text-[11px] tabular-nums text-[var(--app-muted)] sm:flex-row sm:items-center sm:justify-between">
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
          {plottedMarkers.length > 0 || referenceLines.length > 0 ? (
            <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-muted)]">
              {plottedMarkers.some((marker) => marker.kind === 'buy') ? (
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-chart-buy)_42%,transparent)] px-2 py-0.5 text-[var(--app-chart-buy)]">
                  B ·{' '}
                  {
                    plottedMarkers.find((marker) => marker.kind === 'buy')
                      ?.label
                  }
                </span>
              ) : null}
              {plottedMarkers.some((marker) => marker.kind === 'sell') ? (
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-chart-sell)_42%,transparent)] px-2 py-0.5 text-[var(--app-chart-sell)]">
                  S ·{' '}
                  {
                    plottedMarkers.find((marker) => marker.kind === 'sell')
                      ?.label
                  }
                </span>
              ) : null}
              {referenceLines.map((line) => (
                <span
                  key={`${line.label}-legend`}
                  className={`rounded-full border px-2 py-0.5 ${
                    line.tone === 'broker'
                      ? 'border-[color-mix(in_srgb,var(--app-warning)_32%,transparent)] text-[var(--app-warning)]'
                      : 'border-[color-mix(in_srgb,var(--app-accent)_32%,transparent)] text-[var(--app-accent)]'
                  }`}
                >
                  {line.label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
