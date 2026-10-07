import { useId, useMemo, useState } from 'react';

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceDot,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useCopy } from '../../../shared/i18n/context';
import {
  EvidenceState,
  ResponsiveChartFrame,
} from '../../../shared/ui/workbench';
import {
  formatCompactNumber,
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatPublicCode } from '../../../shared/public-labels';
import { usePreferences } from '../../../shared/preferences/context';
import type { BacktestEquityPoint, BacktestFill } from '../api';

type ChartPoint = BacktestEquityPoint & {
  timestampMs: number;
  drawdown: number;
};

type FillMarker = BacktestFill & {
  timestampMs: number;
  equity: number;
  sideLabel: string;
};

function toChartPoints(points: BacktestEquityPoint[]): ChartPoint[] {
  let peak = Number.NEGATIVE_INFINITY;
  return points.map((point) => {
    peak = Math.max(peak, point.equity);
    return {
      ...point,
      timestampMs: new Date(point.timestamp).getTime(),
      drawdown: peak > 0 ? (point.equity - peak) / peak : 0,
    };
  });
}

function formatDate(timestampMs: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(timestampMs);
}

function formatAxisCurrency(value: number) {
  return formatCompactNumber(value);
}

function nearestEquity(points: ChartPoint[], timestampMs: number) {
  if (points.length === 0) {
    return 0;
  }
  return points.reduce((closest, point) =>
    Math.abs(point.timestampMs - timestampMs) <
    Math.abs(closest.timestampMs - timestampMs)
      ? point
      : closest,
  ).equity;
}

function toFillMarkers(
  fills: BacktestFill[],
  points: ChartPoint[],
  locale: 'en' | 'zh',
): FillMarker[] {
  return fills
    .map((fill) => {
      const timestampMs = fill.timestamp
        ? new Date(fill.timestamp).getTime()
        : Number.NaN;
      return {
        ...fill,
        timestampMs,
        equity: nearestEquity(points, timestampMs),
        sideLabel: formatPublicCode(fill.side, locale),
      };
    })
    .filter((marker) => Number.isFinite(marker.timestampMs));
}

function EquityTooltip({
  active,
  payload,
  markers = [],
}: {
  active?: boolean;
  payload?: Array<{ payload?: ChartPoint }>;
  markers?: FillMarker[];
}) {
  const labels = useCopy().backtest.chart;
  const point = payload?.[0]?.payload;
  if (!active || !point) {
    return null;
  }

  const matchingFills = markers.filter(
    (m) => Math.abs(m.timestampMs - point.timestampMs) < 86_400_000,
  );

  return (
    <div className="rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] px-3 py-2 text-xs shadow-[var(--app-shadow-overlay)]">
      <div className="font-medium">{formatTimestamp(point.timestamp)}</div>
      <div className="mt-2 grid gap-1 tabular-nums">
        <div>{formatCurrency(point.equity)}</div>
        <div className="text-[var(--app-pnl-negative)]">
          {labels.drawdown} {formatPercent(point.drawdown)}
        </div>
      </div>
      {matchingFills.length > 0 ? (
        <div className="mt-2 border-t border-[var(--app-divider)] pt-1.5 space-y-1">
          <div className="app-type-micro font-semibold text-[var(--app-text-secondary)]">
            {labels.markersTitle} ({matchingFills.length})
          </div>
          {matchingFills.slice(0, 3).map((marker, i) => (
            <div
              key={`${marker.fill_id ?? marker.order_id ?? marker.symbol}-${i}`}
              className="flex items-center gap-1.5 font-mono app-type-micro tabular-nums"
            >
              <span
                className={`rounded px-1 font-semibold ${
                  marker.side === 'buy'
                    ? 'bg-[color-mix(in_srgb,var(--app-chart-buy)_12%,transparent)] text-[var(--app-chart-buy)]'
                    : 'bg-[color-mix(in_srgb,var(--app-chart-sell)_12%,transparent)] text-[var(--app-chart-sell)]'
                }`}
              >
                {marker.sideLabel}
              </span>
              <span className="font-semibold text-[var(--app-text)]">
                {marker.symbol}
              </span>
              <span>{formatPrice(marker.fill_price)}</span>
              <span className="text-[var(--app-text-tertiary)]">
                ({formatQuantity(marker.fill_quantity)})
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function EquityDrawdownChart({
  fills = [],
  points,
}: {
  fills?: BacktestFill[];
  points: BacktestEquityPoint[];
}) {
  const labels = useCopy().backtest.chart;
  const { locale } = usePreferences();
  const data = toChartPoints(points);
  const fillMarkers = toFillMarkers(fills, data, locale);
  const chartId = useId().replace(/:/g, '');
  const equityGradientId = `backtest-equity-${chartId}`;
  const drawdownGradientId = `backtest-drawdown-${chartId}`;

  const [markerFilter, setMarkerFilter] = useState<
    'all' | 'buy' | 'sell' | 'none'
  >('all');
  const buyCount = fillMarkers.filter((m) => m.side === 'buy').length;
  const sellCount = fillMarkers.filter((m) => m.side === 'sell').length;

  const visibleMarkers = useMemo(() => {
    if (markerFilter === 'none') return [];
    if (markerFilter === 'buy')
      return fillMarkers.filter((m) => m.side === 'buy');
    if (markerFilter === 'sell')
      return fillMarkers.filter((m) => m.side === 'sell');
    return fillMarkers;
  }, [fillMarkers, markerFilter]);

  if (data.length === 0) {
    return (
      <EvidenceState
        kind="empty"
        title={labels.title}
        description={labels.empty}
      />
    );
  }

  return (
    <section
      data-backtest-report-section="equity-drawdown"
      className="min-w-0 border-t border-[var(--app-divider)] pt-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-kicker app-type-overline">{labels.kicker}</div>
          <h3 className="app-type-subsection-title mt-1 text-[var(--app-text)]">
            {labels.title}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {fillMarkers.length > 0 ? (
            <div
              data-testid="backtest-marker-filter-controls"
              className="flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-0.5 text-xs"
            >
              <button
                type="button"
                onClick={() => setMarkerFilter('all')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  markerFilter === 'all'
                    ? 'bg-[var(--app-accent)] text-white'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                {locale === 'zh' ? '全部' : 'All'} ({fillMarkers.length})
              </button>
              <button
                type="button"
                onClick={() => setMarkerFilter('buy')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  markerFilter === 'buy'
                    ? 'bg-[var(--app-chart-buy)] text-white'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                {locale === 'zh' ? '买入' : 'Buy'} ({buyCount})
              </button>
              <button
                type="button"
                onClick={() => setMarkerFilter('sell')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  markerFilter === 'sell'
                    ? 'bg-[var(--app-chart-sell)] text-white'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                {locale === 'zh' ? '卖出' : 'Sell'} ({sellCount})
              </button>
              <button
                type="button"
                onClick={() => setMarkerFilter('none')}
                className={`rounded px-2 py-0.5 font-medium transition-colors ${
                  markerFilter === 'none'
                    ? 'bg-[var(--app-surface)] text-[var(--app-text)] font-semibold'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
              >
                {locale === 'zh' ? '隐藏' : 'Hide'}
              </button>
            </div>
          ) : null}
          <div className="app-muted text-xs tabular-nums">
            {labels.points(data.length)}
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-4">
        <ResponsiveChartFrame
          ariaLabel={`${labels.title}. ${labels.points(data.length)}. ${labels.markersCount(fillMarkers.length)}.`}
          className="h-[320px] border-y border-[var(--app-divider)] bg-transparent"
          testId="backtest-equity-chart-frame"
        >
          {({ height, width }) => (
            <AreaChart
              accessibilityLayer
              baseValue="dataMin"
              className="app-chart-stage"
              data={data}
              height={height}
              margin={{ top: 18, right: 18, bottom: 8, left: 8 }}
              width={width}
            >
              <defs>
                <linearGradient
                  id={equityGradientId}
                  x1="0"
                  x2="0"
                  y1="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor="var(--app-accent)"
                    stopOpacity={0.2}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--app-accent)"
                    stopOpacity={0.015}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--app-chart-grid)" vertical={false} />
              <XAxis
                dataKey="timestampMs"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickFormatter={formatDate}
                tickLine={false}
                axisLine={false}
                minTickGap={30}
                stroke="var(--app-chart-label)"
                fontSize={12}
              />
              <YAxis
                tickFormatter={formatAxisCurrency}
                tickLine={false}
                axisLine={false}
                width={56}
                stroke="var(--app-chart-label)"
                fontSize={12}
              />
              <Tooltip content={<EquityTooltip markers={fillMarkers} />} />
              {visibleMarkers.map((marker, index) => (
                <ReferenceDot
                  fill={
                    marker.side === 'buy'
                      ? 'var(--app-chart-buy)'
                      : 'var(--app-chart-sell)'
                  }
                  ifOverflow="extendDomain"
                  key={`${marker.fill_id ?? marker.order_id ?? marker.symbol}-${index}`}
                  r={5}
                  stroke="var(--app-bg)"
                  strokeWidth={2}
                  x={marker.timestampMs}
                  y={marker.equity}
                />
              ))}
              <Area
                type="monotone"
                dataKey="equity"
                stroke="var(--app-accent)"
                strokeWidth={2.25}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill={`url(#${equityGradientId})`}
                dot={false}
                activeDot={{
                  fill: 'var(--app-accent)',
                  r: 4,
                  stroke: 'var(--app-bg)',
                  strokeWidth: 2,
                }}
                isAnimationActive={false}
              />
            </AreaChart>
          )}
        </ResponsiveChartFrame>

        {fillMarkers.length > 0 ? (
          <div className="border-t border-[var(--app-divider)] pt-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="app-kicker app-type-overline">
                  {labels.markersKicker}
                </div>
                <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
                  {labels.markersTitle}
                </div>
              </div>
              <div className="app-muted text-xs tabular-nums">
                {labels.markersCount(fillMarkers.length)}
              </div>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {visibleMarkers.slice(0, 6).map((marker, index) => (
                <div
                  className="min-w-0 border-l border-[var(--app-divider)] py-1 pl-3 text-xs"
                  key={`${marker.fill_id ?? marker.order_id ?? marker.symbol}-${index}-summary`}
                >
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <span
                      className={`font-semibold ${
                        marker.side === 'buy'
                          ? 'text-[var(--app-chart-buy)]'
                          : 'text-[var(--app-chart-sell)]'
                      }`}
                    >
                      {marker.sideLabel} · {marker.symbol}
                    </span>
                    <span className="tabular-nums text-[var(--app-text)]">
                      {formatPrice(marker.fill_price)}
                    </span>
                  </div>
                  <div className="app-muted mt-1 flex flex-wrap gap-x-3 gap-y-1 tabular-nums">
                    <span>{formatTimestamp(marker.timestamp ?? '')}</span>
                    <span>
                      {labels.markerQuantity}{' '}
                      {formatQuantity(marker.fill_quantity)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <ResponsiveChartFrame
          ariaLabel={`${labels.drawdown}. ${labels.points(data.length)}.`}
          className="h-[150px] border-y border-[var(--app-divider)] bg-transparent"
          testId="backtest-drawdown-chart-frame"
        >
          {({ height, width }) => (
            <AreaChart
              accessibilityLayer
              className="app-chart-stage"
              data={data}
              height={height}
              margin={{ top: 16, right: 18, bottom: 4, left: 8 }}
              width={width}
            >
              <defs>
                <linearGradient
                  id={drawdownGradientId}
                  x1="0"
                  x2="0"
                  y1="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor="var(--app-pnl-negative)"
                    stopOpacity={0.34}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--app-pnl-negative)"
                    stopOpacity={0.03}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--app-chart-grid)" vertical={false} />
              <XAxis
                dataKey="timestampMs"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickFormatter={formatDate}
                tickLine={false}
                axisLine={false}
                minTickGap={30}
                stroke="var(--app-chart-label)"
                fontSize={12}
              />
              <YAxis
                tickFormatter={(value: number) => formatPercent(value)}
                tickLine={false}
                axisLine={false}
                width={56}
                stroke="var(--app-chart-label)"
                fontSize={12}
              />
              <Tooltip content={<EquityTooltip />} />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="var(--app-pnl-negative)"
                strokeWidth={1.5}
                fill={`url(#${drawdownGradientId})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          )}
        </ResponsiveChartFrame>
      </div>
    </section>
  );
}
