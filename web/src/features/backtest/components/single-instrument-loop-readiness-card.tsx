import { useCopy } from '../../../shared/i18n/context';
import {
  Register,
  RegisterRow,
  StatusBadge,
} from '../../../shared/ui/workbench';
import type {
  BacktestAttributionPreviewResponse,
  BacktestPaperShadowPreviewResponse,
  BacktestReport,
  BacktestRiskPreviewResponse,
  StrategySignalPreviewResponse,
} from '../api';
import {
  hasAfterCostEvidence,
  hasDatasetSnapshotEvidence,
  type LoopStep,
} from './backtest-page-model';

export function SingleInstrumentLoopReadinessCard({
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
  const nextReviewStep = !hasAfterCostEvidence(report)
    ? labels.singleInstrumentLoopNextBacktest
    : !preview?.outputs.length
      ? labels.singleInstrumentLoopNextSignal
      : !riskPreviewResult
        ? labels.singleInstrumentLoopNextRisk
        : !riskPreviewResult.passed
          ? labels.singleInstrumentLoopNextBlocked
          : paperShadowPreviewResult?.status !== 'simulated'
            ? labels.singleInstrumentLoopNextPaper
            : attributionPreviewResult?.status !== 'ready_for_review_linkage'
              ? labels.singleInstrumentLoopNextAttribution
              : labels.singleInstrumentLoopNextComplete;

  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      data-testid="backtest-loop-readiness-register"
    >
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {labels.singleInstrumentLoopKicker}
          </div>
          <h3 className="app-type-subsection-title mt-1.5 text-[var(--app-text)]">
            {labels.singleInstrumentLoopTitle}
          </h3>
          <p className="app-muted mt-2 text-sm leading-6">
            {labels.singleInstrumentLoopDetail}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <StatusBadge
            tone={blocked ? 'danger' : allReady ? 'success' : 'warning'}
          >
            {statusLabel}
          </StatusBadge>
          <span className="font-mono text-xs font-semibold tabular-nums text-[var(--app-text-secondary)]">
            {readyCount}/{steps.length}
          </span>
        </div>
      </div>

      <div className="mt-4 flex min-w-0 flex-col gap-2 border-l-2 border-[var(--app-accent-border)] py-1 pl-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {labels.singleInstrumentLoopNextStep}
          </div>
          <p className="mt-1 text-sm font-semibold text-[var(--app-text)]">
            {nextReviewStep}
          </p>
        </div>
        <a
          className="app-link shrink-0 text-xs font-semibold"
          href="#backtest-signal-review-evidence"
        >
          {labels.singleInstrumentLoopEvidenceCta}
        </a>
      </div>

      <Register ariaLabel={labels.singleInstrumentLoopTitle} className="mt-4">
        {steps.map((step) => (
          <RegisterRow
            key={step.key}
            label={step.label}
            value={
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    step.state === 'ready'
                      ? 'bg-[var(--app-success-indicator)]'
                      : step.state === 'blocked'
                        ? 'bg-[var(--app-danger-indicator)]'
                        : 'bg-[var(--app-warning-indicator)]'
                  }`}
                />
                <a
                  aria-label={step.evidenceLabel}
                  className="app-link min-w-0 text-xs font-semibold"
                  href={step.evidenceHref}
                >
                  {labels.singleInstrumentLoopEvidenceCta}
                </a>
              </span>
            }
          />
        ))}
      </Register>
    </section>
  );
}
