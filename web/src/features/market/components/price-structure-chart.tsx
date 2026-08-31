import { useEffect, useMemo, useRef, useState } from 'react';

import {
  buildPriceStructureChartModel,
  DEFAULT_RANGE_LABELS,
  type KlineRangeKey,
  type PriceStructureChartProps,
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
}: PriceStructureChartProps) {
  const [selectedRange, setSelectedRange] = useState<KlineRangeKey>('all');
  const model = useMemo(
    () =>
      buildPriceStructureChartModel({
        bars,
        markers,
        referenceLines,
        selectedRange,
      }),
    [bars, markers, referenceLines, selectedRange],
  );
  const chartScrollRef = useRef<HTMLDivElement>(null);
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
      model={model}
      onRangeChange={setSelectedRange}
      priceLabel={priceLabel}
      rangeAriaLabel={rangeAriaLabel}
      rangeLabels={rangeLabels}
      selectedRange={selectedRange}
      titleLabel={titleLabel}
    />
  );
}
