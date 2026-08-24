import { useEffect, useRef, useState } from 'react';

import type {
  CiticHistoryXlsPreviewResult,
  CiticSourceReviewIntent,
} from './account-truth-citic-types';

export function useCiticReviewSharedState() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sourceFilesRef = useRef<Map<string, File>>(new Map());
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const [batchResults, setBatchResults] = useState<
    CiticHistoryXlsPreviewResult[]
  >([]);
  const [isBatchPending, setIsBatchPending] = useState(false);
  const [reviewIntent, setReviewIntent] =
    useState<CiticSourceReviewIntent | null>(null);

  useEffect(
    () => () => {
      sourceFilesRef.current.clear();
    },
    [],
  );

  return {
    batchResults,
    fileInputRef,
    fileMessage,
    isBatchPending,
    reviewIntent,
    selectedFiles,
    setBatchResults,
    setFileMessage,
    setIsBatchPending,
    setReviewIntent,
    setSelectedFiles,
    sourceFilesRef,
  };
}

export type CiticReviewSharedState = ReturnType<
  typeof useCiticReviewSharedState
>;
