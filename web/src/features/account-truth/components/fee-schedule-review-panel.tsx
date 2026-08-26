import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge,
} from '../../../shared/ui/workbench';
import type { Locale } from '../../../shared/preferences/context';
import { formatDateTime } from '../../../shared/format';
import { formatPublicCode } from '../../../shared/public-labels';
import {
  REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  type AccountTruthEvidenceReadiness,
  type ReviewedFeeSchedulePreview,
} from '../api';
import {
  FEE_SCHEDULE_REVIEW_COPY,
  formatFeeScheduleIssue,
  reviewStatusLabel,
  reviewTone,
} from './fee-schedule-review-copy';
import {
  type FeeScheduleReviewController,
  useFeeScheduleReviewController,
} from './use-fee-schedule-review-controller';

const inputClass =
  'min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]';

function PreviewSummary({
  locale,
  preview,
}: {
  locale: Locale;
  preview: ReviewedFeeSchedulePreview;
}) {
  const text = FEE_SCHEDULE_REVIEW_COPY[locale];
  const components = preview.component_reconciliation;
  const schedule = preview.schedule;
  return (
    <div
      className="mt-4 border-y border-[var(--app-divider)] py-3"
      data-testid="fee-schedule-preview-summary"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="app-type-subsection-title text-[var(--app-text)]">
          {preview.status === 'ready' ? text.previewReady : text.previewBlocked}
        </h3>
        <StatusBadge tone={reviewTone(preview.status)}>
          {formatPublicCode(preview.status, locale)}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs font-semibold text-[var(--app-text-secondary)]">
        {text.reviewedScope} · {text.excludedTrades}:{' '}
        {components.excluded_trade_count ?? 0}
      </p>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-5">
        {[
          [text.trades, String(components.trade_count)],
          [text.matched, String(components.matched_trade_count)],
          [text.buys, String(components.side_counts.buy)],
          [text.sells, String(components.side_counts.sell)],
          [text.tolerance, components.tolerance],
        ].map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-[var(--app-text-tertiary)]">{label}</dt>
            <dd className="mt-0.5 font-mono font-semibold text-[var(--app-text)]">
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <dl className="mt-3 grid gap-2 border-t border-[var(--app-divider)] pt-3 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-[var(--app-text-tertiary)]">{text.stockTerms}</dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.stock_a_commission_rate} · {text.min}{' '}
            {schedule.stock_a_min_commission}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--app-text-tertiary)]">{text.sellTax}</dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.stamp_tax_rate}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--app-text-tertiary)]">
            {text.stockTransfer}
          </dt>
          <dd className="mt-0.5 font-mono text-[var(--app-text)]">
            {schedule.transfer_fee_rate}
          </dd>
        </div>
      </dl>
      {components.mismatch_counts_by_asset_and_side.length > 0 ? (
        <div
          className="mt-3 border-t border-[var(--app-divider)] pt-3"
          data-testid="fee-schedule-mismatch-breakdown"
        >
          <div className="text-xs font-semibold text-[var(--app-text)]">
            {text.mismatchBreakdown}
          </div>
          <ul className="mt-1 space-y-1 text-xs text-[var(--app-text-secondary)]">
            {components.mismatch_counts_by_asset_and_side.map((item) => (
              <li key={`${item.asset_class}:${item.side}`}>
                <span className="font-mono font-semibold text-[var(--app-text)]">
                  {formatPublicCode(item.asset_class, locale)} ·{' '}
                  {formatPublicCode(item.side, locale)}
                </span>{' '}
                — {text.feeMismatch} {item.fee} · {text.taxMismatch} {item.tax}{' '}
                · {text.transferMismatch} {item.transfer_fee}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="app-type-micro mt-3 font-mono leading-5 text-[var(--app-text-tertiary)] [overflow-wrap:anywhere]">
        {text.previewIdentity}: {preview.preview_fingerprint}
      </p>
      {preview.issues.length > 0 ? (
        <div className="mt-3">
          <div className="text-xs font-semibold text-[var(--app-danger)]">
            {text.issues}
          </div>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-[var(--app-text-secondary)]">
            {preview.issues.map((issue) => (
              <li key={issue}>{formatFeeScheduleIssue(issue, locale)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function FeeScheduleReviewPanel({
  locale,
  readiness,
}: {
  locale: Locale;
  readiness: AccountTruthEvidenceReadiness;
}) {
  const controller = useFeeScheduleReviewController(locale, readiness);
  const { current, currentReview, reviewQuery, revocationMutation, text } =
    controller;

  return (
    <section
      className="app-workbench-section min-w-0 px-1 py-4 sm:px-4"
      data-testid="account-truth-fee-schedule-review"
      id="account-truth-fee-schedule-review"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="app-product-mark">{text.kicker}</div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {text.title}
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {text.detail}
          </p>
        </div>
        <StatusBadge tone={reviewTone(current?.status ?? 'missing')}>
          {reviewStatusLabel(current?.status ?? 'missing', locale)}
        </StatusBadge>
      </div>

      <CurrentReviewEvidence
        error={reviewQuery.isError}
        loading={reviewQuery.isLoading}
        status={current?.status}
        text={text}
      />
      {currentReview ? <CurrentReviewIdentity controller={controller} /> : null}
      {(current?.blockers ?? []).length > 0 && current?.status === 'blocked' ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-[var(--app-danger)]">
          {current.blockers.map((blocker) => (
            <li key={blocker}>{formatFeeScheduleIssue(blocker, locale)}</li>
          ))}
        </ul>
      ) : null}
      {revocationMutation.isSuccess ? (
        <EvidenceState className="mt-3" kind="ready" title={text.revoked} />
      ) : null}

      <FeeSchedulePreviewForm controller={controller} locale={locale} />
      <FeeScheduleApprovalZone controller={controller} />
      <FeeScheduleRevocationZone controller={controller} />

      <p className="mt-4 border-t border-[var(--app-divider)] pt-3 text-xs leading-5 text-[var(--app-text-tertiary)]">
        {text.boundary}
      </p>
    </section>
  );
}

function CurrentReviewIdentity({
  controller,
}: {
  controller: FeeScheduleReviewController;
}) {
  const { currentReview, text } = controller;
  if (!currentReview) return null;
  return (
    <dl className="mt-3 grid gap-2 border-y border-[var(--app-divider)] py-3 text-xs sm:grid-cols-2">
      <div>
        <dt className="text-[var(--app-text-tertiary)]">
          {text.reviewIdentity}
        </dt>
        <dd className="mt-0.5 font-mono text-[var(--app-text)] [overflow-wrap:anywhere]">
          {currentReview.review_id} · {currentReview.review_fingerprint}
        </dd>
      </div>
      <div>
        <dt className="text-[var(--app-text-tertiary)]">{text.recordedAt}</dt>
        <dd className="mt-0.5 text-[var(--app-text)]">
          {formatDateTime(currentReview.created_at)} · {currentReview.reviewer}
        </dd>
      </div>
      <div>
        <dt className="text-[var(--app-text-tertiary)]">
          {text.effectiveWindow}
        </dt>
        <dd className="mt-0.5 font-mono text-[var(--app-text)]">
          {currentReview.effective_start_date} –{' '}
          {currentReview.effective_end_date}
        </dd>
      </div>
      <div>
        <dt className="text-[var(--app-text-tertiary)]">
          {text.scheduleIdentity}
        </dt>
        <dd className="mt-0.5 font-mono text-[var(--app-text)] [overflow-wrap:anywhere]">
          {currentReview.schedule_fingerprint}
        </dd>
      </div>
    </dl>
  );
}

function FeeSchedulePreviewForm({
  controller,
  locale,
}: {
  controller: FeeScheduleReviewController;
  locale: Locale;
}) {
  const {
    endDate,
    handlePreview,
    previewMutation,
    reviewQuery,
    setEndDate,
    setStartDate,
    startDate,
    text,
    windowValid,
  } = controller;
  return (
    <>
      <form className="mt-4" onSubmit={handlePreview}>
        <fieldset
          className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
          disabled={reviewQuery.isError}
        >
          <legend className="sr-only">{text.effectiveWindow}</legend>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.startDate}
            <input
              className={inputClass}
              data-testid="fee-schedule-start-date"
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.currentTarget.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.endDate}
            <input
              className={inputClass}
              data-testid="fee-schedule-end-date"
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.currentTarget.value)}
            />
          </label>
          <button
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!windowValid || previewMutation.isPending}
            type="submit"
          >
            {previewMutation.isPending ? text.previewing : text.preview}
          </button>
        </fieldset>
      </form>
      {!windowValid ? (
        <p className="mt-2 text-xs text-[var(--app-danger)]">
          {text.invalidWindow}
        </p>
      ) : null}
      {previewMutation.data ? (
        <PreviewSummary locale={locale} preview={previewMutation.data} />
      ) : null}
      {previewMutation.isError ? (
        <EvidenceState
          className="mt-3"
          kind="error"
          title={text.previewFailed}
        />
      ) : null}
    </>
  );
}

function FeeScheduleApprovalZone({
  controller,
}: {
  controller: FeeScheduleReviewController;
}) {
  const {
    approvalConfirmation,
    approvalMutation,
    approvePreview,
    previewCanBeAccepted,
    previewIsCurrent,
    previewMutation,
    reviewer,
    setApprovalConfirmation,
    setReviewer,
    text,
  } = controller;
  if (previewMutation.data?.status !== 'ready' || !previewIsCurrent)
    return null;
  return (
    <ControlledActionZone
      className="mt-4"
      description={text.approvalDetail}
      evidence={REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION}
      layout="stack"
      title={text.approval}
      tone="info"
    >
      <FeeScheduleReviewerFields
        confirmation={approvalConfirmation}
        confirmationLabel={text.confirmation}
        reviewer={reviewer}
        reviewerLabel={text.reviewer}
        setConfirmation={setApprovalConfirmation}
        setReviewer={setReviewer}
      />
      <button
        className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!previewCanBeAccepted}
        type="button"
        onClick={approvePreview}
      >
        {approvalMutation.isPending ? text.approving : text.approve}
      </button>
      {approvalMutation.isSuccess ? (
        <p className="text-xs font-semibold text-[var(--app-success)]">
          {text.approved}
        </p>
      ) : null}
      {approvalMutation.isError ? (
        <p className="text-xs font-semibold text-[var(--app-danger)]">
          {text.approvalFailed}
        </p>
      ) : null}
    </ControlledActionZone>
  );
}

function FeeScheduleRevocationZone({
  controller,
}: {
  controller: FeeScheduleReviewController;
}) {
  const {
    canRevoke,
    currentReview,
    reviewIsRevocable,
    reviewer,
    revocationConfirmation,
    revocationMutation,
    revokeReview,
    setReviewer,
    setRevocationConfirmation,
    text,
  } = controller;
  if (!reviewIsRevocable || !currentReview) return null;
  return (
    <ControlledActionZone
      className="mt-4"
      description={text.revokeDetail}
      evidence={`${currentReview.review_id} · ${currentReview.review_fingerprint}`}
      layout="stack"
      title={text.revoke}
    >
      <FeeScheduleReviewerFields
        confirmation={revocationConfirmation}
        confirmationLabel={text.revocationConfirmation}
        reviewer={reviewer}
        reviewerLabel={text.reviewer}
        setConfirmation={setRevocationConfirmation}
        setReviewer={setReviewer}
      />
      <button
        className="min-h-10 rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] px-4 text-xs font-semibold text-[var(--app-danger)] disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!canRevoke}
        type="button"
        onClick={revokeReview}
      >
        {revocationMutation.isPending ? text.revoking : text.revokeAction}
      </button>
      {revocationMutation.isError ? (
        <p className="text-xs font-semibold text-[var(--app-danger)]">
          {text.revocationFailed}
        </p>
      ) : null}
    </ControlledActionZone>
  );
}

function FeeScheduleReviewerFields({
  confirmation,
  confirmationLabel,
  reviewer,
  reviewerLabel,
  setConfirmation,
  setReviewer,
}: {
  confirmation: string;
  confirmationLabel: string;
  reviewer: string;
  reviewerLabel: string;
  setConfirmation: (value: string) => void;
  setReviewer: (value: string) => void;
}) {
  return (
    <div className="grid w-full gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
        {reviewerLabel}
        <input
          autoComplete="off"
          className={inputClass}
          maxLength={128}
          value={reviewer}
          onChange={(event) => setReviewer(event.currentTarget.value)}
        />
      </label>
      <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
        {confirmationLabel}
        <input
          autoComplete="off"
          className={inputClass}
          value={confirmation}
          onChange={(event) => setConfirmation(event.currentTarget.value)}
        />
      </label>
    </div>
  );
}

function CurrentReviewEvidence({
  error,
  loading,
  status,
  text,
}: {
  error: boolean;
  loading: boolean;
  status: string | undefined;
  text: (typeof FEE_SCHEDULE_REVIEW_COPY)[Locale];
}) {
  if (error) {
    return (
      <EvidenceState
        className="mt-4"
        kind="error"
        title={text.unavailable}
        description={text.unavailableDetail}
      />
    );
  }
  if (loading) {
    return (
      <EvidenceState className="mt-4" kind="loading" title={text.current} />
    );
  }
  if (status === 'active') {
    return (
      <EvidenceState
        className="mt-4"
        kind="ready"
        title={text.currentActive}
        description={text.currentActiveDetail}
      />
    );
  }
  if (status === 'blocked') {
    return (
      <EvidenceState
        className="mt-4"
        kind="partial"
        title={text.currentBlocked}
        description={text.currentBlockedDetail}
      />
    );
  }
  return (
    <EvidenceState
      className="mt-4"
      kind="partial"
      title={status === 'revoked' ? text.currentRevoked : text.noReview}
      description={
        status === 'revoked' ? text.currentRevokedDetail : text.noReviewDetail
      }
    />
  );
}
