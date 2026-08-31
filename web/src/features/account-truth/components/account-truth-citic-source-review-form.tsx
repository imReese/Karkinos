import { ControlledActionZone } from '../../../shared/ui/workbench';
import {
  parseCiticSourceScopeCodes,
  type CiticSourceReviewIntent,
} from './account-truth-citic-types';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';

export function CiticSourceReviewForm({
  fileFingerprint,
  intakePending,
  locale,
  reviewIntent,
  onCancelReview,
  onConfirmReview,
  onUpdateReviewIntent,
}: {
  fileFingerprint: string;
  intakePending: boolean;
  locale: 'en' | 'zh';
  reviewIntent: CiticSourceReviewIntent;
  onCancelReview: () => void;
  onConfirmReview: () => void;
  onUpdateReviewIntent: (
    updates: Partial<
      Omit<CiticSourceReviewIntent, 'resultId' | 'reviewStatus'>
    >,
  ) => void;
}) {
  const text = labels[locale];
  return (
    <ControlledActionZone
      className="mt-3"
      description={
        reviewIntent.reviewStatus === 'follow_up_required'
          ? text.citicConfirmFollowUpBody
          : text.citicConfirmRejectBody
      }
      evidence={`SHA-256 ${fileFingerprint}`}
      layout="stack"
      title={text.citicConfirmReview}
      tone={reviewIntent.reviewStatus === 'rejected' ? 'danger' : 'info'}
    >
      {reviewIntent.reviewStatus === 'follow_up_required' ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicQueryWindowStart}
            <input
              className="app-input min-h-10"
              type="date"
              value={reviewIntent.queryStartDate}
              onChange={(event) =>
                onUpdateReviewIntent({
                  queryStartDate: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicQueryWindowEnd}
            <input
              className="app-input min-h-10"
              type="date"
              value={reviewIntent.queryEndDate}
              onChange={(event) =>
                onUpdateReviewIntent({
                  queryEndDate: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
            <input
              checked={reviewIntent.queryWindowAttested}
              className="mt-0.5 h-4 w-4"
              type="checkbox"
              onChange={(event) =>
                onUpdateReviewIntent({
                  queryWindowAttested: event.currentTarget.checked,
                })
              }
            />
            <span>{text.citicQueryWindowAttestation}</span>
          </label>
          <p className="app-type-micro text-[var(--app-text-tertiary)] sm:col-span-2">
            {text.citicQueryWindowBoundary}
          </p>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeAccountAlias}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.accountAlias}
              onChange={(event) =>
                onUpdateReviewIntent({
                  accountAlias: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeAccountIdentifier}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              type="password"
              value={reviewIntent.accountIdentifier}
              onChange={(event) =>
                onUpdateReviewIntent({
                  accountIdentifier: event.currentTarget.value,
                })
              }
            />
            <span className="app-type-micro font-normal text-[var(--app-text-tertiary)]">
              {text.citicSourceScopeAccountIdentifierBoundary}
            </span>
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeAccountType}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.accountType}
              onChange={(event) =>
                onUpdateReviewIntent({
                  accountType: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeMarkets}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.marketScopes}
              onChange={(event) =>
                onUpdateReviewIntent({
                  marketScopes: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeAssets}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.assetClasses}
              onChange={(event) =>
                onUpdateReviewIntent({
                  assetClasses: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeBusinessTypes}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.businessTypes}
              onChange={(event) =>
                onUpdateReviewIntent({
                  businessTypes: event.currentTarget.value,
                })
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.citicSourceScopeAccountValueBand}
            <input
              className="app-input min-h-10"
              autoComplete="off"
              value={reviewIntent.accountValueBand}
              onChange={(event) =>
                onUpdateReviewIntent({
                  accountValueBand: event.currentTarget.value,
                })
              }
            />
            <span className="app-type-micro font-normal text-[var(--app-text-tertiary)]">
              {text.citicSourceScopeAccountValueBandBoundary}
            </span>
          </label>
          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
            <input
              checked={reviewIntent.noOtherFiltersAttested}
              className="mt-0.5 h-4 w-4"
              type="checkbox"
              onChange={(event) =>
                onUpdateReviewIntent({
                  noOtherFiltersAttested: event.currentTarget.checked,
                })
              }
            />
            <span>{text.citicSourceScopeNoOtherFiltersAttestation}</span>
          </label>
          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
            <input
              checked={reviewIntent.completeReturnedResultsAttested}
              className="mt-0.5 h-4 w-4"
              type="checkbox"
              onChange={(event) =>
                onUpdateReviewIntent({
                  completeReturnedResultsAttested: event.currentTarget.checked,
                })
              }
            />
            <span>{text.citicSourceScopeCompleteResultsAttestation}</span>
          </label>
          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
            <input
              checked={reviewIntent.sourceScopeAttested}
              className="mt-0.5 h-4 w-4"
              type="checkbox"
              onChange={(event) =>
                onUpdateReviewIntent({
                  sourceScopeAttested: event.currentTarget.checked,
                })
              }
            />
            <span>{text.citicSourceScopeAttestation}</span>
          </label>
          <p className="app-type-micro text-[var(--app-text-tertiary)] sm:col-span-2">
            {text.citicSourceScopeBoundary}
          </p>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={
            intakePending ||
            (reviewIntent.reviewStatus === 'follow_up_required' &&
              (!reviewIntent.queryStartDate ||
                !reviewIntent.queryEndDate ||
                !reviewIntent.queryWindowAttested ||
                !reviewIntent.accountAlias.trim() ||
                !reviewIntent.accountIdentifier.trim() ||
                !reviewIntent.accountType.trim() ||
                parseCiticSourceScopeCodes(reviewIntent.marketScopes).length ===
                  0 ||
                parseCiticSourceScopeCodes(reviewIntent.assetClasses).length ===
                  0 ||
                !reviewIntent.accountValueBand.trim() ||
                parseCiticSourceScopeCodes(reviewIntent.businessTypes)
                  .length === 0 ||
                !reviewIntent.noOtherFiltersAttested ||
                !reviewIntent.completeReturnedResultsAttested ||
                !reviewIntent.sourceScopeAttested))
          }
          type="button"
          onClick={onConfirmReview}
        >
          {text.citicConfirmAction}
        </button>
        <button
          className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={intakePending}
          type="button"
          onClick={onCancelReview}
        >
          {text.citicCancelAction}
        </button>
      </div>
    </ControlledActionZone>
  );
}
