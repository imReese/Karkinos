import { useCopy } from '../../../app/copy';
import {
  EvidenceIdentityDisclosure,
  ExceptionList,
  MetricStrip,
  type ExceptionItem,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import { formatQuantity, formatTimestamp } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type { CurrentHoldingMarketEvidenceReview } from '../../portfolio/api';
import { ConfirmedFundNavRefreshButton } from './confirmed-fund-nav-refresh-button';
import { MarketRefreshButton } from './market-refresh-button';

type Props = {
  report?: CurrentHoldingMarketEvidenceReview | null;
  loading: boolean;
  error: boolean;
};

function reportTone(
  report: CurrentHoldingMarketEvidenceReview | null | undefined,
  loading: boolean,
  error: boolean,
) {
  if (loading) {
    return 'text-[var(--app-info-text)]';
  }
  if (error || !report || report.status === 'blocked_identity') {
    return 'text-[var(--app-danger-text)]';
  }
  if (report.status === 'review_required') {
    return 'text-[var(--app-warning-text)]';
  }
  return 'text-[var(--app-text)]';
}

function reviewItemSeverity(reviewReason: string) {
  return reviewReason === 'quote_missing_or_error' ||
    reviewReason === 'quote_status_not_confirmed'
    ? ('danger' as const)
    : ('warning' as const);
}

export function CurrentHoldingMarketEvidenceReviewPanel({
  report,
  loading,
  error,
}: Props) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.market;
  const actionLabels = labels.holdingEvidenceActions;
  const confirmedNavSymbols =
    report?.items
      .filter(
        (item) =>
          item.review_reason === 'confirmed_nav_missing' &&
          item.explicit_refresh_eligible,
      )
      .map((item) => item.symbol) ?? [];
  const confirmedNavSymbolSet = new Set(confirmedNavSymbols);
  const genericRefreshSymbols =
    report?.refreshable_symbols.filter(
      (symbol) => !confirmedNavSymbolSet.has(symbol),
    ) ?? [];
  const title = loading
    ? copy.states.loading
    : error || !report
      ? labels.holdingEvidenceReviewUnavailable
      : report.status === 'blocked_identity'
        ? labels.holdingEvidenceReviewBlocked
        : report.status === 'no_current_holdings'
          ? labels.holdingEvidenceReviewEmpty
          : report.status === 'complete'
            ? labels.holdingEvidenceReviewComplete
            : labels.holdingEvidenceReviewCount(report.review_required_count);
  const complete = report?.status === 'complete';
  const quiet = complete || report?.status === 'no_current_holdings';
  const showReviewWorkspace =
    report?.status === 'review_required' ||
    report?.status === 'blocked_identity';
  const reasonLabels = labels.holdingEvidenceReasons;
  const exceptionItems: ExceptionItem[] = report
    ? [
        ...(report.status === 'blocked_identity'
          ? [
              {
                id: 'valuation-identity',
                severity: 'danger' as const,
                statusLabel: labels.holdingEvidenceIdentityBlockedStatus,
                title: labels.holdingEvidenceIdentityTitle,
                reason: labels.holdingEvidenceIdentityReason,
                unblockCondition:
                  labels.holdingEvidenceIdentityClearingCondition,
                nextAction: labels.holdingEvidenceIdentityNextAction,
                evidence: (
                  <>
                    <span className="block">
                      {labels.holdingEvidenceIdentityEvidence(
                        report.source_blockers.length,
                      )}
                    </span>
                    <span className="mt-0.5 block font-mono tabular-nums">
                      {formatTimestamp(report.valuation_as_of)}
                    </span>
                  </>
                ),
              },
            ]
          : []),
        ...report.items.map((item) => ({
          id: `${item.symbol}-${item.review_reason}`,
          severity: reviewItemSeverity(item.review_reason),
          statusLabel: formatPublicStatus(item.quote_status, locale),
          title: (
            <span className="min-w-0">
              <span className="block truncate">{item.name}</span>
              <span className="mt-0.5 block font-mono text-[11px] font-normal tabular-nums text-[var(--app-text-tertiary)]">
                {item.symbol} · {formatQuantity(item.quantity)}
              </span>
            </span>
          ),
          reason: (
            <>
              <span className="block">
                {reasonLabels[
                  item.review_reason as keyof typeof reasonLabels
                ] ?? formatPublicCode(item.review_reason, locale)}
              </span>
              {item.blocks_authoritative_decisions ? (
                <span className="mt-0.5 block font-medium text-[var(--app-warning-text)]">
                  {labels.holdingEvidenceBlocksAuthoritativeDecisions}
                </span>
              ) : null}
            </>
          ),
          unblockCondition: labels.holdingEvidenceClearingCondition,
          nextAction:
            actionLabels[
              item.next_manual_action as keyof typeof actionLabels
            ] ?? formatPublicCode(item.next_manual_action, locale),
          evidence: `${item.quote_source ?? '--'} · ${formatTimestamp(item.quote_timestamp)}`,
        })),
      ]
    : [];

  return (
    <section
      id="current-holding-evidence-review"
      className="scroll-mt-24 space-y-4 border-y border-[var(--app-divider)] py-4"
      data-testid="current-holding-market-evidence-review"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.holdingEvidenceReview}
          </div>
          <h2
            className={`${quiet ? 'mt-1 text-sm' : 'mt-2 text-lg'} font-semibold ${reportTone(report, loading, error)}`}
          >
            {title}
          </h2>
          {!quiet ? (
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.holdingEvidenceReviewDetail}
            </p>
          ) : null}
        </div>
        {report ||
        confirmedNavSymbols.length > 0 ||
        genericRefreshSymbols.length > 0 ? (
          <div
            className="flex shrink-0 flex-wrap items-center justify-end gap-2"
            data-testid="holding-evidence-actions"
          >
            {report ? (
              <EvidenceIdentityDisclosure
                className="app-button-secondary inline-flex h-10 items-center rounded-[var(--app-radius-control)] px-2.5 text-[11px] font-semibold sm:h-8"
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
                    value: report.ledger_cutoff_id,
                    mono: true,
                  },
                  {
                    label: copy.common.valuationAsOf,
                    value: formatTimestamp(report.valuation_as_of),
                    mono: true,
                  },
                  {
                    label: copy.common.valuationStatus,
                    value: formatPublicStatus(report.status, locale),
                  },
                  {
                    label: copy.common.reviewFingerprint,
                    value: report.review_fingerprint,
                    mono: true,
                  },
                  {
                    label: copy.common.providerContact,
                    value: report.provider_contact_performed
                      ? copy.common.yes
                      : copy.common.no,
                  },
                  {
                    label: copy.common.databaseWrites,
                    value: report.database_writes_performed
                      ? copy.common.yes
                      : copy.common.no,
                  },
                  {
                    label: copy.common.executionAuthority,
                    value: report.authorizes_execution
                      ? copy.common.yes
                      : copy.common.no,
                  },
                ]}
              />
            ) : null}
            {confirmedNavSymbols.length > 0 ? (
              <ConfirmedFundNavRefreshButton symbols={confirmedNavSymbols} />
            ) : null}
            {genericRefreshSymbols.length > 0 ? (
              <MarketRefreshButton symbols={genericRefreshSymbols} />
            ) : null}
          </div>
        ) : null}
      </div>

      {confirmedNavSymbols.length > 0 ? (
        <p className="app-muted border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5">
          {labels.holdingEvidenceConfirmedNavRefresh}
        </p>
      ) : null}
      {genericRefreshSymbols.length > 0 ? (
        <p className="app-muted border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5">
          {labels.holdingEvidenceExplicitRefresh}
        </p>
      ) : null}

      {report && !showReviewWorkspace ? (
        <div className="flex min-w-0 flex-wrap gap-x-4 gap-y-1 text-[11px] tabular-nums text-[var(--app-text-tertiary)]">
          <span>
            {report.confirmed_holding_count}/{report.current_holding_count}
          </span>
          <span>{formatTimestamp(report.valuation_as_of)}</span>
        </div>
      ) : report && showReviewWorkspace ? (
        <>
          <MetricStrip
            ariaLabel={labels.holdingEvidenceMetricsLabel}
            className="[&>.app-metric-strip-item:last-child:nth-child(odd)]:col-span-2 sm:[&>.app-metric-strip-item:last-child:nth-child(odd)]:col-span-1"
            items={[
              {
                id: 'review-required',
                label: labels.holdingEvidenceMetricReviewRequired,
                value: `${report.review_required_count}/${report.current_holding_count}`,
                detail: formatPublicStatus(report.status, locale),
                tone: 'warning',
              },
              {
                id: 'confirmed',
                label: labels.holdingEvidenceMetricConfirmed,
                value: `${report.confirmed_holding_count}/${report.current_holding_count}`,
                detail: labels.holdingEvidenceConfirmedCount(
                  report.confirmed_holding_count,
                ),
              },
              {
                id: 'valuation-as-of',
                label: copy.common.valuationAsOf,
                value: formatTimestamp(report.valuation_as_of),
              },
            ]}
          />

          <ExceptionList
            ariaLabel={labels.holdingEvidenceExceptionListLabel}
            emptyState={labels.holdingEvidenceReviewEmpty}
            labels={{
              reason: labels.holdingEvidenceReasonLabel,
              unblockCondition: labels.holdingEvidenceClearingConditionLabel,
              nextAction: labels.holdingEvidenceSafeNextStepLabel,
              evidence: labels.holdingEvidenceEvidenceLabel,
            }}
            items={exceptionItems}
          />
        </>
      ) : null}
    </section>
  );
}
