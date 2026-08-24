import { startTransition, useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { formatPublicStatus } from '../../../shared/public-labels';
import { useCopy } from '../../../shared/i18n/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import { APP_MOTION, useReducedMotion } from '../../../shared/motion';
import { usePreferences } from '../../../shared/preferences/context';
import type { EquityCurveRange, EquitySeriesPoint } from '../api';
import {
  ALL_VISIBLE_SERIES,
  CustomTooltip,
  filterByRange,
  formatAxisValue,
  formatChartTimestamp,
  NO_VISIBLE_SERIES,
  renderHighPointDot,
  resolveDefaultVisibleSeries,
  resolveSeriesHighs,
  resolveValuationStatusText,
  resolveXAxisDomain,
  resolveXAxisTicks,
  resolveYAxisDomain,
  SERIES_META,
  TimeAxisTick,
  toChartPoints,
  useChartContainerSize,
  type SeriesKey,
} from './equity-curve-chart-support';
export function EquityCurveSkeleton() {
  const copy = useCopy();

  return (
    <section
      data-testid="equity-curve-skeleton"
      className="w-full space-y-3 py-1"
    >
      <EvidenceState kind="loading" title={copy.overview.curveLoading} />
      <div
        aria-hidden="true"
        data-testid="equity-curve-loading-frame"
        className="relative h-28 overflow-hidden border-y border-[var(--app-divider)] sm:h-36"
      >
        <div className="absolute inset-0 grid grid-rows-3 divide-y divide-[color-mix(in_srgb,var(--app-divider)_72%,transparent)]">
          {Array.from({ length: 3 }).map((_, index) => (
            <span key={index} />
          ))}
        </div>
        <div className="absolute inset-0 grid grid-cols-4 divide-x divide-[color-mix(in_srgb,var(--app-divider)_72%,transparent)] sm:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <span key={index} className={index > 3 ? 'hidden sm:block' : ''} />
          ))}
        </div>
      </div>
    </section>
  );
}

export function EquityCurveCard({
  points,
  range: controlledRange,
  onRangeChange,
}: {
  points: EquitySeriesPoint[];
  range?: EquityCurveRange;
  onRangeChange?: (range: EquityCurveRange) => void;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const reducedMotion = useReducedMotion();
  const labels = copy.overview.equityCurve;
  const [uncontrolledRange, setUncontrolledRange] =
    useState<EquityCurveRange>('all');
  const range = controlledRange ?? uncontrolledRange;
  const defaultVisibleSeries = useMemo(
    () => resolveDefaultVisibleSeries(points),
    [points],
  );
  const [hasManualSeriesSelection, setHasManualSeriesSelection] =
    useState(false);
  const [visibleSeries, setVisibleSeries] =
    useState<Record<SeriesKey, boolean>>(defaultVisibleSeries);

  useEffect(() => {
    if (!hasManualSeriesSelection) {
      setVisibleSeries(defaultVisibleSeries);
    }
  }, [defaultVisibleSeries, hasManualSeriesSelection]);

  const chartPoints = filterByRange(toChartPoints(points), range);
  const hasUsableData = chartPoints.length >= 2;
  const xAxisTicks = resolveXAxisTicks(chartPoints, range);
  const xAxisDomain = resolveXAxisDomain(chartPoints, range);
  const yAxisDomain = resolveYAxisDomain(chartPoints, visibleSeries);
  const latestPoint = chartPoints[chartPoints.length - 1];
  const valuationStatusText = resolveValuationStatusText({
    cachedValuationLabel: labels.cachedValuation,
    locale,
    quoteStatus: latestPoint?.quote_status,
    valuationStatusLabel: labels.valuationStatus,
  });
  const [chartContainerRef, chartSize] =
    useChartContainerSize<HTMLDivElement>();

  const rangeOptions: Array<[EquityCurveRange, string]> = [
    ['1d', labels.oneDay],
    ['5d', labels.fiveDays],
    ['1m', labels.oneMonth],
    ['6m', labels.sixMonths],
    ['1y', labels.oneYear],
    ['all', labels.all],
  ];
  const seriesLabels: Record<SeriesKey, string> = {
    total: labels.total,
    cash: labels.cash,
    stocks: labels.stocks,
    funds: labels.funds,
    others: labels.others,
  };
  const allSeriesSelected = SERIES_META.every(
    (series) => visibleSeries[series.key],
  );
  const seriesHighs = resolveSeriesHighs(
    chartPoints,
    visibleSeries,
    seriesLabels,
  );

  return (
    <section className="w-full px-0 py-1">
      <div className="mb-4 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">
            {copy.overview.dashboard.equityPanel}
          </div>
          <div className="app-card-title mt-1.5 text-[var(--app-text)]">
            {labels.title}
          </div>
          {valuationStatusText ? (
            <div className="app-type-micro mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-2.5 py-1 font-semibold text-[var(--app-warning)]">
              <span className="h-1.5 w-1.5 rounded-full bg-[var(--app-warning)]" />
              <span className="truncate">{valuationStatusText}</span>
            </div>
          ) : null}
          <div
            data-testid="equity-series-controls"
            className="mt-3 flex flex-wrap items-center gap-1.5"
          >
            <button
              type="button"
              aria-pressed={allSeriesSelected}
              aria-label={labels.allSeries}
              onClick={() => {
                setHasManualSeriesSelection(true);
                setVisibleSeries(
                  allSeriesSelected ? NO_VISIBLE_SERIES : ALL_VISIBLE_SERIES,
                );
              }}
              className={`app-chart-control app-type-micro inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium ${
                allSeriesSelected
                  ? 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-text)]'
                  : 'border-transparent bg-transparent text-[var(--app-muted)] opacity-55 hover:border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] hover:opacity-100'
              }`}
            >
              {labels.allSeries}
            </button>
            {SERIES_META.map((series) => {
              const active = visibleSeries[series.key];
              return (
                <button
                  key={series.key}
                  type="button"
                  aria-pressed={active}
                  aria-label={seriesLabels[series.key]}
                  onClick={() => {
                    setHasManualSeriesSelection(true);
                    setVisibleSeries((current) => ({
                      ...current,
                      [series.key]: !current[series.key],
                    }));
                  }}
                  className={`app-chart-control app-type-micro inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium ${
                    active
                      ? 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_18%,transparent)] text-[var(--app-text)]'
                      : 'border-transparent bg-transparent text-[var(--app-muted)] opacity-55 hover:border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] hover:bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] hover:opacity-100'
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: series.color }}
                  />
                  {seriesLabels[series.key]}
                </button>
              );
            })}
          </div>
        </div>

        <div
          data-testid="equity-range-controls"
          className="grid w-full max-w-[340px] grid-cols-6 gap-1 rounded-full border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_30%,transparent)] p-1 shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] sm:w-max"
        >
          {rangeOptions.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-label={`${labels.range}: ${label}`}
              aria-pressed={range === value}
              onClick={() => {
                startTransition(() => {
                  if (controlledRange === undefined) {
                    setUncontrolledRange(value);
                  }
                  onRangeChange?.(value);
                });
              }}
              className={`app-chart-control app-type-micro h-7 min-w-0 rounded-full px-2 font-mono font-semibold ${
                range === value
                  ? 'bg-[color-mix(in_srgb,var(--app-accent)_26%,transparent)] text-[var(--app-accent)] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_8%,transparent)]'
                  : 'text-[var(--app-muted)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {hasUsableData ? (
        <div
          ref={chartContainerRef}
          data-testid="equity-chart-frame"
          className="group/equity-chart h-[340px] w-full overflow-visible rounded-[26px] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[linear-gradient(color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),linear-gradient(90deg,color-mix(in_srgb,var(--app-text)_2%,transparent)_1px,transparent_1px),color-mix(in_srgb,var(--app-panel-strong)_26%,transparent)] bg-[length:44px_44px,44px_44px,auto] shadow-[inset_0_1px_0_color-mix(in_srgb,var(--app-text)_4%,transparent)] sm:h-[410px]"
        >
          {chartSize ? (
            <LineChart
              className="app-chart-stage"
              width={chartSize.width}
              height={chartSize.height}
              data={chartPoints}
              margin={{ left: 14, right: 72, top: 22, bottom: 36 }}
            >
              <defs>
                {SERIES_META.map((series) => (
                  <linearGradient
                    key={series.gradient}
                    id={series.gradient}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop
                      offset="0%"
                      stopColor={series.color}
                      stopOpacity={series.key === 'total' ? 0.18 : 0}
                    />
                    <stop
                      offset="100%"
                      stopColor={series.color}
                      stopOpacity={0}
                    />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid
                stroke="var(--app-border)"
                strokeOpacity={0.12}
                vertical={false}
              />
              <XAxis
                dataKey="timestampMs"
                type="number"
                scale="time"
                domain={xAxisDomain}
                ticks={xAxisTicks}
                tick={<TimeAxisTick range={range} />}
                axisLine={false}
                tickLine={false}
                tickCount={6}
                interval={0}
                height={46}
                tickMargin={14}
                minTickGap={range === '1d' ? 18 : 24}
                stroke="var(--app-subtext-0)"
              />
              <YAxis
                width={60}
                axisLine={false}
                tickLine={false}
                tickMargin={12}
                tickFormatter={formatAxisValue}
                domain={yAxisDomain}
                tick={{ fontSize: 12 }}
                stroke="var(--app-muted)"
              />
              <Tooltip
                content={
                  <CustomTooltip
                    categoryDailyChangeLabel={labels.categoryDailyChange}
                    locale={locale}
                    portfolioTotalLabel={labels.portfolioTotal}
                    quoteStatusLabel={labels.quoteStatus}
                    realtimeUnrealizedPnlLabel={labels.realtimeUnrealizedPnl}
                    unconfirmedCategoryDailyChangeLabel={
                      labels.unconfirmedCategoryDailyChange
                    }
                  />
                }
                cursor={{
                  stroke: 'var(--app-accent)',
                  strokeOpacity: 0.32,
                  strokeWidth: 1,
                }}
                wrapperStyle={{ zIndex: 90, outline: 'none' }}
                allowEscapeViewBox={{ x: false, y: true }}
              />
              {SERIES_META.map((series) => {
                const active = visibleSeries[series.key];
                if (!active) {
                  return null;
                }
                const isPrimarySeries = series.key === 'total';
                const high = seriesHighs.find(
                  (item) => item.key === series.key,
                );
                return (
                  <Line
                    key={series.key}
                    type="monotone"
                    dataKey={series.key}
                    name={seriesLabels[series.key]}
                    stroke={series.color}
                    strokeWidth={isPrimarySeries ? 3.5 : 2}
                    strokeOpacity={isPrimarySeries ? 1 : 0.86}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    animationDuration={APP_MOTION.chartDurationMs}
                    animationEasing={APP_MOTION.easing}
                    dot={
                      high
                        ? renderHighPointDot({
                            high,
                            range,
                            seriesIndex: seriesHighs.findIndex(
                              (item) => item.key === series.key,
                            ),
                            pointCount: chartPoints.length,
                            chartWidth: chartSize.width,
                          })
                        : false
                    }
                    activeDot={{
                      r: series.key === 'total' ? 5 : 4,
                      stroke: 'var(--app-mantle)',
                      strokeWidth: 2,
                      fill: series.color,
                    }}
                    isAnimationActive={!reducedMotion}
                  />
                );
              })}
            </LineChart>
          ) : null}
        </div>
      ) : (
        <div className="flex h-[340px] items-center justify-center rounded-[26px] border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-6 text-center sm:h-[410px]">
          <div>
            <div className="text-sm font-medium text-[var(--app-subtext-0)]">
              {chartPoints.length > 0
                ? labels.insufficientData
                : labels.emptyPeriod}
            </div>
            <div className="app-kicker app-type-overline mt-3">
              {labels.emptyHint}
            </div>
            {latestPoint ? (
              <div className="mt-4 inline-flex flex-wrap items-center justify-center gap-2 rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-panel-strong)_20%,transparent)] px-3 py-1.5 text-xs text-[var(--app-soft)]">
                <span>{labels.currentPoint}</span>
                <span className="font-mono tabular-nums">
                  {formatChartTimestamp(latestPoint.timestamp)}
                </span>
                {latestPoint.quote_status ? (
                  <span className="font-mono">
                    {formatPublicStatus(latestPoint.quote_status, locale)}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}
