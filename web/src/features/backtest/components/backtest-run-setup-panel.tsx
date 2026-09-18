import { ChevronDown } from 'lucide-react';

import { StatusBadge } from '../../../shared/ui/workbench';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import {
  buildSingleAsset,
  parameterDescription,
  parameterDisplayName,
} from './backtest-page-model';
import { useBacktestPage } from './backtest-page-context';
import {
  BacktestResponsiveDisclosure,
  RunContextValue,
  RunReadinessSummary,
} from './backtest-page-primitives';
import { ResearchDatasetPanel } from './research-dataset-panel';
import { ParameterComparePanel } from './parameter-compare-panel';
import { ParameterSweepPanel } from './parameter-sweep-panel';
import { StrategyCatalogPanel } from './strategy-catalog-panel';
import { StrategyMetadataPanel } from './strategy-metadata-panel';

export function BacktestRunSetupPanel() {
  const {
    advancedToolsOpen,
    assetClass,
    assetClassOptions,
    endDate,
    datasetPreparing,
    selectedDataset,
    formError,
    handoffLabels,
    initialCash,
    labels,
    mobileWorkspaceView,
    parameterSchema,
    parameterValues,
    runBacktest,
    searchDefaults,
    selectedAssetClassLabel,
    selectedStrategy,
    setAdvancedToolsOpen,
    setAssetClass,
    setEndDate,
    setInitialCash,
    setMobileWorkspaceTouched,
    setMobileWorkspaceView,
    setParameterValues,
    setStartDate,
    setStrategy,
    setSymbol,
    startDate,
    strategies,
    strategy,
    strategyCatalog,
    submitRun,
    symbol,
  } = useBacktestPage();
  return (
    <details
      className={`group min-w-0 xl:border-l xl:border-[var(--app-divider)] xl:pl-6 ${
        mobileWorkspaceView === 'setup' ? '' : 'hidden xl:block'
      }`}
      data-testid="backtest-run-setup-disclosure"
      id="backtest-mobile-setup"
      open={mobileWorkspaceView === 'setup'}
      onToggle={(event) => {
        const nextView = event.currentTarget.open ? 'setup' : 'results';
        if (nextView !== mobileWorkspaceView) {
          setMobileWorkspaceTouched(true);
          setMobileWorkspaceView(nextView);
        }
      }}
      role="tabpanel"
    >
      <summary className="flex min-h-16 cursor-pointer list-none items-start justify-between gap-4 border-y border-[var(--app-divider)] py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-kicker app-type-overline block">
            {labels.formKicker}
          </span>
          <span className="mt-1 block text-sm font-semibold text-[var(--app-text)]">
            {labels.formTitle}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {labels.formDetail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="mt-1 inline-flex size-6 shrink-0 items-center justify-center text-[var(--app-text-secondary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
        >
          <ChevronDown className="size-4" strokeWidth={1.75} />
        </span>
      </summary>

      <div className="space-y-4 border-b border-[var(--app-divider)] py-4">
        <div className="scroll-mt-24" id="backtest-strategy-catalog">
          <StrategyCatalogPanel
            strategyCatalog={strategyCatalog}
            selectedStrategyName={strategy}
            onSelect={setStrategy}
          />
        </div>

        <section
          className="min-w-0 border-y border-[var(--app-divider)]"
          data-testid="backtest-parameter-panel"
        >
          <div className="p-4 sm:p-5">
            {searchDefaults.hasHandoffContext ? (
              <section
                className="mt-4 border-l-2 border-[var(--app-info-indicator)] py-1 pl-3"
                data-testid="backtest-handoff-context"
              >
                <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="app-kicker">{handoffLabels.kicker}</div>
                    <h3 className="app-type-subsection-title mt-1 text-[var(--app-text)]">
                      {handoffLabels.title}
                    </h3>
                    <p className="app-muted mt-1.5 text-xs leading-5">
                      {handoffLabels.detail}
                    </p>
                  </div>
                  <StatusBadge className="shrink-0" tone="warning">
                    {handoffLabels.badge}
                  </StatusBadge>
                </div>
                <div className="mt-3 grid gap-x-4 text-xs sm:grid-cols-3">
                  <RunContextValue
                    label={labels.symbol}
                    value={symbol || labels.notDeclared}
                    numeric
                  />
                  <RunContextValue
                    label={labels.assetClass}
                    value={selectedAssetClassLabel}
                  />
                  <RunContextValue
                    label={labels.strategy}
                    value={strategyDisplayName(
                      selectedStrategy,
                      labels.strategyNames,
                    )}
                  />
                </div>
              </section>
            ) : null}

            <form className="mt-5 grid gap-4" onSubmit={submitRun}>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2 text-sm font-medium">
                  {labels.startDate}
                  <input
                    className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
                    type="date"
                    value={startDate}
                    disabled={datasetPreparing || runBacktest.isPending}
                    onChange={(event) => setStartDate(event.target.value)}
                    aria-label={labels.startDate}
                  />
                </label>
                <label className="grid gap-2 text-sm font-medium">
                  {labels.endDate}
                  <input
                    className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
                    type="date"
                    value={endDate}
                    disabled={datasetPreparing || runBacktest.isPending}
                    onChange={(event) => setEndDate(event.target.value)}
                    aria-label={labels.endDate}
                  />
                </label>
              </div>

              <label className="grid gap-2 text-sm font-medium">
                {labels.initialCash}
                <input
                  className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm tabular-nums"
                  type="number"
                  min="1"
                  step="1"
                  value={initialCash}
                  onChange={(event) => setInitialCash(event.target.value)}
                  aria-label={labels.initialCash}
                />
              </label>

              <div className="grid gap-3">
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
                        className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm tabular-nums"
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

              <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_160px]">
                <label className="grid min-w-0 gap-2 text-sm font-medium">
                  {labels.symbol}
                  <input
                    className="app-field min-h-11 w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm tabular-nums"
                    value={symbol}
                    disabled={datasetPreparing || runBacktest.isPending}
                    onChange={(event) => setSymbol(event.target.value)}
                    placeholder={labels.symbolPlaceholder}
                    aria-label={labels.symbol}
                  />
                </label>
                <label className="grid min-w-0 gap-2 text-sm font-medium">
                  {labels.assetClass}
                  <select
                    className="app-field min-h-11 w-full min-w-0 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
                    value={assetClass}
                    disabled={datasetPreparing || runBacktest.isPending}
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

              <ResearchDatasetPanel />

              <RunReadinessSummary
                assetClassLabel={selectedAssetClassLabel}
                labels={labels}
                parameterCount={parameterSchema.length}
                selectedStrategy={selectedStrategy}
                symbol={symbol}
              />

              {formError ? (
                <div
                  className="rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-3 py-2.5 text-sm text-[var(--app-danger)]"
                  role="alert"
                >
                  {formError}
                </div>
              ) : null}

              <div className="flex flex-col gap-3 border-t border-[var(--app-divider)] pt-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-sm text-xs leading-5 text-[var(--app-text-secondary)]">
                  {labels.decisionHandoffResearchOnly}
                </p>
                <button
                  type="submit"
                  className="app-button-primary min-h-11 w-full rounded-[var(--app-radius-control)] px-4 py-2.5 text-sm font-semibold transition active:scale-[0.99] sm:w-auto"
                  disabled={runBacktest.isPending || datasetPreparing}
                >
                  {runBacktest.isPending ? labels.running : labels.run}
                </button>
              </div>
            </form>
            {!selectedDataset ? (
              <BacktestResponsiveDisclosure
                detail={labels.advancedToolsDetail}
                id="backtest-advanced-tools"
                open={advancedToolsOpen}
                onToggle={() => setAdvancedToolsOpen((current) => !current)}
                testId="backtest-advanced-tools-disclosure"
                title={labels.advancedToolsTitle}
              >
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
              </BacktestResponsiveDisclosure>
            ) : null}
          </div>
        </section>
      </div>
    </details>
  );
}
