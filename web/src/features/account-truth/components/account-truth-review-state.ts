import { useEffect, useMemo, useRef, useState } from 'react';

import type { Locale } from '../../../shared/preferences/context';
import {
  useAccountTruthEvidenceReadinessQuery,
  useAccountTruthImportRunsQuery,
  useAccountTruthScoreQuery,
  useBrokerStatementCollectorStatusQuery,
  useReconciliationReportDetailQuery,
  useReconciliationReportsQuery,
  useRecordReviewDecisionMutation,
  type ReconciliationStatus,
  type ReviewStatus,
} from '../api';
import { accountTruthReviewLabels as labels } from './account-truth-review-labels';
import type { IndexedReconciliationItem } from './account-truth-reconciliation-review';

export type ReportFilter = ReconciliationStatus | 'all';

export const reportFilters: Array<{
  value: ReportFilter;
  en: string;
  zh: string;
}> = [
  { value: 'all', en: 'All', zh: '全部' },
  { value: 'pass', en: 'Pass', zh: '通过' },
  { value: 'warning', en: 'Warning', zh: '警告' },
  { value: 'mismatch', en: 'Mismatch', zh: '不一致' },
  { value: 'blocked', en: 'Blocked', zh: '阻断' },
];

export function useAccountTruthReviewState(locale: Locale) {
  const text = labels[locale];
  const [filter, setFilter] = useState<ReportFilter>('all');
  const [selectedImportRunId, setSelectedImportRunId] = useState<string | null>(
    null,
  );
  const [savedReviewStatus, setSavedReviewStatus] =
    useState<ReviewStatus | null>(null);
  const [selectedItemIdentity, setSelectedItemIdentity] = useState<
    string | null
  >(null);
  const [showMatchedItems, setShowMatchedItems] = useState(false);

  const readiness = useAccountTruthEvidenceReadinessQuery();
  const score = useAccountTruthScoreQuery();
  const importRuns = useAccountTruthImportRunsQuery();
  const hasSummaryEvidence =
    readiness.data !== undefined &&
    score.data !== undefined &&
    importRuns.data !== undefined;
  const scoreImportRunId = filter === 'all' ? score.data?.import_run_id : null;
  const reportDetailImportRunId =
    selectedImportRunId || scoreImportRunId || null;
  const detail = useReconciliationReportDetailQuery(reportDetailImportRunId);
  const shouldLoadReportHistory =
    hasSummaryEvidence &&
    (filter !== 'all' ||
      !reportDetailImportRunId ||
      detail.data !== undefined ||
      detail.isError);
  const reports = useReconciliationReportsQuery(
    filter,
    shouldLoadReportHistory,
  );
  const selectedReport = useMemo(
    () =>
      reports.data?.find(
        (report) => report.import_run_id === reportDetailImportRunId,
      ) ??
      (detail.data?.import_run_id === reportDetailImportRunId
        ? detail.data
        : null) ??
      reports.data?.[0] ??
      null,
    [detail.data, reportDetailImportRunId, reports.data],
  );
  const reviewMutation = useRecordReviewDecisionMutation();
  const collector = useBrokerStatementCollectorStatusQuery();
  const observedCollectorRunId = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const importRunId = collector.data?.import_run_id ?? null;
    if (observedCollectorRunId.current === undefined) {
      observedCollectorRunId.current = importRunId;
      return;
    }
    if (!importRunId || observedCollectorRunId.current === importRunId) {
      return;
    }
    observedCollectorRunId.current = importRunId;
    setSelectedImportRunId(importRunId);
    setFilter('all');
    void Promise.all([
      readiness.refetch(),
      score.refetch(),
      importRuns.refetch(),
      ...(shouldLoadReportHistory ? [reports.refetch()] : []),
    ]);
  }, [
    collector.data?.import_run_id,
    importRuns,
    readiness,
    reports,
    score,
    shouldLoadReportHistory,
  ]);

  useEffect(() => {
    if (!reports.data?.length) {
      setSelectedImportRunId(null);
      return;
    }
    if (
      !selectedImportRunId ||
      !reports.data.some(
        (report) => report.import_run_id === selectedImportRunId,
      )
    ) {
      setSelectedImportRunId(reports.data[0].import_run_id);
    }
  }, [reports.data, selectedImportRunId]);

  const hasError =
    readiness.isError ||
    score.isError ||
    importRuns.isError ||
    reports.isError ||
    detail.isError;
  const scoreData = score.data;
  const scoreIsMissing = scoreData?.status === 'missing';
  const componentEntries = [
    [text.componentLabels.cash, scoreData?.cash_status],
    [text.componentLabels.position, scoreData?.position_status],
    [text.componentLabels.fee, scoreData?.fee_status],
    [text.componentLabels.costBasis, scoreData?.cost_basis_status],
  ];
  const scoreNeedsAttention = Boolean(
    scoreData &&
    (scoreData.gate_status !== 'pass' ||
      componentEntries.some(([, value]) => value !== 'pass')),
  );
  const indexedItems = useMemo<IndexedReconciliationItem[]>(
    () =>
      (detail.data?.items ?? []).map((item, index) => ({
        id: `${item.item_key}:${item.evidence_fingerprint ?? 'legacy'}:${index}`,
        item,
      })),
    [detail.data?.items],
  );
  const attentionItems = useMemo(
    () =>
      indexedItems.filter(
        ({ item }) =>
          item.status !== 'pass' || item.latest_review?.is_current === false,
      ),
    [indexedItems],
  );
  const visibleItems = useMemo(
    () =>
      attentionItems.length > 0
        ? attentionItems
        : showMatchedItems
          ? indexedItems
          : [],
    [attentionItems, indexedItems, showMatchedItems],
  );
  const selectedItem =
    visibleItems.find(({ id }) => id === selectedItemIdentity) ??
    visibleItems[0] ??
    null;
  const reportHistory = (reports.data ?? []).filter(
    (report) => report.import_run_id !== selectedReport?.import_run_id,
  );

  useEffect(() => {
    setSelectedItemIdentity((current) =>
      current && visibleItems.some(({ id }) => id === current)
        ? current
        : (visibleItems[0]?.id ?? null),
    );
  }, [visibleItems]);

  function selectReport(importRunId: string) {
    setSelectedImportRunId(importRunId);
    setSelectedItemIdentity(null);
    setShowMatchedItems(false);
    setSavedReviewStatus(null);
  }

  function changeFilter(nextFilter: ReportFilter) {
    setFilter(nextFilter);
    setSelectedImportRunId(null);
    setShowMatchedItems(false);
  }

  function selectItem(identity: string) {
    setSelectedItemIdentity(identity);
    setSavedReviewStatus(null);
  }

  function recordReview(reviewStatus: ReviewStatus) {
    if (!detail.data || !selectedItem) return;
    setSavedReviewStatus(null);
    reviewMutation.mutate(
      {
        importRunId: detail.data.import_run_id,
        itemKey: selectedItem.item.item_key,
        category: selectedItem.item.category,
        symbol: selectedItem.item.symbol,
        review_status: reviewStatus,
      },
      {
        onSuccess: (decision) => {
          setSavedReviewStatus(decision.review_status);
        },
      },
    );
  }

  function imported(importRunId: string) {
    selectReport(importRunId);
    setFilter('all');
  }

  return {
    attentionItems,
    changeFilter,
    collector,
    componentEntries,
    detail,
    filter,
    hasError,
    hasSummaryEvidence,
    imported,
    importRuns,
    indexedItems,
    recordReview,
    reportHistory,
    reports,
    reviewMutation,
    readiness,
    savedReviewStatus,
    scoreData,
    scoreIsMissing,
    scoreNeedsAttention,
    selectItem,
    selectedItem,
    selectedReport,
    selectReport,
    showMatchedItems,
    toggleMatchedItems: () => setShowMatchedItems((current) => !current),
    visibleItems,
  };
}

export type AccountTruthReviewState = ReturnType<
  typeof useAccountTruthReviewState
>;
