import { useCopy } from '../../../app/copy';
import { EvidenceIdentityDisclosure } from '../../../app/components/workbench';
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
    return 'text-[var(--app-danger)]';
  }
  if (report.status === 'review_required') {
    return 'text-[var(--app-warning)]';
  }
  return 'text-[var(--app-text)]';
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

  return (
    <section
      id="current-holding-evidence-review"
      className={
        complete
          ? 'scroll-mt-24 border-y border-[var(--app-divider)] py-3'
          : 'app-panel scroll-mt-24 rounded-[var(--app-radius-surface)] p-4'
      }
      data-testid="current-holding-market-evidence-review"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.holdingEvidenceReview}
          </div>
          <div
            className={`${complete ? 'mt-1 text-sm' : 'mt-2 text-lg'} font-semibold ${reportTone(report, loading, error)}`}
          >
            {title}
          </div>
          {!complete ? (
            <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
              {labels.holdingEvidenceReviewDetail}
            </p>
          ) : null}
        </div>
        {report ||
        confirmedNavSymbols.length > 0 ||
        genericRefreshSymbols.length > 0 ? (
          <div className="flex shrink-0 flex-wrap justify-end gap-3">
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

      {report && complete ? (
        <div className="mt-2 flex min-w-0 flex-wrap gap-x-4 gap-y-1 text-[11px] tabular-nums text-[var(--app-text-tertiary)]">
          <span>
            {report.confirmed_holding_count}/{report.current_holding_count}
          </span>
          <span>{formatTimestamp(report.valuation_as_of)}</span>
        </div>
      ) : report ? (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <EvidenceIdentity
              label={labels.holdingEvidenceReview}
              value={`${report.review_required_count}/${report.current_holding_count}`}
            />
            <EvidenceIdentity
              label={labels.holdingEvidenceConfirmedCount(
                report.confirmed_holding_count,
              )}
              value={formatPublicStatus(report.status, locale)}
            />
            <EvidenceIdentity
              label={copy.common.valuationAsOf}
              value={formatTimestamp(report.valuation_as_of)}
            />
          </div>

          {report.items.length > 0 ? (
            <div className="mt-4 grid gap-2 lg:grid-cols-2">
              {report.items.map((item) => (
                <article
                  key={`${item.symbol}-${item.review_reason}`}
                  className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-4 py-3"
                >
                  <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                        {item.name}
                      </div>
                      <div className="app-muted mt-1 font-mono text-xs tabular-nums">
                        {item.symbol} · {formatQuantity(item.quantity)}
                      </div>
                    </div>
                    <span className="rounded-full border border-[color-mix(in_srgb,var(--app-warning)_30%,transparent)] px-2.5 py-1 text-[10px] font-semibold text-[var(--app-warning)]">
                      {formatPublicStatus(item.quote_status, locale)}
                    </span>
                  </div>
                  <div className="app-muted mt-3 grid gap-1 text-xs leading-5">
                    <span>
                      {actionLabels[
                        item.next_manual_action as keyof typeof actionLabels
                      ] ?? formatPublicCode(item.next_manual_action, locale)}
                    </span>
                    <span>
                      {item.quote_source ?? '--'} ·{' '}
                      {formatTimestamp(item.quote_timestamp)}
                    </span>
                  </div>
                </article>
              ))}
            </div>
          ) : null}

          {confirmedNavSymbols.length > 0 ? (
            <p className="app-muted mt-4 text-xs leading-5">
              {labels.holdingEvidenceConfirmedNavRefresh}
            </p>
          ) : null}
          {genericRefreshSymbols.length > 0 ? (
            <p className="app-muted mt-4 text-xs leading-5">
              {labels.holdingEvidenceExplicitRefresh}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function EvidenceIdentity({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <div className="app-kicker text-[10px] tracking-[0.14em]">{label}</div>
      <div className="mt-1 truncate font-mono text-xs font-semibold tabular-nums text-[var(--app-soft)]">
        {value}
      </div>
    </div>
  );
}
