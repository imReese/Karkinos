import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import type { CiticBatchPreviewController } from './account-truth-citic-batch-preview';
import type { CiticSourceReviewController } from './account-truth-citic-source-review';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import {
  formatCiticEventTypeCounts,
  statusTone,
} from './account-truth-review-format';

export function CiticDirectoryEvidence({
  batch,
  locale,
  sourceReview,
}: {
  batch: CiticBatchPreviewController;
  locale: 'en' | 'zh';
  sourceReview: CiticSourceReviewController;
}) {
  const text = labels[locale];
  const { directoryScanMutation, directoryStatusQuery } = batch;
  return (
    <div className="mt-4 border-y border-[var(--app-divider)] py-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {text.citicDirectoryTitle}
      </div>
      <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
        {text.citicDirectoryBody}
      </p>
      {directoryStatusQuery.isPending ? (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.collectorLoading}
        />
      ) : directoryStatusQuery.isError || !directoryStatusQuery.data ? (
        <EvidenceState
          className="mt-3"
          kind="error"
          title={text.citicDirectoryUnavailable}
        />
      ) : directoryStatusQuery.data.enabled ? (
        <button
          className="app-button-secondary mt-3 min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={batch.scanPending || sourceReview.intakePending}
          type="button"
          onClick={batch.previewConfiguredDirectory}
        >
          {text.citicDirectoryScanAction}
        </button>
      ) : (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.citicDirectoryDisabled}
        />
      )}
      {directoryScanMutation.data ? (
        <>
          <p
            className="app-type-micro mt-2 text-[var(--app-text-tertiary)]"
            data-testid="citic-directory-scan-summary"
          >
            {text.citicDirectorySummary(
              directoryScanMutation.data.candidate_file_count,
              directoryScanMutation.data.preview_count,
              directoryScanMutation.data.duplicate_file_count,
            )}
          </p>
          <CiticDirectoryBatchAssessment
            locale={locale}
            scan={directoryScanMutation.data}
          />
        </>
      ) : null}
    </div>
  );
}

type DirectoryScan = NonNullable<
  CiticBatchPreviewController['directoryScanMutation']['data']
>;

function CiticDirectoryBatchAssessment({
  locale,
  scan,
}: {
  locale: 'en' | 'zh';
  scan: DirectoryScan;
}) {
  const text = labels[locale];
  return (
    <div
      className="mt-3 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3"
      data-testid="citic-directory-batch-assessment"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold text-[var(--app-text)]">
          {text.citicBatchAssessmentTitle}
        </div>
        <StatusBadge tone={statusTone('blocked')}>
          {scan.batch_assessment.integrity_status === 'clear'
            ? text.citicBatchIntegrityClear
            : text.citicBatchIntegrityBlocked}
        </StatusBadge>
      </div>
      <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
        {text.citicBatchObservedMonths(
          scan.batch_assessment.observed_event_months.join(', '),
        )}
      </p>
      <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
        {text.citicBatchIntegritySummary(
          scan.batch_assessment.unique_event_count,
          scan.batch_assessment.cross_file_duplicate_event_count,
          scan.batch_assessment.conflicting_event_identity_count,
          scan.batch_assessment.source_without_financial_events_count,
        )}
      </p>
      <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
        {text.citicBatchQueryWindowProgress(
          scan.query_window_review_summary.reviewed_source_count,
          scan.preview_count,
        )}
      </p>
      <div
        className="mt-3 border-t border-[var(--app-border)] pt-3"
        data-testid="citic-query-window-batch-assessment"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-semibold text-[var(--app-text)]">
            {text.citicQueryWindowBatchTitle}
          </div>
          <StatusBadge
            tone={
              scan.query_window_batch_assessment.integrity_status === 'clear'
                ? 'info'
                : scan.query_window_batch_assessment.integrity_status ===
                    'partial'
                  ? 'warning'
                  : scan.query_window_batch_assessment.integrity_status ===
                      'blocked'
                    ? 'danger'
                    : 'neutral'
            }
          >
            {scan.query_window_batch_assessment.integrity_status === 'clear'
              ? text.citicQueryWindowBatchClear
              : scan.query_window_batch_assessment.integrity_status ===
                  'partial'
                ? text.citicQueryWindowBatchPartial
                : scan.query_window_batch_assessment.integrity_status ===
                    'blocked'
                  ? text.citicQueryWindowBatchBlocked
                  : text.citicQueryWindowBatchUnavailable}
          </StatusBadge>
        </div>
        <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
          {text.citicQueryWindowBatchSummary(
            scan.query_window_batch_assessment.declared_window_start_date,
            scan.query_window_batch_assessment.declared_window_end_date,
            scan.query_window_batch_assessment.covered_calendar_day_count,
            scan.query_window_batch_assessment.gap_calendar_day_count,
            scan.query_window_batch_assessment.overlap_calendar_day_count,
          )}
        </p>
        <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
          {text.citicQueryWindowBatchBoundary}
        </p>
      </div>
      <div
        className="mt-3 border-t border-[var(--app-border)] pt-3"
        data-testid="citic-source-scope-batch-assessment"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-semibold text-[var(--app-text)]">
            {text.citicSourceScopeBatchTitle}
          </div>
          <StatusBadge
            tone={
              scan.source_scope_batch_assessment.integrity_status === 'clear'
                ? 'info'
                : scan.source_scope_batch_assessment.integrity_status ===
                    'partial'
                  ? 'warning'
                  : scan.source_scope_batch_assessment.integrity_status ===
                      'blocked'
                    ? 'danger'
                    : 'neutral'
            }
          >
            {scan.source_scope_batch_assessment.integrity_status === 'clear'
              ? text.citicSourceScopeBatchClear
              : scan.source_scope_batch_assessment.integrity_status ===
                  'partial'
                ? text.citicSourceScopeBatchPartial
                : scan.source_scope_batch_assessment.integrity_status ===
                    'blocked'
                  ? text.citicSourceScopeBatchBlocked
                  : text.citicSourceScopeBatchUnavailable}
          </StatusBadge>
        </div>
        <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
          {text.citicSourceScopeBatchSummary(
            scan.source_scope_batch_assessment.reviewed_source_count,
            scan.source_scope_batch_assessment.source_count,
            scan.source_scope_batch_assessment.account_binding_consistent,
            scan.source_scope_batch_assessment.declared_scope_consistent,
          )}
        </p>
        <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
          {text.citicSourceScopeBatchDeclared(
            scan.source_scope_batch_assessment.declared_account_type,
            scan.source_scope_batch_assessment.declared_market_scopes.join(
              ', ',
            ),
            scan.source_scope_batch_assessment.declared_asset_classes.join(
              ', ',
            ),
            scan.source_scope_batch_assessment.declared_account_value_band,
            scan.source_scope_batch_assessment.declared_business_types.join(
              ', ',
            ),
          )}
        </p>
        <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
          {text.citicSourceScopeBatchBoundary}
        </p>
      </div>
      <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
        {text.citicBatchCoverageBoundary}
      </p>
      <div
        className="mt-3 border-t border-[var(--app-border)] pt-3"
        data-testid="citic-canonical-lineage-assessment"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-xs font-semibold text-[var(--app-text)]">
            {text.citicCanonicalLineageTitle}
          </div>
          <StatusBadge
            tone={statusTone(
              scan.canonical_lineage_assessment.event_lineage_status === 'exact'
                ? 'pass'
                : 'blocked',
            )}
          >
            {scan.canonical_lineage_assessment.event_lineage_status === 'exact'
              ? text.citicCanonicalLineageExact
              : scan.canonical_lineage_assessment.event_lineage_status ===
                  'partial'
                ? text.citicCanonicalLineagePartial
                : text.citicCanonicalLineageUnavailable}
          </StatusBadge>
        </div>
        <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
          {text.citicCanonicalLineageSummary(
            scan.canonical_lineage_assessment.semantically_matched_event_count,
            scan.canonical_lineage_assessment.source_supported_event_count,
            scan.canonical_lineage_assessment
              .exact_event_identity_matched_event_count,
            scan.canonical_lineage_assessment
              .broker_order_identity_matched_event_count,
            scan.canonical_lineage_assessment
              .source_events_with_broker_order_identity_count,
            scan.canonical_lineage_assessment.canonical_unmatched_event_count,
          )}
        </p>
        <div
          className="app-type-micro mt-1 grid gap-1 text-[var(--app-text-secondary)]"
          data-testid="citic-canonical-lineage-type-diagnostics"
        >
          <p>
            {text.citicCanonicalLineageObservedTypes(
              formatCiticEventTypeCounts(
                scan.canonical_lineage_assessment.source_event_type_counts,
                locale,
              ),
              formatCiticEventTypeCounts(
                scan.canonical_lineage_assessment.canonical_event_type_counts,
                locale,
              ),
            )}
          </p>
          <p>
            {text.citicCanonicalLineageMismatchTypes(
              formatCiticEventTypeCounts(
                scan.canonical_lineage_assessment
                  .semantically_matched_event_type_counts,
                locale,
              ),
              formatCiticEventTypeCounts(
                scan.canonical_lineage_assessment
                  .source_unmatched_event_type_counts,
                locale,
              ),
              formatCiticEventTypeCounts(
                scan.canonical_lineage_assessment
                  .canonical_unmatched_event_type_counts,
                locale,
              ),
            )}
          </p>
          <p>
            {text.citicCanonicalLineageIdentityPresence(
              scan.canonical_lineage_assessment
                .source_events_with_broker_order_identity_count,
              scan.canonical_lineage_assessment
                .canonical_events_with_broker_order_identity_count,
            )}
          </p>
        </div>
        <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
          {text.citicCanonicalLineageBoundary}
        </p>
      </div>
    </div>
  );
}
