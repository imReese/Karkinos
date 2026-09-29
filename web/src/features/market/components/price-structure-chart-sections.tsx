import {
  KLINE_RANGES,
  type KlineRangeKey,
  type KlineRangeLabels,
  type PriceStructureChartModel,
  type PriceStructureChartType,
  type PriceStructureChartTypeLabels,
} from './price-structure-chart-model';

export function PriceStructureChartTypeControls({
  chartType,
  labels,
  onChartTypeChange,
  chartTypeAriaLabel,
}: {
  chartType: PriceStructureChartType;
  labels: PriceStructureChartTypeLabels;
  onChartTypeChange: (type: PriceStructureChartType) => void;
  chartTypeAriaLabel?: (label: string) => string;
}) {
  const types: PriceStructureChartType[] = ['line', 'candlestick'];
  return (
    <div
      className="inline-flex rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-overlay)_60%,transparent)] p-0.5"
      role="group"
      aria-label="Chart view type"
    >
      {types.map((type) => {
        const selected = chartType === type;
        const label = labels[type];
        return (
          <button
            key={type}
            type="button"
            data-testid={`chart-type-toggle-${type}`}
            className={`app-type-micro rounded-[calc(var(--app-radius-control)-2px)] px-2.5 py-1 font-semibold transition-colors ${
              selected
                ? 'border border-[color-mix(in_srgb,var(--app-accent)_50%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_20%,transparent)] text-[var(--app-text)] shadow-xs'
                : 'border border-transparent text-[var(--app-muted)] hover:text-[var(--app-soft)]'
            }`}
            aria-pressed={selected}
            aria-label={
              chartTypeAriaLabel
                ? chartTypeAriaLabel(label)
                : `Show ${label} view`
            }
            onClick={() => onChartTypeChange(type)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function PriceStructureRangeControls({
  labels,
  onRangeChange,
  rangeAriaLabel,
  selectedRange,
  titleLabel,
}: {
  labels: KlineRangeLabels;
  onRangeChange: (range: KlineRangeKey) => void;
  rangeAriaLabel: (label: string) => string;
  selectedRange: KlineRangeKey;
  titleLabel: string;
}) {
  return (
    <div
      className="flex min-w-0 flex-wrap gap-2"
      role="group"
      aria-label={titleLabel}
    >
      {KLINE_RANGES.map((rangeOption) => {
        const label = labels[rangeOption.key];
        const selected = selectedRange === rangeOption.key;
        return (
          <button
            key={rangeOption.key}
            type="button"
            className={`app-chart-control app-type-micro rounded-[var(--app-radius-control)] border px-3 py-1.5 font-semibold ${
              selected
                ? 'border-[color-mix(in_srgb,var(--app-accent)_58%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_16%,transparent)] text-[var(--app-text)]'
                : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] text-[var(--app-muted)] hover:border-[color-mix(in_srgb,var(--app-accent)_34%,transparent)] hover:text-[var(--app-soft)]'
            }`}
            aria-pressed={selected}
            aria-label={rangeAriaLabel(label)}
            onClick={() => onRangeChange(rangeOption.key)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

export function PriceStructureLegend({
  model,
  showMovingAverages = true,
  onToggleMovingAverages,
  visiblePeriods = [5, 10, 20, 60],
  onTogglePeriod,
}: {
  model: PriceStructureChartModel;
  showMovingAverages?: boolean;
  onToggleMovingAverages?: () => void;
  visiblePeriods?: number[];
  onTogglePeriod?: (period: number) => void;
}) {
  const { chartType, maSeries, plottedMarkers, plottedReferenceLines } = model;
  const hasCandlestick = chartType === 'candlestick';
  const hasMarkersOrLines =
    plottedMarkers.length > 0 || plottedReferenceLines.length > 0;
  if (!hasMarkersOrLines && !hasCandlestick) {
    return null;
  }
  return (
    <div className="mt-3 flex min-w-0 flex-wrap items-center gap-2 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-muted)]">
      {hasCandlestick && onToggleMovingAverages ? (
        <button
          type="button"
          data-testid="chart-ma-toggle"
          aria-pressed={showMovingAverages}
          onClick={onToggleMovingAverages}
          className={`app-type-micro rounded-[var(--app-radius-control)] border px-2 py-0.5 font-semibold transition-colors ${
            showMovingAverages
              ? 'border-[color-mix(in_srgb,var(--app-accent)_50%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_16%,transparent)] text-[var(--app-text)]'
              : 'border-[var(--app-border)] text-[var(--app-muted)] opacity-60'
          }`}
        >
          MA
        </button>
      ) : null}
      {hasCandlestick && showMovingAverages
        ? maSeries.map((s) => {
            const isPeriodActive = visiblePeriods.includes(s.period);
            if (onTogglePeriod) {
              return (
                <button
                  key={s.label}
                  type="button"
                  data-testid={`chart-ma-pill-${s.period}`}
                  aria-pressed={isPeriodActive}
                  onClick={() => onTogglePeriod(s.period)}
                  aria-label={`Toggle ${s.label}`}
                  className={`app-type-micro inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono font-medium transition-colors ${
                    isPeriodActive
                      ? 'border-current bg-[color-mix(in_srgb,var(--app-surface-raised)_70%,transparent)]'
                      : 'border-[color-mix(in_srgb,var(--app-border)_40%,transparent)] text-[var(--app-muted)] opacity-50 line-through'
                  }`}
                  style={{ color: isPeriodActive ? s.color : undefined }}
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: isPeriodActive
                        ? s.color
                        : 'var(--app-muted)',
                    }}
                  />
                  {s.label}
                </button>
              );
            }
            return (
              <span
                key={s.label}
                style={{ color: s.color }}
                className="flex items-center gap-1 font-mono"
              >
                <span
                  className="inline-block h-1 w-2.5 rounded-full"
                  style={{ backgroundColor: s.color }}
                />
                {s.label}
              </span>
            );
          })
        : null}
      {plottedMarkers.some((marker) => marker.kind === 'buy') ? (
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-chart-buy)_42%,transparent)] px-2 py-0.5 text-[var(--app-chart-buy)]">
          B · {plottedMarkers.find((marker) => marker.kind === 'buy')?.label}
        </span>
      ) : null}
      {plottedMarkers.some((marker) => marker.kind === 'sell') ? (
        <span className="rounded-full border border-[color-mix(in_srgb,var(--app-chart-sell)_42%,transparent)] px-2 py-0.5 text-[var(--app-chart-sell)]">
          S · {plottedMarkers.find((marker) => marker.kind === 'sell')?.label}
        </span>
      ) : null}
      {plottedReferenceLines.map((line) => (
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
  );
}
