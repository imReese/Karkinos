import { formatTimestamp } from '../../../shared/format';
import type { AppCopy } from '../../../shared/i18n/context';
import type {
  CurrentHoldingMarketEvidenceReview,
  PortfolioSnapshot,
} from '../overview-feature-boundary';
import type { TodayQueueItem } from './today-queue-types';

function currentHoldingMarketReviewSummary(
  report: CurrentHoldingMarketEvidenceReview,
  labels: AppCopy['overview']['dashboard'],
) {
  return labels.dataReviewSummary(
    report.fund_nav_review_count,
    report.stale_or_cached_review_count,
    report.missing_or_error_review_count,
    report.estimated_review_count,
    report.unknown_status_review_count,
  );
}

function currentHoldingMarketReviewContractIsValid(
  report?: CurrentHoldingMarketEvidenceReview | null,
  portfolioSnapshot?: PortfolioSnapshot | null,
) {
  if (!report || !portfolioSnapshot) {
    return false;
  }
  const identityContractValid =
    report.status === 'blocked_identity'
      ? report.source_blockers.length > 0
      : Boolean(
          report.valuation_snapshot_id &&
          report.ledger_fingerprint &&
          report.quote_set_fingerprint,
        );
  const crossResponseIdentityValid = Boolean(
    report.valuation_snapshot_id === portfolioSnapshot.valuation_snapshot_id &&
    report.ledger_cutoff_id === portfolioSnapshot.ledger_cutoff_id &&
    report.ledger_fingerprint === portfolioSnapshot.ledger_fingerprint &&
    report.quote_set_fingerprint === portfolioSnapshot.quote_set_fingerprint,
  );
  return Boolean(
    report.schema_version ===
      'karkinos.current_holding_market_evidence_review.v1' &&
    report.reads_persisted_facts_only === true &&
    report.provider_contact_performed === false &&
    report.runtime_connector_query_performed === false &&
    report.database_writes_performed === false &&
    report.does_not_mutate_oms === true &&
    report.does_not_mutate_production_ledger === true &&
    report.does_not_mutate_risk === true &&
    report.does_not_mutate_kill_switch === true &&
    report.does_not_change_capital_authority === true &&
    report.authorizes_execution === false &&
    report.review_fingerprint.startsWith('sha256:') &&
    report.current_holding_count ===
      report.confirmed_holding_count + report.review_required_count &&
    report.items.length === report.review_required_count &&
    identityContractValid &&
    crossResponseIdentityValid &&
    Number.isInteger(report.ledger_cutoff_id) &&
    report.ledger_cutoff_id >= 0,
  );
}

export function buildMarketEvidenceQueueItem({
  overview,
  portfolioSnapshot,
  marketEvidenceReview,
  marketEvidenceReviewLoading,
  marketEvidenceReviewError,
  copy,
}: {
  overview: { valuation_timestamp?: string | null };
  portfolioSnapshot: PortfolioSnapshot;
  marketEvidenceReview?: CurrentHoldingMarketEvidenceReview | null;
  marketEvidenceReviewLoading: boolean;
  marketEvidenceReviewError: boolean;
  copy: AppCopy;
}) {
  const labels = copy.overview.dashboard;
  const contractValid = currentHoldingMarketReviewContractIsValid(
    marketEvidenceReview,
    portfolioSnapshot,
  );
  const unavailable =
    marketEvidenceReviewError ||
    (!marketEvidenceReviewLoading && !contractValid);
  const identityBlocked =
    contractValid && marketEvidenceReview?.status === 'blocked_identity';
  const needsReview = Boolean(
    unavailable ||
    identityBlocked ||
    marketEvidenceReview?.status === 'review_required',
  );
  const detail = marketEvidenceReviewLoading
    ? labels.dataReviewLoading
    : unavailable
      ? labels.dataReviewUnavailable
      : identityBlocked
        ? labels.dataReviewIdentityBlocked
        : marketEvidenceReview?.status === 'review_required'
          ? currentHoldingMarketReviewSummary(marketEvidenceReview, labels)
          : `${labels.valuationTime}: ${formatTimestamp(
              marketEvidenceReview?.valuation_as_of ??
                overview.valuation_timestamp,
            )}`;
  const meta = marketEvidenceReviewLoading
    ? copy.states.loading
    : unavailable
      ? '--'
      : marketEvidenceReview?.status === 'review_required'
        ? labels.affectedCount(marketEvidenceReview.review_required_count)
        : labels.dataReviewConfirmedCount(
            marketEvidenceReview?.confirmed_holding_count ?? 0,
          );
  const refreshSymbols =
    contractValid && marketEvidenceReview?.status === 'review_required'
      ? marketEvidenceReview.refreshable_symbols
      : [];
  const item: TodayQueueItem = {
    key: 'data',
    title: marketEvidenceReviewLoading
      ? labels.dataReviewLoading
      : needsReview
        ? labels.dataNeedsReview
        : labels.dataUsable,
    detail,
    meta,
    href: '/market#current-holding-evidence-review',
    actionLabel: labels.viewData,
    tone: unavailable
      ? 'danger'
      : needsReview
        ? 'warning'
        : marketEvidenceReviewLoading
          ? 'neutral'
          : 'success',
    priority: unavailable || needsReview ? 'first' : 'normal',
    resolution:
      needsReview && !marketEvidenceReviewLoading
        ? labels.dataResolutionCondition
        : undefined,
  };
  return { item, needsReview, refreshSymbols };
}
