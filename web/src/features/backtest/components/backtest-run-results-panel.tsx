import { formatCurrency, formatPercent } from '../../../shared/format';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import { StatusBadge } from '../../../shared/ui/workbench';
import { BacktestReportView } from './backtest-report-view';
import { useBacktestPage } from './backtest-page-context';
import { RunContextValue } from './backtest-page-primitives';
import { DatasetSnapshotPanel } from './dataset-snapshot-panel';
import { EquityDrawdownChart } from './equity-drawdown-chart';
import { FillsTable } from './fills-table';
import { MetricsGrid } from './metrics-grid';
import { SingleInstrumentLoopReadinessCard } from './single-instrument-loop-readiness-card';
import { StrategySignalPreviewPanel } from './strategy-signal-preview-panel';
import { SummaryValue } from './strategy-metadata-panel';
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
    signalPreview,
    singleInstrumentAudit,
    summary,
  } = useBacktestPage();
  return (
    <section
      className={`app-workbench-section min-w-0 ${
        mobileWorkspaceView === 'results' ? '' : 'hidden xl:block'
      }`}
      data-testid="backtest-result-panel"
      id="backtest-mobile-results"
      role="tabpanel"
    >
      <div className="p-4 sm:p-5">
        {latestReport ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="app-kicker">{labels.currentKicker}</div>
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
                    tone="pnl-negative"
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
            <div className="mt-5 space-y-5">
              <EquityDrawdownChart
                fills={latestReport.fills ?? []}
                points={latestReport.equity_curve}
              />
              <section
                className="border-l-2 border-[var(--app-info-indicator)] py-1 pl-3"
                data-testid="backtest-run-context-summary"
              >
                <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="app-kicker">{labels.runContextKicker}</div>
                    <h3 className="app-type-subsection-title mt-1.5 text-[var(--app-text)]">
                      {labels.runContextTitle}
                    </h3>
                    <p className="app-muted mt-2 text-sm leading-6">
                      {labels.runContextDetail}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {reportSymbol ? (
                      <a
                        className="inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] border border-[var(--app-border)] px-2.5 py-1 text-xs font-semibold text-[var(--app-text)] transition hover:border-[var(--app-accent)] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                        href={`/portfolio/${encodeURIComponent(reportSymbol)}`}
                      >
                        {labels.runContextReviewHolding}
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
                acceptanceAudit={singleInstrumentAudit.data?.audits[0] ?? null}
                auditError={singleInstrumentAudit.isError}
                auditLoading={singleInstrumentAudit.isLoading}
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
              <FillsTable fills={latestReport.fills ?? []} />
            </div>
          </>
        ) : (
          <section
            className="min-w-0"
            data-testid="backtest-persisted-evidence"
          >
            <BacktestReportView />
          </section>
        )}
      </div>
    </section>
  );
}
