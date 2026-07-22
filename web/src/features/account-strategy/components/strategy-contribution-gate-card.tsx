import { useCopy } from '../../../app/copy';
import {
  EvidenceIdentityDisclosure,
  EvidenceState,
  MetricStrip,
  StatusBadge,
} from '../../../app/components/workbench';
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
      className="min-w-0"
      data-testid="strategy-contribution-gate-card"
      data-variant={variant}
    >
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
        <div className="space-y-3">
          <MetricStrip
            ariaLabel={labels.accountStrategyContributionPublicTitle}
            className="sm:grid-flow-row sm:grid-cols-2"
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
        <div className="space-y-3">
          <EvidenceState
            kind={isNotApplicable ? 'empty' : 'partial'}
            title={labels.accountStrategyContributionHiddenUntilEvidence}
            description={`${labels.accountStrategyNextManualAction}: ${nextAction}`}
          />
          <MetricStrip
            ariaLabel={labels.accountStrategyContributionPublicTitle}
            className="sm:grid-flow-row sm:grid-cols-2"
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
            <p className="border-l-2 border-l-[var(--app-warning-indicator)] px-3 py-2 text-xs font-semibold text-[var(--app-warning-text)]">
              {labels.accountStrategyMissingValuation(
                formatInstrumentDisplayLabelsBySymbol(
                  report.missing_valuation_symbols,
                  instruments,
                ),
              )}
            </p>
          ) : null}
          {report?.blockers?.length ? (
            <div className="border-y border-[var(--app-divider)]">
              <div className="px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)]">
                {labels.accountStrategyBlockers}
              </div>
              <ul className="divide-y divide-[var(--app-divider)] text-xs text-[var(--app-text-secondary)]">
                {report.blockers.map((blocker) => (
                  <li className="break-words px-3 py-2" key={blocker}>
                    {formatPublicNote(blocker, locale)}
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
    <ul className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
      {limitations.map((limitation) => (
        <li
          className="px-3 py-2 text-xs leading-5 text-[var(--app-text-secondary)]"
          key={limitation}
        >
          {formatPublicNote(limitation, locale)}
        </li>
      ))}
    </ul>
  );
}
