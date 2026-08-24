import {
  hashAccountTruthAccountReference,
  useCiticHistoryXlsDirectoryIntakeMutation,
  useCiticHistoryXlsDirectoryQueryWindowReviewMutation,
  useCiticHistoryXlsIntakeMutation,
  useCiticHistoryXlsIntakesQuery,
  useCiticHistoryXlsQueryWindowReviewMutation,
  useCiticHistoryXlsQueryWindowReviewRevokeMutation,
  useCiticHistoryXlsSourceScopeReviewMutation,
  useCiticHistoryXlsSourceScopeReviewRevokeMutation,
  type CiticSourceIntake,
  type CiticSourceQueryWindowReview,
  type CiticSourceReviewStatus,
} from '../api';
import { readCiticFileAsBase64 } from './account-truth-citic-file';
import type { CiticReviewSharedState } from './account-truth-citic-shared-state';
import {
  parseCiticSourceScopeCodes,
  type CiticSourceReviewIntent,
} from './account-truth-citic-types';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';

function createReviewIntent(
  resultId: string,
  reviewStatus: CiticSourceReviewStatus,
): CiticSourceReviewIntent {
  return {
    resultId,
    reviewStatus,
    queryStartDate: '',
    queryEndDate: '',
    queryWindowAttested: false,
    accountAlias: '',
    accountIdentifier: '',
    accountType: '',
    marketScopes: '',
    assetClasses: '',
    accountValueBand: '',
    businessTypes: 'history_trades',
    noOtherFiltersAttested: false,
    completeReturnedResultsAttested: false,
    sourceScopeAttested: false,
  };
}

export function useCiticSourceReviewController(
  locale: 'en' | 'zh',
  shared: CiticReviewSharedState,
) {
  const text = labels[locale];
  const {
    batchResults,
    reviewIntent,
    setBatchResults,
    setFileMessage,
    setReviewIntent,
    sourceFilesRef,
  } = shared;
  const intakeMutation = useCiticHistoryXlsIntakeMutation();
  const intakesQuery = useCiticHistoryXlsIntakesQuery();
  const directoryIntakeMutation = useCiticHistoryXlsDirectoryIntakeMutation();
  const queryWindowMutation = useCiticHistoryXlsQueryWindowReviewMutation();
  const directoryQueryWindowMutation =
    useCiticHistoryXlsDirectoryQueryWindowReviewMutation();
  const queryWindowRevokeMutation =
    useCiticHistoryXlsQueryWindowReviewRevokeMutation();
  const sourceScopeMutation = useCiticHistoryXlsSourceScopeReviewMutation();
  const sourceScopeRevokeMutation =
    useCiticHistoryXlsSourceScopeReviewRevokeMutation();
  const intakePending =
    intakeMutation.isPending ||
    directoryIntakeMutation.isPending ||
    queryWindowMutation.isPending ||
    directoryQueryWindowMutation.isPending ||
    queryWindowRevokeMutation.isPending ||
    sourceScopeMutation.isPending ||
    sourceScopeRevokeMutation.isPending;

  function resetReviewMutations() {
    intakeMutation.reset();
    directoryIntakeMutation.reset();
    queryWindowMutation.reset();
    directoryQueryWindowMutation.reset();
    queryWindowRevokeMutation.reset();
    sourceScopeMutation.reset();
    sourceScopeRevokeMutation.reset();
  }

  function startSourceReview(
    resultId: string,
    reviewStatus: CiticSourceReviewStatus,
  ) {
    setFileMessage(null);
    resetReviewMutations();
    setReviewIntent(createReviewIntent(resultId, reviewStatus));
  }

  async function confirmSourceReview() {
    if (!reviewIntent) {
      return;
    }
    const result = batchResults.find(
      (candidate) => candidate.id === reviewIntent.resultId,
    );
    const sourceFile = sourceFilesRef.current.get(reviewIntent.resultId);
    const preview = result?.preview;
    const recordsQueryWindow =
      reviewIntent.reviewStatus === 'follow_up_required';
    if (
      !result ||
      !preview ||
      (result.sourceKind === 'browser_file' && !sourceFile)
    ) {
      setFileMessage(text.citicIntakeFailed);
      setReviewIntent(null);
      return;
    }
    if (
      recordsQueryWindow &&
      (!reviewIntent.queryStartDate ||
        !reviewIntent.queryEndDate ||
        !reviewIntent.queryWindowAttested ||
        !reviewIntent.accountAlias.trim() ||
        !reviewIntent.accountIdentifier.trim() ||
        !reviewIntent.accountType.trim() ||
        parseCiticSourceScopeCodes(reviewIntent.marketScopes).length === 0 ||
        parseCiticSourceScopeCodes(reviewIntent.assetClasses).length === 0 ||
        !reviewIntent.accountValueBand.trim() ||
        parseCiticSourceScopeCodes(reviewIntent.businessTypes).length === 0 ||
        !reviewIntent.noOtherFiltersAttested ||
        !reviewIntent.completeReturnedResultsAttested ||
        !reviewIntent.sourceScopeAttested)
    ) {
      setFileMessage(text.citicSourceScopeRequired);
      return;
    }

    setBatchResults((current) =>
      current.map((candidate) =>
        candidate.id === reviewIntent.resultId
          ? {
              ...candidate,
              intakeState: 'pending',
              sourceScopeState: recordsQueryWindow ? 'pending' : 'idle',
            }
          : candidate,
      ),
    );
    let contentBase64 = '';
    let savedIntake: CiticSourceIntake | null = null;
    let savedQueryWindowReview: CiticSourceQueryWindowReview | null = null;
    try {
      if (result.sourceKind === 'browser_file') {
        contentBase64 = await readCiticFileAsBase64(sourceFile as File);
      }
      savedIntake =
        result.sourceKind === 'configured_directory'
          ? await directoryIntakeMutation.mutateAsync({
              expected_file_fingerprint: preview.file_fingerprint,
              review_status: reviewIntent.reviewStatus,
            })
          : await intakeMutation.mutateAsync({
              content_base64: contentBase64,
              expected_file_fingerprint: preview.file_fingerprint,
              review_status: reviewIntent.reviewStatus,
            });
      setBatchResults((current) =>
        current.map((candidate) =>
          candidate.id === reviewIntent.resultId
            ? {
                ...candidate,
                intakeState: 'saved',
                intake: savedIntake,
                queryWindowState: recordsQueryWindow ? 'pending' : 'idle',
                sourceScopeState: recordsQueryWindow ? 'pending' : 'idle',
              }
            : candidate,
        ),
      );
      if (recordsQueryWindow) {
        const payload = {
          expected_file_fingerprint: preview.file_fingerprint,
          expected_source_preview_fingerprint:
            preview.source_preview_fingerprint,
          query_start_date: reviewIntent.queryStartDate,
          query_end_date: reviewIntent.queryEndDate,
          query_window_attested: true as const,
        };
        const command =
          result.sourceKind === 'configured_directory'
            ? await directoryQueryWindowMutation.mutateAsync(payload)
            : await queryWindowMutation.mutateAsync({
                ...payload,
                content_base64: contentBase64,
              });
        savedIntake = {
          ...savedIntake,
          query_window_review: command.review,
        };
        savedQueryWindowReview = command.review;
        setBatchResults((current) =>
          current.map((candidate) =>
            candidate.id === reviewIntent.resultId
              ? {
                  ...candidate,
                  intakeState: 'saved',
                  intake: savedIntake,
                  queryWindowState: 'saved',
                  queryWindowReview: command.review,
                  sourceScopeState: 'pending',
                }
              : candidate,
          ),
        );
        const accountReferenceHash = await hashAccountTruthAccountReference(
          'citic',
          reviewIntent.accountIdentifier,
        );
        const sourceScopeCommand = await sourceScopeMutation.mutateAsync({
          intake_id: savedIntake.intake_id,
          expected_file_fingerprint: preview.file_fingerprint,
          expected_source_preview_fingerprint:
            preview.source_preview_fingerprint,
          expected_query_window_review_id: command.review.review_id,
          expected_query_window_review_fingerprint:
            command.review.review_fingerprint,
          account_alias: reviewIntent.accountAlias.trim(),
          account_reference_hash: accountReferenceHash,
          account_type: reviewIntent.accountType.trim().toLowerCase(),
          market_scopes: parseCiticSourceScopeCodes(reviewIntent.marketScopes),
          asset_classes: parseCiticSourceScopeCodes(reviewIntent.assetClasses),
          account_value_band: reviewIntent.accountValueBand
            .trim()
            .toLowerCase(),
          business_types: parseCiticSourceScopeCodes(
            reviewIntent.businessTypes,
          ),
          no_other_filters_attested: true,
          complete_returned_results_attested: true,
          source_scope_attested: true,
        });
        savedIntake = {
          ...savedIntake,
          source_scope_review: sourceScopeCommand.review,
        };
        setBatchResults((current) =>
          current.map((candidate) =>
            candidate.id === reviewIntent.resultId
              ? {
                  ...candidate,
                  intakeState: 'saved',
                  intake: savedIntake,
                  sourceScopeState: 'saved',
                  sourceScopeReview: sourceScopeCommand.review,
                }
              : candidate,
          ),
        );
      }
      sourceFilesRef.current.delete(reviewIntent.resultId);
      setReviewIntent(null);
    } catch {
      setBatchResults((current) =>
        current.map((candidate) =>
          candidate.id === reviewIntent.resultId
            ? savedIntake && recordsQueryWindow
              ? {
                  ...candidate,
                  intakeState: 'saved',
                  intake: savedIntake,
                  queryWindowState: savedQueryWindowReview ? 'saved' : 'error',
                  queryWindowReview:
                    savedQueryWindowReview ?? candidate.queryWindowReview,
                  sourceScopeState: savedQueryWindowReview ? 'error' : 'idle',
                }
              : { ...candidate, intakeState: 'error' }
            : candidate,
        ),
      );
      setFileMessage(
        savedIntake && recordsQueryWindow
          ? savedQueryWindowReview
            ? text.citicSourceScopeFailed
            : text.citicQueryWindowFailed
          : text.citicIntakeFailed,
      );
      setReviewIntent(null);
    } finally {
      contentBase64 = '';
    }
  }

  function updateReviewIntent(
    updates: Partial<
      Omit<CiticSourceReviewIntent, 'resultId' | 'reviewStatus'>
    >,
  ) {
    setReviewIntent((current) =>
      current ? { ...current, ...updates } : current,
    );
  }

  async function revokeQueryWindowReview(intake: CiticSourceIntake) {
    const review = intake.query_window_review;
    if (!review || review.effective_status !== 'active') {
      return;
    }
    setFileMessage(null);
    let revocationStep: 'scope' | 'query' = 'query';
    try {
      const sourceScopeReview = intake.source_scope_review;
      if (sourceScopeReview?.effective_status === 'active') {
        revocationStep = 'scope';
        const sourceScopeCommand = await sourceScopeRevokeMutation.mutateAsync({
          intake_id: intake.intake_id,
          expected_active_review_id: sourceScopeReview.review_id,
          expected_active_review_fingerprint:
            sourceScopeReview.review_fingerprint,
        });
        setBatchResults((current) =>
          current.map((candidate) =>
            candidate.intake?.intake_id === intake.intake_id
              ? {
                  ...candidate,
                  intake: {
                    ...candidate.intake,
                    source_scope_review: sourceScopeCommand.review,
                  },
                  sourceScopeState: 'idle',
                  sourceScopeReview: sourceScopeCommand.review,
                }
              : candidate,
          ),
        );
      }
      revocationStep = 'query';
      const command = await queryWindowRevokeMutation.mutateAsync({
        intake_id: intake.intake_id,
        expected_active_review_id: review.review_id,
        expected_active_review_fingerprint: review.review_fingerprint,
      });
      setBatchResults((current) =>
        current.map((candidate) =>
          candidate.intake?.intake_id === intake.intake_id
            ? {
                ...candidate,
                intake: {
                  ...candidate.intake,
                  query_window_review: command.review,
                },
                queryWindowState: 'idle',
                queryWindowReview: command.review,
              }
            : candidate,
        ),
      );
    } catch {
      setFileMessage(
        revocationStep === 'scope'
          ? text.citicSourceScopeRevokeFailed
          : text.citicQueryWindowRevokeFailed,
      );
    }
  }

  return {
    cancelReview: () => setReviewIntent(null),
    confirmSourceReview,
    intakePending,
    intakesQuery,
    resetReviewMutations,
    revokePending:
      queryWindowRevokeMutation.isPending ||
      sourceScopeRevokeMutation.isPending,
    revokeQueryWindowReview,
    startSourceReview,
    updateReviewIntent,
  };
}

export type CiticSourceReviewController = ReturnType<
  typeof useCiticSourceReviewController
>;
