import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useCopy } from '../../../app/copy';
import { formatCurrency, formatPercent } from '../../../shared/format';
import { BacktestReportView } from './backtest-report-view';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import {
  useRunBacktestMutation,
  useBacktestStrategiesQuery,
  type BacktestReport,
  type BacktestRunRequest,
  type BacktestStrategyInfo,
  type StrategyParameterSchema,
} from '../api';

function todayDate() {
  return new Date().toISOString().slice(0, 10);
}

const fallbackStrategies: BacktestStrategyInfo[] = [
  {
    strategy_id: 'dual_ma',
    name: 'dual_ma',
    display_name: 'Dual Moving Average',
    description: 'Dual moving-average crossover baseline.',
    params: [],
    parameter_schema: [
      {
        name: 'short_period',
        type: 'int',
        default: 5,
        required: false,
        min: 1,
        max: 250,
        allowed_values: null,
        description: 'Short moving-average window in trading bars.',
      },
      {
        name: 'long_period',
        type: 'int',
        default: 20,
        required: false,
        min: 2,
        max: 500,
        allowed_values: null,
        description: 'Long moving-average window in trading bars.',
      },
    ],
  },
];

function buildSingleAsset(
  symbol: string,
  assetClass: string,
): BacktestRunRequest['assets'] {
  const normalized = symbol.trim();
  if (!normalized) {
    return undefined;
  }
  return [{ symbol: normalized, asset_class: assetClass }];
}

function isPositiveNumber(value: string) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

function schemaDefaultValue(param: StrategyParameterSchema) {
  if (param.default === null || param.default === undefined) {
    return '';
  }
  if (typeof param.default === 'object') {
    return JSON.stringify(param.default);
  }
  return String(param.default);
}

function parseParamValue(param: StrategyParameterSchema, value: string) {
  if (value.trim() === '') {
    return null;
  }
  if (param.type === 'int') {
    return Number.parseInt(value, 10);
  }
  if (param.type === 'float') {
    return Number(value);
  }
  if (param.type === 'bool') {
    return value === 'true';
  }
  return value;
}

function buildParamValues(
  schema: StrategyParameterSchema[],
): Record<string, string> {
  return Object.fromEntries(
    schema.map((param) => [param.name, schemaDefaultValue(param)]),
  );
}

function strategyDisplayName(
  strategy: BacktestStrategyInfo,
  localizedNames: Record<string, string>,
) {
  return (
    localizedNames[strategy.name] ??
    localizedNames[strategy.strategy_id] ??
    strategy.display_name ??
    strategy.name
  );
}

function humanizeParameterName(name: string) {
  return name
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function parameterDisplayName(
  param: StrategyParameterSchema,
  localizedNames?: Record<string, string>,
) {
  return localizedNames?.[param.name] ?? humanizeParameterName(param.name);
}

function parameterDescription(
  param: StrategyParameterSchema,
  localizedDescriptions?: Record<string, string>,
) {
  return localizedDescriptions?.[param.name] ?? param.description;
}

function buildRunPayload({
  startDate,
  endDate,
  initialCash,
  strategy,
  parameterSchema,
  parameterValues,
  symbol,
  assetClass,
}: {
  startDate: string;
  endDate: string;
  initialCash: string;
  strategy: string;
  parameterSchema: StrategyParameterSchema[];
  parameterValues: Record<string, string>;
  symbol: string;
  assetClass: string;
}): BacktestRunRequest {
  const params = Object.fromEntries(
    parameterSchema.map((param) => [
      param.name,
      parseParamValue(param, parameterValues[param.name] ?? ''),
    ]),
  );
  const shortPeriod = params.short_period;
  const longPeriod = params.long_period;
  return {
    start_date: startDate,
    end_date: endDate,
    initial_cash: Number(initialCash),
    strategy: strategy.trim() || 'dual_ma',
    ...(typeof shortPeriod === 'number' ? { short_period: shortPeriod } : {}),
    ...(typeof longPeriod === 'number' ? { long_period: longPeriod } : {}),
    params,
    assets: buildSingleAsset(symbol, assetClass),
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
  const strategies = useBacktestStrategiesQuery();
  const [startDate, setStartDate] = useState('2025-01-02');
  const [endDate, setEndDate] = useState(() => todayDate());
  const [initialCash, setInitialCash] = useState('100000');
  const [strategy, setStrategy] = useState('dual_ma');
  const [parameterValues, setParameterValues] = useState<
    Record<string, string>
  >(() => buildParamValues(fallbackStrategies[0].parameter_schema));
  const [symbol, setSymbol] = useState('');
  const [assetClass, setAssetClass] = useState('stock');
  const [latestReport, setLatestReport] = useState<BacktestReport | null>(null);
  const [formError, setFormError] = useState('');

  const summary = useMemo(() => resultSummary(latestReport), [latestReport]);
  const strategyCatalog = useMemo(
    () =>
      strategies.data && strategies.data.length > 0
        ? strategies.data
        : fallbackStrategies,
    [strategies.data],
  );
  const selectedStrategy = useMemo(
    () =>
      strategyCatalog.find((item) => item.name === strategy) ??
      strategyCatalog[0],
    [strategy, strategyCatalog],
  );
  const parameterSchema = useMemo(
    () => selectedStrategy.parameter_schema ?? [],
    [selectedStrategy],
  );

  useEffect(() => {
    setParameterValues(buildParamValues(parameterSchema));
  }, [strategy, parameterSchema]);

  const submitRun = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !startDate ||
      !endDate ||
      !isPositiveNumber(initialCash) ||
      parameterSchema.some((param) => {
        if (param.type !== 'int' && param.type !== 'float') {
          return false;
        }
        const value = parameterValues[param.name] ?? '';
        return !isPositiveNumber(value);
      })
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
          parameterSchema,
          parameterValues,
          symbol,
          assetClass,
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
                  step="1"
                  value={initialCash}
                  onChange={(event) => setInitialCash(event.target.value)}
                  aria-label={labels.initialCash}
                />
              </label>

              <div className="grid gap-3">
                <label className="grid gap-2 text-sm font-medium">
                  {labels.strategy}
                  <select
                    className="app-field rounded-2xl px-4 py-3 text-sm"
                    value={strategy}
                    onChange={(event) => setStrategy(event.target.value)}
                    aria-label={labels.strategy}
                  >
                    {strategyCatalog.map((item) => (
                      <option key={item.strategy_id} value={item.name}>
                        {strategyDisplayName(item, labels.strategyNames)}
                      </option>
                    ))}
                  </select>
                </label>
                {strategies.isError ? (
                  <span className="app-muted text-xs">
                    {labels.strategyRegistryFailed}
                  </span>
                ) : null}
                {strategies.isPending ? (
                  <span className="app-muted text-xs">
                    {labels.strategyRegistryLoading}
                  </span>
                ) : null}
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {parameterSchema.map((param) => {
                  const displayName = parameterDisplayName(
                    param,
                    labels.parameterLabels,
                  );
                  const description = parameterDescription(
                    param,
                    labels.parameterDescriptions,
                  );
                  return (
                    <label
                      key={param.name}
                      className="grid gap-2 text-sm font-medium"
                    >
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span>{displayName}</span>
                      </span>
                      <input
                        className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                        type={
                          param.type === 'int' || param.type === 'float'
                            ? 'number'
                            : 'text'
                        }
                        min={param.min ?? undefined}
                        max={param.max ?? undefined}
                        step={param.type === 'float' ? '0.1' : '1'}
                        value={parameterValues[param.name] ?? ''}
                        onChange={(event) =>
                          setParameterValues((current) => ({
                            ...current,
                            [param.name]: event.target.value,
                          }))
                        }
                        aria-label={displayName}
                      />
                      {description || displayName !== param.name ? (
                        <span className="app-muted flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          {description ? <span>{description}</span> : null}
                          {displayName !== param.name ? (
                            <span className="font-mono text-[11px]">
                              {labels.parameterCode(param.name)}
                            </span>
                          ) : null}
                        </span>
                      ) : null}
                    </label>
                  );
                })}
              </div>

              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_160px]">
                <label className="grid gap-2 text-sm font-medium">
                  {labels.symbol}
                  <input
                    className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                    value={symbol}
                    onChange={(event) => setSymbol(event.target.value)}
                    placeholder={labels.symbolPlaceholder}
                    aria-label={labels.symbol}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.assetClass}
                  <select
                    className="app-field rounded-2xl px-4 py-3 text-sm"
                    value={assetClass}
                    onChange={(event) => setAssetClass(event.target.value)}
                    aria-label={labels.assetClass}
                  >
                    <option value="stock">stock</option>
                    <option value="etf">etf</option>
                    <option value="fund">fund</option>
                    <option value="gold">gold</option>
                    <option value="bond">bond</option>
                  </select>
                </label>
                <span className="app-muted text-xs sm:col-span-2">
                  {labels.singleSymbolHint}
                </span>
              </div>

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
