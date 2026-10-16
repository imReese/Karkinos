import { useEffect, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';

import { formatTimestamp } from '../../../shared/format';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import { StatusBadge } from '../../../shared/ui/workbench';
import { BacktestReportView } from './backtest-report-view';
import { useBacktestPage } from './backtest-page-context';
import { RunContextValue } from './backtest-page-primitives';
import { DatasetSnapshotPanel } from './dataset-snapshot-panel';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import { CashDividendAccountingPanel } from './cash-dividend-accounting-panel';
import { BacktestCostEvidencePanel } from './backtest-cost-evidence-panel';
import { SingleInstrumentLoopReadinessCard } from './single-instrument-loop-readiness-card';
import { StrategySignalPreviewPanel } from './strategy-signal-preview-panel';
import { ResearchObservationsPanel } from './research-observations-panel';
import { ValidationEvidencePanel } from './validation-evidence-panel';

export function BacktestRunResultsPanel() {
  const {
    attributionPreview,
    labels,
    latestReport,
    mobileWorkspaceView,
    paperShadowPreview,
    reportAssetClassLabel,
    reportStrategy,
    reportSymbol,
    riskPreview,
    runContextSourceLabel,
    setMobileWorkspaceTouched,
    setMobileWorkspaceView,
    signalPreview,
  } = useBacktestPage();
  const [observationsVisited, setObservationsVisited] = useState(false);
  useEffect(() => {
    if (mobileWorkspaceView === 'observations') setObservationsVisited(true);
  }, [mobileWorkspaceView]);
  return (
    <section
      className="min-w-0"
      hidden={mobileWorkspaceView === 'setup'}
      data-testid="backtest-result-panel"
      id="backtest-mobile-results"
      aria-labelledby={`backtest-tab-${mobileWorkspaceView === 'observations' ? 'observations' : 'results'}`}
      role="tabpanel"
      onClick={(event) => {
        if (
          !(event.target instanceof Element) ||
          !event.target.closest('a[href="#backtest-strategy-catalog"]')
        )
          return;
        setMobileWorkspaceTouched(true);
        setMobileWorkspaceView('setup');
        window.setTimeout(
          () =>
            document
              .getElementById('backtest-strategy-catalog')
              ?.scrollIntoView?.({ block: 'start' }),
          0,
        );
      }}
    >
      <div className="min-w-0">
        {latestReport ? (
          <>
            <div
              hidden={mobileWorkspaceView !== 'observations'}
              className="space-y-4"
              data-testid="backtest-current-forward-workspace"
            >
              <h2 className="app-type-section-title">
                {labels.currentTitle} #{latestReport.id}
              </h2>
              <p className="app-muted max-w-3xl text-sm leading-6">
                {labels.observationsDetail}
              </p>
              {observationsVisited || mobileWorkspaceView === 'observations' ? (
                <ResearchObservationsPanel
                  key={latestReport.id}
                  report={latestReport}
                />
              ) : null}
            </div>
            <div
              hidden={mobileWorkspaceView !== 'results'}
              className="space-y-6"
              data-testid="backtest-current-financial-results"
            >
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="app-kicker">{labels.currentKicker}</div>
                  <h2 className="app-type-section-title mt-2">
                    {labels.currentTitle}
                  </h2>
                  <p className="app-muted mt-2 text-sm">
                    {strategyDisplayName(reportStrategy, labels.strategyNames)}{' '}
                    · #{latestReport.id} ·{' '}
                    {formatTimestamp(latestReport.created_at)}
                  </p>
                  <p className="app-muted mt-1 text-xs tabular-nums">
                    {latestReport.metrics_json?.execution_window
                      ? labels.evaluatedInterval
                      : labels.configuredInterval}
                    :{' '}
                    {latestReport.metrics_json?.execution_window
                      ? latestReport.metrics_json.execution_window
                          .metric_start_date &&
                        latestReport.metrics_json.execution_window
                          .metric_end_date
                        ? `${latestReport.metrics_json.execution_window.metric_start_date} → ${latestReport.metrics_json.execution_window.metric_end_date}`
                        : labels.notDeclared
                      : `${latestReport.config.start_date} → ${latestReport.config.end_date}`}
                  </p>
                  <a
                    className="mt-2 inline-flex min-h-8 items-center text-xs text-[var(--app-accent)] hover:underline"
                    href={`/backtest?id=${latestReport.id}`}
                  >
                    {labels.reportPermalink}
                    <ArrowUpRight
                      aria-hidden="true"
                      className="ml-1 size-3.5"
                    />
                  </a>
                </div>
              </div>
              <div className="space-y-6">
                <MetricsGrid report={latestReport} variant="primary" />
                <EquityDrawdownChart
                  fills={latestReport.fills ?? []}
                  points={latestReport.equity_curve}
                />
                <div
                  className="scroll-mt-24 space-y-5"
                  id="backtest-after-cost-evidence"
                >
                  <MetricsGrid report={latestReport} variant="secondary" />
                  <BacktestCostEvidencePanel report={latestReport} />
                  <CashDividendAccountingPanel
                    accounting={
                      latestReport.metrics_json?.cash_dividend_accounting
                    }
                  />
                  <ValidationEvidencePanel report={latestReport} />
                </div>
                <div className="scroll-mt-24" id="backtest-dataset-evidence">
                  <DatasetSnapshotPanel report={latestReport} />
                </div>
                <details className="min-w-0 border-y border-[var(--app-divider)] py-4">
                  <summary className="cursor-pointer text-sm font-semibold">
                    {labels.reportEvidence}
                  </summary>
                  <div className="space-y-6 pt-6">
                    <section
                      className="border-l-2 border-[var(--app-info-indicator)] py-1 pl-3"
                      data-testid="backtest-run-context-summary"
                    >
                      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <div className="app-kicker">
                            {labels.runContextKicker}
                          </div>
                          <h3 className="app-type-subsection-title mt-1 text-[var(--app-text)]">
                            {labels.runContextTitle}
                          </h3>
                        </div>
                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          {reportSymbol ? (
                            <a
                              className="inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] border border-[var(--app-border)] px-2.5 py-1 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent)] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                              href={
                                (latestReport.config.assets?.length ?? 0) > 1
                                  ? '/portfolio'
                                  : `/portfolio/${encodeURIComponent(reportSymbol)}`
                              }
                            >
                              {(latestReport.config.assets?.length ?? 0) > 1
                                ? labels.runContextReviewPortfolio
                                : labels.runContextReviewHolding}
                            </a>
                          ) : null}
                          <StatusBadge tone="warning">
                            {labels.decisionHandoffResearchOnly}
                          </StatusBadge>
                        </div>
                      </div>
                      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
                        <RunContextValue
                          label={labels.runContextSource}
                          value={runContextSourceLabel}
                        />
                        <RunContextValue
                          label={labels.runContextInstrument}
                          value={reportSymbol || labels.notDeclared}
                          numeric
                        />
                        <RunContextValue
                          label={labels.runContextAssetClass}
                          value={reportAssetClassLabel}
                        />
                        <RunContextValue
                          label={labels.runContextStrategy}
                          value={strategyDisplayName(
                            reportStrategy,
                            labels.strategyNames,
                          )}
                        />
                      </div>
                    </section>
                    <SingleInstrumentLoopReadinessCard
                      attributionPreviewResult={attributionPreview.data ?? null}
                      paperShadowPreviewResult={paperShadowPreview.data ?? null}
                      preview={signalPreview.data ?? null}
                      report={latestReport}
                      riskPreviewResult={riskPreview.data ?? null}
                    />
                    <div
                      className="scroll-mt-24"
                      id="backtest-signal-review-evidence"
                    >
                      <StrategySignalPreviewPanel
                        onRiskInputsChange={() => {
                          riskPreview.reset();
                          paperShadowPreview.reset();
                          attributionPreview.reset();
                        }}
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
                                risk_preview_passed:
                                  payload.risk_preview_passed,
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
                        attributionPreviewResult={
                          attributionPreview.data ?? null
                        }
                        paperShadowPreviewError={paperShadowPreview.isError}
                        paperShadowPreviewLoading={paperShadowPreview.isPending}
                        paperShadowPreviewResult={
                          paperShadowPreview.data ?? null
                        }
                        preview={signalPreview.data ?? null}
                        riskPreviewError={riskPreview.isError}
                        riskPreviewLoading={riskPreview.isPending}
                        riskPreviewResult={riskPreview.data ?? null}
                        singleAsset={
                          latestReport.config.assets?.length === 1
                            ? latestReport.config.assets[0]
                            : null
                        }
                      />
                    </div>
                  </div>
                </details>
                <FillsTable fills={latestReport.fills ?? []} />
              </div>
            </div>
          </>
        ) : (
          <section
            className="min-w-0"
            data-testid="backtest-persisted-evidence"
          >
            <BacktestReportView
              view={
                mobileWorkspaceView === 'observations'
                  ? 'observations'
                  : 'results'
              }
            />
          </section>
        )}
      </div>
    </section>
  );
}
