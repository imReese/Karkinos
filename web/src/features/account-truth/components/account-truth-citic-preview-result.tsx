import { EvidenceState, StatusBadge } from '../../../shared/ui/workbench';
import type { CiticSourceReviewStatus } from '../api';
import { CiticSourceReviewForm } from './account-truth-citic-source-review-form';
import type {
  CiticHistoryXlsPreviewResult,
  CiticSourceReviewIntent,
} from './account-truth-citic-types';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import { formatCode, statusTone } from './account-truth-review-format';

export function CiticPreviewResultRow({
  intakePending,
  isDuplicate,
  locale,
  result,
  reviewIntent,
  onCancelReview,
  onConfirmReview,
  onStartReview,
  onUpdateReviewIntent,
}: {
  intakePending: boolean;
  isDuplicate: boolean;
  locale: 'en' | 'zh';
  result: CiticHistoryXlsPreviewResult;
  reviewIntent: CiticSourceReviewIntent | null;
  onCancelReview: () => void;
  onConfirmReview: () => void;
  onStartReview: (
    resultId: string,
    reviewStatus: CiticSourceReviewStatus,
  ) => void;
  onUpdateReviewIntent: (
    updates: Partial<
      Omit<CiticSourceReviewIntent, 'resultId' | 'reviewStatus'>
    >,
  ) => void;
}) {
  const text = labels[locale];
  const sourceIsOwnerIdentifiable =
    result.sourceKind === 'browser_file' || Boolean(result.localNameMonthHint);
  const blockingErrors =
    result.preview?.errors.filter(
      (error) =>
        error.code !== 'citic_history_xls_non_financial_activity_ignored',
    ) ?? [];
  const statusLabel =
    result.status === 'pending'
      ? formatCode('checking', locale, 'status')
      : result.status === 'error'
        ? result.errorKind === 'read'
          ? text.citicReadFailed
          : text.citicFilePreviewFailed
        : isDuplicate
          ? text.citicDuplicateFile
          : text.citicFilePreviewComplete;
  return (
    <div
      className="grid min-w-0 gap-1 px-3 py-2.5 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-3"
      data-testid={`citic-preview-result-${result.id}`}
      key={result.id}
    >
      <div className="min-w-0">
        <div className="truncate font-semibold text-[var(--app-text)]">
          {result.localFileName}
        </div>
        {result.preview ? (
          <div className="app-type-micro mt-1 break-all font-mono text-[var(--app-text-tertiary)]">
            SHA-256 {result.preview.file_fingerprint}
          </div>
        ) : null}
        {result.sourceKind === 'configured_directory' &&
        result.localNameMonthHint ? (
          <div className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
            {text.citicLocalNameMonthHint(result.localNameMonthHint)} ·{' '}
            {text.citicLocalNameMonthHintBoundary}
          </div>
        ) : null}
      </div>
      <StatusBadge
        tone={statusTone(
          result.status === 'pending'
            ? 'checking'
            : result.status === 'error'
              ? 'error'
              : 'blocked',
        )}
      >
        {statusLabel}
      </StatusBadge>
      {result.preview ? (
        <div className="sm:col-span-2">
          <div className="app-type-micro flex flex-wrap gap-x-3 gap-y-1 text-[var(--app-text-secondary)]">
            <span>
              {text.validRows}: {result.preview.valid_row_count}
            </span>
            <span>
              {text.invalidRows}: {result.preview.invalid_row_count}
            </span>
            <span>
              {text.citicRecognizedEvents}: {result.preview.total_event_count}
            </span>
            {result.preview.recognized_non_financial_activity_count > 0 ? (
              <span>
                {text.citicRecognizedNonFinancialActivities}:{' '}
                {result.preview.recognized_non_financial_activity_count}
              </span>
            ) : null}
          </div>
          {blockingErrors.length > 0 ? (
            <div className="app-type-micro mt-1 flex flex-wrap gap-1.5 text-[var(--app-danger-text)]">
              {blockingErrors.slice(0, 3).map((error) => (
                <span key={`${error.row_number ?? 'file'}-${error.code}`}>
                  {error.row_number ? `#${error.row_number} ` : ''}
                  {formatCode(error.code, locale, 'code')}
                </span>
              ))}
            </div>
          ) : null}
          {!isDuplicate && !sourceIsOwnerIdentifiable ? (
            <EvidenceState
              className="mt-2"
              kind="partial"
              title={text.citicConfiguredSourceUnidentified}
            />
          ) : null}
          {!isDuplicate &&
          sourceIsOwnerIdentifiable &&
          result.intakeState === 'idle' ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {result.preview.recordable_for_follow_up ? (
                <button
                  className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={intakePending}
                  type="button"
                  onClick={() => onStartReview(result.id, 'follow_up_required')}
                >
                  {text.citicReviewFollowUp}
                </button>
              ) : null}
              <button
                className="app-button-ghost min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                disabled={intakePending}
                type="button"
                onClick={() => onStartReview(result.id, 'rejected')}
              >
                {text.citicRejectSource}
              </button>
            </div>
          ) : null}
          {reviewIntent?.resultId === result.id ? (
            <CiticSourceReviewForm
              fileFingerprint={result.preview.file_fingerprint}
              intakePending={intakePending}
              locale={locale}
              reviewIntent={reviewIntent}
              onCancelReview={onCancelReview}
              onConfirmReview={onConfirmReview}
              onUpdateReviewIntent={onUpdateReviewIntent}
            />
          ) : null}
          {result.intakeState === 'saved' && result.intake ? (
            <EvidenceState
              className="mt-2"
              kind={
                result.intake.review_status === 'rejected' ? 'stale' : 'partial'
              }
              title={
                result.intake.review_status === 'rejected'
                  ? text.citicRejectionSaved
                  : result.sourceScopeState === 'saved'
                    ? text.citicSourceScopeSaved
                    : result.queryWindowState === 'saved'
                      ? text.citicQueryWindowSaved
                      : text.citicIntakeSaved
              }
              description={
                result.sourceScopeState === 'saved' && result.sourceScopeReview
                  ? `${result.sourceScopeReview.account_alias} · ${result.sourceScopeReview.account_type} · ${result.sourceScopeReview.market_scopes.join(', ')} · ${result.sourceScopeReview.asset_classes.join(', ')} · ${result.sourceScopeReview.account_value_band || 'unverified'} · ${text.citicQueryWindowStillBlocked}`
                  : result.queryWindowState === 'saved' &&
                      result.queryWindowReview
                    ? `${result.queryWindowReview.query_start_date} — ${result.queryWindowReview.query_end_date} · ${text.citicQueryWindowStillBlocked}`
                    : result.intake.intake_id
              }
            />
          ) : null}
          {result.intakeState === 'saved' &&
          result.intake?.review_status === 'follow_up_required' &&
          (result.queryWindowState !== 'saved' ||
            result.sourceScopeState !== 'saved') &&
          sourceIsOwnerIdentifiable &&
          reviewIntent?.resultId !== result.id ? (
            <button
              className="app-button-secondary mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              disabled={intakePending}
              type="button"
              onClick={() => onStartReview(result.id, 'follow_up_required')}
            >
              {result.queryWindowState === 'saved'
                ? text.citicReviewSourceScope
                : text.citicReviewQueryWindow}
            </button>
          ) : null}
          {result.queryWindowState === 'error' ? (
            <EvidenceState
              className="mt-2"
              kind="error"
              title={text.citicQueryWindowFailed}
              description={text.citicIntakeStillSaved}
            />
          ) : null}
          {result.sourceScopeState === 'error' ? (
            <EvidenceState
              className="mt-2"
              kind="error"
              title={text.citicSourceScopeFailed}
              description={text.citicQueryWindowStillBlocked}
            />
          ) : null}
          {result.intakeState === 'error' ? (
            <EvidenceState
              className="mt-2"
              kind="error"
              title={text.citicIntakeFailed}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
