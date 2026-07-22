import { useCopy } from '../../../app/copy';
import { EvidenceIdentityDisclosure } from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import {
  formatInstrumentDisplayLabelsBySymbol,
  type InstrumentDisplayRecord,
} from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicStatus,
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
    report.schema_version === 'karkinos.account_strategy_contribution.v2' &&
    report.contribution_status === 'evidence_bound_from_posted_fills' &&
    report.evidence_binding_status === 'bound' &&
    report.linked_fill_count > 0 &&
    report.ledger_posted_fill_count === report.linked_fill_count &&
    report.unposted_linked_fill_count === 0 &&
    Boolean(report.valuation_snapshot_id) &&
    (report.ledger_cutoff_id ?? 0) > 0 &&
    Boolean(report.contribution_fingerprint) &&
    report.evidence_refs.length > 0 &&
    report.missing_valuation_symbols.length === 0 &&
    report.persisted_facts_only === true &&
    report.provider_contacted === false &&
    report.database_writes_performed === false &&
    report.authorizes_execution === false,
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
  const isNotApplicable =
    report?.contribution_status === 'no_linked_fills' &&
    report.linked_fill_count === 0 &&
    (report.unattributed_fill_count ?? 0) === 0;
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
  const bindingStatus = (report?.evidence_binding_status ??
    'blocked') as keyof typeof labels.accountStrategyEvidenceBindingStatusMap;
  const bindingLabel =
    labels.accountStrategyEvidenceBindingStatusMap[bindingStatus] ??
    formatPublicCode(report?.evidence_binding_status, locale);
  const nextAction = report?.next_manual_action
    ? (labels.accountStrategyNextActionMap[
        report.next_manual_action as keyof typeof labels.accountStrategyNextActionMap
      ] ?? formatPublicCode(report.next_manual_action, locale))
    : labels.accountStrategyContributionHiddenUntilEvidence;
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
          <div className="flex flex-wrap items-center gap-2">
            {report ? (
              <EvidenceIdentityDisclosure
                triggerLabel={copy.common.viewEvidenceIdentity}
                title={copy.common.evidenceIdentityTitle}
                description={copy.common.evidenceIdentityDescription}
                closeLabel={copy.common.closeEvidenceIdentity}
                copyLabel={copy.common.copyEvidenceValue}
                copiedLabel={copy.common.evidenceValueCopied}
                fields={[
                  {
                    label: copy.common.valuationSnapshot,
                    value: report.valuation_snapshot_id ?? '--',
                    mono: true,
                  },
                  {
                    label: copy.common.ledgerCutoff,
                    value: report.ledger_cutoff_id ?? '--',
                    mono: true,
                  },
                  {
                    label: copy.common.valuationAsOf,
                    value: formatTimestamp(report.valuation_as_of),
                    mono: true,
                  },
                  {
                    label: copy.common.valuationStatus,
                    value: formatPublicStatus(report.valuation_status, locale),
                  },
                  {
                    label: copy.common.reviewFingerprint,
                    value: report.contribution_fingerprint ?? '--',
                    mono: true,
                  },
                  ...(strategyAuditId
                    ? [
                        {
                          label: labels.accountStrategyAuditId,
                          value: strategyAuditId,
                          mono: true,
                        },
                      ]
                    : []),
                ]}
              />
            ) : null}
            <span
              className={`w-fit rounded-full border px-3 py-1 text-xs font-semibold ${
                isSupported
                  ? 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success-text)]'
                  : isNotApplicable
                    ? 'border-[color-mix(in_srgb,var(--app-border)_55%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_24%,transparent)] text-[var(--app-soft)]'
                    : 'border-[color-mix(in_srgb,var(--app-warning)_45%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_16%,transparent)] text-[var(--app-warning)]'
              }`}
            >
              {isSupported
                ? labels.accountStrategyEvidenceLinked
                : isNotApplicable
                  ? labels.accountStrategyEvidenceNotApplicable
                  : labels.accountStrategyEvidenceRequired}
            </span>
          </div>
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
                </>
              )}
              <Metric
                label={labels.accountStrategyNetContribution}
                value={formatCurrency(report.net_contribution)}
                tone={
                  report.net_contribution === null
                    ? 'neutral'
                    : report.net_contribution >= 0
                      ? 'positive'
                      : 'negative'
                }
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
                label={labels.accountStrategyLedgerPostedFills}
                value={`${report.ledger_posted_fill_count ?? 0} / ${report.linked_fill_count}`}
              />
              {isCompact ? null : (
                <Metric
                  label={labels.accountStrategyEvidenceRefs}
                  value={String(report.evidence_refs.length)}
                />
              )}
            </div>
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
              <Metric
                label={labels.accountStrategyEvidenceBinding}
                value={bindingLabel}
              />
              <Metric
                label={labels.accountStrategyLedgerPostedFills}
                value={`${report?.ledger_posted_fill_count ?? 0} / ${report?.linked_fill_count ?? 0}`}
              />
            </div>
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
            <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_9%,transparent)] px-3 py-3 text-sm leading-6 text-[var(--app-soft)]">
              <div className="text-xs font-semibold text-[var(--app-warning)]">
                {labels.accountStrategyNextManualAction}
              </div>
              <p className="mt-1">{nextAction}</p>
            </div>
            {report?.blockers?.length ? (
              <div className="space-y-1 text-xs text-[var(--app-soft)]">
                <div className="font-semibold">
                  {labels.accountStrategyBlockers}
                </div>
                {report.blockers.map((blocker) => (
                  <div className="break-words" key={blocker}>
                    {formatPublicNote(blocker, locale)}
                  </div>
                ))}
              </div>
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
      ? 'text-[var(--app-pnl-positive)]'
      : tone === 'negative'
        ? 'text-[var(--app-pnl-negative)]'
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
