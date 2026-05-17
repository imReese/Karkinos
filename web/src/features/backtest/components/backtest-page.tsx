import { useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import { formatCurrency, formatPercent } from '../../../shared/format';
import { BacktestReportView } from './backtest-report-view';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import {
  useRunBacktestMutation,
  type BacktestReport,
  type BacktestRunRequest,
} from '../api';

function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

function parseAssetLines(value: string): BacktestRunRequest['assets'] {
  const assets = value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [symbol, assetClass] = line
        .split(/[:,\s]+/)
        .map((part) => part.trim());
      return {
        symbol,
        asset_class: assetClass || 'stock',
      };
    })
    .filter((asset) => asset.symbol.length > 0);

  return assets.length > 0 ? assets : undefined;
}

function isPositiveNumber(value: string) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

function buildRunPayload({
  startDate,
  endDate,
  initialCash,
  strategy,
  shortPeriod,
  longPeriod,
  assetLines,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  strategy: string;
  shortPeriod: string;
  longPeriod: string;
  assetLines: string;
}): BacktestRunRequest {
  return {
    start_date: startDate,
    end_date: endDate,
    initial_cash: Number(initialCash),
    strategy: strategy.trim() || 'dual_ma',
    short_period: Number(shortPeriod),
    long_period: Number(longPeriod),
    assets: parseAssetLines(assetLines),
  };
}

function resultSummary(report: BacktestReport | null) {
  if (!report) {
    return null;
  }
  const metrics = { ...report.metrics, ...report.metrics_json };
  const costs = report.cost_summary_json ?? {};
  return {
    returnValue: metrics.total_return,
    drawdown: metrics.max_drawdown,
    trades:
      costs.total_trades ?? metrics.total_trades ?? report.fills?.length ?? 0,
    cost:
      (costs.total_commission ?? metrics.total_commission ?? 0) +
      (costs.total_slippage ?? metrics.total_slippage ?? 0),
  };
}

export function BacktestPage() {
  const copy = useCopy();
  const labels = copy.backtest.page;
  const common = copy.common;
  const runBacktest = useRunBacktestMutation();
  const [startDate, setStartDate] = useState('2025-01-02');
  const [endDate, setEndDate] = useState(() => todayDate());
  const [initialCash, setInitialCash] = useState('100000');
  const [strategy, setStrategy] = useState('dual_ma');
  const [shortPeriod, setShortPeriod] = useState('5');
  const [longPeriod, setLongPeriod] = useState('20');
  const [assetLines, setAssetLines] = useState('');
  const [latestReport, setLatestReport] = useState<BacktestReport | null>(null);
  const [formError, setFormError] = useState('');

  const summary = useMemo(() => resultSummary(latestReport), [latestReport]);

  const submitRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !startDate ||
      !endDate ||
      !isPositiveNumber(initialCash) ||
      !isPositiveNumber(shortPeriod) ||
      !isPositiveNumber(longPeriod)
    ) {
      setFormError(common.mustBePositive);
      return;
    }
    setFormError('');
    try {
      const report = await runBacktest.mutateAsync(
        buildRunPayload({
          startDate,
          endDate,
          initialCash,
          strategy,
          shortPeriod,
          longPeriod,
          assetLines,
        }),
      );
      setLatestReport(report);
    } catch (error) {
      setFormError(
        error instanceof Error && error.message
          ? error.message
          : common.genericSubmitError,
      );
    }
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <header className="app-page-header pb-1">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.kicker}</div>
            <h1 className="app-page-title mt-2">{labels.title}</h1>
          </div>
          <p className="app-page-subtitle sm:max-w-xl sm:text-right">
            {labels.subtitle}
          </p>
        </div>
      </header>

      <div className="grid gap-5 2xl:grid-cols-[minmax(360px,0.72fr)_minmax(0,1.28fr)]">
        <section className="app-terminal-panel rounded-[28px] p-[1px]">
          <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
            <div className="app-kicker text-xs uppercase tracking-[0.16em]">
              {labels.formKicker}
            </div>
            <h2 className="app-card-title mt-1.5">{labels.formTitle}</h2>
            <p className="app-muted mt-2 text-sm leading-6">
              {labels.formDetail}
            </p>

            <form className="mt-5 grid gap-4" onSubmit={submitRun}>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">
                  {labels.startDate}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm"
                    type="date"
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    aria-label={labels.startDate}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.endDate}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm"
                    type="date"
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                    aria-label={labels.endDate}
                  />
                </label>
              </div>

              <label className="grid gap-2 text-sm font-medium">
                {labels.initialCash}
                <input
                  className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                  type="number"
                  min="1"
                  step="1000"
                  value={initialCash}
                  onChange={(event) => setInitialCash(event.target.value)}
                  aria-label={labels.initialCash}
                />
              </label>

              <div className="grid gap-3 sm:grid-cols-3">
                <label className="grid gap-2 text-sm font-medium sm:col-span-1">
                  {labels.strategy}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm"
                    value={strategy}
                    onChange={(event) => setStrategy(event.target.value)}
                    aria-label={labels.strategy}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.shortPeriod}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                    type="number"
                    min="1"
                    value={shortPeriod}
                    onChange={(event) => setShortPeriod(event.target.value)}
                    aria-label={labels.shortPeriod}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.longPeriod}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                    type="number"
                    min="1"
                    value={longPeriod}
                    onChange={(event) => setLongPeriod(event.target.value)}
                    aria-label={labels.longPeriod}
                  />
                </label>
              </div>

              <label className="grid gap-2 text-sm font-medium">
                {labels.assets}
                <textarea
                  className="app-field min-h-28 rounded-2xl px-4 py-3 text-sm leading-6"
                  value={assetLines}
                  onChange={(event) => setAssetLines(event.target.value)}
                  placeholder={labels.assetsPlaceholder}
                  aria-label={labels.assets}
                />
                <span className="app-muted text-xs">{labels.assetsHint}</span>
              </label>

              {formError ? (
                <div
                  className="rounded-2xl border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-4 py-3 text-sm text-[var(--app-danger)]"
                  role="alert"
                >
                  {formError}
                </div>
              ) : null}

              <button
                type="submit"
                className="app-button-primary rounded-2xl px-4 py-3 text-sm font-semibold transition active:scale-[0.99]"
                disabled={runBacktest.isPending}
              >
                {runBacktest.isPending ? labels.running : labels.run}
              </button>
            </form>
          </div>
        </section>

        <section className="app-terminal-panel rounded-[28px] p-[1px]">
          <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="app-kicker text-xs uppercase tracking-[0.16em]">
                  {labels.currentKicker}
                </div>
                <h2 className="app-card-title mt-1.5">{labels.currentTitle}</h2>
              </div>
              {summary ? (
                <div className="grid grid-cols-2 gap-3 text-right text-xs tabular-nums sm:grid-cols-4">
                  <SummaryValue
                    label={labels.totalReturn}
                    value={formatPercent(summary.returnValue)}
                  />
                  <SummaryValue
                    label={labels.maxDrawdown}
                    value={formatPercent(summary.drawdown)}
                    danger
                  />
                  <SummaryValue
                    label={labels.totalCost}
                    value={formatCurrency(summary.cost)}
                  />
                  <SummaryValue
                    label={labels.fillsCount}
                    value={String(summary.trades)}
                  />
                </div>
              ) : null}
            </div>

            {latestReport ? (
              <div className="mt-5 space-y-5">
                <MetricsGrid report={latestReport} />
                <EquityDrawdownChart points={latestReport.equity_curve} />
                <FillsTable fills={latestReport.fills ?? []} />
              </div>
            ) : (
              <div className="mt-5 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-5 text-sm text-[var(--app-muted)]">
                {labels.emptyCurrent}
              </div>
            )}
          </div>
        </section>
      </div>

      <BacktestReportView />
    </section>
  );
}

function SummaryValue({
  label,
  value,
  danger = false,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <div>
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {label}
      </div>
      <div
        className={`mt-1 font-semibold ${danger ? 'text-[var(--app-danger)]' : ''}`}
      >
        {value}
      </div>
    </div>
  );
}
