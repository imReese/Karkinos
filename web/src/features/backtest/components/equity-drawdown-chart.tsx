import { useId } from 'react';

import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useCopy } from '../../../app/copy';
import {
  EvidenceState,
  ResponsiveChartFrame,
} from '../../../app/components/workbench';
import {
  formatCompactNumber,
  formatCurrency,
  formatPercent,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatPublicCode } from '../../../shared/public-labels';
import { usePreferences } from '../../../app/preferences';
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
}: {
  active?: boolean;
  payload?: Array<{ payload?: ChartPoint }>;
}) {
  const labels = useCopy().backtest.chart;
  const point = payload?.[0]?.payload;
  if (!active || !point) {
    return null;
  }

  return (
    <div className="rounded-[var(--app-radius-overlay)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] px-3 py-2 text-xs shadow-[var(--app-shadow-overlay)]">
      <div className="font-medium">{formatTimestamp(point.timestamp)}</div>
      <div className="mt-2 grid gap-1 tabular-nums">
        <div>{formatCurrency(point.equity)}</div>
        <div className="text-[var(--app-pnl-negative)]">
          {labels.drawdown} {formatPercent(point.drawdown)}
        </div>
      </div>
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
  const drawdownGradientId = `backtest-drawdown-${useId().replace(/:/g, '')}`;

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
      className="app-workbench-section min-w-0 border-t border-[var(--app-divider)] pt-4"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <h3 className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {labels.title}
          </h3>
        </div>
        <div className="app-muted text-xs tabular-nums">
          {labels.points(data.length)}
        </div>
      </div>

      <div className="mt-5 grid gap-4">
        <ResponsiveChartFrame
          ariaLabel={`${labels.title}. ${labels.points(data.length)}. ${labels.markersCount(fillMarkers.length)}.`}
          className="h-[320px] border-y border-[var(--app-divider)] bg-transparent"
          testId="backtest-equity-chart-frame"
        >
          {({ height, width }) => (
            <LineChart
              accessibilityLayer
              data={data}
              height={height}
              margin={{ top: 18, right: 18, bottom: 8, left: 8 }}
              width={width}
            >
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
              <Tooltip content={<EquityTooltip />} />
              {fillMarkers.map((marker, index) => (
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
              <Line
                type="monotone"
                dataKey="equity"
                stroke="var(--app-accent-secondary)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </LineChart>
          )}
        </ResponsiveChartFrame>

        {fillMarkers.length > 0 ? (
          <div className="border-t border-[var(--app-divider)] pt-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
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
              {fillMarkers.slice(0, 6).map((marker, index) => (
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
