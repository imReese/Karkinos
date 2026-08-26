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
import type { Locale } from '../../../shared/preferences/context';
import type { EquityCurveRange, EquitySeriesPoint } from '../api';

export type SeriesKey = 'total' | 'stocks' | 'funds' | 'others' | 'cash';

export type ChartPoint = EquitySeriesPoint & {
  timestampMs: number;
};

export type TooltipPayload = {
  color?: string;
  dataKey?: string | number;
  name?: string | number;
  payload?: ChartPoint;
  value?: number | string | null;
};

export type CustomTooltipProps = {
  active?: boolean;
  categoryDailyChangeLabel: (label: string) => string;
  locale: Locale;
  portfolioTotalLabel: string;
  quoteStatusLabel: string;
  realtimeUnrealizedPnlLabel: string;
  unconfirmedCategoryDailyChangeLabel: (label: string) => string;
  payload?: TooltipPayload[];
};

export type ChartSize = {
  height: number;
  width: number;
};

export const SERIES_META: Array<{
  key: SeriesKey;
  color: string;
  gradient: string;
}> = [
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

export const ALL_VISIBLE_SERIES: Record<SeriesKey, boolean> = {
  total: true,
  cash: true,
  stocks: true,
  funds: true,
  others: true,
};

export const NO_VISIBLE_SERIES: Record<SeriesKey, boolean> = {
  total: false,
  cash: false,
  stocks: false,
  funds: false,
  others: false,
};

export const RANGE_DAYS: Record<EquityCurveRange, number> = {
  '1d': 1,
  '5d': 5,
  '1m': 31,
  '6m': 183,
  '1y': 366,
  all: Number.POSITIVE_INFINITY,
};

export function isUnconfirmedQuoteStatus(status?: string | null) {
  return isUnconfirmedMarketDataStatus(status);
}

export function isMissingQuoteObservation(status?: string | null) {
  const normalized = normalizeMarketDataStatus(status);
  return normalized === 'missing' || normalized === 'error';
}

export function resolveValuationStatusText({
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

export function formatAxisValue(value: number) {
  return formatCompactNumber(value);
}

export function formatChartTimestamp(value: string | number | Date) {
  return formatDateTime(value);
}

export function formatAxisTimestamp(
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

export function formatWholeCurrency(value: number) {
  return formatCurrency(value, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

export function readChartElementSize(
  element: HTMLElement | null,
): ChartSize | null {
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

export function toChartPoints(points: EquitySeriesPoint[]): ChartPoint[] {
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

export function resolveTooltipSeriesKey(
  dataKey: TooltipPayload['dataKey'],
): SeriesKey | null {
  if (typeof dataKey !== 'string') {
    return null;
  }
  return SERIES_META.some((series) => series.key === dataKey)
    ? (dataKey as SeriesKey)
    : null;
}

export function resolveDailyChange(point: ChartPoint, seriesKey: SeriesKey) {
  if (seriesKey === 'cash') {
    return null;
  }

  const dailyChangeKey = `${seriesKey}_daily_change` as keyof ChartPoint;
  const value = point[dailyChangeKey];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function resolveDefaultVisibleSeries(points: EquitySeriesPoint[]) {
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

export function clonePointAtTimestamp(point: ChartPoint, timestampMs: number) {
  return {
    ...point,
    timestamp: new Date(timestampMs).toISOString(),
    timestampMs,
  };
}

export function filterByRange(points: ChartPoint[], range: EquityCurveRange) {
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

export function buildTimeTicks(points: ChartPoint[], tickCount: number) {
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

export function buildIntradaySessionTicks(points: ChartPoint[]) {
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

export function resolveXAxisTicks(
  points: ChartPoint[],
  range: EquityCurveRange,
) {
  if (range === '1d') {
    return buildIntradaySessionTicks(points);
  }
  return buildTimeTicks(points, 6);
}

export function resolveXAxisDomain(
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

export function resolveYAxisDomain(
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

export function resolveSeriesHighs(
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
