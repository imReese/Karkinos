import { useCopy } from '../../../app/copy';
import { formatCurrency } from '../../../shared/format';
import type { AccountStrategyContributionReport } from '../api';

type Props = {
  report?: AccountStrategyContributionReport | null;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
};

function canShowContribution(
  report?: AccountStrategyContributionReport | null,
) {
  return Boolean(
    report &&
    report.contribution_status === 'estimated_from_linked_fills' &&
    report.linked_fill_count > 0 &&
    report.evidence_refs.length > 0 &&
    report.missing_valuation_symbols.length === 0,
  );
}

export function StrategyContributionGateCard({
  report,
  isLoading = false,
  isError = false,
  onRetry,
}: Props) {
  const copy = useCopy();
  const labels = copy.backtest.page;
  const isSupported = canShowContribution(report);
  const contributionStatus = (report?.contribution_status ??
    'no_linked_fills') as keyof typeof labels.accountStrategyContributionStatusMap;
  const statusLabel =
    labels.accountStrategyContributionStatusMap[contributionStatus] ??
    report?.contribution_status ??
    '--';

  return (
    <section className="app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5">
      <div className="app-terminal-inner min-w-0 p-4 sm:p-5">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.accountStrategyContributionReport}
            </div>
            <h2 className="app-card-title mt-1.5 text-xl">
              {labels.accountStrategyContributionPublicTitle}
            </h2>
          </div>
          <span
            className={`w-fit rounded-full border px-3 py-1 text-xs font-semibold ${
              isSupported
                ? 'border-[color-mix(in_srgb,var(--app-positive)_45%,transparent)] bg-[color-mix(in_srgb,var(--app-positive)_16%,transparent)] text-[var(--app-positive)]'
                : 'border-[color-mix(in_srgb,var(--app-warning)_45%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_16%,transparent)] text-[var(--app-warning)]'
            }`}
          >
            {isSupported
              ? labels.accountStrategyEvidenceLinked
              : labels.accountStrategyEvidenceRequired}
          </span>
        </div>

        {isLoading ? (
          <p className="app-muted text-sm">
            {labels.accountStrategyContributionLoading}
          </p>
        ) : isError ? (
          <div className="space-y-3">
            <p className="app-muted text-sm">
              {labels.accountStrategyContributionUnavailable}
            </p>
            {onRetry ? (
              <button
                type="button"
                className="app-button-secondary rounded-2xl px-4 py-2 text-sm"
                onClick={onRetry}
              >
                {copy.states.retry}
              </button>
            ) : null}
          </div>
        ) : isSupported && report ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <Metric
              label={labels.accountStrategyNetContribution}
              value={formatCurrency(report.net_contribution)}
              tone={report.net_contribution >= 0 ? 'positive' : 'negative'}
            />
            <Metric
              label={labels.accountStrategyContributionStatus}
              value={statusLabel}
            />
            <Metric
              label={labels.accountStrategyOrdersFills}
              value={String(report.linked_fill_count)}
            />
            <Metric
              label={labels.accountStrategyEvidenceRefs}
              value={String(report.evidence_refs.length)}
            />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="app-muted text-sm">
              {labels.accountStrategyContributionHiddenUntilEvidence}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Metric
                label={labels.accountStrategyContributionStatus}
                value={statusLabel}
              />
              <Metric
                label={labels.accountStrategyOrdersFills}
                value={String(report?.linked_fill_count ?? 0)}
              />
            </div>
            {report?.missing_valuation_symbols.length ? (
              <p className="text-xs font-semibold text-[var(--app-warning)]">
                {labels.accountStrategyMissingValuation(
                  report.missing_valuation_symbols.join(', '),
                )}
              </p>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'negative' | 'neutral';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-[var(--app-positive)]'
      : tone === 'negative'
        ? 'text-[var(--app-negative)]'
        : 'text-[var(--app-text)]';
  return (
    <div className="rounded-3xl border border-[color-mix(in_srgb,var(--app-border)_62%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_35%,transparent)] p-3">
      <div className="app-muted text-xs font-semibold">{label}</div>
      <div className={`mt-2 text-lg font-bold tabular-nums ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}
