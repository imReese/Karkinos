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
}: {
  bars: PriceStructureBar[];
  markers: PriceStructureMarker[];
  referenceLines: PriceStructureReferenceLine[];
  selectedRange: KlineRangeKey;
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
  const plot = {
    left: 64,
    right: 620,
    top: 10,
    bottom: hasVolume ? 174 : 218,
  };
  const volumePlot = { top: 190, bottom: 218 };
  const xAxisY = hasVolume ? volumePlot.bottom : plot.bottom;
  const plotWidth = plot.right - plot.left;
  const plotHeight = plot.bottom - plot.top;
  const plotY = (value: number) =>
    plot.bottom - ((value - min) / range) * plotHeight;
  const step = plotWidth / Math.max(plottedBars.length, 1);
  const candleWidth = Math.max(Math.min(step * 0.48, 14), 4);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = min + range * ratio;
    return { value, y: plotY(value) };
  });
  const xTickIndexes = Array.from(
    new Set([
      0,
      Math.max(0, Math.floor((plottedBars.length - 1) / 2)),
      Math.max(0, plottedBars.length - 1),
    ]),
  );
  return {
    candleWidth,
    hasVolume,
    max,
    maxVolume,
    min,
    plot,
    plottedBars,
    plottedMarkers,
    plottedReferenceLines,
    plotY,
    step,
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
