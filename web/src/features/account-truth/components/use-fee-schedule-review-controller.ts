import { useState, type FormEvent } from 'react';

import type { Locale } from '../../../shared/preferences/context';
import {
  REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION,
  REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
  useReviewedFeeScheduleApprovalMutation,
  useReviewedFeeSchedulePreviewMutation,
  useReviewedFeeScheduleReviewQuery,
  useReviewedFeeScheduleRevocationMutation,
  type AccountTruthEvidenceReadiness,
} from '../api';
import { FEE_SCHEDULE_REVIEW_COPY } from './fee-schedule-review-copy';

const DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES: ['stock'] = ['stock'];

export function useFeeScheduleReviewController(
  locale: Locale,
  readiness: AccountTruthEvidenceReadiness,
) {
  const text = FEE_SCHEDULE_REVIEW_COPY[locale];
  const reviewedWindow = readiness.evidence_scope.declared_coverage_window;
  const [startDate, setStartDate] = useState(reviewedWindow.start_date ?? '');
  const [endDate, setEndDate] = useState(reviewedWindow.end_date ?? '');
  const [reviewer, setReviewer] = useState('');
  const [approvalConfirmation, setApprovalConfirmation] = useState('');
  const [revocationConfirmation, setRevocationConfirmation] = useState('');
  const reviewQuery = useReviewedFeeScheduleReviewQuery();
  const previewMutation = useReviewedFeeSchedulePreviewMutation();
  const approvalMutation = useReviewedFeeScheduleApprovalMutation();
  const revocationMutation = useReviewedFeeScheduleRevocationMutation();
  const current = reviewQuery.data;
  const currentReview = current?.review ?? null;
  const windowValid = Boolean(startDate && endDate && startDate <= endDate);
  const previewIsCurrent = Boolean(
    previewMutation.data &&
    previewMutation.data.effective_start_date === startDate &&
    previewMutation.data.effective_end_date === endDate,
  );
  const previewCanBeAccepted = Boolean(
    previewMutation.data?.status === 'ready' &&
    previewIsCurrent &&
    reviewer.trim() &&
    approvalConfirmation === REVIEWED_FEE_SCHEDULE_APPROVAL_CONFIRMATION &&
    !reviewQuery.isError &&
    !reviewQuery.isLoading &&
    !approvalMutation.isPending,
  );
  const reviewIsRevocable = currentReview?.decision === 'accepted';
  const canRevoke = Boolean(
    reviewIsRevocable &&
    reviewer.trim() &&
    revocationConfirmation === REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION &&
    !reviewQuery.isError &&
    !revocationMutation.isPending,
  );

  const handlePreview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    approvalMutation.reset();
    if (!windowValid || reviewQuery.isError) return;
    previewMutation.mutate({
      effective_start_date: startDate,
      effective_end_date: endDate,
      reviewed_asset_classes: DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES,
    });
  };

  const approvePreview = () => {
    const preview = previewMutation.data;
    if (!preview || !previewCanBeAccepted) return;
    approvalMutation.mutate(
      {
        effective_start_date: startDate,
        effective_end_date: endDate,
        reviewed_asset_classes: DAILY_CANDIDATE_REVIEWED_ASSET_CLASSES,
        expected_preview_fingerprint: preview.preview_fingerprint,
        reviewer: reviewer.trim(),
        confirmation: approvalConfirmation,
      },
      {
        onSuccess: () => {
          setApprovalConfirmation('');
          previewMutation.reset();
          revocationMutation.reset();
        },
      },
    );
  };

  const revokeReview = () => {
    if (!canRevoke || !currentReview) return;
    revocationMutation.mutate(
      {
        expected_review_id: currentReview.review_id,
        expected_review_fingerprint: currentReview.review_fingerprint,
        reviewer: reviewer.trim(),
        confirmation: revocationConfirmation,
      },
      {
        onSuccess: () => {
          setApprovalConfirmation('');
          setRevocationConfirmation('');
          approvalMutation.reset();
          previewMutation.reset();
        },
      },
    );
  };

  return {
    approvalConfirmation,
    approvalMutation,
    approvePreview,
    canRevoke,
    current,
    currentReview,
    endDate,
    handlePreview,
    previewCanBeAccepted,
    previewIsCurrent,
    previewMutation,
    reviewIsRevocable,
    reviewer,
    reviewQuery,
    revocationConfirmation,
    revocationMutation,
    revokeReview,
    setApprovalConfirmation,
    setEndDate,
    setReviewer,
    setRevocationConfirmation,
    setStartDate,
    startDate,
    text,
    windowValid,
  };
}

export type FeeScheduleReviewController = ReturnType<
  typeof useFeeScheduleReviewController
>;
