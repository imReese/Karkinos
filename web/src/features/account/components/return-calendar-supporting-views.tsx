import { useState } from 'react';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import { useCopy, type AppCopy } from '../../../shared/i18n/context';
import {
  formatReturnCurrency,
  type ReturnCalendarPosition,
} from './return-calendar-model';

export function ReturnCalendarEmptyState({
  positions,
  copy,
  compact,
}: {
  positions: ReturnCalendarPosition[];
  copy: AppCopy;
  compact: boolean;
}) {
  const totalUnrealizedPnl = positions.reduce(
    (total, position) => total + position.unrealized_pnl,
    0,
  );
  const totalRealizedPnl = positions.reduce(
    (total, position) => total + position.realized_pnl,
    0,
  );
  const totalMarketValue = positions.reduce(
    (total, position) => total + position.market_value,
    0,
  );
  const totalPnl = totalUnrealizedPnl + totalRealizedPnl;
  const rankedPositions = positions
    .slice()
    .sort(
      (left, right) =>
        Math.abs(right.unrealized_pnl + right.realized_pnl) -
        Math.abs(left.unrealized_pnl + left.realized_pnl),
    )
    .slice(0, 4);
  const wrapperClass = compact
    ? 'mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_240px]'
    : 'mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]';

  return (
    <div className={wrapperClass} data-testid="return-calendar-empty-state">
      <div className="min-w-0 rounded-md border border-dashed border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-0)_58%,transparent)] p-3">
        <div className="app-kicker app-type-overline">
          {copy.explainability.currentPositionPnl}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <CalendarFallbackMetric
            label={copy.explainability.netChange}
            value={formatReturnCurrency(totalPnl)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.marketValue}
            value={formatReturnCurrency(totalMarketValue)}
          />
          <CalendarFallbackMetric
            label={copy.explainability.unrealizedPnl}
            value={formatReturnCurrency(totalUnrealizedPnl)}
          />
        </div>
        {rankedPositions.length > 0 ? (
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {rankedPositions.map((position) => {
              const positionPnl =
                position.unrealized_pnl + position.realized_pnl;
              const displayName =
                position.display_name || position.name || position.symbol;
              const assetClass = position.asset_class || '--';
              const assetClassDisplay = formatAssetClassLabel(
                assetClass,
                copy.common,
              );
              return (
                <div
                  key={position.symbol}
                  className="rounded-md border border-[var(--app-border)] px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate font-semibold">
                      {displayName}
                    </span>
                    <span
                      className={
                        positionPnl > 0
                          ? 'text-[var(--app-pnl-positive)]'
                          : positionPnl < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : 'text-[var(--app-pnl-neutral)]'
                      }
                    >
                      {formatReturnCurrency(positionPnl)}
                    </span>
                  </div>
                  <div className="app-muted app-type-micro mt-1 flex items-center gap-2 uppercase">
                    <span>{position.symbol}</span>
                    <span aria-hidden="true">/</span>
                    <span>{assetClassDisplay}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] p-3">
        <div className="app-kicker app-type-overline">
          {copy.explainability.returnCalendarWarmingUp}
        </div>
        <div className="app-muted mt-2 text-sm">
          {copy.explainability.returnCalendarEmptyDetail}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            href="/activity"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.addActivity}
          </a>
          <a
            href="/market"
            className="rounded-full border border-[var(--app-border)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent-border)] hover:text-[var(--app-accent)]"
          >
            {copy.explainability.checkDataSource}
          </a>
        </div>
      </div>
    </div>
  );
}

function CalendarFallbackMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-[var(--app-border)] bg-[color-mix(in_srgb,var(--app-surface-1)_72%,transparent)] px-3 py-2">
      <div className="app-muted app-type-micro">{label}</div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}

export function ReturnCurveChart({
  points,
}: {
  points: Array<{ label: string; value: number }>;
}) {
  const copy = useCopy();
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (points.length === 0) {
    return null;
  }
  const width = 820;
  const height = 420;
  const left = 96;
  const right = 36;
  const top = 30;
  const bottom = 68;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const values = points.map((point) => point.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const range = max - min || 1;
  const positionForPoint = (point: { value: number }, index: number) => {
    const x = left + (index / Math.max(points.length - 1, 1)) * chartWidth;
    const y = top + chartHeight - ((point.value - min) / range) * chartHeight;
    return { x, y };
  };
  const positionedPoints = points.map((point, index) => ({
    ...point,
    ...positionForPoint(point, index),
  }));
  const line = positionedPoints
    .map((point) => `${point.x},${point.y}`)
    .join(' ');
  const ticks = Array.from(new Set(max === min ? [max] : [max, 0, min]));
  const zeroY = top + chartHeight - ((0 - min) / range) * chartHeight;
  const firstLabel = points[0]?.label ?? '';
  const lastLabel = points[points.length - 1]?.label ?? firstLabel;
  const activePoint =
    activeIndex === null ? null : (positionedPoints[activeIndex] ?? null);
  const tooltipX = activePoint
    ? Math.min(Math.max(activePoint.x + 12, left), width - 184)
    : 0;
  const tooltipY = activePoint ? Math.max(top + 6, activePoint.y - 54) : 0;

  return (
    <div
      aria-label={copy.explainability.curveView}
      className="max-w-full overflow-x-auto overscroll-x-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
      data-testid="return-curve-chart-scroll"
      role="region"
      tabIndex={0}
    >
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="block h-[360px] w-full min-w-[720px] sm:h-[420px] sm:min-w-0"
        data-testid="return-curve-chart"
      >
        <line
          data-testid="return-curve-y-axis"
          x1={left}
          y1={top}
          x2={left}
          y2={top + chartHeight}
          stroke="currentColor"
          strokeOpacity="0.48"
          strokeWidth="1.2"
        />
        <line
          data-testid="return-curve-x-axis"
          x1={left}
          y1={top + chartHeight}
          x2={left + chartWidth}
          y2={top + chartHeight}
          stroke="currentColor"
          strokeOpacity="0.48"
          strokeWidth="1.2"
        />
        <line
          data-testid="return-curve-zero-axis"
          x1={left}
          y1={zeroY}
          x2={left + chartWidth}
          y2={zeroY}
          stroke="currentColor"
          strokeDasharray="4 5"
          strokeOpacity="0.34"
          strokeWidth="1.2"
        />
        {ticks.map((tick) => {
          const y = top + chartHeight - ((tick - min) / range) * chartHeight;
          return (
            <g key={tick}>
              <line
                x1={left}
                y1={y}
                x2={left + chartWidth}
                y2={y}
                stroke="currentColor"
                strokeOpacity="0.16"
              />
              <text
                x={left - 10}
                y={y + 5}
                textAnchor="end"
                className="app-type-compact fill-current font-semibold opacity-85"
              >
                {formatReturnCurrency(tick)}
              </text>
            </g>
          );
        })}
        <text
          x={left}
          y={height - 16}
          textAnchor="start"
          className="app-type-compact fill-current font-semibold opacity-85"
        >
          {firstLabel}
        </text>
        <text
          x={left + chartWidth}
          y={height - 16}
          textAnchor="end"
          className="app-type-compact fill-current font-semibold opacity-85"
        >
          {lastLabel}
        </text>
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="4"
          points={line}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {positionedPoints.map((point, index) => (
          <circle
            key={point.label}
            cx={point.x}
            cy={point.y}
            r={activeIndex === index ? 6 : 4}
            tabIndex={0}
            role="img"
            aria-label={`${point.label} · ${formatReturnCurrency(point.value)}`}
            data-testid={`return-curve-point-${index}`}
            fill="var(--app-text)"
            stroke="var(--app-mantle)"
            strokeWidth="2.4"
            opacity={activeIndex === null || activeIndex === index ? 1 : 0.56}
            onClick={() => setActiveIndex(index)}
            onFocus={() => setActiveIndex(index)}
            onBlur={() => setActiveIndex(null)}
            onPointerEnter={() => setActiveIndex(index)}
            onPointerMove={() => setActiveIndex(index)}
            onPointerLeave={() => setActiveIndex(null)}
            onMouseEnter={() => setActiveIndex(index)}
            onMouseLeave={() => setActiveIndex(null)}
          />
        ))}
        {activePoint ? (
          <g data-testid="return-curve-tooltip">
            <rect
              x={tooltipX}
              y={tooltipY}
              width="162"
              height="46"
              rx="10"
              fill="var(--app-panel-strong)"
              stroke="var(--app-border)"
              opacity="0.98"
            />
            <text
              x={tooltipX + 12}
              y={tooltipY + 18}
              className="app-type-label fill-current font-semibold"
            >
              {activePoint.label}
            </text>
            <text
              x={tooltipX + 12}
              y={tooltipY + 36}
              className="app-type-compact fill-current font-bold"
            >
              {formatReturnCurrency(activePoint.value)}
            </text>
          </g>
        ) : null}
      </svg>
    </div>
  );
}
