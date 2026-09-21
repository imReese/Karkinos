export type PriceStructureBar = {
  timestamp?: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
};

export type KlineRangeKey =
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

export type PriceStructureChartType = 'candlestick' | 'line';

export type PriceStructureChartTypeLabels = {
  candlestick: string;
  line: string;
};

export const DEFAULT_CHART_TYPE_LABELS: PriceStructureChartTypeLabels = {
  candlestick: 'K线',
  line: '走势',
};

export type PriceStructureChartProps = {
  bars: PriceStructureBar[];
  emptyLabel: string;
  titleLabel: string;
  priceLabel: string;
  rangeLabels?: KlineRangeLabels;
  axisLabels?: KlineAxisLabels;
  rangeAriaLabel?: (label: string) => string;
  markers?: PriceStructureMarker[];
  referenceLines?: PriceStructureReferenceLine[];
  initialChartType?: PriceStructureChartType;
  chartTypeLabels?: PriceStructureChartTypeLabels;
  chartTypeAriaLabel?: (label: string) => string;
};

export const DEFAULT_RANGE_LABELS: KlineRangeLabels = {
  oneMonth: '1M',
  threeMonths: '3M',
  sixMonths: '6M',
  oneYear: '1Y',
  all: 'All',
};

export const KLINE_RANGES: Array<{
  key: KlineRangeKey;
  days: number | null;
}> = [
  { key: 'oneMonth', days: 31 },
  { key: 'threeMonths', days: 93 },
  { key: 'sixMonths', days: 186 },
  { key: 'oneYear', days: 366 },
  { key: 'all', days: null },
];

export function toFiniteNumber(value: number | null | undefined) {
  return Number.isFinite(value ?? NaN) ? Number(value) : null;
}

export function parseBarTime(bar: PriceStructureBar) {
  if (!bar.timestamp) {
    return null;
  }
  const time = Date.parse(bar.timestamp);
  return Number.isFinite(time) ? time : null;
}

export function formatDateTick(
  timestamp: string | undefined,
  fallback: number,
) {
  if (!timestamp) {
    return `${fallback + 1}`;
  }
  const match = timestamp.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) {
    return `${match[1]}-${match[2]}-${match[3]}`;
  }
  return timestamp.slice(0, 10);
}

export function filterBarsByRange(
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

function buildPlottedMarkers(
  markers: PriceStructureMarker[],
  plottedBars: PriceStructureBar[],
) {
  const plottedTimes = plottedBars.map((bar) => parseBarTime(bar));
  const finitePlottedTimes = plottedTimes.filter(
    (value): value is number => value !== null,
  );
  const plottedStart =
    finitePlottedTimes.length > 0 ? Math.min(...finitePlottedTimes) : null;
  const plottedEnd =
    finitePlottedTimes.length > 0 ? Math.max(...finitePlottedTimes) : null;
  return markers.flatMap((marker) => {
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
    if (!bar || price === undefined || !Number.isFinite(price)) {
      return [];
    }
    return [{ ...marker, price, barIndex: nearestIndex }];
  });
}

export function buildPriceStructureChartModel({
  bars,
  markers,
  referenceLines,
  selectedRange,
  width = 720,
  height = 280,
  chartType = 'candlestick',
}: {
  bars: PriceStructureBar[];
  markers: PriceStructureMarker[];
  referenceLines: PriceStructureReferenceLine[];
  selectedRange: KlineRangeKey;
  width?: number;
  height?: number;
  chartType?: PriceStructureChartType;
}) {
  const validBars = bars
    .filter((bar) => Number.isFinite(bar.close))
    .sort((left, right) => {
      const leftTime = parseBarTime(left);
      const rightTime = parseBarTime(right);
      if (leftTime === null || rightTime === null) {
        return 0;
      }
      return leftTime - rightTime;
    });
  if (validBars.length === 0) {
    return null;
  }

  const visibleBars = filterBarsByRange(validBars, selectedRange);
  const plottedBars = visibleBars.length > 0 ? visibleBars : validBars;
  const lows = plottedBars.map((bar) => toFiniteNumber(bar.low) ?? bar.close);
  const highs = plottedBars.map((bar) => toFiniteNumber(bar.high) ?? bar.close);
  const volumes = plottedBars.map((bar) =>
    Math.max(0, toFiniteNumber(bar.volume) ?? 0),
  );
  const maxVolume = Math.max(...volumes, 0);
  const hasVolume = maxVolume > 0;
  const plottedMarkers = buildPlottedMarkers(markers, plottedBars);
  const plottedReferenceLines = referenceLines.filter((line) =>
    Number.isFinite(line.value),
  );
  const finiteReferenceValues = plottedReferenceLines.map((line) => line.value);
  const finiteMarkerValues = plottedMarkers.map((marker) => marker.price);
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

  const chartWidth = Math.max(width, 720);
  const chartHeight = Math.max(height, 240);
  const plot = {
    left: 56,
    right: chartWidth - 16,
    top: 12,
    bottom: hasVolume ? chartHeight - 74 : chartHeight - 26,
  };
  const volumePlot = {
    top: chartHeight - 58,
    bottom: chartHeight - 26,
  };
  const xAxisY = hasVolume ? volumePlot.bottom : plot.bottom;
  const plotWidth = Math.max(plot.right - plot.left, 10);
  const plotHeight = Math.max(plot.bottom - plot.top, 10);
  const plotY = (value: number) =>
    plot.bottom - ((value - min) / range) * plotHeight;
  const step = plotWidth / Math.max(plottedBars.length, 1);

  // Professional financial candlestick sizing:
  // Strictly prevent overlapping between adjacent candles
  let candleWidth = 1;
  if (step >= 6) {
    candleWidth = Math.max(1, Math.min(Math.floor(step * 0.72), 16));
  } else if (step >= 3) {
    candleWidth = Math.max(1, Math.floor(step - 1));
  } else {
    candleWidth = 1;
  }

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = min + range * ratio;
    return { value, y: plotY(value) };
  });

  const tickCount = Math.min(
    Math.max(2, Math.floor(plotWidth / 150)),
    plottedBars.length,
  );
  const xTickIndexes = Array.from(
    new Set(
      Array.from({ length: tickCount }, (_, i) =>
        i === tickCount - 1
          ? plottedBars.length - 1
          : Math.floor((i / (tickCount - 1)) * (plottedBars.length - 1)),
      ),
    ),
  );

  const latestBar = plottedBars[plottedBars.length - 1] ?? null;

  // Continuous line and area paths (Apple Stocks style)
  const linePoints = plottedBars.map((bar, index) => ({
    x: Math.round(plot.left + step * index + step / 2),
    y: Math.round(plotY(bar.close)),
    close: bar.close,
    timestamp: bar.timestamp,
  }));

  const linePath =
    linePoints.length > 0
      ? linePoints
          .map(
            (point, index) =>
              `${index === 0 ? 'M' : 'L'} ${point.x},${point.y}`,
          )
          .join(' ')
      : '';

  const areaBaseline = plot.bottom;
  const areaPath =
    linePoints.length > 0
      ? `${linePath} L ${linePoints[linePoints.length - 1]?.x},${areaBaseline} L ${linePoints[0]?.x},${areaBaseline} Z`
      : '';

  const firstBar = plottedBars[0];
  const isBullishTrend =
    latestBar && firstBar ? latestBar.close >= firstBar.close : true;
  const trendTone = isBullishTrend
    ? 'var(--app-pnl-positive)'
    : 'var(--app-pnl-negative)';
  const latestPoint = linePoints[linePoints.length - 1] ?? null;

  return {
    areaPath,
    candleWidth,
    chartHeight,
    chartType,
    chartWidth,
    hasVolume,
    isBullishTrend,
    latestBar,
    latestPoint,
    linePath,
    linePoints,
    max,
    maxVolume,
    min,
    plot,
    plottedBars,
    plottedMarkers,
    plottedReferenceLines,
    plotY,
    step,
    trendTone,
    validBars,
    volumes,
    volumePlot,
    xAxisY,
    xTickIndexes,
    yTicks,
  };
}

export type PriceStructureChartModel = NonNullable<
  ReturnType<typeof buildPriceStructureChartModel>
>;
