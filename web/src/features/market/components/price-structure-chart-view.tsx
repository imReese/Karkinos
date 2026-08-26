import type { RefObject } from 'react';

import { formatCurrency } from '../../../shared/format';
import { EvidenceState } from '../../../shared/ui/workbench';
import {
  formatDateTick,
  type KlineAxisLabels,
  type KlineRangeKey,
  type KlineRangeLabels,
  type PriceStructureChartModel,
} from './price-structure-chart-model';
import {
  PriceStructureLegend,
  PriceStructureRangeControls,
} from './price-structure-chart-sections';
import { PriceStructureChartSvg } from './price-structure-chart-svg';

export function PriceStructureEmptyView({
  emptyLabel,
  titleLabel,
}: {
  emptyLabel: string;
  titleLabel: string;
}) {
  return (
    <div
      className="border-y border-[var(--app-divider)] py-3"
      aria-label={titleLabel}
    >
      <div className="app-kicker app-type-overline">{titleLabel}</div>
      <EvidenceState className="mt-3" kind="empty" title={emptyLabel} />
    </div>
  );
}

export function PriceStructureChartView({
  axisLabels,
  chartScrollRef,
  model,
  onRangeChange,
  priceLabel,
  rangeAriaLabel,
  rangeLabels,
  selectedRange,
  titleLabel,
}: {
  axisLabels: KlineAxisLabels;
  chartScrollRef: RefObject<HTMLDivElement | null>;
  model: PriceStructureChartModel;
  onRangeChange: (range: KlineRangeKey) => void;
  priceLabel: string;
  rangeAriaLabel: (label: string) => string;
  rangeLabels: KlineRangeLabels;
  selectedRange: KlineRangeKey;
  titleLabel: string;
}) {
  return (
    <div
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
      aria-label={titleLabel}
    >
      <div className="mb-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="app-kicker app-type-overline">{titleLabel}</div>
        <PriceStructureRangeControls
          labels={rangeLabels}
          onRangeChange={onRangeChange}
          rangeAriaLabel={rangeAriaLabel}
          selectedRange={selectedRange}
          titleLabel={titleLabel}
        />
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
          <PriceStructureChartSvg
            axisLabels={axisLabels}
            model={model}
            priceLabel={priceLabel}
            selectedRange={selectedRange}
            titleLabel={titleLabel}
          />
          <div className="app-type-micro mt-2 flex flex-col gap-1 tabular-nums text-[var(--app-muted)] sm:flex-row sm:items-center sm:justify-between">
            <span>
              {formatDateTick(model.plottedBars[0]?.timestamp, 0)} -{' '}
              {formatDateTick(
                model.plottedBars[model.plottedBars.length - 1]?.timestamp,
                model.plottedBars.length - 1,
              )}
            </span>
            <span>
              {formatCurrency(model.min)} - {formatCurrency(model.max)}
            </span>
          </div>
          <PriceStructureLegend model={model} />
        </div>
      </div>
    </div>
  );
}
