import { useCopy } from '../../../shared/i18n/context';
import type {
  AcceptanceAuditSummary,
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
  acceptanceAudit,
  auditLoading,
  auditError,
}: {
  report: BacktestReport;
  preview: StrategySignalPreviewResponse | null;
  riskPreviewResult: BacktestRiskPreviewResponse | null;
  paperShadowPreviewResult: BacktestPaperShadowPreviewResponse | null;
  attributionPreviewResult: BacktestAttributionPreviewResponse | null;
  acceptanceAudit: AcceptanceAuditSummary | null;
  auditLoading: boolean;
  auditError: boolean;
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
  const auditCoverageLabel = acceptanceAudit
    ? `${acceptanceAudit.completed_count}/${acceptanceAudit.required_count} ${labels.singleInstrumentLoopAuditVerified}`
    : auditLoading
      ? labels.singleInstrumentLoopAuditLoading
      : labels.singleInstrumentLoopAuditUnavailable;
  const auditDisplayName =
    acceptanceAudit?.key ?? labels.singleInstrumentLoopAuditFallbackKey;
  const auditCardState = acceptanceAudit?.is_complete
    ? 'complete'
    : auditError
      ? 'error'
      : 'pending';

  return (
    <section className="rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] p-4">
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
      <div className="mt-4 flex min-w-0 flex-col gap-2 rounded-2xl border border-[color-mix(in_srgb,var(--app-accent)_30%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-accent)_9%,transparent)] px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {labels.singleInstrumentLoopNextStep}
          </div>
          <p className="mt-1 text-sm font-semibold text-[var(--app-text)]">
            {nextReviewStep}
          </p>
        </div>
        <a
          className="inline-flex shrink-0 items-center justify-center rounded-full border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
          href="#backtest-signal-review-evidence"
        >
          {labels.singleInstrumentLoopEvidenceCta}
        </a>
      </div>
      <div
        className={`mt-3 grid gap-2 rounded-2xl border px-3 py-2.5 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center ${
          auditCardState === 'complete'
            ? 'border-[color-mix(in_srgb,var(--app-success)_28%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)]'
            : auditCardState === 'error'
              ? 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)]'
              : 'border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_12%,transparent)]'
        }`}
      >
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {labels.singleInstrumentLoopAuditCoverage}
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
            <span
              className={`font-semibold ${
                auditCardState === 'complete'
                  ? 'text-[var(--app-success)]'
                  : auditCardState === 'error'
                    ? 'text-[var(--app-warning)]'
                    : 'text-[var(--app-muted)]'
              }`}
            >
              {auditCoverageLabel}
            </span>
            <code className="app-type-micro min-w-0 break-all rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)] px-2.5 py-1 font-semibold text-[var(--app-muted)]">
              {auditDisplayName}
            </code>
          </div>
        </div>
        <p className="app-muted min-w-0 text-xs leading-5 sm:max-w-sm sm:text-right">
          {labels.singleInstrumentLoopAuditBoundary}
        </p>
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
              className="app-type-micro mt-2 inline-flex max-w-full items-center rounded-full border border-[color-mix(in_srgb,currentColor_24%,transparent)] px-2.5 py-1 font-semibold text-inherit opacity-85 transition hover:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
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
