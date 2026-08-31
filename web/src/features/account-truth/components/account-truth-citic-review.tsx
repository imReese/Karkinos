import {
  ControlledActionZone,
  EvidenceState,
} from '../../../shared/ui/workbench';
import { useCiticBatchPreviewController } from './account-truth-citic-batch-preview';
import { CiticDirectoryEvidence } from './account-truth-citic-directory-evidence';
import { CiticHistoryXlsPreviewPanel } from './account-truth-citic-preview';
import { CiticSourceIntakeHistory } from './account-truth-citic-intake-history';
import { useCiticReviewSharedState } from './account-truth-citic-shared-state';
import { useCiticSourceReviewController } from './account-truth-citic-source-review';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';

export function CiticHistoryXlsPreviewTool({
  locale,
}: {
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  const shared = useCiticReviewSharedState();
  const sourceReview = useCiticSourceReviewController(locale, shared);
  const batch = useCiticBatchPreviewController(locale, shared, sourceReview);

  return (
    <ControlledActionZone
      title={text.citicPreviewTitle}
      description={text.citicPreviewBody}
      evidence={text.citicPrivacyBoundary}
      layout="stack"
      tone="info"
    >
      <div
        className="w-full min-w-0"
        data-testid="account-truth-citic-xls-preview"
      >
        <div className="app-product-mark">{text.citicPreviewKicker}</div>
        <CiticDirectoryEvidence
          batch={batch}
          locale={locale}
          sourceReview={sourceReview}
        />
        <label className="mt-4 grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.citicChooseFile}
          <input
            accept=".xls,application/vnd.ms-excel"
            className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-dashed border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
            disabled={batch.scanPending || sourceReview.intakePending}
            multiple
            ref={shared.fileInputRef}
            type="file"
            onChange={batch.handleFileChange}
          />
        </label>
        {shared.selectedFiles.length > 0 ? (
          <div className="mt-2 text-xs text-[var(--app-text-secondary)]">
            <div className="font-semibold">
              {text.citicSelectedFiles(shared.selectedFiles.length)}
            </div>
            <ul
              className="mt-1 grid gap-0.5"
              data-testid="citic-selected-files"
            >
              {shared.selectedFiles.map((file, index) => (
                <li key={`${index}-${file.name}-${file.size}`}>{file.name}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <button
          className="app-button-secondary mt-4 min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={
            shared.selectedFiles.length === 0 ||
            batch.scanPending ||
            sourceReview.intakePending
          }
          type="button"
          onClick={batch.previewStatements}
        >
          {text.citicPreviewAction}
        </button>
        {shared.fileMessage ? (
          <EvidenceState
            className="mt-3"
            kind="partial"
            title={shared.fileMessage}
          />
        ) : null}
        {shared.batchResults.length > 0 ? (
          <>
            <CiticHistoryXlsPreviewPanel
              intakePending={sourceReview.intakePending}
              locale={locale}
              reviewIntent={shared.reviewIntent}
              results={shared.batchResults}
              onCancelReview={sourceReview.cancelReview}
              onConfirmReview={sourceReview.confirmSourceReview}
              onStartReview={sourceReview.startSourceReview}
              onUpdateReviewIntent={sourceReview.updateReviewIntent}
            />
            <p className="app-type-micro mt-3 text-[var(--app-text-tertiary)]">
              {shared.batchResults.some(
                (result) => result.sourceKind === 'configured_directory',
              )
                ? text.citicDirectoryRetainedBoundary
                : text.citicRetainedFileBoundary}
            </p>
            <button
              className="app-button-ghost mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
              disabled={batch.scanPending || sourceReview.intakePending}
              type="button"
              onClick={batch.clearLocalBatch}
            >
              {text.citicClearBatch}
            </button>
          </>
        ) : null}
        <CiticSourceIntakeHistory
          intakes={sourceReview.intakesQuery.data ?? []}
          isError={sourceReview.intakesQuery.isError}
          isPending={sourceReview.intakesQuery.isPending}
          locale={locale}
          revokePending={sourceReview.revokePending}
          onRevokeQueryWindow={sourceReview.revokeQueryWindowReview}
        />
      </div>
    </ControlledActionZone>
  );
}
