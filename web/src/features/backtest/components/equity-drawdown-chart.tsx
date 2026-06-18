import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
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
  formatTimestamp,
} from '../../../shared/format';
import type { BacktestEquityPoint } from '../api';

type ChartPoint = BacktestEquityPoint & {
  timestampMs: number;
  drawdown: number;
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
  points,
}: {
  points: BacktestEquityPoint[];
}) {
  const labels = useCopy().backtest.chart;
  const data = toChartPoints(points);

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
