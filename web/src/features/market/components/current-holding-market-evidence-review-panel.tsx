import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { formatQuantity, formatTimestamp } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type { CurrentHoldingMarketEvidenceReview } from '../../portfolio/api';
import { MarketRefreshButton } from './market-refresh-button';

type Props = {
  report?: CurrentHoldingMarketEvidenceReview | null;
  loading: boolean;
  error: boolean;
};

function reportTone(report?: CurrentHoldingMarketEvidenceReview | null) {
  if (!report || report.status === 'blocked_identity') {
    return 'text-[var(--app-danger)]';
  }
  if (report.status === 'review_required') {
    return 'text-[var(--app-warning)]';
  }
  return 'text-[var(--app-success)]';
}

function shortIdentity(value?: string | null) {
  if (!value) {
    return '--';
  }
  return value.length > 22 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
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

  return (
    <section
      id="current-holding-evidence-review"
      className="app-panel scroll-mt-24 rounded-2xl p-4 sm:p-5"
      data-testid="current-holding-market-evidence-review"
    >
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-xs uppercase tracking-[0.18em]">
            {labels.holdingEvidenceReview}
          </div>
          <div className={`mt-2 text-lg font-semibold ${reportTone(report)}`}>
            {title}
          </div>
          <p className="app-muted mt-2 max-w-3xl text-sm leading-6">
            {labels.holdingEvidenceReviewDetail}
          </p>
        </div>
        {report && report.refreshable_symbols.length > 0 ? (
          <div className="shrink-0">
            <MarketRefreshButton symbols={report.refreshable_symbols} />
          </div>
        ) : null}
      </div>

      {report ? (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
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
              label={labels.holdingEvidenceSnapshot}
              value={shortIdentity(report.valuation_snapshot_id)}
              title={report.valuation_snapshot_id ?? undefined}
            />
            <EvidenceIdentity
              label={labels.holdingEvidenceLedgerCutoff}
              value={String(report.ledger_cutoff_id)}
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

          {report.refreshable_symbols.length > 0 ? (
            <p className="app-muted mt-4 text-xs leading-5">
              {labels.holdingEvidenceExplicitRefresh}
            </p>
          ) : null}
          <div className="app-muted mt-3 flex min-w-0 flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] tabular-nums">
            <span title={report.review_fingerprint}>
              {labels.holdingEvidenceFingerprint}:{' '}
              {shortIdentity(report.review_fingerprint)}
            </span>
            <span>{formatTimestamp(report.valuation_as_of)}</span>
            <span>provider_contact=false</span>
            <span>authorizes_execution=false</span>
          </div>
        </>
      ) : null}
    </section>
  );
}

function EvidenceIdentity({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_22%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2">
      <div className="app-kicker text-[10px] tracking-[0.14em]">{label}</div>
      <div
        className="mt-1 truncate font-mono text-xs font-semibold tabular-nums text-[var(--app-soft)]"
        title={title}
      >
        {value}
      </div>
    </div>
  );
}
