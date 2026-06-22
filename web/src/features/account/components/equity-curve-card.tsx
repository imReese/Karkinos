import {
  startTransition,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useCopy } from '../../../app/copy';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  formatCompactNumber,
  formatCurrency,
  formatDateTime,
} from '../../../shared/format';
import {
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import { formatPublicStatus } from '../../../shared/public-labels';
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
  value?: number | string | null;
};

type CustomTooltipProps = {
  active?: boolean;
  categoryDailyChangeLabel: (label: string) => string;
  locale: Locale;
  portfolioTotalLabel: string;
  quoteStatusLabel: string;
  realtimeUnrealizedPnlLabel: string;
  unconfirmedCategoryDailyChangeLabel: (label: string) => string;
  payload?: TooltipPayload[];
};

type ChartSize = {
  height: number;
  width: number;
};

const SERIES_META: Array<{ key: SeriesKey; color: string; gradient: string }> =
  [
    { key: 'total', color: 'var(--app-accent)', gradient: 'totalGradient' },
    { key: 'cash', color: 'var(--app-teal)', gradient: 'cashGradient' },
    {
      key: 'stocks',
      color: 'var(--app-accent-secondary)',
      gradient: 'stocksGradient',
    },
    { key: 'funds', color: 'var(--app-success)', gradient: 'fundsGradient' },
    { key: 'others', color: 'var(--app-warning)', gradient: 'othersGradient' },
  ];

const ALL_VISIBLE_SERIES: Record<SeriesKey, boolean> = {
  total: true,
  cash: true,
  stocks: true,
  funds: true,
  others: true,
};

const NO_VISIBLE_SERIES: Record<SeriesKey, boolean> = {
  total: false,
  cash: false,
  stocks: false,
  funds: false,
  others: false,
};

const RANGE_DAYS: Record<EquityCurveRange, number> = {
  '1d': 1,
  '5d': 5,
  '1m': 31,
  '6m': 183,
  '1y': 366,
  all: Number.POSITIVE_INFINITY,
};

function isUnconfirmedQuoteStatus(status?: string | null) {
  return isUnconfirmedMarketDataStatus(status);
}

function isMissingQuoteObservation(status?: string | null) {
  const normalized = normalizeMarketDataStatus(status);
  return normalized === 'missing' || normalized === 'error';
}

function resolveValuationStatusText({
  cachedValuationLabel,
  locale,
  quoteStatus,
  valuationStatusLabel,
}: {
  cachedValuationLabel: string;
  locale: Locale;
  quoteStatus?: string | null;
  valuationStatusLabel: (status: string) => string;
}) {
  const normalized = normalizeMarketDataStatus(quoteStatus);
  if (!normalized || isConfirmedMarketDataStatus(normalized)) {
    return null;
  }
  if (isCacheLikeMarketDataStatus(normalized)) {
    return cachedValuationLabel;
  }
  return valuationStatusLabel(formatPublicStatus(normalized, locale));
}

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

function readChartElementSize(element: HTMLElement | null): ChartSize | null {
  if (!element) {
    return null;
  }

  const rect = element.getBoundingClientRect();
  const width = Math.floor(rect.width || element.clientWidth || 0);
  const height = Math.floor(rect.height || element.clientHeight || 0);

  if (width <= 0 || height <= 0) {
    return null;
  }

  return { width, height };
}

function useChartContainerSize<TElement extends HTMLElement>() {
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
    .map((point) => {
      const timestampMs = new Date(point.timestamp).getTime();
      if (isMissingQuoteObservation(point.quote_status)) {
        return {
          ...point,
          total: null,
          stocks: null,
          funds: null,
          others: null,
          unrealized_pnl: null,
          total_daily_change: null,
          stocks_daily_change: null,
          funds_daily_change: null,
          others_daily_change: null,
          timestampMs,
        };
      }
      return {
        ...point,
        timestampMs,
      };
    })
    .filter((point) => Number.isFinite(point.timestampMs))
    .sort((a, b) => a.timestampMs - b.timestampMs);
}

function resolveTooltipSeriesKey(
  dataKey: TooltipPayload['dataKey'],
): SeriesKey | null {
  if (typeof dataKey !== 'string') {
    return null;
  }
  return SERIES_META.some((series) => series.key === dataKey)
    ? (dataKey as SeriesKey)
    : null;
}

function resolveDailyChange(point: ChartPoint, seriesKey: SeriesKey) {
  if (seriesKey === 'cash') {
    return null;
  }

  const dailyChangeKey = `${seriesKey}_daily_change` as keyof ChartPoint;
  const value = point[dailyChangeKey];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function resolveDefaultVisibleSeries(points: EquitySeriesPoint[]) {
  const chartPoints = toChartPoints(points);
  const nextVisible = { ...NO_VISIBLE_SERIES };
  for (const series of SERIES_META) {
    nextVisible[series.key] = chartPoints.some((point) => {
      const value = point[series.key];
      return (
        typeof value === 'number' &&
        Number.isFinite(value) &&
        Math.abs(value) > 0
      );
    });
  }
  return nextVisible;
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

function resolveSeriesHighs(
  points: ChartPoint[],
  visibleSeries: Record<SeriesKey, boolean>,
  seriesLabels: Record<SeriesKey, string>,
) {
  return SERIES_META.flatMap((series) => {
    if (!visibleSeries[series.key]) {
      return [];
    }
    const high = points.reduce<{
      point: ChartPoint;
      pointIndex: number;
      value: number;
    } | null>((currentHigh, point, pointIndex) => {
      const value = point[series.key];
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        return currentHigh;
      }
      if (!currentHigh || value > currentHigh.value) {
        return { point, pointIndex, value };
      }
      return currentHigh;
    }, null);
    if (!high) {
      return [];
    }
    return [
      {
        key: series.key,
        color: series.color,
        label: seriesLabels[series.key],
        value: high.value,
        timestampMs: high.point.timestampMs,
        pointIndex: high.pointIndex,
      },
    ];
  });
}

function renderHighPointDot({
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
        <g className="transition-opacity duration-150 group-hover/equity-chart:opacity-0">
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
            className="fill-current text-[10px] font-semibold"
          >
            <tspan>{high.label}</tspan>
            <tspan dx="7" className="opacity-70">
              {displayDate}
            </tspan>
          </text>
          <text
            x={textX}
            y={labelY + 30}
            className="fill-current text-[11px] font-semibold"
          >
            {displayValue}
          </text>
        </g>
      </g>
    );
  };
}

function CustomTooltip({
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
    <div className="z-[90] max-w-[min(18rem,calc(100vw-2rem))] rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_92%,transparent)] px-3 py-2.5 text-xs shadow-[0_18px_54px_color-mix(in_srgb,var(--app-mantle)_54%,transparent),inset_0_1px_0_color-mix(in_srgb,var(--app-text)_6%,transparent)] backdrop-blur-md tabular-nums">
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
  const { locale } = usePreferences();
  const labels = copy.overview.equityCurve;
  const [uncontrolledRange, setUncontrolledRange] =
    useState<EquityCurveRange>('all');
  const range = controlledRange ?? uncontrolledRange;
  const defaultVisibleSeries = useMemo(
    () => resolveDefaultVisibleSeries(points),
    [points],
  );
  const [hasManualSeriesSelection, setHasManualSeriesSelection] =
    useState(false);
  const [visibleSeries, setVisibleSeries] =
    useState<Record<SeriesKey, boolean>>(defaultVisibleSeries);

  useEffect(() => {
    if (!hasManualSeriesSelection) {
      setVisibleSeries(defaultVisibleSeries);
    }
  }, [defaultVisibleSeries, hasManualSeriesSelection]);

  const chartPoints = filterByRange(toChartPoints(points), range);
  const hasUsableData = chartPoints.length >= 2;
  const xAxisTicks = resolveXAxisTicks(chartPoints, range);
  const xAxisDomain = resolveXAxisDomain(chartPoints, range);
  const yAxisDomain = resolveYAxisDomain(chartPoints, visibleSeries);
  const latestPoint = chartPoints[chartPoints.length - 1];
  const valuationStatusText = resolveValuationStatusText({
    cachedValuationLabel: labels.cachedValuation,
    locale,
    quoteStatus: latestPoint?.quote_status,
    valuationStatusLabel: labels.valuationStatus,
  });
  const [chartContainerRef, chartSize] =
    useChartContainerSize<HTMLDivElement>();

  const rangeOptions: Array<[EquityCurveRange, string]> = [
    ['1d', labels.oneDay],
    ['5d', labels.fiveDays],
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  const seriesLabels: Record<SeriesKey, string> = {
    total: labels.total,
    cash: labels.cash,
    stocks: labels.stocks,
    funds: labels.funds,
    others: labels.others,
  };
  const allSeriesSelected = SERIES_META.every(
    (series) => visibleSeries[series.key],
  );
  const seriesHighs = resolveSeriesHighs(
    chartPoints,
    visibleSeries,
    seriesLabels,
  );

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
          {valuationStatusText ? (
            <div className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-2.5 py-1 text-[11px] font-semibold text-[var(--app-warning)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
              <span className="truncate">{valuationStatusText}</span>
            </div>
          ) : null}
          <div
            data-testid="equity-series-controls"
            className="mt-3 flex flex-wrap items-center gap-1.5"
          >
            <button
              type="button"
              aria-pressed={allSeriesSelected}
              aria-label={labels.allSeries}
              onClick={() => {
                setHasManualSeriesSelection(true);
                setVisibleSeries(
                  allSeriesSelected ? NO_VISIBLE_SERIES : ALL_VISIBLE_SERIES,
                );
              }}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-[background-color,border-color,color,opacity,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.98] ${
                allSeriesSelected
                  ? 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-text)]'
                  : 'border-transparent bg-transparent text-[var(--app-muted)] opacity-55 hover:border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] hover:opacity-100'
              }`}
            >
              {labels.allSeries}
            </button>
            {SERIES_META.map((series) => {
              const active = visibleSeries[series.key];
              return (
                <button
                  key={series.key}
                  type="button"
                  aria-pressed={active}
                  aria-label={seriesLabels[series.key]}
                  onClick={() => {
                    setHasManualSeriesSelection(true);
                    setVisibleSeries((current) => ({
                      ...current,
                      [series.key]: !current[series.key],
                    }));
                  }}
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

        <div
          data-testid="equity-range-controls"
          className="grid w-full max-w-[340px] grid-cols-6 gap-1 rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_30%,transparent)] p-1 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] sm:w-max"
        >
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
              className={`h-7 min-w-0 rounded-full px-2 font-mono text-[11px] font-semibold transition-[background-color,box-shadow,color,transform] duration-300 active:scale-[0.98] ${
                range === value
                  ? 'bg-[color-mix(in_srgb,var(--app-accent)_26%,transparent)] text-[var(--app-accent)] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_8%,transparent)]'
                  : 'text-[var(--app-muted)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {hasUsableData ? (
        <div
          ref={chartContainerRef}
          data-testid="equity-chart-frame"
          className="group/equity-chart h-[340px] w-full overflow-visible rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[linear-gradient(color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),linear-gradient(90deg,color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),color-mix(in_srgb,var(--app-panel-strong)_26%,transparent)] bg-[length:44px_44px,44px_44px,auto] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] sm:h-[410px]"
        >
          {chartSize ? (
            <LineChart
              width={chartSize.width}
              height={chartSize.height}
              data={chartPoints}
              margin={{ left: 14, right: 72, top: 22, bottom: 36 }}
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
                    categoryDailyChangeLabel={labels.categoryDailyChange}
                    locale={locale}
                    portfolioTotalLabel={labels.portfolioTotal}
                    quoteStatusLabel={labels.quoteStatus}
                    realtimeUnrealizedPnlLabel={labels.realtimeUnrealizedPnl}
                    unconfirmedCategoryDailyChangeLabel={
                      labels.unconfirmedCategoryDailyChange
                    }
                  />
                }
                cursor={{
                  stroke: 'var(--app-accent)',
                  strokeOpacity: 0.32,
                  strokeWidth: 1,
                }}
                wrapperStyle={{ zIndex: 90, outline: 'none' }}
                allowEscapeViewBox={{ x: false, y: true }}
              />
              {SERIES_META.map((series) => {
                const active = visibleSeries[series.key];
                if (!active) {
                  return null;
                }
                const isPrimarySeries = series.key === 'total';
                const high = seriesHighs.find(
                  (item) => item.key === series.key,
                );
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
                    dot={
                      high
                        ? renderHighPointDot({
                            high,
                            range,
                            seriesIndex: seriesHighs.findIndex(
                              (item) => item.key === series.key,
                            ),
                            pointCount: chartPoints.length,
                            chartWidth: chartSize.width,
                          })
                        : false
                    }
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
          ) : null}
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
                  <span className="font-mono">
                    {formatPublicStatus(latestPoint.quote_status, locale)}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
