import type { ChangeEvent } from 'react';

import {
  useCiticHistoryXlsDirectoryScanMutation,
  useCiticHistoryXlsDirectoryStatusQuery,
  useCiticHistoryXlsPreviewMutation,
} from '../api';
import {
  CITIC_HISTORY_XLS_MAX_BYTES,
  CITIC_HISTORY_XLS_MAX_FILES,
  readCiticFileAsBase64,
} from './account-truth-citic-file';
import type { CiticReviewSharedState } from './account-truth-citic-shared-state';
import type { CiticSourceReviewController } from './account-truth-citic-source-review';
import type { CiticHistoryXlsPreviewResult } from './account-truth-citic-types';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';

export function useCiticBatchPreviewController(
  locale: 'en' | 'zh',
  shared: CiticReviewSharedState,
  sourceReview: CiticSourceReviewController,
) {
  const text = labels[locale];
  const {
    fileInputRef,
    selectedFiles,
    setBatchResults,
    setFileMessage,
    setIsBatchPending,
    setReviewIntent,
    setSelectedFiles,
    sourceFilesRef,
  } = shared;
  const previewMutation = useCiticHistoryXlsPreviewMutation();
  const directoryStatusQuery = useCiticHistoryXlsDirectoryStatusQuery();
  const directoryScanMutation = useCiticHistoryXlsDirectoryScanMutation();

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    if (files.length === 0) {
      return;
    }
    previewMutation.reset();
    directoryScanMutation.reset();
    sourceReview.resetReviewMutations();
    sourceFilesRef.current.clear();
    setReviewIntent(null);
    setBatchResults([]);
    setSelectedFiles([]);
    if (files.length > CITIC_HISTORY_XLS_MAX_FILES) {
      event.currentTarget.value = '';
      setFileMessage(text.citicTooManyFiles);
      return;
    }
    if (files.some((file) => !file.name.toLowerCase().endsWith('.xls'))) {
      event.currentTarget.value = '';
      setFileMessage(text.citicWrongFile);
      return;
    }
    if (files.some((file) => file.size > CITIC_HISTORY_XLS_MAX_BYTES)) {
      event.currentTarget.value = '';
      setFileMessage(text.citicFileTooLarge);
      return;
    }
    setFileMessage(null);
    setSelectedFiles(files);
  }

  async function previewStatements() {
    if (selectedFiles.length === 0) {
      setFileMessage(text.citicNoFile);
      return;
    }
    const filesForPreview = selectedFiles;
    setFileMessage(null);
    directoryScanMutation.reset();
    setSelectedFiles([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    const preparedResults = filesForPreview.map((file, index) => ({
      id: `citic-preview-${index}-${file.size}-${file.lastModified}`,
      localFileName: file.name,
      localNameMonthHint: null,
      sourceKind: 'browser_file' as const,
      status: 'pending' as const,
      errorKind: null,
      preview: null,
      intakeState: 'idle' as const,
      intake: null,
      queryWindowState: 'idle' as const,
      queryWindowReview: null,
      sourceScopeState: 'idle' as const,
      sourceScopeReview: null,
    }));
    sourceFilesRef.current = new Map(
      preparedResults.map((result, index) => [
        result.id,
        filesForPreview[index],
      ]),
    );
    setBatchResults(preparedResults);
    setIsBatchPending(true);

    for (const [index, file] of filesForPreview.entries()) {
      let contentBase64 = '';
      let errorKind: CiticHistoryXlsPreviewResult['errorKind'] = 'read';
      try {
        contentBase64 = await readCiticFileAsBase64(file);
        errorKind = 'preview';
        const result = await previewMutation.mutateAsync({
          content_base64: contentBase64,
        });
        setBatchResults((current) =>
          current.map((item, itemIndex) =>
            itemIndex === index
              ? {
                  ...item,
                  status: 'complete',
                  errorKind: null,
                  preview: result,
                }
              : item,
          ),
        );
      } catch {
        sourceFilesRef.current.delete(preparedResults[index].id);
        setBatchResults((current) =>
          current.map((item, itemIndex) =>
            itemIndex === index
              ? { ...item, status: 'error', errorKind, preview: null }
              : item,
          ),
        );
      } finally {
        contentBase64 = '';
        previewMutation.reset();
      }
    }
    setIsBatchPending(false);
  }

  async function previewConfiguredDirectory() {
    setFileMessage(null);
    setSelectedFiles([]);
    setReviewIntent(null);
    setBatchResults([]);
    sourceFilesRef.current.clear();
    previewMutation.reset();
    sourceReview.resetReviewMutations();
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    try {
      const scan = await directoryScanMutation.mutateAsync();
      if (scan.items.length === 0) {
        setFileMessage(
          scan.state === 'empty' || scan.state === 'disabled'
            ? text.citicDirectoryEmpty
            : text.citicDirectoryScanFailed,
        );
        return;
      }
      setBatchResults(
        scan.items.map(
          (
            {
              local_name_month_hint: localNameMonthHint,
              source_intake: sourceIntake,
              ...preview
            },
            index,
          ) => ({
            id: `citic-directory-${preview.file_fingerprint}`,
            localFileName: text.citicConfiguredSource(index + 1),
            localNameMonthHint,
            sourceKind: 'configured_directory' as const,
            status: 'complete' as const,
            errorKind: null,
            preview,
            intakeState: sourceIntake ? ('saved' as const) : ('idle' as const),
            intake: sourceIntake,
            queryWindowState:
              sourceIntake?.query_window_review?.effective_status === 'active'
                ? ('saved' as const)
                : ('idle' as const),
            queryWindowReview: sourceIntake?.query_window_review ?? null,
            sourceScopeState:
              sourceIntake?.source_scope_review?.effective_status === 'active'
                ? ('saved' as const)
                : ('idle' as const),
            sourceScopeReview: sourceIntake?.source_scope_review ?? null,
          }),
        ),
      );
      if (scan.unreadable_file_count > 0) {
        setFileMessage(text.citicDirectoryPartial(scan.unreadable_file_count));
      }
    } catch {
      setFileMessage(text.citicDirectoryScanFailed);
    }
  }
  function clearLocalBatch() {
    sourceFilesRef.current.clear();
    setSelectedFiles([]);
    setBatchResults([]);
    setReviewIntent(null);
    setFileMessage(null);
    previewMutation.reset();
    directoryScanMutation.reset();
    sourceReview.resetReviewMutations();
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }

  return {
    clearLocalBatch,
    directoryScanMutation,
    directoryStatusQuery,
    handleFileChange,
    previewConfiguredDirectory,
    previewStatements,
    scanPending: shared.isBatchPending || directoryScanMutation.isPending,
  };
}

export type CiticBatchPreviewController = ReturnType<
  typeof useCiticBatchPreviewController
>;
