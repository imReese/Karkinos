import { formatCurrency } from '../../../shared/format';
import {
  formatDateTick,
  toFiniteNumber,
  type KlineAxisLabels,
  type KlineRangeKey,
  type PriceStructureChartModel,
} from './price-structure-chart-model';

export function PriceStructureChartSvg({
  axisLabels,
  model,
  priceLabel,
  selectedRange,
  titleLabel,
}: {
  axisLabels: KlineAxisLabels;
  model: PriceStructureChartModel;
  priceLabel: string;
  selectedRange: KlineRangeKey;
  titleLabel: string;
}) {
  const {
    candleWidth,
    hasVolume,
    maxVolume,
    plot,
    plottedBars,
    plottedMarkers,
    plottedReferenceLines,
    plotY,
    step,
    volumes,
    volumePlot,
    xAxisY,
    xTickIndexes,
    yTicks,
  } = model;
  return (
    <svg
      key={selectedRange}
      viewBox="0 0 640 246"
      className="app-chart-stage h-64 w-full overflow-visible text-[var(--app-soft)] sm:h-80 xl:h-[21rem]"
      role="img"
      aria-label={`${titleLabel} · ${axisLabels.price} · ${axisLabels.date}`}
    >
      <desc>
        {`${priceLabel} · ${axisLabels.price} · ${axisLabels.date}${
          hasVolume ? ` · ${axisLabels.volume ?? 'Volume'}` : ''
        }`}
      </desc>
      <line
        x1={plot.left}
        x2={plot.left}
        y1={plot.top}
        y2={xAxisY}
        stroke="currentColor"
        strokeOpacity="0.22"
      />
      <line
        x1={plot.left}
        x2={plot.right}
        y1={xAxisY}
        y2={xAxisY}
        stroke="currentColor"
        strokeOpacity="0.22"
      />
      {yTicks.map((tick) => (
        <g key={tick.value}>
          <line
            x1={plot.left}
            x2={plot.right}
            y1={tick.y}
            y2={tick.y}
            stroke="currentColor"
            strokeOpacity="0.08"
          />
          <text
            x={plot.left - 8}
            y={tick.y + 4}
            textAnchor="end"
            className="fill-current text-[length:var(--app-font-size-micro)] tabular-nums"
          >
            {formatCurrency(tick.value)}
          </text>
        </g>
      ))}
      {plottedReferenceLines.map((line) => {
        const tone =
          line.tone === 'broker' ? 'var(--app-warning)' : 'var(--app-accent)';
        return (
          <g
            key={`${line.label}-${line.value}`}
            data-testid="kline-reference-line"
          >
            <title>{line.label}</title>
            <line
              x1={plot.left}
              x2={plot.right}
              y1={plotY(line.value)}
              y2={plotY(line.value)}
              stroke={tone}
              strokeDasharray={line.tone === 'broker' ? '3 3' : '7 4'}
              strokeOpacity="0.8"
              strokeWidth="1.2"
            />
          </g>
        );
      })}
      {xTickIndexes.map((index) => {
        const bar = plottedBars[index];
        const x = plot.left + step * index + step / 2;
        const textAnchor =
          index === 0
            ? 'start'
            : index === plottedBars.length - 1
              ? 'end'
              : 'middle';
        return (
          <g key={`${bar.timestamp ?? index}-tick`}>
            <line
              x1={x}
              x2={x}
              y1={xAxisY}
              y2={xAxisY + 5}
              stroke="currentColor"
              strokeOpacity="0.22"
            />
            <text
              x={x}
              y={xAxisY + 20}
              textAnchor={textAnchor}
              className="fill-current text-[length:var(--app-font-size-micro)] tabular-nums"
            >
              {formatDateTick(bar.timestamp, index)}
            </text>
          </g>
        );
      })}
      {plottedBars.map((bar, index) => {
        const open = toFiniteNumber(bar.open) ?? bar.close;
        const high = toFiniteNumber(bar.high) ?? Math.max(open, bar.close);
        const low = toFiniteNumber(bar.low) ?? Math.min(open, bar.close);
        const x = plot.left + step * index + step / 2;
        const openY = plotY(open);
        const closeY = plotY(bar.close);
        const topY = Math.min(openY, closeY);
        const height = Math.max(Math.abs(openY - closeY), 2);
        const tone =
          bar.close >= open
            ? 'var(--app-pnl-positive)'
            : 'var(--app-pnl-negative)';
        return (
          <g
            key={`${bar.timestamp ?? index}-${bar.close}`}
            data-testid="kline-candle"
          >
            <line
              x1={x}
              x2={x}
              y1={plotY(high)}
              y2={plotY(low)}
              stroke={tone}
              strokeOpacity="0.9"
              strokeWidth="1.4"
            />
            <rect
              x={x - candleWidth / 2}
              y={topY}
              width={candleWidth}
              height={height}
              rx="1"
              fill={tone}
              fillOpacity={bar.close >= open ? '0.18' : '0.34'}
              stroke={tone}
              strokeWidth="1.5"
            />
          </g>
        );
      })}
      {hasVolume ? (
        <g data-testid="kline-volume-series">
          <line
            x1={plot.left}
            x2={plot.right}
            y1={volumePlot.top - 7}
            y2={volumePlot.top - 7}
            stroke="currentColor"
            strokeOpacity="0.08"
          />
          <text
            x={plot.right}
            y={volumePlot.top - 7}
            textAnchor="end"
            className="fill-current text-[length:var(--app-font-size-micro)]"
          >
            {axisLabels.volume ?? 'Volume'}
          </text>
          {volumes.map((volume, index) => {
            if (volume <= 0) {
              return null;
            }
            const x = plot.left + step * index + step / 2;
            const height = Math.max(
              1,
              (volume / maxVolume) * (volumePlot.bottom - volumePlot.top),
            );
            return (
              <rect
                key={`${plottedBars[index]?.timestamp ?? index}-volume`}
                data-testid="kline-volume-bar"
                x={x - candleWidth / 2}
                y={volumePlot.bottom - height}
                width={candleWidth}
                height={height}
                rx="0.75"
                fill="var(--app-chart-label)"
                fillOpacity="0.24"
              />
            );
          })}
        </g>
      ) : null}
      {plottedMarkers.map((marker, index) => {
        const x = plot.left + step * marker.barIndex + step / 2;
        const y = plotY(marker.price);
        const isBuy = marker.kind === 'buy';
        const tone = isBuy ? 'var(--app-chart-buy)' : 'var(--app-chart-sell)';
        return (
          <g
            key={`${marker.timestamp}-${marker.kind}-${index}`}
            data-testid={`kline-trade-marker-${marker.kind}`}
          >
            <title>{marker.label}</title>
            <circle
              cx={x}
              cy={y}
              r="5.5"
              fill="var(--app-panel-strong)"
              stroke={tone}
              strokeWidth="2"
            />
            <text
              x={x}
              y={y + 3}
              textAnchor="middle"
              fill={tone}
              className="text-[length:var(--app-font-size-micro)] font-bold"
            >
              {isBuy ? 'B' : 'S'}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
