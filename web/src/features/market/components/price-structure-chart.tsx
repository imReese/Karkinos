import { useEffect, useMemo, useRef, useState } from 'react';

import {
  buildPriceStructureChartModel,
  DEFAULT_CHART_TYPE_LABELS,
  DEFAULT_RANGE_LABELS,
  type KlineRangeKey,
  type PriceStructureChartProps,
  type PriceStructureChartType,
} from './price-structure-chart-model';
import {
  PriceStructureChartView,
  PriceStructureEmptyView,
} from './price-structure-chart-view';

export { PriceStructureLoadingState } from './price-structure-loading-state';
export type {
  KlineAxisLabels,
  KlineRangeLabels,
  PriceStructureBar,
  PriceStructureChartType,
  PriceStructureChartTypeLabels,
  PriceStructureMarker,
  PriceStructureReferenceLine,
} from './price-structure-chart-model';

function defaultRangeAriaLabel(label: string) {
  return `Show ${label} K-line range`;
}

export function PriceStructureChart({
  bars,
  emptyLabel,
  titleLabel,
  priceLabel,
  rangeLabels = DEFAULT_RANGE_LABELS,
  axisLabels = { price: 'Price axis', date: 'Date axis' },
  rangeAriaLabel = defaultRangeAriaLabel,
  markers = [],
  referenceLines = [],
  initialChartType = 'candlestick',
  chartTypeLabels = DEFAULT_CHART_TYPE_LABELS,
  chartTypeAriaLabel,
}: PriceStructureChartProps) {
  const [selectedRange, setSelectedRange] = useState<KlineRangeKey>('all');
  const [chartType, setChartType] =
    useState<PriceStructureChartType>(initialChartType);
  const chartScrollRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState<number>(0);

  useEffect(() => {
    if (initialChartType) {
      setChartType(initialChartType);
    }
  }, [initialChartType]);

  useEffect(() => {
    const el = chartScrollRef.current;
    if (!el) return;
    const updateSize = () => {
      const w = el.clientWidth;
      if (w > 0) {
        setContainerWidth(w);
      }
    };
    updateSize();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(updateSize);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', updateSize);
    return () => window.removeEventListener('resize', updateSize);
  }, []);

  const chartWidth = Math.max(containerWidth || 720, 720);
  const chartHeight = 280;

  const model = useMemo(
    () =>
      buildPriceStructureChartModel({
        bars,
        chartType,
        markers,
        referenceLines,
        selectedRange,
        width: chartWidth,
        height: chartHeight,
      }),
    [
      bars,
      chartHeight,
      chartType,
      chartWidth,
      markers,
      referenceLines,
      selectedRange,
    ],
  );
  const plottedBarCount = model?.plottedBars.length ?? 0;

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
  }, [plottedBarCount, selectedRange]);

  if (!model) {
    return (
      <PriceStructureEmptyView
        emptyLabel={emptyLabel}
        titleLabel={titleLabel}
      />
    );
  }
  return (
    <PriceStructureChartView
      axisLabels={axisLabels}
      chartScrollRef={chartScrollRef}
      chartType={chartType}
      chartTypeAriaLabel={chartTypeAriaLabel}
      chartTypeLabels={chartTypeLabels}
      model={model}
      onChartTypeChange={setChartType}
      onRangeChange={setSelectedRange}
      priceLabel={priceLabel}
      rangeAriaLabel={rangeAriaLabel}
      rangeLabels={rangeLabels}
      selectedRange={selectedRange}
      titleLabel={titleLabel}
    />
  );
}
