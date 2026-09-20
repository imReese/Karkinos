import { useState } from 'react';
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
  NO_VISIBLE_SERIES,
  resolveXAxisDomain,
  resolveXAxisTicks,
  resolveYAxisDomain,
  SERIES_META,
  TimeAxisTick,
  toChartPoints,
  type SeriesKey,
  useChartContainerSize,
} from './equity-curve-chart-support';

const OVERVIEW_SERIES: SeriesKey[] = [
  'total',
  'cash',
  'stocks',
  'funds',
  'others',
];

function historyStartLabel(timestamp: string | undefined, locale: 'en' | 'zh') {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(date);
}

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
  const [selectedSeries, setSelectedSeries] = useState<SeriesKey>('total');
  const axisNumber = new Intl.NumberFormat(
    locale === 'zh' ? 'zh-CN' : 'en-US',
    { maximumFractionDigits: 2 },
  );
  const labels = copy.overview.equityCurve;
  const seriesLabels: Record<SeriesKey, string> = {
    total: copy.overview.cards.totalAssets,
    cash: labels.cash,
    stocks: labels.stocks,
    funds: labels.funds,
    others: labels.others,
  };
  const unconfirmedQuoteStatuses = new Set([
    'estimated',
    'confirmed_nav_missing',
    'confirmed_fund_nav_missing_estimate_only',
    'unknown',
    'conflict',
    'conflicting',
  ]);
  const chartPoints = toChartPoints(points).map((point) => {
    const rawValue = point[selectedSeries];
    const finiteValue =
      typeof rawValue === 'number' && Number.isFinite(rawValue)
        ? rawValue
        : null;
    const valuationComplete =
      !point.valuation_status || point.valuation_status === 'complete';
    const quoteConfirmed = !unconfirmedQuoteStatuses.has(
      point.quote_status ?? '',
    );
    const confirmed = valuationComplete && quoteConfirmed;
    return {
      ...point,
      confirmedSeries: confirmed ? finiteValue : null,
      indicativeSeries: finiteValue,
      indicativeOnly: finiteValue != null && !confirmed,
    };
  });
  const usablePoints = chartPoints.filter(
    (point) =>
      typeof point.indicativeSeries === 'number' &&
      Number.isFinite(point.indicativeSeries),
  );
  const hasIndicativePoints = chartPoints.some((point) => point.indicativeOnly);
  const [chartRef, size] = useChartContainerSize<HTMLDivElement>();
  const ranges: Array<[EquityCurveRange, string]> = [
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  const visibleSeries = {
    ...NO_VISIBLE_SERIES,
    [selectedSeries]: true,
  };
  const historyStart =
    range === 'all'
      ? historyStartLabel(chartPoints[0]?.timestamp, locale)
      : null;
  const selectedLabel = seriesLabels[selectedSeries];

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
        className="mb-2 flex min-w-0 flex-wrap items-center gap-1"
        data-testid="equity-series-controls"
        role="group"
        aria-label={labels.series}
      >
        {OVERVIEW_SERIES.map((seriesKey) => {
          const active = selectedSeries === seriesKey;
          const meta = SERIES_META.find((series) => series.key === seriesKey);
          return (
            <button
              key={seriesKey}
              type="button"
              aria-pressed={active}
              aria-label={seriesLabels[seriesKey]}
              onClick={() => setSelectedSeries(seriesKey)}
              className={
                'app-chart-control app-type-micro inline-flex min-h-7 items-center gap-1.5 rounded-[var(--app-radius-control)] border px-2.5 font-medium ' +
                (active
                  ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-text)]'
                  : 'border-transparent bg-transparent text-[var(--app-text-secondary)] hover:border-[var(--app-divider)] hover:bg-[var(--app-surface-overlay)]')
              }
            >
              <span
                aria-hidden="true"
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: meta?.color }}
              />
              {seriesLabels[seriesKey]}
            </button>
          );
        })}
      </div>

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
            aria-label={selectedLabel}
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
                  domain={resolveYAxisDomain(chartPoints, visibleSeries)}
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
                    dataKey="indicativeSeries"
                    name={labels.indicativeSeries(selectedLabel)}
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
                  dataKey="confirmedSeries"
                  name={selectedLabel}
                  type="linear"
                  stroke={
                    SERIES_META.find((series) => series.key === selectedSeries)
                      ?.color ?? 'var(--app-accent)'
                  }
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

      {historyStart || hasIndicativePoints ? (
        <div className="app-type-micro mt-2 space-y-1 text-[var(--app-text-tertiary)]">
          {historyStart ? (
            <p data-testid="equity-history-start">
              {labels.historyStart(historyStart)}
            </p>
          ) : null}
          {hasIndicativePoints ? (
            <p data-testid="equity-indicative-note">
              {labels.indicativeHistoryNote}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
