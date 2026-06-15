import { formatCurrency, formatPercent } from '../../../shared/format';

export type PriceStructureBar = {
  timestamp?: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close: number;
  volume?: number | null;
};

export function PriceStructureChart({
  bars,
  emptyLabel,
  titleLabel,
  priceLabel,
}: {
  bars: PriceStructureBar[];
  emptyLabel: string;
  titleLabel: string;
  priceLabel: string;
}) {
  const validBars = bars.filter((bar) => Number.isFinite(bar.close));

  if (validBars.length === 0) {
    return (
      <div
        className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] p-4"
        aria-label={titleLabel}
      >
        <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
          {titleLabel}
        </div>
        <div className="mt-3 flex h-48 items-center justify-center rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] text-sm text-[var(--app-muted)] sm:h-56">
          {emptyLabel}
        </div>
      </div>
    );
  }

  const closes = validBars.map((bar) => bar.close);
  const lows = validBars.map((bar) =>
    Number.isFinite(bar.low ?? NaN) ? Number(bar.low) : bar.close,
  );
  const highs = validBars.map((bar) =>
    Number.isFinite(bar.high ?? NaN) ? Number(bar.high) : bar.close,
  );
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const range = max - min || 1;
  const latest = closes[closes.length - 1] ?? 0;
  const first = closes[0] ?? latest;
  const change = latest - first;
  const changePercent = first === 0 ? 0 : change / first;
  const latestTone =
    change >= 0 ? 'text-[var(--app-success)]' : 'text-[var(--app-danger)]';
  const plotY = (value: number) => 190 - ((value - min) / range) * 160 + 15;
  const step = 640 / Math.max(validBars.length, 1);
  const candleWidth = Math.max(Math.min(step * 0.48, 14), 4);
  const closePoints = validBars
    .map((bar, index) => {
      const x = step * index + step / 2;
      return `${x},${plotY(bar.close)}`;
    })
    .join(' ');

  return (
    <div
      className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] p-4"
      aria-label={titleLabel}
    >
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="app-kicker text-[11px] uppercase tracking-[0.16em]">
            {titleLabel}
          </div>
          <div className="mt-1 font-mono text-2xl font-semibold tabular-nums text-[var(--app-text)]">
            {formatCurrency(latest)}
          </div>
        </div>
        <div className={`font-mono text-sm font-semibold ${latestTone}`}>
          {change >= 0 ? '+' : ''}
          {formatCurrency(change)} · {formatPercent(changePercent)}
        </div>
      </div>
      <svg
        viewBox="0 0 640 220"
        className="h-48 w-full overflow-visible text-[var(--app-soft)] sm:h-56"
        role="img"
        aria-label={`${titleLabel} ${priceLabel}`}
      >
        {[40, 90, 140, 190].map((y) => (
          <line
            key={y}
            x1="0"
            x2="640"
            y1={y}
            y2={y}
            stroke="currentColor"
            strokeOpacity="0.08"
          />
        ))}
        {validBars.map((bar, index) => {
          const open = Number.isFinite(bar.open ?? NaN)
            ? Number(bar.open)
            : bar.close;
          const high = Number.isFinite(bar.high ?? NaN)
            ? Number(bar.high)
            : Math.max(open, bar.close);
          const low = Number.isFinite(bar.low ?? NaN)
            ? Number(bar.low)
            : Math.min(open, bar.close);
          const x = step * index + step / 2;
          const openY = plotY(open);
          const closeY = plotY(bar.close);
          const topY = Math.min(openY, closeY);
          const height = Math.max(Math.abs(openY - closeY), 2);
          const tone =
            bar.close >= open ? 'var(--app-success)' : 'var(--app-danger)';

          return (
            <g key={`${bar.timestamp ?? index}-${bar.close}`}>
              <line
                x1={x}
                x2={x}
                y1={plotY(high)}
                y2={plotY(low)}
                stroke={tone}
                strokeOpacity="0.75"
                strokeWidth="1.5"
              />
              <rect
                x={x - candleWidth / 2}
                y={topY}
                width={candleWidth}
                height={height}
                rx="1.5"
                fill={tone}
                fillOpacity="0.22"
                stroke={tone}
                strokeWidth="1.4"
              />
            </g>
          );
        })}
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          points={closePoints}
          strokeLinejoin="round"
          strokeLinecap="round"
          strokeOpacity="0.9"
        />
      </svg>
      <div className="mt-2 flex items-center justify-between font-mono text-[11px] text-[var(--app-muted)]">
        <span>{formatCurrency(min)}</span>
        <span>{formatCurrency(max)}</span>
      </div>
    </div>
  );
}
