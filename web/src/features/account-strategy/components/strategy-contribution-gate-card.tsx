import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { formatCurrency } from '../../../shared/format';
import {
  formatInstrumentDisplayLabelsBySymbol,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicNote,
} from '../../../shared/public-labels';
import { formatStrategyDisplayName } from '../../../shared/strategy-display';
import type { AccountStrategyContributionReport } from '../api';

type Props = {
  report?: AccountStrategyContributionReport | null;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  instruments?: InstrumentDisplayRecord[];
  variant?: 'full' | 'compact';
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
  instruments = [],
  variant = 'full',
}: Props) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.backtest.page;
  const isCompact = variant === 'compact';
  const isSupported = canShowContribution(report);
  const contributionStatus = (report?.contribution_status ??
    'no_linked_fills') as keyof typeof labels.accountStrategyContributionStatusMap;
  const statusLabel =
    labels.accountStrategyContributionStatusMap[contributionStatus] ??
    formatPublicCode(report?.contribution_status, locale);
  const healthStatus = (report?.strategy_health_status ??
    'needs_review') as keyof typeof labels.accountStrategyHealthStatusMap;
  const healthLabel =
    labels.accountStrategyHealthStatusMap[healthStatus] ??
    formatPublicCode(report?.strategy_health_status, locale);
  const strategyLabel = formatStrategyDisplayName(
    { strategy_id: report?.strategy_id },
    labels.strategyNames,
  );
  const strategyAuditId =
    report?.strategy_id && strategyLabel !== report.strategy_id
      ? report.strategy_id
      : null;

  return (
    <section
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5"
      data-testid="strategy-contribution-gate-card"
      data-variant={variant}
    >
      <div className="app-terminal-inner min-w-0 p-4 sm:p-5">
        <div
          className={`flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between ${
            isCompact ? 'mb-3' : 'mb-4'
          }`}
        >
          <div className="min-w-0">
            <div className="app-product-mark">
              {labels.accountStrategyContributionReport}
            </div>
            <h2
              className={`app-card-title mt-1.5 ${
                isCompact ? 'text-lg' : 'text-xl'
              }`}
            >
              {labels.accountStrategyContributionPublicTitle}
            </h2>
            {isCompact ? null : (
              <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
                {labels.accountStrategyContributionExplanation}
              </p>
            )}
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
          <div className="space-y-3">
            <div
              className={
                isCompact
                  ? 'grid gap-2 sm:grid-cols-2'
                  : 'grid gap-3 sm:grid-cols-2 xl:grid-cols-4'
              }
            >
              <Metric label={labels.strategy} value={strategyLabel} />
              {isCompact ? null : (
                <>
                  <Metric
                    label={labels.accountStrategyGrossRealizedPnl}
                    value={formatCurrency(report.gross_realized_pnl)}
                  />
                  <Metric
                    label={labels.accountStrategyGrossUnrealizedPnl}
                    value={formatCurrency(report.gross_unrealized_pnl)}
                  />
                  <Metric
                    label={labels.accountStrategyCommissionSlippage}
                    value={`${formatCurrency(report.total_commission)} / ${formatCurrency(report.total_slippage)}`}
                  />
                  <Metric
                    label={labels.accountStrategyTax}
                    value={formatCurrency(report.total_tax)}
                  />
                  <Metric
                    label={labels.accountStrategyManualCashFlowMovement}
                    value={`${formatCurrency(report.manual_unattributed_pnl)} / ${formatCurrency(report.cash_flow_pnl)}`}
                  />
                  <Metric
                    label={labels.accountStrategyTaxExcludedMovement}
                    value={`${formatCurrency(report.total_tax)} / ${formatCurrency(report.unattributed_account_pnl)}`}
                  />
                </>
              )}
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
                label={labels.accountStrategyHealthStatus}
                value={healthLabel}
              />
              <Metric
                label={labels.accountStrategyOrdersFills}
                value={String(report.linked_fill_count)}
              />
              {isCompact ? null : (
                <Metric
                  label={labels.accountStrategyEvidenceRefs}
                  value={String(report.evidence_refs.length)}
                />
              )}
            </div>
            {strategyAuditId ? (
              <div className="app-muted text-xs font-semibold">
                {labels.accountStrategyAuditId} {strategyAuditId}
              </div>
            ) : null}
            <ContributionLimitations
              limitations={report.limitations}
              locale={locale}
            />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="app-muted text-sm">
              {labels.accountStrategyContributionHiddenUntilEvidence}
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Metric label={labels.strategy} value={strategyLabel} />
              <Metric
                label={labels.accountStrategyContributionStatus}
                value={statusLabel}
              />
              <Metric
                label={labels.accountStrategyHealthStatus}
                value={healthLabel}
              />
              <Metric
                label={labels.accountStrategyOrdersFills}
                value={String(report?.linked_fill_count ?? 0)}
              />
            </div>
            {strategyAuditId ? (
              <div className="app-muted text-xs font-semibold">
                {labels.accountStrategyAuditId} {strategyAuditId}
              </div>
            ) : null}
            {report?.missing_valuation_symbols.length ? (
              <p className="text-xs font-semibold text-[var(--app-warning)]">
                {labels.accountStrategyMissingValuation(
                  formatInstrumentDisplayLabelsBySymbol(
                    report.missing_valuation_symbols,
                    instruments,
                  ),
                )}
              </p>
            ) : null}
            <ContributionLimitations
              limitations={report?.limitations ?? []}
              locale={locale}
            />
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

function ContributionLimitations({
  limitations,
  locale,
}: {
  limitations: string[];
  locale: 'en' | 'zh';
}) {
  if (limitations.length === 0) {
    return null;
  }

  return (
    <div className="grid gap-2">
      {limitations.map((limitation) => (
        <p
          className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_22%,transparent)] px-3 py-2 text-sm leading-6 text-[var(--app-soft)]"
          key={limitation}
        >
          {formatPublicNote(limitation, locale)}
        </p>
      ))}
    </div>
  );
}
