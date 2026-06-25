import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { useCopy } from '../../../app/copy';
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
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_66%,transparent)] px-3 py-2 text-xs shadow-[0_14px_44px_rgba(17,17,27,0.22)] backdrop-blur-md">
      <div className="font-medium">{formatTimestamp(point.timestamp)}</div>
      <div className="mt-2 grid gap-1 tabular-nums">
        <div>{formatCurrency(point.equity)}</div>
        <div className="text-[var(--app-danger)]">
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

  if (data.length === 0) {
    return (
      <section className="app-panel rounded-2xl p-5">
        <div className="app-card-title">{labels.title}</div>
        <div className="app-muted mt-4 text-sm">{labels.empty}</div>
      </section>
    );
  }

  return (
    <section className="app-panel rounded-2xl p-4 sm:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="app-kicker text-xs uppercase tracking-[0.16em]">
            {labels.kicker}
          </div>
          <div className="app-card-title mt-1.5">{labels.title}</div>
        </div>
        <div className="app-muted text-xs tabular-nums">
          {labels.points(data.length)}
        </div>
      </div>

      <div className="mt-5 grid gap-4">
        <div className="h-[320px] min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)]">
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={1}
            minHeight={320}
            initialDimension={{ width: 1, height: 320 }}
          >
            <LineChart
              data={data}
              margin={{ top: 18, right: 18, bottom: 8, left: 8 }}
            >
              <CartesianGrid
                stroke="color-mix(in srgb, var(--app-border) 28%, transparent)"
                vertical={false}
              />
              <XAxis
                dataKey="timestampMs"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickFormatter={formatDate}
                tickLine={false}
                axisLine={false}
                minTickGap={30}
                stroke="var(--app-muted)"
                fontSize={12}
              />
              <YAxis
                tickFormatter={formatAxisCurrency}
                tickLine={false}
                axisLine={false}
                width={56}
                stroke="var(--app-muted)"
                fontSize={12}
              />
              <Tooltip content={<EquityTooltip />} />
              {fillMarkers.map((marker, index) => (
                <ReferenceDot
                  fill={
                    marker.side === 'buy'
                      ? 'var(--app-success)'
                      : 'var(--app-danger)'
                  }
                  ifOverflow="extendDomain"
                  key={`${marker.fill_id ?? marker.order_id ?? marker.symbol}-${index}`}
                  r={5}
                  stroke="var(--app-base)"
                  strokeWidth={2}
                  x={marker.timestampMs}
                  y={marker.equity}
                />
              ))}
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#89b4fa"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {fillMarkers.length > 0 ? (
          <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
                  {labels.markersKicker}
                </div>
                <div className="mt-1 text-sm font-black text-[var(--app-text)]">
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
                  className="min-w-0 rounded-2xl bg-[color-mix(in_srgb,var(--app-mantle)_34%,transparent)] px-3 py-2 text-xs"
                  key={`${marker.fill_id ?? marker.order_id ?? marker.symbol}-${index}-summary`}
                >
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <span
                      className={`font-black ${
                        marker.side === 'buy'
                          ? 'text-[var(--app-success)]'
                          : 'text-[var(--app-danger)]'
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

        <div className="h-[150px] min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-danger-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)]">
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={1}
            minHeight={150}
            initialDimension={{ width: 1, height: 150 }}
          >
            <AreaChart
              data={data}
              margin={{ top: 16, right: 18, bottom: 4, left: 8 }}
            >
              <defs>
                <linearGradient
                  id="backtestDrawdown"
                  x1="0"
                  x2="0"
                  y1="0"
                  y2="1"
                >
                  <stop offset="0%" stopColor="#f38ba8" stopOpacity={0.42} />
                  <stop offset="100%" stopColor="#f38ba8" stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid
                stroke="color-mix(in srgb, var(--app-border) 22%, transparent)"
                vertical={false}
              />
              <XAxis
                dataKey="timestampMs"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickFormatter={formatDate}
                tickLine={false}
                axisLine={false}
                minTickGap={30}
                stroke="var(--app-muted)"
                fontSize={12}
              />
              <YAxis
                tickFormatter={(value: number) => formatPercent(value)}
                tickLine={false}
                axisLine={false}
                width={56}
                stroke="var(--app-muted)"
                fontSize={12}
              />
              <Tooltip content={<EquityTooltip />} />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="#f38ba8"
                strokeWidth={1.5}
                fill="url(#backtestDrawdown)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}
