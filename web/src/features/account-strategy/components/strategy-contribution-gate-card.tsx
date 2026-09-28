import { useCopy } from '../../../shared/i18n/context';
import {
  EvidenceIdentityDisclosure,
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../shared/ui/workbench';
import { usePreferences } from '../../../shared/preferences/context';
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
      className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-4 sm:p-5 shadow-xs space-y-4"
      data-testid="strategy-contribution-gate-card"
      data-variant={variant}
    >
      <div
        className={`flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between ${
          isCompact ? 'mb-1' : 'mb-2'
        }`}
      >
        <div className="min-w-0">
          <div className="app-product-mark">
            {labels.accountStrategyContributionReport}
          </div>
          <h2
            className={`mt-1 text-[var(--app-text)] ${
              isCompact ? 'text-base font-semibold' : 'text-lg font-semibold'
            }`}
          >
            {labels.accountStrategyContributionPublicTitle}
          </h2>
          {isCompact ? null : (
            <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
              {labels.accountStrategyContributionExplanation}
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
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
          <StatusBadge
            tone={
              isSupported ? 'success' : isNotApplicable ? 'neutral' : 'warning'
            }
          >
            {isSupported
              ? labels.accountStrategyEvidenceLinked
              : isNotApplicable
                ? labels.accountStrategyEvidenceNotApplicable
                : labels.accountStrategyEvidenceRequired}
          </StatusBadge>
        </div>
      </div>

      {isLoading ? (
        <EvidenceState
          kind="loading"
          title={labels.accountStrategyContributionLoading}
        />
      ) : isError ? (
        <EvidenceState
          kind="error"
          title={labels.accountStrategyContributionUnavailable}
          action={
            onRetry ? (
              <button
                type="button"
                className="app-button-secondary min-h-8 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
                onClick={onRetry}
              >
                {copy.states.retry}
              </button>
            ) : undefined
          }
        />
      ) : isSupported && report ? (
        <div className="space-y-4">
          <MetricStrip
            ariaLabel={labels.accountStrategyContributionPublicTitle}
            className="app-strategy-gate-metric-strip grid grid-cols-2 gap-2 border-0 bg-transparent sm:grid-cols-3 sm:auto-cols-auto sm:grid-flow-row"
            items={[
              {
                id: 'strategy',
                label: labels.strategy,
                value: strategyLabel,
              },
              ...(!isCompact
                ? [
                    {
                      id: 'gross-realized',
                      label: labels.accountStrategyGrossRealizedPnl,
                      value: formatCurrency(report.gross_realized_pnl),
                    },
                    {
                      id: 'gross-unrealized',
                      label: labels.accountStrategyGrossUnrealizedPnl,
                      value: formatCurrency(report.gross_unrealized_pnl),
                    },
                    {
                      id: 'commission-slippage',
                      label: labels.accountStrategyCommissionSlippage,
                      value: `${formatCurrency(report.total_commission)} / ${formatCurrency(report.total_slippage)}`,
                    },
                    {
                      id: 'tax',
                      label: labels.accountStrategyTax,
                      value: formatCurrency(report.total_tax),
                    },
                  ]
                : []),
              {
                id: 'net-contribution',
                label: labels.accountStrategyNetContribution,
                value: formatCurrency(report.net_contribution),
                tone:
                  report.net_contribution === null
                    ? ('neutral' as const)
                    : report.net_contribution >= 0
                      ? ('pnl-positive' as const)
                      : ('pnl-negative' as const),
              },
              {
                id: 'contribution-status',
                label: labels.accountStrategyContributionStatus,
                value: statusLabel,
              },
              {
                id: 'health-status',
                label: labels.accountStrategyHealthStatus,
                value: healthLabel,
              },
              {
                id: 'posted-fills',
                label: labels.accountStrategyLedgerPostedFills,
                value: `${report.ledger_posted_fill_count ?? 0} / ${report.linked_fill_count}`,
              },
              ...(!isCompact
                ? [
                    {
                      id: 'evidence-refs',
                      label: labels.accountStrategyEvidenceRefs,
                      value: String(report.evidence_refs.length),
                    },
                  ]
                : []),
            ]}
          />
          <ContributionLimitations
            limitations={report.limitations}
            locale={locale}
          />
        </div>
      ) : (
        <div className="space-y-4">
          <EvidenceState
            kind={isNotApplicable ? 'empty' : 'partial'}
            title={labels.accountStrategyContributionHiddenUntilEvidence}
            description={`${labels.accountStrategyNextManualAction}: ${nextAction}`}
            className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-4 py-3"
          />
          <MetricStrip
            ariaLabel={labels.accountStrategyContributionPublicTitle}
            className="app-strategy-gate-metric-strip grid grid-cols-2 gap-2 border-0 bg-transparent sm:grid-cols-3 sm:auto-cols-auto sm:grid-flow-row"
            items={[
              {
                id: 'strategy',
                label: labels.strategy,
                value: strategyLabel,
              },
              {
                id: 'contribution-status',
                label: labels.accountStrategyContributionStatus,
                value: statusLabel,
              },
              {
                id: 'health-status',
                label: labels.accountStrategyHealthStatus,
                value: healthLabel,
              },
              {
                id: 'orders-fills',
                label: labels.accountStrategyOrdersFills,
                value: String(report?.linked_fill_count ?? 0),
              },
              {
                id: 'evidence-binding',
                label: labels.accountStrategyEvidenceBinding,
                value: bindingLabel,
              },
              {
                id: 'posted-fills',
                label: labels.accountStrategyLedgerPostedFills,
                value: `${report?.ledger_posted_fill_count ?? 0} / ${report?.linked_fill_count ?? 0}`,
              },
            ]}
          />
          {report?.missing_valuation_symbols.length ? (
            <p className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] border-l-2 border-l-[var(--app-warning-indicator)] bg-[var(--app-surface-raised)] px-3 py-2 text-xs font-semibold text-[var(--app-warning-text)]">
              {labels.accountStrategyMissingValuation(
                formatInstrumentDisplayLabelsBySymbol(
                  report.missing_valuation_symbols,
                  instruments,
                ),
              )}
            </p>
          ) : null}
          {report?.blockers?.length ? (
            <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold text-[var(--app-text)]">
                  {labels.accountStrategyBlockers}
                </div>
                <span className="inline-flex items-center rounded-full bg-[var(--app-surface)] px-2 py-0.5 text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-warning-text)] border border-[var(--app-divider)]">
                  {report.blockers.length}{' '}
                  {locale === 'zh' ? '项待复核' : 'items'}
                </span>
              </div>
              <ul className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                {report.blockers.map((blocker, index) => (
                  <li
                    className="flex items-start gap-2.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-2.5 text-[var(--app-text-secondary)] shadow-2xs"
                    key={`${blocker}-${index}`}
                  >
                    <span
                      className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--app-warning-indicator)]"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 break-words leading-relaxed font-medium text-[var(--app-text)]">
                      {formatPublicNote(blocker, locale)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <ContributionLimitations
            limitations={report?.limitations ?? []}
            locale={locale}
          />
        </div>
      )}
    </section>
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
    <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-3">
      <ul className="divide-y divide-[var(--app-divider)] text-xs text-[var(--app-text-secondary)]">
        {limitations.map((limitation, index) => (
          <li
            className="flex items-start gap-2 py-1.5 first:pt-0 last:pb-0 leading-5"
            key={`${limitation}-${index}`}
          >
            <span
              className="text-[var(--app-text-tertiary)]"
              aria-hidden="true"
            >
              ℹ
            </span>
            <span>{formatPublicNote(limitation, locale)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
