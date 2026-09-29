import { useState, type RefObject } from 'react';

import {
  formatAmount,
  formatCompactNumber,
  formatCurrency,
} from '../../../shared/format';
import { EvidenceState } from '../../../shared/ui/workbench';
import {
  formatDateTick,
  type KlineAxisLabels,
  type KlineRangeKey,
  type KlineRangeLabels,
  type PriceStructureChartModel,
  type PriceStructureChartType,
  type PriceStructureChartTypeLabels,
} from './price-structure-chart-model';
import {
  PriceStructureChartTypeControls,
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
  chartType,
  chartTypeAriaLabel,
  chartTypeLabels,
  model,
  onChartTypeChange,
  onRangeChange,
  priceLabel,
  rangeAriaLabel,
  rangeLabels,
  selectedRange,
  titleLabel,
}: {
  axisLabels: KlineAxisLabels;
  chartScrollRef: RefObject<HTMLDivElement | null>;
  chartType: PriceStructureChartType;
  chartTypeAriaLabel?: (label: string) => string;
  chartTypeLabels: PriceStructureChartTypeLabels;
  model: PriceStructureChartModel;
  onChartTypeChange: (type: PriceStructureChartType) => void;
  onRangeChange: (range: KlineRangeKey) => void;
  priceLabel: string;
  rangeAriaLabel: (label: string) => string;
  rangeLabels: KlineRangeLabels;
  selectedRange: KlineRangeKey;
  titleLabel: string;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [showMovingAverages, setShowMovingAverages] = useState(true);
  const [visiblePeriods, setVisiblePeriods] = useState<number[]>([
    5, 10, 20, 60,
  ]);

  const handleTogglePeriod = (period: number) => {
    setVisiblePeriods((prev) =>
      prev.includes(period)
        ? prev.filter((p) => p !== period)
        : [...prev, period],
    );
  };

  const activeIndex =
    hoverIndex !== null &&
    hoverIndex >= 0 &&
    hoverIndex < model.plottedBars.length
      ? hoverIndex
      : model.plottedBars.length - 1;

  const activeBar =
    activeIndex >= 0 && activeIndex < model.plottedBars.length
      ? model.plottedBars[activeIndex]
      : null;

  return (
    <div
      className="min-w-0 border-y border-[var(--app-divider)] py-3"
      aria-label={titleLabel}
    >
      <div className="mb-4 flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="app-kicker app-type-overline">{titleLabel}</div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 sm:gap-3">
          <PriceStructureChartTypeControls
            chartType={chartType}
            labels={chartTypeLabels}
            onChartTypeChange={onChartTypeChange}
            chartTypeAriaLabel={chartTypeAriaLabel}
          />
          <PriceStructureRangeControls
            labels={rangeLabels}
            onRangeChange={onRangeChange}
            rangeAriaLabel={rangeAriaLabel}
            selectedRange={selectedRange}
            titleLabel={titleLabel}
          />
        </div>
      </div>
      <div
        ref={chartScrollRef}
        data-testid="price-structure-chart-scroll"
        className="app-horizontal-scroll-cue min-w-0 max-w-full overflow-x-auto overscroll-x-contain pb-2"
      >
        <div
          data-testid="price-structure-chart-canvas"
          className="min-w-[720px] w-full"
        >
          {activeBar ? (
            <div
              data-testid={
                hoverIndex !== null ? 'kline-crosshair-hud' : 'kline-latest-hud'
              }
              className="app-type-micro mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-raised)_70%,transparent)] px-2.5 py-1 font-mono tabular-nums text-[var(--app-text-secondary)]"
            >
              <span className="font-medium text-[var(--app-text)]">
                {formatDateTick(activeBar.timestamp, activeIndex)}
              </span>
              <span>
                <span className="text-[var(--app-muted)]">O</span>{' '}
                {formatAmount(activeBar.open ?? activeBar.close)}
              </span>
              <span>
                <span className="text-[var(--app-muted)]">H</span>{' '}
                {formatAmount(
                  activeBar.high ??
                    Math.max(
                      activeBar.open ?? activeBar.close,
                      activeBar.close,
                    ),
                )}
              </span>
              <span>
                <span className="text-[var(--app-muted)]">L</span>{' '}
                {formatAmount(
                  activeBar.low ??
                    Math.min(
                      activeBar.open ?? activeBar.close,
                      activeBar.close,
                    ),
                )}
              </span>
              <span>
                <span className="text-[var(--app-muted)]">C</span>{' '}
                {formatAmount(activeBar.close)}
              </span>
              {activeBar.volume ? (
                <span>
                  <span className="text-[var(--app-muted)]">V</span>{' '}
                  {formatCompactNumber(activeBar.volume)}
                </span>
              ) : null}
              {showMovingAverages &&
                model.maSeries
                  .filter((s) => visiblePeriods.includes(s.period))
                  .map((s) => {
                    const val = s.values[activeIndex];
                    return val !== null ? (
                      <span key={s.period} style={{ color: s.color }}>
                        {s.label} {formatAmount(val)}
                      </span>
                    ) : null;
                  })}
            </div>
          ) : null}
          <PriceStructureChartSvg
            axisLabels={axisLabels}
            model={model}
            priceLabel={priceLabel}
            selectedRange={selectedRange}
            titleLabel={titleLabel}
            hoverIndex={hoverIndex}
            onHoverIndexChange={setHoverIndex}
            showMovingAverages={showMovingAverages}
            visiblePeriods={visiblePeriods}
          />
          <div className="app-type-micro mt-2 flex flex-col gap-1 font-mono tabular-nums text-[var(--app-muted)] sm:flex-row sm:items-center sm:justify-between">
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
          <PriceStructureLegend
            model={model}
            showMovingAverages={showMovingAverages}
            onToggleMovingAverages={() =>
              setShowMovingAverages((prev) => !prev)
            }
            visiblePeriods={visiblePeriods}
            onTogglePeriod={handleTogglePeriod}
          />
        </div>
      </div>
    </div>
  );
}
