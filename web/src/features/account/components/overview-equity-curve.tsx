import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { useCopy } from '../../../shared/i18n/context';
import type { EquityCurveRange, EquitySeriesPoint } from '../api';
import {
  resolveXAxisDomain,
  resolveXAxisTicks,
  resolveYAxisDomain,
  TimeAxisTick,
  toChartPoints,
  useChartContainerSize,
} from './equity-curve-chart-support';

const portfolioSeries = {
  total: true,
  cash: false,
  stocks: false,
  funds: false,
  others: false,
};

export function OverviewEquityCurve({
  points,
  range,
  onRangeChange,
}: {
  points: EquitySeriesPoint[];
  range: EquityCurveRange;
  onRangeChange: (range: EquityCurveRange) => void;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const axisNumber = new Intl.NumberFormat(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { maximumFractionDigits: 2 },
  );
  const labels = copy.overview.equityCurve;
  const chartPoints = toChartPoints(points).map((point) =>
    (point.valuation_status && point.valuation_status !== 'complete') ||
    [
      'estimated',
      'confirmed_nav_missing',
      'confirmed_fund_nav_missing_estimate_only',
      'unknown',
      'conflict',
      'conflicting',
    ].includes(point.quote_status ?? '')
      ? { ...point, total: null }
      : point,
  );
  const usablePoints = chartPoints.filter(
    (point) => typeof point.total === 'number' && Number.isFinite(point.total),
  );
  const [chartRef, size] = useChartContainerSize<HTMLDivElement>();
  const ranges: Array<[EquityCurveRange, string]> = [
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  return (
    <div className="min-w-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--app-text)]">
          {copy.overview.dashboard.equityPanel}
        </h2>
        <div
          className="flex gap-1"
          data-testid="equity-range-controls"
          aria-label={labels.range}
        >
          {ranges.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={range === value}
              aria-label={`${labels.range}: ${label}`}
              onClick={() => onRangeChange(value)}
              className={`min-h-8 border-b-2 px-2 text-xs font-medium ${range === value ? 'border-[var(--app-accent)] text-[var(--app-accent)]' : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div
        ref={chartRef}
        className={`${usablePoints.length >= 2 ? 'h-[220px] sm:h-[248px]' : 'h-[96px] sm:h-[112px]'} min-w-0`}
      >
        {usablePoints.length >= 2 ? (
          <div
            data-testid="equity-chart-frame"
            role="img"
            aria-label={labels.portfolioTotal}
          >
            {size ? (
              <LineChart
                width={size.width}
                height={size.height}
                data={chartPoints}
                margin={{ left: 0, right: 14, top: 12, bottom: 10 }}
              >
                <CartesianGrid
                  stroke="var(--app-divider)"
                  strokeOpacity={0.65}
                  vertical={false}
                />
                <XAxis
                  dataKey="timestampMs"
                  type="number"
                  scale="time"
                  domain={resolveXAxisDomain(chartPoints, range)}
                  ticks={resolveXAxisTicks(chartPoints, range)}
                  tick={<TimeAxisTick range={range} />}
                  axisLine={false}
                  tickLine={false}
                  height={38}
                />
                <YAxis
                  width={76}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(value: number) => axisNumber.format(value)}
                  domain={resolveYAxisDomain(chartPoints, portfolioSeries)}
                  tick={{ fontSize: 11, fill: 'var(--app-text-tertiary)' }}
                />
                <Tooltip
                  formatter={(value) => [
                    formatCurrency(typeof value === 'number' ? value : null),
                    labels.portfolioTotal,
                  ]}
                  labelFormatter={(value) =>
                    formatTimestamp(new Date(Number(value)).toISOString())
                  }
                  contentStyle={{
                    background: 'var(--app-surface)',
                    border: '1px solid var(--app-divider)',
                    borderRadius: 'var(--app-radius-control)',
                    fontSize: 12,
                  }}
                  cursor={{ stroke: 'var(--app-accent)', strokeOpacity: 0.3 }}
                />
                <Line
                  dataKey="total"
                  name={labels.portfolioTotal}
                  type="linear"
                  stroke="var(--app-accent)"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              </LineChart>
            ) : null}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center text-sm text-[var(--app-text-secondary)]">
            {usablePoints.length
              ? labels.insufficientData
              : chartPoints.length
                ? labels.unverifiedPeriod
                : labels.emptyPeriod}
          </div>
        )}
      </div>
    </div>
  );
}
