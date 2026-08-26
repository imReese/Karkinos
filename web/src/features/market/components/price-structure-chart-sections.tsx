import {
  KLINE_RANGES,
  type KlineRangeKey,
  type KlineRangeLabels,
  type PriceStructureChartModel,
} from './price-structure-chart-model';

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
}: {
  model: PriceStructureChartModel;
}) {
  const { plottedMarkers, plottedReferenceLines } = model;
  if (plottedMarkers.length === 0 && plottedReferenceLines.length === 0) {
    return null;
  }
  return (
    <div className="mt-3 flex min-w-0 flex-wrap gap-2 text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-muted)]">
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
