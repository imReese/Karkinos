import { StatusBadge } from '../../../shared/ui/workbench';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import {
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
import { CashDividendModeControl } from './cash-dividend-mode-control';
import { BacktestCostControls } from './backtest-cost-controls';
import { backtestCostCopy } from '../copy-costs';
import { ParameterComparePanel } from './parameter-compare-panel';
import { ParameterSweepPanel } from './parameter-sweep-panel';
import { StrategyCatalogPanel } from './strategy-catalog-panel';
import { ResearchUniverseEditor } from './research-universe-editor';
import { datasetMatchesResearchInputs } from './backtest-universe';
import { BacktestDraftContext } from './backtest-page-header';

function BacktestSetupForm() {
  const {
    assetClass,
    additionalAssets,
    assetClassOptions,
    costInputs,
    datasetPreparing,
    endDate,
    formError,
    initialCash,
    latestReport,
    labels,
    parameterSchema,
    parameterValues,
    runBacktest,
    runAssets,
    savedResults,
    selectedAssetClassLabel,
    selectedStrategy,
    setAssetClass,
    setEndDate,
    setInitialCash,
    setParameterValues,
    setStartDate,
    setSymbol,
    startDate,
    strategies,
    submitRun,
    symbol,
  } = useBacktestPage();

  return (
    <form
      className={`mt-3 grid min-w-0 gap-4 ${latestReport || savedResults.data?.length ? '' : 'lg:grid-cols-2'}`}
      onSubmit={submitRun}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-2 text-sm font-medium">
          {labels.startDate}
          <input
            className="app-field min-h-11 rounded-[var(--app-radius-control)] px-3 py-2.5 text-sm"
            type="date"
            max={endDate || undefined}
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
            min={startDate || undefined}
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
          disabled={datasetPreparing || runBacktest.isPending}
          onChange={(event) => setInitialCash(event.target.value)}
          aria-label={labels.initialCash}
        />
      </label>

      {strategies.isError || strategies.isPending ? (
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
        </div>
      ) : null}

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
            <label key={param.name} className="grid gap-2 text-sm font-medium">
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
                disabled={datasetPreparing || runBacktest.isPending}
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
        {!additionalAssets.length ? (
          <span className="app-muted text-xs sm:col-span-2">
            {labels.singleSymbolHint}
          </span>
        ) : null}
      </div>
      <ResearchUniverseEditor />

      <ResearchDatasetPanel />
      <CashDividendModeControl />
      <BacktestCostControls
        inputs={costInputs}
        disabled={datasetPreparing || runBacktest.isPending}
      />

      <RunReadinessSummary
        assetClassLabel={selectedAssetClassLabel}
        labels={labels}
        parameterCount={parameterSchema.length}
        selectedStrategy={selectedStrategy}
        symbol={runAssets?.map((asset) => asset.symbol).join(', ') || symbol}
      />

      {formError ? (
        <div
          className="col-span-full rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] px-3 py-2.5 text-sm text-[var(--app-danger)]"
          role="alert"
        >
          {formError}
        </div>
      ) : null}

      <div className="col-span-full flex justify-end border-t border-[var(--app-divider)] pt-3">
        <button
          type="submit"
          className="app-button-primary min-h-11 w-full rounded-[var(--app-radius-control)] px-4 py-2.5 text-sm font-semibold transition active:scale-[0.99] sm:w-auto"
          disabled={runBacktest.isPending || datasetPreparing}
          aria-busy={
            runBacktest.isPending || datasetPreparing ? 'true' : undefined
          }
        >
          {runBacktest.isPending ? labels.running : labels.run}
        </button>
      </div>
    </form>
  );
}

export function BacktestRunSetupPanel() {
  const {
    advancedToolsOpen,
    corporateActionMode,
    datasetPreparing,
    costInputs,
    endDate,
    initialCash,
    handoffLabels,
    labels,
    locale,
    mobileWorkspaceView,
    parameterSchema,
    parameterValues,
    searchDefaults,
    selectedAssetClassLabel,
    selectedDataset,
    runBacktest,
    runAssets,
    universeError,
    selectedStrategy,
    setAdvancedToolsOpen,
    setMobileWorkspaceTouched,
    setStrategy,
    startDate,
    strategy,
    strategyCatalog,
    symbol,
  } = useBacktestPage();
  const advancedDisabledReason =
    (datasetPreparing || runBacktest.isPending
      ? labels.running
      : !startDate || !endDate || startDate > endDate
        ? labels.dateRangeInvalid
        : universeError) ||
    (!datasetMatchesResearchInputs(
      selectedDataset,
      runAssets,
      startDate,
      endDate,
    )
      ? locale === 'zh'
        ? '所选 Dataset 与完整资产篮子或日期不一致，请重新选择或准备。'
        : 'The selected Dataset does not match the complete asset universe or dates. Select or prepare a matching dataset.'
      : !costInputs.valid
        ? backtestCostCopy[locale].invalid
        : undefined);
  return (
    <section
      className="min-w-0 space-y-6"
      hidden={mobileWorkspaceView !== 'setup'}
      data-testid="backtest-run-setup-disclosure"
      id="backtest-mobile-setup"
      aria-labelledby="backtest-tab-setup"
      role="tabpanel"
    >
      <BacktestDraftContext />
      <header>
        <h2 className="app-type-section-title text-[var(--app-text)]">
          {labels.formTitle}
        </h2>
        <p className="app-muted mt-2 text-sm">{labels.formDetail}</p>
      </header>
      <div className="space-y-6">
        <div className="scroll-mt-24" id="backtest-strategy-catalog">
          <StrategyCatalogPanel
            strategyCatalog={strategyCatalog}
            selectedStrategyName={strategy}
            disabled={datasetPreparing || runBacktest.isPending}
            onSelect={setStrategy}
          />
        </div>

        <section className="min-w-0" data-testid="backtest-parameter-panel">
          <div>
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

            <BacktestSetupForm />
            <BacktestResponsiveDisclosure
              detail={labels.advancedToolsDetail}
              id="backtest-advanced-tools"
              open={advancedToolsOpen}
              onToggle={() => {
                setMobileWorkspaceTouched(true);
                setAdvancedToolsOpen((current) => !current);
              }}
              testId="backtest-advanced-tools-disclosure"
              title={labels.advancedToolsTitle}
            >
              <ParameterSweepPanel
                disabledReason={advancedDisabledReason}
                startDate={startDate}
                endDate={endDate}
                initialCash={initialCash}
                costAssumptions={costInputs.assumptions}
                corporateActionMode={corporateActionMode}
                strategy={strategy}
                parameterSchema={parameterSchema}
                parameterValues={parameterValues}
                assets={runAssets}
                datasetId={selectedDataset?.dataset_id}
              />
              <ParameterComparePanel
                disabledReason={advancedDisabledReason}
                startDate={startDate}
                endDate={endDate}
                initialCash={initialCash}
                costAssumptions={costInputs.assumptions}
                corporateActionMode={corporateActionMode}
                strategy={strategy}
                parameterSchema={parameterSchema}
                assets={runAssets}
                datasetId={selectedDataset?.dataset_id}
              />
            </BacktestResponsiveDisclosure>
          </div>
        </section>
      </div>
    </section>
  );
}
