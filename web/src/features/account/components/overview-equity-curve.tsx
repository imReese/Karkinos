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
import { SectionHeader } from '../../../shared/ui/workbench';
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
  const unconfirmedQuoteStatuses = new Set([
    'estimated',
    'confirmed_nav_missing',
    'confirmed_fund_nav_missing_estimate_only',
    'unknown',
    'conflict',
    'conflicting',
  ]);
  const chartPoints = toChartPoints(points).map((point) => {
    const rawTotal =
      typeof point.total === 'number' && Number.isFinite(point.total)
        ? point.total
        : null;
    const valuationComplete =
      !point.valuation_status || point.valuation_status === 'complete';
    const quoteConfirmed = !unconfirmedQuoteStatuses.has(
      point.quote_status ?? '',
    );
    const confirmed = valuationComplete && quoteConfirmed;
    return {
      ...point,
      confirmedTotal: confirmed ? rawTotal : null,
      indicativeTotal: rawTotal,
      indicativeOnly: rawTotal != null && !confirmed,
    };
  });
  const usablePoints = chartPoints.filter(
    (point) =>
      typeof point.indicativeTotal === 'number' &&
      Number.isFinite(point.indicativeTotal),
  );
  const hasIndicativePoints = chartPoints.some((point) => point.indicativeOnly);
  const [chartRef, size] = useChartContainerSize<HTMLDivElement>();
  const ranges: Array<[EquityCurveRange, string]> = [
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  return (
    <div className="min-w-0">
      <SectionHeader
        title={copy.overview.dashboard.equityPanel}
        className="mb-2"
        actions={
          <div
            className="app-inline-segmented"
            data-testid="equity-range-controls"
            aria-label={labels.range}
            role="group"
          >
            {ranges.map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={range === value}
                aria-label={labels.range + ': ' + label}
                onClick={() => onRangeChange(value)}
                className={
                  'app-inline-segmented-btn ' +
                  (range === value ? 'app-inline-segmented-btn-active' : '')
                }
              >
                {label}
              </button>
            ))}
          </div>
        }
      />
      <div
        ref={chartRef}
        className={
          (usablePoints.length >= 2
            ? 'h-[200px] sm:h-[224px] xl:h-[236px]'
            : 'h-[72px] sm:h-[84px]') + ' min-w-0 overflow-hidden'
        }
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
                  formatter={(value, name) => [
                    formatCurrency(typeof value === 'number' ? value : null),
                    String(name),
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
                {hasIndicativePoints ? (
                  <Line
                    dataKey="indicativeTotal"
                    name={labels.indicativePortfolioTotal}
                    type="linear"
                    stroke="var(--app-text-tertiary)"
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                    strokeOpacity={0.8}
                    dot={false}
                    activeDot={{ r: 3 }}
                    isAnimationActive={false}
                    connectNulls={false}
                  />
                ) : null}
                <Line
                  dataKey="confirmedTotal"
                  name={labels.confirmedPortfolioTotal}
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
      {hasIndicativePoints ? (
        <p
          className="app-type-micro mt-2 text-[var(--app-text-tertiary)]"
          data-testid="equity-indicative-note"
        >
          {labels.indicativeHistoryNote}
        </p>
      ) : null}
    </div>
  );
}
