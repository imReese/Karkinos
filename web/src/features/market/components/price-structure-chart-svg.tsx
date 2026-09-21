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
    areaPath,
    candleWidth,
    chartHeight,
    chartType,
    chartWidth,
    hasVolume,
    latestBar,
    latestPoint,
    linePath,
    maxVolume,
    plot,
    plottedBars,
    plottedMarkers,
    plottedReferenceLines,
    plotY,
    step,
    trendTone,
    volumes,
    volumePlot,
    xAxisY,
    xTickIndexes,
    yTicks,
  } = model;
  return (
    <svg
      key={selectedRange}
      viewBox={`0 0 ${chartWidth} ${chartHeight}`}
      preserveAspectRatio="none"
      className="app-chart-stage h-64 w-full overflow-visible text-[var(--app-soft)] sm:h-80 xl:h-[21rem]"
      role="img"
      aria-label={`${titleLabel} · ${axisLabels.price} · ${axisLabels.date}`}
    >
      <defs>
        <linearGradient
          id="price-structure-line-gradient"
          x1="0"
          y1="0"
          x2="0"
          y2="1"
        >
          <stop offset="0%" stopColor={trendTone} stopOpacity="0.28" />
          <stop offset="85%" stopColor={trendTone} stopOpacity="0.04" />
          <stop offset="100%" stopColor={trendTone} stopOpacity="0" />
        </linearGradient>
      </defs>
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
        if (!bar) return null;
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
              y={xAxisY + 18}
              textAnchor={textAnchor}
              className="fill-current text-[length:var(--app-font-size-micro)] tabular-nums"
            >
              {formatDateTick(bar.timestamp, index)}
            </text>
          </g>
        );
      })}
      {latestBar ? (
        <g data-testid="kline-latest-price-indicator">
          <line
            x1={plot.left}
            x2={plot.right}
            y1={plotY(latestBar.close)}
            y2={plotY(latestBar.close)}
            stroke={
              latestBar.close >= (latestBar.open ?? latestBar.close)
                ? 'var(--app-pnl-positive)'
                : 'var(--app-pnl-negative)'
            }
            strokeDasharray="3 3"
            strokeOpacity="0.5"
            strokeWidth="1"
          />
        </g>
      ) : null}
      {chartType === 'line' ? (
        <g data-testid="price-line-series">
          {areaPath ? (
            <path
              d={areaPath}
              fill="url(#price-structure-line-gradient)"
              className="pointer-events-none"
            />
          ) : null}
          {linePath ? (
            <path
              d={linePath}
              data-testid="close-price-trend"
              fill="none"
              stroke={trendTone}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ) : null}
          {latestPoint ? (
            <g data-testid="price-line-latest-dot">
              <circle
                cx={latestPoint.x}
                cy={latestPoint.y}
                r="4"
                fill={trendTone}
                stroke="var(--app-panel-strong)"
                strokeWidth="1.5"
              />
              <circle
                cx={latestPoint.x}
                cy={latestPoint.y}
                r="7"
                fill={trendTone}
                fillOpacity="0.22"
              />
            </g>
          ) : null}
        </g>
      ) : (
        plottedBars.map((bar, index) => {
          const open = toFiniteNumber(bar.open) ?? bar.close;
          const high = toFiniteNumber(bar.high) ?? Math.max(open, bar.close);
          const low = toFiniteNumber(bar.low) ?? Math.min(open, bar.close);
          const x = plot.left + step * index + step / 2;
          const openY = plotY(open);
          const closeY = plotY(bar.close);
          const topY = Math.min(openY, closeY);
          const rawHeight = Math.abs(openY - closeY);
          const isDoji = rawHeight < 1;
          const height = Math.max(rawHeight, 1);
          const isBullish = bar.close >= open;
          const tone = isBullish
            ? 'var(--app-pnl-positive)'
            : 'var(--app-pnl-negative)';
          return (
            <g
              key={`${bar.timestamp ?? index}-${bar.close}`}
              data-testid="kline-candle"
            >
              <line
                x1={Math.round(x)}
                x2={Math.round(x)}
                y1={Math.round(plotY(high))}
                y2={Math.round(plotY(low))}
                stroke={tone}
                strokeOpacity="0.95"
                strokeWidth="1"
              />
              {isDoji ? (
                <line
                  x1={Math.round(x - candleWidth / 2)}
                  x2={Math.round(x + candleWidth / 2)}
                  y1={Math.round(openY)}
                  y2={Math.round(openY)}
                  stroke={tone}
                  strokeWidth="1.5"
                />
              ) : (
                <rect
                  x={Math.round(x - candleWidth / 2)}
                  y={Math.round(topY)}
                  width={candleWidth}
                  height={Math.max(Math.round(height), 1)}
                  fill={tone}
                  fillOpacity={isBullish ? '0.88' : '0.92'}
                  stroke={tone}
                  strokeWidth="1"
                />
              )}
            </g>
          );
        })
      )}
      {hasVolume ? (
        <g data-testid="kline-volume-series">
          <line
            x1={plot.left}
            x2={plot.right}
            y1={volumePlot.top - 6}
            y2={volumePlot.top - 6}
            stroke="currentColor"
            strokeOpacity="0.12"
          />
          <text
            x={plot.right}
            y={volumePlot.top - 6}
            textAnchor="end"
            className="fill-current text-[length:var(--app-font-size-micro)]"
          >
            {axisLabels.volume ?? 'Volume'}
          </text>
          {volumes.map((volume, index) => {
            if (volume <= 0) {
              return null;
            }
            const bar = plottedBars[index];
            const isBullish =
              (bar?.close ?? 0) >= (bar?.open ?? bar?.close ?? 0);
            const volumeTone = isBullish
              ? 'var(--app-pnl-positive)'
              : 'var(--app-pnl-negative)';
            const x = plot.left + step * index + step / 2;
            const height = Math.max(
              1,
              (volume / maxVolume) * (volumePlot.bottom - volumePlot.top),
            );
            return (
              <rect
                key={`${bar?.timestamp ?? index}-volume`}
                data-testid="kline-volume-bar"
                x={Math.round(x - candleWidth / 2)}
                y={Math.round(volumePlot.bottom - height)}
                width={candleWidth}
                height={Math.max(Math.round(height), 1)}
                fill={volumeTone}
                fillOpacity="0.55"
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
