import { useLayoutEffect, useRef, useState } from 'react';

import { formatPublicStatus } from '../../../shared/public-labels';
import type { EquityCurveRange } from '../api';
import {
  formatAxisTimestamp,
  formatChartTimestamp,
  formatWholeCurrency,
  isUnconfirmedQuoteStatus,
  readChartElementSize,
  resolveDailyChange,
  resolveSeriesHighs,
  resolveTooltipSeriesKey,
  type ChartPoint,
  type ChartSize,
  type CustomTooltipProps,
  type TooltipPayload,
} from './equity-curve-chart-model';

export function useChartContainerSize<TElement extends HTMLElement>() {
  const ref = useRef<TElement | null>(null);
  const [size, setSize] = useState<ChartSize | null>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) {
      return undefined;
    }

    let animationFrame: number | null = null;

    const commitSize = () => {
      const nextSize = readChartElementSize(element);
      if (!nextSize) {
        return;
      }
      setSize((currentSize) => {
        if (
          currentSize?.width === nextSize.width &&
          currentSize.height === nextSize.height
        ) {
          return currentSize;
        }
        return nextSize;
      });
    };

    const scheduleSizeCommit = () => {
      if (typeof window === 'undefined') {
        commitSize();
        return;
      }
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = null;
        commitSize();
      });
    };

    commitSize();

    const resizeObserver =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(scheduleSizeCommit);
    resizeObserver?.observe(element);
    window.addEventListener('resize', scheduleSizeCommit);

    return () => {
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
      resizeObserver?.disconnect();
      window.removeEventListener('resize', scheduleSizeCommit);
    };
  }, []);

  return [ref, size] as const;
}

export function TimeAxisTick({
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

export function renderHighPointDot({
  high,
  range,
  seriesIndex,
  pointCount,
  chartWidth,
}: {
  high: ReturnType<typeof resolveSeriesHighs>[number];
  range: EquityCurveRange;
  seriesIndex: number;
  pointCount: number;
  chartWidth: number;
}) {
  return ({
    cx,
    cy,
    payload,
    value,
  }: {
    cx?: number;
    cy?: number;
    payload?: ChartPoint;
    value?: number;
  }) => {
    if (
      typeof cx !== 'number' ||
      typeof cy !== 'number' ||
      typeof value !== 'number' ||
      payload?.timestampMs !== high.timestampMs ||
      value !== high.value
    ) {
      return null;
    }

    const labelWidth = 116;
    const edgePadding = 20;
    const isNearRightEdge =
      cx > chartWidth - labelWidth - edgePadding ||
      high.pointIndex >= Math.max(pointCount - 1, 0);
    const isNearTop = cy < 96;
    const labelHeight = 38;
    const laneOffset = (seriesIndex % 3) * 28;
    const labelSide = isNearRightEdge ? 'left' : 'right';
    const labelX = labelSide === 'left' ? -labelWidth - 10 : 10;
    const labelY = isNearTop ? 12 + laneOffset : -labelHeight - 8 - laneOffset;
    const textX = labelX + 9;
    const displayDate = formatAxisTimestamp(high.timestampMs, range);
    const displayValue = formatWholeCurrency(high.value);

    return (
      <g
        data-testid={`equity-series-high-marker-${high.key}`}
        data-label-side={labelSide}
        transform={`translate(${cx} ${cy})`}
        pointerEvents="none"
      >
        <circle
          r="5"
          fill={high.color}
          stroke="var(--app-mantle)"
          strokeWidth="2.5"
        />
        <circle
          r="9"
          fill="none"
          stroke={high.color}
          strokeOpacity="0.38"
          strokeWidth="1.5"
        />
        <g className="app-chart-annotation group-hover/equity-chart:opacity-0">
          <line
            x1="0"
            y1={isNearTop ? 8 : -8}
            x2="0"
            y2={labelY + (isNearTop ? 0 : labelHeight)}
            stroke={high.color}
            strokeOpacity="0.42"
            strokeDasharray="3 4"
          />
          <rect
            x={labelX}
            y={labelY}
            width={labelWidth}
            height={labelHeight}
            rx="10"
            fill="var(--app-panel-strong)"
            stroke={high.color}
            strokeOpacity="0.54"
          />
          <text
            x={textX}
            y={labelY + 14}
            className="app-type-micro fill-current font-semibold"
          >
            <tspan>{high.label}</tspan>
            <tspan dx="7" className="opacity-70">
              {displayDate}
            </tspan>
          </text>
          <text
            x={textX}
            y={labelY + 30}
            className="app-type-micro fill-current font-semibold"
          >
            {displayValue}
          </text>
        </g>
      </g>
    );
  };
}

export function CustomTooltip({
  active,
  payload,
  categoryDailyChangeLabel,
  locale,
  portfolioTotalLabel,
  quoteStatusLabel,
  realtimeUnrealizedPnlLabel,
  unconfirmedCategoryDailyChangeLabel,
}: CustomTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }

  const validPayload = payload.filter(
    (item): item is TooltipPayload => item !== undefined && item !== null,
  );
  if (!validPayload.length) {
    return null;
  }

  const point = validPayload[0]?.payload;
  if (!point) {
    return null;
  }

  const includesTotalSeries = validPayload.some(
    (item) => item.dataKey === 'total',
  );
  const hasUnconfirmedQuoteStatus = isUnconfirmedQuoteStatus(
    point.quote_status,
  );
  const categoryChangeRows = validPayload.flatMap((item) => {
    const seriesKey = resolveTooltipSeriesKey(item.dataKey);
    if (seriesKey !== 'stocks' && seriesKey !== 'funds') {
      return [];
    }
    const change = resolveDailyChange(point, seriesKey);
    if (change === null) {
      return [];
    }
    return [
      {
        key: seriesKey,
        label: hasUnconfirmedQuoteStatus
          ? unconfirmedCategoryDailyChangeLabel(String(item.name))
          : categoryDailyChangeLabel(String(item.name)),
        value: change,
      },
    ];
  });
  const shouldShowPortfolioContext =
    includesTotalSeries || categoryChangeRows.length > 0;

  return (
    <div className="app-chart-tooltip z-[90] max-w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_92%,transparent)] px-3 py-2.5 text-xs shadow-[0_18px_54px_color-mix(in_srgb,var(--app-mantle)_54%,transparent),inset_0_1px_0_color-mix(in_srgb,var(--app-text)_6%,transparent)] backdrop-blur-md tabular-nums">
      <div className="mb-2 font-medium text-[var(--app-text)]">
        {formatChartTimestamp(point.timestamp)}
      </div>
      <div className="space-y-1.5">
        {validPayload.map((item) => {
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
        {categoryChangeRows.map((row) => (
          <div
            key={`${row.key}-daily-change`}
            className="mt-2 flex min-w-40 items-center justify-between gap-5 border-t border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] pt-2"
          >
            <span className="text-[var(--app-muted)]">{row.label}</span>
            <span
              className={`font-medium tabular-nums ${
                row.value >= 0
                  ? 'text-[var(--app-success)]'
                  : 'text-[var(--app-danger)]'
              }`}
            >
              {formatWholeCurrency(row.value)}
            </span>
          </div>
        ))}
        {!includesTotalSeries &&
        categoryChangeRows.length > 0 &&
        typeof point.total === 'number' ? (
          <div className="flex min-w-40 items-center justify-between gap-5">
            <span className="text-[var(--app-muted)]">
              {portfolioTotalLabel}
            </span>
            <span className="font-medium tabular-nums text-[var(--app-text)]">
              {formatWholeCurrency(point.total)}
            </span>
          </div>
        ) : null}
        {shouldShowPortfolioContext &&
        typeof point.unrealized_pnl === 'number' ? (
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
              {formatPublicStatus(point.quote_status, locale)}
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
