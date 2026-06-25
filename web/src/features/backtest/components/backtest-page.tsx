import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';

import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { apiClient } from '../../../lib/api/client';
import { formatCurrency, formatPercent } from '../../../shared/format';
import {
  formatInstrumentDisplayLabelsBySymbol,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicCodeList,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import { BacktestReportView } from './backtest-report-view';
import { DatasetSnapshotPanel } from './dataset-snapshot-panel';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import { ParameterComparePanel } from './parameter-compare-panel';
import { ParameterSweepPanel } from './parameter-sweep-panel';
import { ValidationEvidencePanel } from './validation-evidence-panel';
import {
  useAccountStrategyAssignmentQuery,
  useAccountStrategyAttributionQuery,
  useAccountStrategyContributionQuery,
  useBacktestAttributionPreviewMutation,
  useUpdateAccountStrategyAssignmentMutation,
  useRunBacktestMutation,
  useBacktestPaperShadowPreviewMutation,
  useBacktestRiskPreviewMutation,
  useBacktestStrategiesQuery,
  useStrategySignalPreviewMutation,
  useStrategyPromotionReadinessQuery,
  useStrategyValidationQuery,
  type AccountStrategyAssignment,
  type AccountStrategyAttributionSummary,
  type AccountStrategyContributionReport,
  type BacktestAttributionPreviewResponse,
  type BacktestReport,
  type BacktestPaperShadowPreviewRequest,
  type BacktestPaperShadowPreviewResponse,
  type BacktestRiskPreviewRequest,
  type BacktestRiskPreviewResponse,
  type BacktestRunRequest,
  type BacktestStrategyInfo,
  type StrategySignalPreviewOutput,
  type StrategySignalPreviewResponse,
  type StrategyPromotionReadiness,
  type StrategyParameterSchema,
  type StrategyValidationRow,
  type StrategyValidationMatrix,
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

type BacktestPortfolioInstrumentSnapshot = {
  positions: InstrumentDisplayRecord[];
};

function useBacktestPortfolioInstrumentsQuery() {
  return useQuery({
    queryKey: ['backtest-portfolio-instruments'],
    queryFn: () =>
      apiClient<BacktestPortfolioInstrumentSnapshot>('/api/portfolio'),
    staleTime: 10_000,
  });
}

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

function strategyDescription(
  strategy: BacktestStrategyInfo,
  localizedDescriptions: Record<string, string>,
) {
  return (
    localizedDescriptions[strategy.name] ??
    localizedDescriptions[strategy.strategy_id] ??
    strategy.description
  );
}

function benchmarkRoleDisplayName(
  role: string | null | undefined,
  localizedRoles: Record<string, string>,
  fallback: string,
) {
  if (!role) {
    return fallback;
  }
  return localizedRoles[role] ?? role;
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

type LoopStepState = 'ready' | 'waiting' | 'blocked';

type LoopStep = {
  key: string;
  label: string;
  state: LoopStepState;
  evidenceHref: string;
  evidenceLabel: string;
};

function hasDatasetSnapshotEvidence(report: BacktestReport) {
  return Boolean(report.metrics_json?.dataset_snapshot?.snapshot_id);
}

function hasAfterCostEvidence(report: BacktestReport) {
  return Boolean(
    report.evidence_json ||
    report.metrics_json?.evidence_bundle ||
    report.cost_summary_json,
  );
}

function formatGateScore(score: number | null) {
  return score === null ? '--' : String(score);
}

function lookupLabel<T extends Record<string, string>>(
  labels: T,
  key: string,
  fallback: string,
) {
  return labels[key] ?? fallback;
}

function accountStrategyPnlAttributionTier(
  attribution: AccountStrategyAttributionSummary | null,
  contribution: AccountStrategyContributionReport | null,
) {
  const attributionStatus = attribution?.attribution_status ?? 'not_started';
  const contributionStatus =
    contribution?.contribution_status ?? 'no_linked_fills';
  const linkedEvidenceCount =
    (attribution?.signal_count ?? 0) +
    (attribution?.action_count ?? 0) +
    (attribution?.risk_decision_count ?? 0) +
    (attribution?.order_count ?? 0) +
    (attribution?.fill_count ?? 0) +
    (contribution?.linked_fill_count ?? 0);
  const hasMissingValuation =
    contributionStatus === 'valuation_missing' ||
    Boolean(contribution?.missing_valuation_symbols.length);

  if (
    attributionStatus === 'blocked' ||
    attributionStatus === 'failed' ||
    contributionStatus === 'blocked' ||
    contributionStatus === 'failed'
  ) {
    return 'blocked';
  }
  if (hasMissingValuation) {
    return 'stale';
  }
  if (attributionStatus === 'complete' || attributionStatus === 'attributed') {
    return 'complete';
  }
  if (
    linkedEvidenceCount === 0 &&
    ['not_started', 'assignment_only'].includes(attributionStatus)
  ) {
    return 'not_started';
  }
  return 'partial';
}

export function BacktestPage() {
  const copy = useCopy();
  const labels = copy.backtest.page;
  const common = copy.common;
  const runBacktest = useRunBacktestMutation();
  const signalPreview = useStrategySignalPreviewMutation();
  const riskPreview = useBacktestRiskPreviewMutation();
  const paperShadowPreview = useBacktestPaperShadowPreviewMutation();
  const attributionPreview = useBacktestAttributionPreviewMutation();
  const strategies = useBacktestStrategiesQuery();
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const accountStrategyAttribution = useAccountStrategyAttributionQuery();
  const accountStrategyContribution = useAccountStrategyContributionQuery();
  const portfolioInstruments = useBacktestPortfolioInstrumentsQuery();
  const updateAccountStrategy = useUpdateAccountStrategyAssignmentMutation();
  const validation = useStrategyValidationQuery();
  const readiness = useStrategyPromotionReadinessQuery();
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
  const assetClassOptions = [
    { value: 'stock', label: common.assetClassStock },
    { value: 'etf', label: common.assetClassEtf },
    { value: 'fund', label: common.assetClassFund },
    { value: 'gold', label: common.assetClassGold },
    { value: 'bond', label: common.assetClassBond },
  ];

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
      const payload = buildRunPayload({
        startDate,
        endDate,
        initialCash,
        strategy,
        parameterSchema,
        parameterValues,
        symbol,
        assetClass,
      });
      const report = await runBacktest.mutateAsync(payload);
      setLatestReport(report);
      signalPreview.reset();
      riskPreview.reset();
      paperShadowPreview.reset();
      attributionPreview.reset();
      const previewAsset = payload.assets?.[0];
      if (previewAsset) {
        signalPreview.mutate({
          strategy: payload.strategy,
          symbol: previewAsset.symbol,
          asset_class: previewAsset.asset_class,
          start_date: payload.start_date,
          end_date: payload.end_date,
          params: payload.params,
        });
      }
    } catch (error) {
      setFormError(
        error instanceof Error && error.message
          ? error.message
          : common.genericSubmitError,
      );
    }
  };

  const assignSelectedStrategy = async () => {
    await updateAccountStrategy.mutateAsync({
      strategy_id: selectedStrategy.name,
      status: 'research_only',
      scope: 'account',
      notes: 'Assigned from Backtest page for research review.',
    });
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

      <div className="scroll-mt-24" id="backtest-strategy-catalog">
        <StrategyCatalogPanel
          strategyCatalog={strategyCatalog}
          selectedStrategyName={strategy}
          onSelect={setStrategy}
        />
      </div>

      <AccountStrategyPanel
        assignment={accountStrategy.data ?? null}
        attribution={accountStrategyAttribution.data ?? null}
        contribution={accountStrategyContribution.data ?? null}
        instruments={portfolioInstruments.data?.positions ?? []}
        selectedStrategy={selectedStrategy}
        strategyCatalog={strategyCatalog}
        loading={accountStrategy.isLoading}
        error={accountStrategy.isError}
        attributionLoading={accountStrategyAttribution.isLoading}
        attributionError={accountStrategyAttribution.isError}
        contributionLoading={accountStrategyContribution.isLoading}
        contributionError={accountStrategyContribution.isError}
        assigning={updateAccountStrategy.isPending}
        assignError={updateAccountStrategy.isError}
        onAssignSelected={assignSelectedStrategy}
      />

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
                <StrategyMetadataPanel
                  strategy={selectedStrategy}
                  description={strategyDescription(
                    selectedStrategy,
                    labels.strategyDescriptions,
                  )}
                  labels={labels}
                />
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
                      {description ? (
                        <span className="app-muted flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          <span>{description}</span>
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
                    {assetClassOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
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
            <ParameterSweepPanel
              startDate={startDate}
              endDate={endDate}
              initialCash={initialCash}
              strategy={strategy}
              parameterSchema={parameterSchema}
              parameterValues={parameterValues}
              assets={buildSingleAsset(symbol, assetClass)}
            />
            <ParameterComparePanel
              startDate={startDate}
              endDate={endDate}
              initialCash={initialCash}
              strategy={strategy}
              parameterSchema={parameterSchema}
              assets={buildSingleAsset(symbol, assetClass)}
            />
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
                <SingleInstrumentLoopReadinessCard
                  attributionPreviewResult={attributionPreview.data ?? null}
                  paperShadowPreviewResult={paperShadowPreview.data ?? null}
                  preview={signalPreview.data ?? null}
                  report={latestReport}
                  riskPreviewResult={riskPreview.data ?? null}
                />
                <div
                  className="scroll-mt-24 space-y-5"
                  id="backtest-after-cost-evidence"
                >
                  <MetricsGrid report={latestReport} />
                  <ValidationEvidencePanel report={latestReport} />
                </div>
                <div className="scroll-mt-24" id="backtest-dataset-evidence">
                  <DatasetSnapshotPanel report={latestReport} />
                </div>
                <div
                  className="scroll-mt-24"
                  id="backtest-signal-review-evidence"
                >
                  <StrategySignalPreviewPanel
                    error={signalPreview.isError}
                    loading={signalPreview.isPending}
                    onPaperShadowPreview={(payload) => {
                      attributionPreview.reset();
                      paperShadowPreview.mutate(payload, {
                        onSuccess: (result) => {
                          attributionPreview.mutate({
                            strategy: payload.strategy,
                            symbol: payload.symbol,
                            asset_class: payload.asset_class,
                            signal_id: payload.signal_id ?? null,
                            dataset_snapshot_id:
                              payload.dataset_snapshot_id ?? null,
                            risk_preview_passed: payload.risk_preview_passed,
                            risk_reasons: payload.risk_reasons,
                            paper_shadow_status: result.status,
                            paper_shadow_order: result.order,
                            paper_shadow_fill: result.fill as Record<
                              string,
                              unknown
                            > | null,
                          });
                        },
                      });
                    }}
                    onRiskPreview={(payload) => {
                      paperShadowPreview.reset();
                      attributionPreview.reset();
                      riskPreview.mutate(payload);
                    }}
                    attributionPreviewError={attributionPreview.isError}
                    attributionPreviewLoading={attributionPreview.isPending}
                    attributionPreviewResult={attributionPreview.data ?? null}
                    paperShadowPreviewError={paperShadowPreview.isError}
                    paperShadowPreviewLoading={paperShadowPreview.isPending}
                    paperShadowPreviewResult={paperShadowPreview.data ?? null}
                    preview={signalPreview.data ?? null}
                    riskPreviewError={riskPreview.isError}
                    riskPreviewLoading={riskPreview.isPending}
                    riskPreviewResult={riskPreview.data ?? null}
                    singleAsset={latestReport.config.assets?.[0] ?? null}
                  />
                </div>
                <EquityDrawdownChart
                  fills={latestReport.fills ?? []}
                  points={latestReport.equity_curve}
                />
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

      <StrategyEvidenceGatePanel
        strategyCatalog={strategyCatalog}
        validation={validation.data ?? null}
        readiness={readiness.data ?? null}
        loading={validation.isLoading || readiness.isLoading}
        error={validation.isError || readiness.isError}
      />

      <BacktestReportView />
    </section>
  );
}

function SingleInstrumentLoopReadinessCard({
  report,
  preview,
  riskPreviewResult,
  paperShadowPreviewResult,
  attributionPreviewResult,
}: {
  report: BacktestReport;
  preview: StrategySignalPreviewResponse | null;
  riskPreviewResult: BacktestRiskPreviewResponse | null;
  paperShadowPreviewResult: BacktestPaperShadowPreviewResponse | null;
  attributionPreviewResult: BacktestAttributionPreviewResponse | null;
}) {
  const labels = useCopy().backtest.page;
  const steps: LoopStep[] = [
    {
      key: 'dataset',
      label: hasDatasetSnapshotEvidence(report)
        ? labels.singleInstrumentLoopDatasetReady
        : labels.singleInstrumentLoopDatasetWaiting,
      state: hasDatasetSnapshotEvidence(report) ? 'ready' : 'waiting',
      evidenceHref: '#backtest-dataset-evidence',
      evidenceLabel: labels.singleInstrumentLoopDatasetEvidence,
    },
    {
      key: 'strategy',
      label: report.config.strategy
        ? labels.singleInstrumentLoopStrategyReady
        : labels.singleInstrumentLoopStrategyWaiting,
      state: report.config.strategy ? 'ready' : 'waiting',
      evidenceHref: '#backtest-strategy-catalog',
      evidenceLabel: labels.singleInstrumentLoopStrategyEvidence,
    },
    {
      key: 'backtest',
      label: hasAfterCostEvidence(report)
        ? labels.singleInstrumentLoopBacktestReady
        : labels.singleInstrumentLoopBacktestWaiting,
      state: hasAfterCostEvidence(report) ? 'ready' : 'waiting',
      evidenceHref: '#backtest-after-cost-evidence',
      evidenceLabel: labels.singleInstrumentLoopBacktestEvidence,
    },
    {
      key: 'signal',
      label: preview?.outputs.length
        ? labels.singleInstrumentLoopSignalReady
        : labels.singleInstrumentLoopSignalWaiting,
      state: preview?.outputs.length ? 'ready' : 'waiting',
      evidenceHref: '#backtest-signal-review-evidence',
      evidenceLabel: labels.singleInstrumentLoopSignalEvidence,
    },
    {
      key: 'risk',
      label: riskPreviewResult
        ? riskPreviewResult.passed
          ? labels.singleInstrumentLoopRiskPassed
          : labels.singleInstrumentLoopRiskBlocked
        : labels.singleInstrumentLoopRiskWaiting,
      state: riskPreviewResult
        ? riskPreviewResult.passed
          ? 'ready'
          : 'blocked'
        : 'waiting',
      evidenceHref: '#backtest-signal-review-evidence',
      evidenceLabel: labels.singleInstrumentLoopRiskEvidence,
    },
    {
      key: 'paper',
      label:
        paperShadowPreviewResult?.status === 'simulated'
          ? labels.singleInstrumentLoopPaperReady
          : labels.singleInstrumentLoopPaperWaiting,
      state:
        paperShadowPreviewResult?.status === 'simulated' ? 'ready' : 'waiting',
      evidenceHref: '#backtest-signal-review-evidence',
      evidenceLabel: labels.singleInstrumentLoopPaperEvidence,
    },
    {
      key: 'attribution',
      label:
        attributionPreviewResult?.status === 'ready_for_review_linkage'
          ? labels.singleInstrumentLoopAttributionReady
          : labels.singleInstrumentLoopAttributionWaiting,
      state:
        attributionPreviewResult?.status === 'ready_for_review_linkage'
          ? 'ready'
          : 'waiting',
      evidenceHref: '#backtest-signal-review-evidence',
      evidenceLabel: labels.singleInstrumentLoopAttributionEvidence,
    },
  ];
  const readyCount = steps.filter((step) => step.state === 'ready').length;
  const blocked = steps.some((step) => step.state === 'blocked');
  const allReady = readyCount === steps.length;
  const statusLabel = blocked
    ? labels.singleInstrumentLoopBlocked
    : allReady
      ? labels.singleInstrumentLoopReady
      : labels.singleInstrumentLoopWaiting;

  return (
    <section className="rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-4">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.singleInstrumentLoopKicker}
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-[var(--app-text)]">
            {labels.singleInstrumentLoopTitle}
          </h3>
          <p className="app-muted mt-2 text-sm leading-6">
            {labels.singleInstrumentLoopDetail}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span
            className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
              blocked
                ? 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]'
                : allReady
                  ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]'
                  : 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning)]'
            }`}
          >
            {statusLabel}
          </span>
          <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] tabular-nums">
            {readyCount}/{steps.length}
          </span>
        </div>
      </div>
      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {steps.map((step) => (
          <div
            className={`min-w-0 rounded-2xl border px-3 py-2 text-sm font-semibold ${
              step.state === 'ready'
                ? 'border-[color-mix(in_srgb,var(--app-success)_40%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] text-[var(--app-success)]'
                : step.state === 'blocked'
                  ? 'border-[color-mix(in_srgb,var(--app-danger)_42%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-danger)_10%,transparent)] text-[var(--app-danger)]'
                  : 'border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_14%,transparent)] text-[var(--app-muted)]'
            }`}
            key={step.key}
          >
            <div className="min-w-0">{step.label}</div>
            <a
              aria-label={step.evidenceLabel}
              className="mt-2 inline-flex max-w-full items-center rounded-full border border-[color-mix(in_srgb,currentColor_24%,transparent)] px-2.5 py-1 text-[11px] font-semibold text-inherit opacity-85 transition hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus)]"
              href={step.evidenceHref}
            >
              {labels.singleInstrumentLoopEvidenceCta}
            </a>
          </div>
        ))}
      </div>
    </section>
  );
}

function StrategyCatalogPanel({
  strategyCatalog,
  selectedStrategyName,
  onSelect,
}: {
  strategyCatalog: BacktestStrategyInfo[];
  selectedStrategyName: string;
  onSelect: (strategyName: string) => void;
}) {
  const labels = useCopy().backtest.page;

  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.strategyCatalogKicker}
            </div>
            <h2 className="app-card-title mt-1.5">
              {labels.strategyCatalogTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.strategyCatalogDetail}
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
          {strategyCatalog.map((item) => {
            const name = strategyDisplayName(item, labels.strategyNames);
            const description = strategyDescription(
              item,
              labels.strategyDescriptions,
            );
            const selected = item.name === selectedStrategyName;
            const badges = [
              item.requires_out_of_sample_validation
                ? labels.oosRequired
                : null,
              item.requires_after_cost_report ? labels.afterCostRequired : null,
            ].filter(Boolean);
            return (
              <button
                aria-label={labels.selectStrategy(name)}
                className={`min-w-0 rounded-3xl border px-4 py-4 text-left transition ${
                  selected
                    ? 'border-[var(--app-accent)] bg-[color-mix(in_srgb,var(--app-accent)_18%,transparent)] shadow-[0_0_0_1px_color-mix(in_srgb,var(--app-accent)_30%,transparent)]'
                    : 'border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))]'
                }`}
                key={item.strategy_id}
                onClick={() => onSelect(item.name)}
                type="button"
              >
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-base font-semibold text-[var(--app-text)]">
                      {name}
                    </div>
                    <div className="app-muted mt-1 line-clamp-2 text-sm leading-5">
                      {description}
                    </div>
                  </div>
                  {selected ? (
                    <span className="shrink-0 rounded-full bg-[var(--app-accent)] px-2.5 py-1 text-xs font-semibold text-[var(--app-base)]">
                      {labels.selectedStrategy}
                    </span>
                  ) : null}
                </div>
                {badges.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {badges.map((badge) => (
                      <span
                        className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2.5 py-1 text-xs font-semibold text-[var(--app-muted)]"
                        key={badge}
                      >
                        {badge}
                      </span>
                    ))}
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function AccountStrategyPanel({
  assignment,
  attribution,
  contribution,
  selectedStrategy,
  strategyCatalog,
  loading,
  error,
  attributionLoading,
  attributionError,
  contributionLoading,
  contributionError,
  instruments,
  assigning,
  assignError,
  onAssignSelected,
}: {
  assignment: AccountStrategyAssignment | null;
  attribution: AccountStrategyAttributionSummary | null;
  contribution: AccountStrategyContributionReport | null;
  selectedStrategy: BacktestStrategyInfo;
  strategyCatalog: BacktestStrategyInfo[];
  loading: boolean;
  error: boolean;
  attributionLoading: boolean;
  attributionError: boolean;
  contributionLoading: boolean;
  contributionError: boolean;
  instruments: InstrumentDisplayRecord[];
  assigning: boolean;
  assignError: boolean;
  onAssignSelected: () => void;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const strategyInfo =
    strategyCatalog.find(
      (item) =>
        item.strategy_id === assignment?.strategy_id ||
        item.name === assignment?.strategy_id,
    ) ?? null;
  const strategyName = assignment
    ? strategyDisplayName(
        strategyInfo ?? {
          strategy_id: assignment.strategy_id,
          name: assignment.strategy_name,
        },
        labels.strategyNames,
      )
    : labels.notDeclared;
  const status = assignment
    ? lookupLabel(
        labels.accountStrategyStatus,
        assignment.status,
        formatPublicStatus(assignment.status, locale),
      )
    : labels.notDeclared;
  const assignmentAttributionStatus = assignment
    ? lookupLabel(
        labels.accountStrategyAttribution,
        assignment.attribution_status,
        formatPublicStatus(assignment.attribution_status, locale),
      )
    : labels.notDeclared;
  const scope = assignment
    ? lookupLabel(
        labels.accountStrategyScope,
        assignment.scope,
        formatPublicStatus(assignment.scope, locale),
      )
    : labels.notDeclared;
  const scopeValue =
    assignment?.symbol && assignment.scope === 'symbol'
      ? `${scope} · ${assignment.symbol}`
      : scope;
  const selectedStrategyName = strategyDisplayName(
    selectedStrategy,
    labels.strategyNames,
  );
  const selectedIsAssigned =
    assignment?.strategy_id === selectedStrategy.name ||
    assignment?.strategy_id === selectedStrategy.strategy_id;
  const pnlAttributionTier = accountStrategyPnlAttributionTier(
    attribution,
    contribution,
  );
  const rawAttributionStatus = attribution?.attribution_status ?? 'not_started';
  const rawContributionStatus =
    contribution?.contribution_status ?? 'no_linked_fills';
  const rawAttributionLabel = lookupLabel(
    labels.accountStrategyAttribution,
    rawAttributionStatus,
    formatPublicStatus(rawAttributionStatus, locale),
  );
  const rawContributionLabel = lookupLabel(
    labels.accountStrategyContributionStatusMap,
    rawContributionStatus,
    formatPublicCode(rawContributionStatus, locale),
  );

  return (
    <section className="app-terminal-panel rounded-[28px] p-[1px]">
      <div className="app-terminal-inner rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.accountStrategyKicker}
            </div>
            <h2 className="app-card-title mt-1.5">
              {labels.accountStrategyTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.accountStrategyDetail}
            </p>
          </div>
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.accountStrategyAutoTradeOff}
          </span>
        </div>

        <div className="mt-4 flex min-w-0 flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="app-muted min-w-0 text-sm leading-6">
            {labels.accountStrategySelectedHint(selectedStrategyName)}
          </p>
          <button
            className="app-button-secondary shrink-0 rounded-2xl px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
            disabled={loading || error || assigning || selectedIsAssigned}
            onClick={onAssignSelected}
            type="button"
          >
            {selectedIsAssigned
              ? labels.accountStrategyAssigned
              : assigning
                ? labels.accountStrategyAssigning
                : labels.accountStrategyAssignSelected}
          </button>
        </div>

        {loading ? (
          <p className="app-muted mt-4 text-sm">
            {labels.accountStrategyLoading}
          </p>
        ) : error ? (
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyUnavailable}
          </p>
        ) : (
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatusTile label={labels.strategy} value={strategyName} />
            <StatusTile label={labels.promotionReadiness} value={status} />
            <StatusTile label={labels.assetUniverse} value={scopeValue} />
            <StatusTile
              label={labels.totalReturn}
              value={assignmentAttributionStatus}
            />
          </div>
        )}

        {assignError ? (
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
            {labels.accountStrategyAssignFailed}
          </p>
        ) : null}

        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.accountStrategyPnlAttributionStatus}
          </div>
          <div className="mt-2 text-lg font-semibold text-[var(--app-text)]">
            {lookupLabel(
              labels.accountStrategyPnlAttributionTier,
              pnlAttributionTier,
              pnlAttributionTier,
            )}
          </div>
          <p className="app-muted mt-1 text-sm leading-6">
            {lookupLabel(
              labels.accountStrategyPnlAttributionTierDetail,
              pnlAttributionTier,
              pnlAttributionTier,
            )}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-[var(--app-muted)]">
              {labels.accountStrategyAttributionSourceStatus}:{' '}
              {rawAttributionLabel}
            </span>
            <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-[var(--app-muted)]">
              {labels.accountStrategyContributionSourceStatus}:{' '}
              {rawContributionLabel}
            </span>
            {rawContributionStatus === 'valuation_missing' ? (
              <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-[var(--app-warning)]">
                {labels.accountStrategyValuationStale}
              </span>
            ) : null}
            {rawAttributionStatus === 'blocked' ? (
              <span className="rounded-full border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-3 py-1.5 text-[var(--app-danger)]">
                {rawAttributionLabel}
              </span>
            ) : null}
          </div>
        </div>

        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
              {labels.accountStrategyAttributionEvidence}
            </div>
            {attributionLoading ? (
              <span className="app-muted text-xs">
                {labels.accountStrategyAttributionLoading}
              </span>
            ) : null}
          </div>
          {attributionError ? (
            <p className="mt-3 text-sm text-[var(--app-warning)]">
              {labels.accountStrategyAttributionUnavailable}
            </p>
          ) : attribution ? (
            <>
              <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <StatusTile
                  label={labels.accountStrategySignalActionRisk}
                  value={`${attribution.signal_count} / ${attribution.action_count} / ${attribution.risk_decision_count}`}
                />
                <StatusTile
                  label={labels.accountStrategyOrdersFills}
                  value={`${attribution.order_count} / ${attribution.fill_count}`}
                />
                <StatusTile
                  label={labels.accountStrategyPnlStatus}
                  value={lookupLabel(
                    labels.accountStrategyAttribution,
                    attribution.attribution_status,
                    formatPublicStatus(attribution.attribution_status, locale),
                  )}
                />
                <StatusTile
                  label={labels.totalCost}
                  value={formatCurrency(attribution.total_fees)}
                />
              </div>
              {attribution.limitations.length ? (
                <div className="mt-3 grid gap-2">
                  {attribution.limitations.map((limitation) => (
                    <p
                      className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_14%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
                      key={limitation}
                    >
                      {formatPublicNote(limitation, locale)}
                    </p>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}
        </div>

        <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
              {labels.accountStrategyContributionReport}
            </div>
            {contributionLoading ? (
              <span className="app-muted text-xs">
                {labels.accountStrategyContributionLoading}
              </span>
            ) : null}
          </div>
          {contributionError ? (
            <p className="mt-3 text-sm text-[var(--app-warning)]">
              {labels.accountStrategyContributionUnavailable}
            </p>
          ) : contribution ? (
            <>
              <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <StatusTile
                  label={labels.accountStrategyContributionStatus}
                  value={lookupLabel(
                    labels.accountStrategyContributionStatusMap,
                    contribution.contribution_status,
                    formatPublicCode(contribution.contribution_status, locale),
                  )}
                />
                <StatusTile
                  label={labels.accountStrategyGrossRealizedPnl}
                  value={formatCurrency(contribution.gross_realized_pnl)}
                />
                <StatusTile
                  label={labels.accountStrategyGrossUnrealizedPnl}
                  value={formatCurrency(contribution.gross_unrealized_pnl)}
                />
                <StatusTile
                  label={labels.accountStrategyCommissionSlippage}
                  value={`${formatCurrency(contribution.total_commission)} / ${formatCurrency(contribution.total_slippage)}`}
                />
                <StatusTile
                  label={labels.accountStrategyTax}
                  value={formatCurrency(contribution.total_tax)}
                />
                <StatusTile
                  label={labels.accountStrategyManualCashFlowMovement}
                  value={`${formatCurrency(contribution.manual_unattributed_pnl)} / ${formatCurrency(contribution.cash_flow_pnl)}`}
                />
                <StatusTile
                  label={labels.accountStrategyTaxExcludedMovement}
                  value={`${formatCurrency(contribution.total_tax)} / ${formatCurrency(contribution.unattributed_account_pnl)}`}
                />
                <StatusTile
                  label={labels.accountStrategyNetContribution}
                  value={formatCurrency(contribution.net_contribution)}
                />
              </div>
              {contribution.missing_valuation_symbols.length ? (
                <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                  {labels.accountStrategyMissingValuation(
                    formatInstrumentDisplayLabelsBySymbol(
                      contribution.missing_valuation_symbols,
                      instruments,
                    ),
                  )}
                </p>
              ) : null}
              {contribution.limitations.length ? (
                <div className="mt-3 grid gap-2">
                  {contribution.limitations.map((limitation) => (
                    <p
                      className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_14%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
                      key={limitation}
                    >
                      {formatPublicNote(limitation, locale)}
                    </p>
                  ))}
                </div>
              ) : null}
            </>
          ) : null}
        </div>

        <div className="mt-4 grid gap-2">
          <p className="app-muted text-sm">
            {labels.accountStrategyPnlPending}
          </p>
          {assignment?.limitations?.map((limitation) => (
            <p
              className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
              key={limitation}
            >
              {formatPublicNote(limitation, locale)}
            </p>
          ))}
        </div>
      </div>
    </section>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3">
      <div className="app-muted text-xs font-semibold">{label}</div>
      <div className="mt-1.5 truncate text-base font-semibold text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

function StrategySignalPreviewPanel({
  preview,
  loading,
  error,
  singleAsset,
  onRiskPreview,
  onPaperShadowPreview,
  riskPreviewResult,
  riskPreviewLoading,
  riskPreviewError,
  paperShadowPreviewResult,
  paperShadowPreviewLoading,
  paperShadowPreviewError,
  attributionPreviewResult,
  attributionPreviewLoading,
  attributionPreviewError,
}: {
  preview: StrategySignalPreviewResponse | null;
  loading: boolean;
  error: boolean;
  singleAsset: { symbol: string; asset_class: string } | null;
  onRiskPreview: (payload: BacktestRiskPreviewRequest) => void;
  onPaperShadowPreview: (payload: BacktestPaperShadowPreviewRequest) => void;
  riskPreviewResult: BacktestRiskPreviewResponse | null;
  riskPreviewLoading: boolean;
  riskPreviewError: boolean;
  paperShadowPreviewResult: BacktestPaperShadowPreviewResponse | null;
  paperShadowPreviewLoading: boolean;
  paperShadowPreviewError: boolean;
  attributionPreviewResult: BacktestAttributionPreviewResponse | null;
  attributionPreviewLoading: boolean;
  attributionPreviewError: boolean;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const output = preview?.outputs[0] ?? null;
  const [riskQuantity, setRiskQuantity] = useState('');
  const dataQuality = output?.evidence.data_quality_status ?? 'unknown';
  const referencePrice = output?.price ?? output?.evidence.reference_price;
  const parsedReferencePrice =
    referencePrice === null || referencePrice === undefined
      ? null
      : Number(referencePrice);
  const referencePriceText =
    parsedReferencePrice !== null && Number.isFinite(parsedReferencePrice)
      ? formatCurrency(parsedReferencePrice)
      : labels.notDeclared;
  const actionLabel = output
    ? signalPreviewActionLabel(output, locale, labels)
    : labels.notDeclared;
  const reviewGates = output?.review_gates ?? [];
  const gateRequired = output
    ? output.requires_risk_gate ||
      output.requires_account_truth_gate ||
      output.requires_paper_shadow_review ||
      output.requires_manual_review
    : false;
  const riskPreviewable =
    Boolean(output && singleAsset) &&
    (output?.action === 'buy' || output?.action === 'sell') &&
    parsedReferencePrice !== null &&
    Number.isFinite(parsedReferencePrice) &&
    parsedReferencePrice > 0;
  const paperShadowPreviewable =
    riskPreviewable && Boolean(riskPreviewResult?.passed);

  useEffect(() => {
    setRiskQuantity('');
  }, [output?.output_id]);

  const submitRiskPreview = () => {
    if (!preview || !output || !singleAsset || !riskPreviewable) {
      return;
    }
    const quantity = Number(riskQuantity);
    if (
      !Number.isFinite(quantity) ||
      quantity <= 0 ||
      parsedReferencePrice === null
    ) {
      return;
    }
    onRiskPreview({
      strategy: preview.strategy_id,
      symbol: output.symbol,
      asset_class: singleAsset.asset_class,
      action: output.action,
      quantity,
      reference_price: parsedReferencePrice,
      target_weight: output.target_weight ?? null,
      data_quality_status: dataQuality,
    });
  };
  const submitPaperShadowPreview = () => {
    if (
      !preview ||
      !output ||
      !singleAsset ||
      !paperShadowPreviewable ||
      parsedReferencePrice === null
    ) {
      return;
    }
    const quantity = Number(riskQuantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return;
    }
    onPaperShadowPreview({
      strategy: preview.strategy_id,
      symbol: output.symbol,
      asset_class: singleAsset.asset_class,
      action: output.action,
      quantity,
      reference_price: parsedReferencePrice,
      target_weight: output.target_weight ?? null,
      signal_id: output.output_id,
      dataset_snapshot_id:
        preview.dataset_snapshot_id ?? output.evidence.dataset_snapshot_id,
      risk_preview_passed: riskPreviewResult?.passed ?? false,
      risk_reasons: riskPreviewResult?.reasons ?? [],
    });
  };

  return (
    <div className="rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-4">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
            {labels.signalPreviewKicker}
          </div>
          <h3 className="mt-1.5 text-base font-semibold text-[var(--app-text)]">
            {labels.signalPreviewTitle}
          </h3>
          <p className="app-muted mt-2 text-sm leading-6">
            {labels.signalPreviewDetail}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
          {labels.signalPreviewResearchOnly}
        </span>
      </div>

      {!singleAsset ? (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewSkipped}</p>
      ) : loading ? (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewLoading}</p>
      ) : error ? (
        <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
          {labels.signalPreviewUnavailable}
        </p>
      ) : output ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <MetadataItem
              label={labels.signalPreviewAction}
              value={actionLabel}
            />
            <MetadataItem
              label={labels.signalPreviewDataQualityLabel}
              value={formatPublicStatus(dataQuality, locale)}
            />
            <MetadataItem
              label={labels.signalPreviewBars}
              value={labels.signalPreviewBarCount(
                output.evidence.bar_count ?? 0,
              )}
            />
            <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_22%,transparent)] px-3 py-2">
              <div className="app-muted text-[11px]">
                {labels.signalPreviewReferencePriceLabel}
              </div>
              <div className="mt-1 truncate text-sm font-semibold tabular-nums">
                {labels.signalPreviewReferencePrice(referencePriceText)}
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewReason}
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--app-text)]">
                {signalPreviewReason(output, labels)}
              </p>
            </div>
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewDataset}
              </div>
              <p className="mt-2 break-words text-sm font-semibold text-[var(--app-text)]">
                {preview?.dataset_snapshot_id ??
                  output.evidence.dataset_snapshot_id ??
                  labels.notDeclared}
              </p>
              <p className="app-muted mt-2 text-sm leading-6">
                {labels.signalPreviewDataQuality(
                  formatPublicStatus(dataQuality, locale),
                )}
              </p>
            </div>
          </div>
          {reviewGates.length > 0 ? (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="app-muted text-xs font-semibold">
                {labels.signalPreviewReviewGates}
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
                {reviewGates.map((gate) => (
                  <div
                    key={`${gate.key}:${gate.status}`}
                    className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] px-3 py-2"
                  >
                    <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                      {signalPreviewGateLabel(gate, labels)}
                    </div>
                    <div className="app-muted mt-1 truncate text-xs">
                      {formatPublicStatus(gate.status, locale)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {riskPreviewable ? (
            <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_16%,transparent)] px-4 py-3">
              <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <label className="grid min-w-0 flex-1 gap-2 text-sm font-medium">
                  {labels.signalPreviewRiskQuantity}
                  <input
                    aria-label={labels.signalPreviewRiskQuantity}
                    className="app-field rounded-2xl px-4 py-3 text-sm tabular-nums"
                    min="1"
                    step="1"
                    type="number"
                    value={riskQuantity}
                    onChange={(event) => setRiskQuantity(event.target.value)}
                  />
                </label>
                <button
                  className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={
                    riskPreviewLoading || !isPositiveNumber(riskQuantity)
                  }
                  onClick={submitRiskPreview}
                  type="button"
                >
                  {riskPreviewLoading
                    ? labels.signalPreviewRiskPreviewLoading
                    : labels.signalPreviewRiskPreviewButton}
                </button>
              </div>
              {riskPreviewError ? (
                <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                  {labels.signalPreviewRiskPreviewUnavailable}
                </p>
              ) : riskPreviewResult ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3">
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="app-muted text-xs font-semibold">
                        {labels.signalPreviewRiskPreviewTitle}
                      </div>
                      <div
                        className={`mt-1 text-base font-semibold ${
                          riskPreviewResult.passed
                            ? 'text-[var(--app-profit)]'
                            : 'text-[var(--app-danger)]'
                        }`}
                      >
                        {riskPreviewResult.passed
                          ? labels.signalPreviewRiskPassed
                          : labels.signalPreviewRiskBlocked}
                      </div>
                    </div>
                    {riskPreviewResult.does_not_create_order ? (
                      <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
                        {labels.signalPreviewRiskNoOrder}
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(riskPreviewResult.reasons.length
                      ? riskPreviewResult.reasons
                      : [riskPreviewResult.status]
                    ).map((reason) => (
                      <span
                        className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-muted)]"
                        key={reason}
                      >
                        {signalPreviewRiskReasonLabel(reason, locale, labels)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="app-muted mt-3 text-sm leading-6">
                  {labels.signalPreviewRiskPending}
                </p>
              )}
              {riskPreviewResult ? (
                <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3">
                  <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0">
                      <div className="app-muted text-xs font-semibold">
                        {labels.signalPreviewPaperShadowTitle}
                      </div>
                      <p className="app-muted mt-1 text-sm leading-6">
                        {paperShadowPreviewable
                          ? labels.signalPreviewPaperShadowReady
                          : labels.signalPreviewPaperShadowBlocked}
                      </p>
                    </div>
                    <button
                      className="app-button-secondary rounded-2xl px-4 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={
                        paperShadowPreviewLoading || !paperShadowPreviewable
                      }
                      onClick={submitPaperShadowPreview}
                      type="button"
                    >
                      {paperShadowPreviewLoading
                        ? labels.signalPreviewPaperShadowLoading
                        : labels.signalPreviewPaperShadowButton}
                    </button>
                  </div>
                  {paperShadowPreviewError ? (
                    <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                      {labels.signalPreviewPaperShadowUnavailable}
                    </p>
                  ) : paperShadowPreviewResult ? (
                    <PaperShadowPreviewResult
                      result={paperShadowPreviewResult}
                    />
                  ) : null}
                  {attributionPreviewLoading ? (
                    <p className="app-muted mt-3 text-sm">
                      {labels.signalPreviewAttributionLoading}
                    </p>
                  ) : attributionPreviewError ? (
                    <p className="mt-3 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm text-[var(--app-warning)]">
                      {labels.signalPreviewAttributionUnavailable}
                    </p>
                  ) : attributionPreviewResult ? (
                    <AttributionPreviewResult
                      result={attributionPreviewResult}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
          <p className="mt-4 rounded-2xl border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm font-semibold text-[var(--app-warning)]">
            {gateRequired
              ? labels.signalPreviewGateRequired
              : labels.signalPreviewNoGateRequired}
          </p>
          <p className="app-muted mt-3 text-xs leading-5">
            {labels.signalPreviewExecutionBoundary}
          </p>
        </>
      ) : (
        <p className="app-muted mt-4 text-sm">{labels.signalPreviewPending}</p>
      )}
    </div>
  );
}

function signalPreviewActionLabel(
  output: StrategySignalPreviewOutput,
  locale: 'en' | 'zh',
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (output.action === 'buy') {
    return labels.signalPreviewActions.buy;
  }
  if (output.action === 'sell') {
    return labels.signalPreviewActions.sell;
  }
  if (output.action === 'rebalance') {
    return labels.signalPreviewActions.rebalance;
  }
  if (output.action === 'no_action') {
    return labels.signalPreviewActions.no_action;
  }
  return formatPublicStatus(output.action, locale);
}

function signalPreviewReason(
  output: StrategySignalPreviewOutput,
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (output.action === 'buy') {
    return labels.signalPreviewReasons.buy;
  }
  if (output.action === 'sell') {
    return labels.signalPreviewReasons.sell;
  }
  if (output.action === 'rebalance') {
    return labels.signalPreviewReasons.rebalance;
  }
  return labels.signalPreviewReasons.no_action;
}

function signalPreviewGateLabel(
  gate: NonNullable<StrategySignalPreviewOutput['review_gates']>[number],
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  if (gate.status === 'not_required') {
    return labels.signalPreviewGateLabels.notRequired;
  }
  if (gate.key === 'data') {
    if (['blocked', 'missing', 'unavailable'].includes(gate.status)) {
      return labels.signalPreviewGateLabels.dataBlocked;
    }
    if (['pass', 'ok', 'complete', 'confirmed', 'live'].includes(gate.status)) {
      return labels.signalPreviewGateLabels.dataReady;
    }
    return labels.signalPreviewGateLabels.dataNeedsReview;
  }
  if (gate.key === 'account_truth') {
    return labels.signalPreviewGateLabels.accountTruthRequired;
  }
  if (gate.key === 'risk') {
    return labels.signalPreviewGateLabels.riskRequired;
  }
  if (gate.key === 'paper_shadow') {
    return labels.signalPreviewGateLabels.paperShadowWaiting;
  }
  if (gate.key === 'manual_review') {
    return labels.signalPreviewGateLabels.manualReviewRequired;
  }
  return labels.signalPreviewGateLabels.unknown;
}

function signalPreviewRiskReasonLabel(
  reason: string,
  locale: 'en' | 'zh',
  labels: ReturnType<typeof useCopy>['backtest']['page'],
) {
  const normalized = reason.toLowerCase();
  if (normalized.includes('approved')) {
    return labels.signalPreviewRiskReasonLabels.approved;
  }
  if (normalized.includes('kill switch')) {
    return labels.signalPreviewRiskReasonLabels.killSwitch;
  }
  if (normalized.includes('data quality')) {
    return labels.signalPreviewRiskReasonLabels.dataQuality;
  }
  if (normalized.includes('cash reserve')) {
    return labels.signalPreviewRiskReasonLabels.cashReserve;
  }
  if (normalized.includes('order notional')) {
    return labels.signalPreviewRiskReasonLabels.orderNotional;
  }
  if (normalized.includes('position weight')) {
    return labels.signalPreviewRiskReasonLabels.positionWeight;
  }
  return formatPublicStatus(reason, locale);
}

function PaperShadowPreviewResult({
  result,
}: {
  result: BacktestPaperShadowPreviewResponse;
}) {
  const labels = useCopy().backtest.page;
  const fill = result.fill;
  const fillPrice = Number(fill?.fill_price ?? 0);
  const fillQuantity = fill?.fill_quantity ?? '--';
  const totalFee = Number(
    fill?.fee_breakdown?.total_fee ?? fill?.commission ?? 0,
  );
  const hasFill = result.status === 'simulated' && fill !== null;

  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div>
          <div className="app-muted text-xs font-semibold">
            {labels.signalPreviewPaperShadowResultTitle}
          </div>
          <div className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {hasFill
              ? labels.signalPreviewPaperShadowSimulatedFill
              : labels.signalPreviewPaperShadowBlockedResult}
          </div>
        </div>
        {result.does_not_mutate_ledger ? (
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.signalPreviewPaperShadowNoLedgerMutation}
          </span>
        ) : null}
      </div>
      {hasFill ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <MetadataItem
            label={labels.signalPreviewPaperShadowFill}
            value={labels.signalPreviewPaperShadowFillSummary(
              String(fillQuantity),
              formatCurrency(fillPrice),
            )}
          />
          <MetadataItem
            label={labels.signalPreviewPaperShadowFee}
            value={labels.signalPreviewPaperShadowEstimatedFee(
              formatCurrency(totalFee),
            )}
          />
        </div>
      ) : (
        <p className="app-muted mt-3 text-sm leading-6">
          {labels.signalPreviewPaperShadowBlocked}
        </p>
      )}
    </div>
  );
}

function AttributionPreviewResult({
  result,
}: {
  result: BacktestAttributionPreviewResponse;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const previewEvidence =
    result.evidence_counts.signal_preview +
    result.evidence_counts.risk_preview +
    result.evidence_counts.paper_shadow_order +
    result.evidence_counts.paper_shadow_fill;
  const productionFacts =
    result.evidence_counts.production_order +
    result.evidence_counts.production_fill;
  const isReady = result.status === 'ready_for_review_linkage';

  return (
    <div className="mt-4 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_20%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
        <div>
          <div className="app-muted text-xs font-semibold">
            {labels.signalPreviewAttributionTitle}
          </div>
          <div className="mt-1 text-base font-semibold text-[var(--app-text)]">
            {isReady
              ? labels.signalPreviewAttributionReady
              : labels.signalPreviewAttributionIncomplete}
          </div>
        </div>
        {!result.can_attribute_pnl ? (
          <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--app-warning)]">
            {labels.signalPreviewAttributionNoPnl}
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <MetadataItem
          label={labels.signalPreviewAttributionEvidence}
          value={labels.signalPreviewAttributionEvidenceSummary(
            previewEvidence,
            productionFacts,
          )}
        />
        <MetadataItem
          label={labels.signalPreviewAttributionBoundary}
          value={labels.signalPreviewAttributionPreviewOnly}
        />
      </div>
      {result.review_linkage_candidate ? (
        <div className="mt-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_28%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] px-4 py-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.signalPreviewReviewLinkageTitle}
              </div>
              <p className="app-muted mt-1 text-sm leading-5">
                {labels.signalPreviewReviewLinkageDetail}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {result.review_linkage_candidate.manual_confirmation_required ? (
                <span className="rounded-full border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-1 text-xs font-semibold text-[var(--app-warning)]">
                  {labels.signalPreviewReviewLinkageManual}
                </span>
              ) : null}
              {result.review_linkage_candidate.does_not_create_order &&
              result.review_linkage_candidate.does_not_mutate_ledger ? (
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-muted)]">
                  {labels.signalPreviewReviewLinkageNoWrite}
                </span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      {result.limitations.length ? (
        <div className="mt-3 grid gap-2">
          {result.limitations.map((limitation) => (
            <p
              className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-4 py-3 text-sm text-[var(--app-text)]"
              key={limitation}
            >
              {formatPublicNote(limitation, locale)}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function StrategyEvidenceGatePanel({
  strategyCatalog,
  validation,
  readiness,
  loading,
  error,
}: {
  strategyCatalog: BacktestStrategyInfo[];
  validation: StrategyValidationMatrix | null;
  readiness: StrategyPromotionReadiness | null;
  loading: boolean;
  error: boolean;
}) {
  const labels = useCopy().backtest.page;
  const { locale } = usePreferences();
  const validationRows = validation?.rows ?? [];
  const readinessRows = readiness?.rows ?? [];
  const visibleRows = useMemo(() => {
    const rowsByStrategy = new Map<string, StrategyValidationRow>();
    validationRows.forEach((row) => {
      rowsByStrategy.set(row.strategy_id, row);
    });
    readinessRows.forEach((row) => {
      if (rowsByStrategy.has(row.strategy_id)) {
        return;
      }

      rowsByStrategy.set(row.strategy_id, {
        strategy_id: row.strategy_id,
        benchmark_role: row.benchmark_role,
        requires_out_of_sample_validation: true,
        requires_after_cost_report: true,
        has_out_of_sample_validation: row.has_after_cost_and_oos_evidence,
        has_after_cost_report: row.has_after_cost_and_oos_evidence,
        validation_status: null,
        backtest_result_id: row.backtest_result_id,
        missing_requirements: [],
        is_ready: row.has_after_cost_and_oos_evidence,
      });
    });
    return Array.from(rowsByStrategy.values());
  }, [validationRows, readinessRows]);
  const strategyById = useMemo(
    () =>
      new Map(
        strategyCatalog.flatMap((strategy) => [
          [strategy.strategy_id, strategy],
          [strategy.name, strategy],
        ]),
      ),
    [strategyCatalog],
  );

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]">
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.evidenceGate}</div>
            <h2 className="app-card-title mt-1.5">
              {labels.evidenceGateTitle}
            </h2>
            <p className="app-muted mt-2 max-w-3xl break-words text-sm leading-6">
              {labels.evidenceGateDetail}
            </p>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-2 text-right text-xs tabular-nums sm:min-w-72">
            <EvidenceCount
              label={labels.validationMatrix}
              value={
                validation
                  ? `${validation.ready_strategy_count}/${validation.required_strategy_count}`
                  : '--'
              }
            />
            <EvidenceCount
              label={labels.promotionReadiness}
              value={
                readiness
                  ? `${readiness.promotable_strategy_count}/${readiness.required_strategy_count}`
                  : '--'
              }
            />
          </div>
        </div>

        {loading ? (
          <div className="app-muted mt-4 text-sm">
            {labels.evidenceGateLoading}
          </div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">
            {labels.evidenceGateFailed}
          </div>
        ) : visibleRows.length === 0 ? (
          <div className="app-muted mt-4 rounded-2xl border border-dashed border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] px-4 py-5 text-sm">
            {labels.noEvidenceRows}
          </div>
        ) : (
          <div className="mt-4 min-w-0 overflow-x-auto overscroll-x-contain">
            <table className="min-w-[1060px] table-fixed text-left text-sm">
              <thead>
                <tr className="app-kicker border-b border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] text-[11px] uppercase tracking-[0.16em]">
                  <th className="w-[190px] px-3 py-3">{labels.strategy}</th>
                  <th className="w-[150px] px-3 py-3">
                    {labels.validationMatrix}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.promotionReadiness}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.accountTruthGate}
                  </th>
                  <th className="w-[170px] px-3 py-3">
                    {labels.strategyAttributionGate}
                  </th>
                  <th className="px-3 py-3">{labels.missingRequirements}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => {
                  const readinessRow = readinessRows.find(
                    (item) => item.strategy_id === row.strategy_id,
                  );
                  const strategyInfo = strategyById.get(row.strategy_id);
                  const displayName = strategyInfo
                    ? strategyDisplayName(strategyInfo, labels.strategyNames)
                    : strategyDisplayName(
                        { strategy_id: row.strategy_id, name: row.strategy_id },
                        labels.strategyNames,
                      );
                  const missing = [
                    ...row.missing_requirements,
                    ...(readinessRow?.missing_requirements ?? []),
                  ];
                  return (
                    <tr
                      key={row.strategy_id}
                      className="border-b border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] align-top"
                    >
                      <td className="px-3 py-3">
                        <div className="font-semibold text-[var(--app-text)]">
                          {displayName}
                        </div>
                        <div className="app-muted mt-1 break-all font-mono text-xs tabular-nums">
                          {row.strategy_id}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <EvidenceBadge complete={row.is_ready}>
                          {row.is_ready ? labels.complete : labels.incomplete}
                        </EvidenceBadge>
                      </td>
                      <td className="px-3 py-3">
                        <EvidenceBadge
                          complete={Boolean(readinessRow?.is_promotable)}
                        >
                          {readinessRow
                            ? formatPublicStatus(
                                readinessRow.promotion_status,
                                locale,
                              )
                            : labels.notDeclared}
                        </EvidenceBadge>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5">
                        <div className="font-semibold text-[var(--app-text)]">
                          {readinessRow
                            ? formatPublicStatus(
                                readinessRow.account_truth_gate_status,
                                locale,
                              )
                            : labels.notDeclared}{' '}
                          ·{' '}
                          {formatGateScore(
                            readinessRow?.account_truth_score ?? null,
                          )}
                        </div>
                        <div className="app-muted mt-1">
                          {readinessRow?.has_account_truth_evidence
                            ? labels.accountTruthEvidencePresent
                            : labels.accountTruthEvidenceMissing}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5">
                        <div className="break-words font-semibold text-[var(--app-text)]">
                          {readinessRow
                            ? formatPublicCode(
                                readinessRow.strategy_attribution_status,
                                locale,
                              )
                            : labels.notDeclared}
                        </div>
                        <div className="app-muted mt-1">
                          {readinessRow?.has_strategy_attribution_evidence
                            ? labels.strategyAttributionReady
                            : labels.strategyAttributionPending}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs leading-5 text-[var(--app-muted)]">
                        {missing.length > 0
                          ? formatPublicCodeList(
                              Array.from(new Set(missing)),
                              locale,
                            ).join(' · ')
                          : labels.none}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function EvidenceCount({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <div className="app-muted text-[11px]">{label}</div>
      <div className="mt-1 text-lg font-semibold text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}

function EvidenceBadge({
  complete,
  children,
}: {
  complete: boolean;
  children: string;
}) {
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
        complete
          ? 'bg-[var(--app-success-bg)] text-[var(--app-success)] ring-1 ring-[var(--app-success-border)]'
          : 'bg-[var(--app-warning-bg)] text-[var(--app-warning)] ring-1 ring-[var(--app-warning-border)]'
      }`}
    >
      {children}
    </span>
  );
}

function StrategyMetadataPanel({
  strategy,
  description,
  labels,
}: {
  strategy: BacktestStrategyInfo;
  description: string;
  labels: ReturnType<typeof useCopy>['backtest']['page'];
}) {
  const { locale } = usePreferences();
  const assetUniverse = strategy.asset_universe ?? strategy.benchmark_universe;
  const frequencies = strategy.supported_frequencies;
  const validationBadges = [
    strategy.requires_out_of_sample_validation ? labels.oosRequired : null,
    strategy.requires_after_cost_report ? labels.afterCostRequired : null,
  ].filter(Boolean);
  const validationNoteLabels: Record<string, string> = labels.validationNotes;

  return (
    <section className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] p-4">
      <div className="app-kicker text-[10px] uppercase tracking-[0.14em]">
        {labels.strategyMetadata}
      </div>
      <p className="mt-2 text-sm leading-6 text-[var(--app-text)]">
        {description}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <MetadataItem
          label={labels.assetUniverse}
          value={formatMetadataList(assetUniverse, labels.notDeclared)}
        />
        <MetadataItem
          label={labels.supportedFrequencies}
          value={formatMetadataList(frequencies, labels.notDeclared)}
        />
        <MetadataItem
          label={labels.benchmarkRole}
          value={benchmarkRoleDisplayName(
            strategy.benchmark_role,
            labels.benchmarkRoleNames,
            labels.notDeclared,
          )}
        />
        <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_22%,transparent)] px-3 py-2">
          <div className="app-muted text-[11px]">
            {labels.validationRequirements}
          </div>
          {validationBadges.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {validationBadges.map((badge) => (
                <span
                  key={badge}
                  className="rounded-full border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_10%,transparent)] px-2 py-1 text-[11px] font-semibold text-[var(--app-accent-strong)]"
                >
                  {badge}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-1 text-sm font-semibold">
              {labels.notDeclared}
            </div>
          )}
        </div>
      </div>
      {strategy.validation_notes?.length ? (
        <ul className="mt-3 space-y-1 text-xs leading-5 text-[var(--app-muted)]">
          {strategy.validation_notes.map((note) => (
            <li key={note}>
              {validationNoteLabels[note] ?? formatPublicNote(note, locale)}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function MetadataItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_18%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_22%,transparent)] px-3 py-2">
      <div className="app-muted text-[11px]">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold tabular-nums">
        {value}
      </div>
    </div>
  );
}

function formatMetadataList(values: string[] | undefined, fallback: string) {
  return values && values.length > 0 ? values.join(', ') : fallback;
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
