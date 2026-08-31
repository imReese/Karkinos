import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../../shared/api/client';
import type {
  ReviewedFeeSchedulePreview,
  ReviewedFeeScheduleReviewCommand,
  ReviewedFeeScheduleReviewStatus,
} from './api-contracts';
import { postAccountTruthJson } from './api-request';

export function useReviewedFeeScheduleReviewQuery() {
  return useQuery({
    queryKey: ['account-truth-fee-schedule-review'],
    queryFn: () =>
      apiClient<ReviewedFeeScheduleReviewStatus>(
        '/api/account-truth/fee-schedule/review',
      ),
    staleTime: 5_000,
  });
}

export function useReviewedFeeSchedulePreviewMutation() {
  return useMutation({
    mutationFn: (payload: {
      effective_start_date: string;
      effective_end_date: string;
      reviewed_asset_classes: ['stock'];
    }) =>
      postAccountTruthJson<ReviewedFeeSchedulePreview>(
        '/api/account-truth/fee-schedule/preview',
        payload,
      ),
  });
}

export function useReviewedFeeScheduleApprovalMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      effective_start_date: string;
      effective_end_date: string;
      reviewed_asset_classes: ['stock'];
      expected_preview_fingerprint: string;
      reviewer: string;
      confirmation: string;
    }) =>
      postAccountTruthJson<ReviewedFeeScheduleReviewCommand>(
        '/api/account-truth/fee-schedule/reviews',
        payload,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-fee-schedule-review'],
      });
    },
  });
}

export function useReviewedFeeScheduleRevocationMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      expected_review_id: string;
      expected_review_fingerprint: string;
      reviewer: string;
      confirmation: string;
    }) =>
      postAccountTruthJson<ReviewedFeeScheduleReviewCommand>(
        '/api/account-truth/fee-schedule/reviews/revoke',
        payload,
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['account-truth-fee-schedule-review'],
      });
    },
  });
}
