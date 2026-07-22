import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react';

import { usePreferences } from '../../../app/preferences';
import {
  ControlledActionZone,
  EvidenceIdentityDisclosure,
  EvidenceState,
  MetricStrip,
  StatusBadge,
  WorkspaceHeader,
  type StatusTone,
} from '../../../app/components/workbench';
import {
  formatCurrency,
  formatDateTime,
  formatQuantity,
} from '../../../shared/format';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicReviewActionLabel,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatLedgerEvidenceReference } from '../../../shared/ledger-format';
import {
  useBrokerStatementImportMutation,
  useBrokerStatementPreviewMutation,
  useBrokerStatementCollectorStatusQuery,
  useAccountTruthImportRunsQuery,
  useAccountTruthScoreQuery,
  useReconciliationReportDetailQuery,
  useReconciliationReportsQuery,
  useRecordReviewDecisionMutation,
  type BrokerStatementPreview,
  type BrokerStatementCollectorStatus,
  type ReconciliationItem,
  type ReconciliationStatus,
  type ReviewStatus,
} from '../api';

type ReportFilter = ReconciliationStatus | 'all';

type IndexedReconciliationItem = {
  id: string;
  item: ReconciliationItem;
};

const filters: Array<{ value: ReportFilter; en: string; zh: string }> = [
  { value: 'all', en: 'All', zh: '全部' },
  { value: 'pass', en: 'Pass', zh: '通过' },
  { value: 'warning', en: 'Warning', zh: '警告' },
  { value: 'mismatch', en: 'Mismatch', zh: '不一致' },
  { value: 'blocked', en: 'Blocked', zh: '阻断' },
];

const reviewActions: ReviewStatus[] = [
  'accepted',
  'ignored',
  'known_difference',
  'ledger_candidate',
  'needs_investigation',
];

const labels = {
  en: {
    kicker: 'Account Truth',
    title: 'Account Truth Review Center',
    subtitle:
      'Review broker evidence, reconciliation gaps, and manual decisions before relying on account facts.',
    loading: 'Loading Account Truth evidence.',
    error: 'Failed to load Account Truth evidence.',
    score: 'Score',
    scorePending: 'Not ready',
    gate: 'Gate',
    unresolved: 'Unresolved',
    resolved: 'Resolved reviews',
    freshness: 'Freshness',
    components: 'Component reasons',
    blockingReasons: 'Blocking reasons',
    requiredActions: 'Required actions',
    imports: 'Import runs',
    reports: 'Reconciliation reports',
    reviewWorkspace: 'Current reconciliation',
    reviewWorkspaceDetail:
      'Start with unresolved or stale review evidence. Matched rows stay quiet until requested.',
    detail: 'Report detail',
    reportHistory: 'Earlier reconciliation reports',
    reportHistoryCount: (count: number) =>
      `${count} earlier ${count === 1 ? 'report' : 'reports'}`,
    reportListLabel: 'Reconciliation report selection',
    currentReport: 'Selected report',
    attentionItems: 'Items requiring review',
    matchedItems: 'Matched rows',
    matchedItemsQuiet: (count: number) =>
      `${count} matched ${count === 1 ? 'row is' : 'rows are'} quiet because no current blocker was found.`,
    showMatchedItems: (count: number) =>
      `Inspect ${count} matched ${count === 1 ? 'row' : 'rows'}`,
    hideMatchedItems: 'Hide matched rows',
    itemListLabel: 'Reconciliation item selection',
    selectItem: 'Inspect item',
    itemCount: (count: number) => `${count} ${count === 1 ? 'item' : 'items'}`,
    rows: 'Rows',
    duplicates: 'duplicates',
    cashDifference: 'Cash difference',
    feeDifference: 'Fee difference',
    taxDifference: 'Tax difference',
    validation: 'Validation',
    source: 'Source',
    created: 'Created',
    limitations: 'Limitations',
    noImports: 'No staged broker evidence yet.',
    noReports: 'No reconciliation reports for this filter.',
    noItems: 'No reconciliation differences in this report.',
    notReadyTitle: 'Account facts are not ready',
    notReadyBody:
      'No broker statement, position snapshot, or cash snapshot has been staged yet.',
    workflowTitle: 'How to use this page',
    workflowSteps: [
      'Import broker evidence',
      'Run reconciliation against Karkinos ledger and positions',
      'Then return here to review differences',
    ],
    importWizardKicker: 'Broker CSV',
    importWizardTitle: 'Upload broker statement',
    importWizardBody:
      'Upload or paste a standard broker statement CSV. Preview validates the file without staging evidence.',
    importToolsTitle: 'Stage new broker evidence',
    importToolsDetail:
      'Explicit ingestion writes an auditable evidence run; it never posts the production ledger.',
    importHistoryTitle: 'Import history',
    importHistoryDetail: (count: number) =>
      `${count} persisted ${count === 1 ? 'import run' : 'import runs'}`,
    scoreEvidenceTitle: 'Account Truth gate evidence',
    scoreEvidenceDetail:
      'Component states, blockers, and required human actions supporting the score.',
    sourceName: 'Source name',
    chooseFile: 'Choose CSV file',
    csvContent: 'CSV content',
    previewImport: 'Preview',
    confirmImport: 'Stage evidence and reconcile',
    previewReady: 'Preview ready',
    importReady: 'Evidence staged',
    importFailed: 'Import failed',
    noFileContent: 'Choose a CSV file or paste CSV content first.',
    validRows: 'Valid rows',
    invalidRows: 'Invalid rows',
    duplicateRows: 'Duplicate rows',
    eventPreview: 'Event preview',
    importBoundary:
      'This stages broker evidence only. It does not mutate the production ledger, positions, cash, or broker orders.',
    collectorTitle: 'Automatic local reader',
    collectorLoading: 'Checking the local collector.',
    collectorUnavailable: 'Collector status is unavailable.',
    collectorPath: 'Path',
    collectorRun: 'Import run',
    collectorFallback:
      'Manual upload remains available as a fallback. Automatic reading never posts the ledger.',
    broker: 'Broker',
    karkinos: 'Karkinos',
    difference: 'Difference',
    suggestedAction: 'Suggested action',
    evidence: 'Evidence',
    evidenceDetail: 'Evidence detail',
    openEvidence: 'Open evidence detail',
    closeEvidence: 'Close evidence detail',
    copyEvidence: (field: string) => `Copy ${field}`,
    copiedEvidence: (field: string) => `Copied ${field}`,
    importRunIdentity: 'Import run',
    itemIdentity: 'Item identity',
    evidenceReference: (index: number) => `Evidence reference ${index}`,
    auditDecision: 'Record audit decision',
    auditDecisionDetail:
      'This appends a review label only. New persisted evidence is still required to clear a material mismatch.',
    showAuditActions: 'Show audit review actions',
    latestReview: 'Latest review',
    currentReview: 'Bound to current facts',
    staleReview: 'Stale review — reconciliation facts changed',
    reviewSaved: 'Review saved',
    reviewFailed: 'Review failed',
    safety:
      'Manual review is an audit label only. It cannot clear a material mismatch, mutate the production ledger, or submit broker orders.',
    componentLabels: {
      cash: 'Cash',
      position: 'Position',
      fee: 'Fee',
      costBasis: 'Cost basis',
    },
  },
  zh: {
    kicker: '账户事实',
    title: '账户事实复核中心',
    subtitle: '在依赖账户事实前，复核券商证据、对账差异和人工处理状态。',
    loading: '正在加载账户事实证据。',
    error: '账户事实证据加载失败。',
    score: '分数',
    scorePending: '待导入',
    gate: '闸门',
    unresolved: '未解决差异',
    resolved: '已复核',
    freshness: '新鲜度',
    components: '组件原因',
    blockingReasons: '阻断原因',
    requiredActions: '下一步动作',
    imports: '导入批次',
    reports: '对账报告',
    reviewWorkspace: '当前对账复核',
    reviewWorkspaceDetail:
      '优先查看未解决差异与已失效复核；匹配明细默认保持安静。',
    detail: '报告明细',
    reportHistory: '历史对账报告',
    reportHistoryCount: (count: number) => `${count} 份较早报告`,
    reportListLabel: '选择对账报告',
    currentReport: '当前报告',
    attentionItems: '待复核明细',
    matchedItems: '已匹配明细',
    matchedItemsQuiet: (count: number) =>
      `${count} 条明细未发现当前阻断，默认收起。`,
    showMatchedItems: (count: number) => `查看 ${count} 条已匹配明细`,
    hideMatchedItems: '收起已匹配明细',
    itemListLabel: '选择对账明细',
    selectItem: '查看明细',
    itemCount: (count: number) => `${count} 条明细`,
    rows: '行数',
    duplicates: '重复',
    cashDifference: '现金差异',
    feeDifference: '费用差异',
    taxDifference: '税费差异',
    validation: '校验',
    source: '来源',
    created: '创建时间',
    limitations: '限制',
    noImports: '还没有暂存的券商证据。',
    noReports: '当前筛选下没有对账报告。',
    noItems: '该报告没有对账差异。',
    notReadyTitle: '账户事实尚未建立',
    notReadyBody:
      '还没有暂存券商交割单、持仓快照或现金快照，暂时无法计算账户事实分。',
    workflowTitle: '这个页面怎么用',
    workflowSteps: [
      '先导入券商证据',
      '把券商证据与 Karkinos 账本和持仓做对账',
      '回到这里逐条复核差异',
    ],
    importWizardKicker: '券商 CSV',
    importWizardTitle: '上传券商流水',
    importWizardBody:
      '上传或粘贴标准券商流水 CSV。预览只校验文件，不会暂存证据。',
    importToolsTitle: '暂存新的券商证据',
    importToolsDetail:
      '显式导入会写入可审计证据批次，但不会把数据写入生产账本。',
    importHistoryTitle: '导入历史',
    importHistoryDetail: (count: number) => `${count} 个持久化导入批次`,
    scoreEvidenceTitle: '账户事实闸门证据',
    scoreEvidenceDetail: '查看分数组件、阻断原因和所需人工动作。',
    sourceName: '来源名称',
    chooseFile: '选择 CSV 文件',
    csvContent: 'CSV 内容',
    previewImport: '预览',
    confirmImport: '暂存证据并对账',
    previewReady: '预览完成',
    importReady: '证据已暂存',
    importFailed: '导入失败',
    noFileContent: '请先选择 CSV 文件或粘贴 CSV 内容。',
    validRows: '有效行',
    invalidRows: '无效行',
    duplicateRows: '重复行',
    eventPreview: '事件预览',
    importBoundary:
      '这里只暂存券商证据；不会修改生产账本、持仓、现金，也不会提交券商订单。',
    collectorTitle: '本地自动读取',
    collectorLoading: '正在检查本地 collector。',
    collectorUnavailable: '暂时无法读取 collector 状态。',
    collectorPath: '文件',
    collectorRun: '导入批次',
    collectorFallback: '手工上传仍作为 fallback；自动读取永远不会自动入账。',
    broker: '券商',
    karkinos: 'Karkinos',
    difference: '差异',
    suggestedAction: '建议动作',
    evidence: '证据',
    evidenceDetail: '证据详情',
    openEvidence: '查看证据详情',
    closeEvidence: '关闭证据详情',
    copyEvidence: (field: string) => `复制${field}`,
    copiedEvidence: (field: string) => `已复制${field}`,
    importRunIdentity: '导入批次',
    itemIdentity: '明细标识',
    evidenceReference: (index: number) => `证据引用 ${index}`,
    auditDecision: '记录审计处理',
    auditDecisionDetail:
      '这里只追加复核标签；物质性差异仍需新的持久化证据才能解除。',
    showAuditActions: '显示审计复核动作',
    latestReview: '最近复核',
    currentReview: '已绑定当前事实',
    staleReview: '复核已失效：对账事实已变化',
    reviewSaved: '复核已保存',
    reviewFailed: '复核保存失败',
    safety:
      '人工复核只是审计标签，不能清除仍存在的物质性差异，不会修改生产账本，也不会提交券商订单。',
    componentLabels: {
      cash: '现金',
      position: '持仓',
      fee: '费用',
      costBasis: '成本价',
    },
  },
} as const;

const currencyReconciliationCategories = new Set([
  'cash',
  'fee',
  'tax',
  'trade_gross_amount',
  'net_cash_impact',
  'transfer_fee',
]);

function parseReconciliationNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed || trimmed === '--') {
    return null;
  }
  const parsed = Number(trimmed.replace(/,/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function formatReconciliationValue(
  category: string,
  value: string,
  locale: 'en' | 'zh',
) {
  const parsed = parseReconciliationNumber(value);
  if (parsed === null) {
    return value || '--';
  }

  if (category === 'position') {
    return `${formatQuantity(parsed)} ${locale === 'zh' ? '股' : 'shares'}`;
  }

  if (category === 'cost_basis') {
    return formatCurrency(parsed, {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });
  }

  if (currencyReconciliationCategories.has(category)) {
    return formatCurrency(parsed);
  }

  return value;
}

export function AccountTruthReviewPage() {
  const { locale } = usePreferences();
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

  const score = useAccountTruthScoreQuery();
  const importRuns = useAccountTruthImportRunsQuery();
  const reports = useReconciliationReportsQuery(filter);
  const selectedReport = useMemo(
    () =>
      reports.data?.find(
        (report) => report.import_run_id === selectedImportRunId,
      ) ??
      reports.data?.[0] ??
      null,
    [reports.data, selectedImportRunId],
  );
  const detail = useReconciliationReportDetailQuery(
    selectedReport?.import_run_id ?? null,
  );
  const reviewMutation = useRecordReviewDecisionMutation();
  const collector = useBrokerStatementCollectorStatusQuery();
  const observedCollectorRunId = useRef<string | null>(null);

  useEffect(() => {
    const importRunId = collector.data?.import_run_id ?? null;
    if (!importRunId || observedCollectorRunId.current === importRunId) {
      return;
    }
    observedCollectorRunId.current = importRunId;
    setSelectedImportRunId(importRunId);
    setFilter('all');
    void Promise.all([
      score.refetch(),
      importRuns.refetch(),
      reports.refetch(),
    ]);
  }, [collector.data?.import_run_id, importRuns, reports, score]);

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

  const loading =
    score.isLoading ||
    importRuns.isLoading ||
    reports.isLoading ||
    detail.isLoading;
  const hasError =
    score.isError || importRuns.isError || reports.isError || detail.isError;
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

  const selectReport = (importRunId: string) => {
    setSelectedImportRunId(importRunId);
    setSelectedItemIdentity(null);
    setShowMatchedItems(false);
    setSavedReviewStatus(null);
  };

  return (
    <section
      className="app-account-truth-route app-workbench-route mx-auto grid w-full max-w-[1440px] gap-5 sm:gap-6"
      data-workbench-route="account-truth"
    >
      <WorkspaceHeader
        eyebrow={text.kicker}
        title={text.title}
        description={text.subtitle}
        context={text.safety}
      />

      {hasError ? <EvidenceState kind="error" title={text.error} /> : null}
      {loading ? <EvidenceState kind="loading" title={text.loading} /> : null}

      <MetricStrip
        ariaLabel={text.score}
        items={[
          {
            id: 'score',
            label: text.score,
            value: scoreData?.score ?? text.scorePending,
            detail: `${text.gate}: ${formatCode(
              scoreData?.gate_status ?? '--',
              locale,
              'status',
            )}`,
            tone: scoreData?.gate_status === 'blocked' ? 'warning' : 'neutral',
          },
          {
            id: 'unresolved',
            label: text.unresolved,
            value: String(scoreData?.unresolved_mismatch_count ?? '--'),
          },
          {
            id: 'resolved',
            label: text.resolved,
            value: String(scoreData?.resolved_review_count ?? '--'),
          },
          {
            id: 'freshness',
            label: text.freshness,
            value: formatCode(
              scoreData?.data_freshness_status ?? '--',
              locale,
              'status',
            ),
          },
        ]}
      />

      <section
        className="app-workbench-section min-w-0 px-1 py-4 sm:px-4"
        data-testid="account-truth-review-workspace"
      >
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{text.reports}</div>
            <h2 className="mt-1 text-base font-semibold text-[var(--app-text)]">
              {text.reviewWorkspace}
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
              {text.reviewWorkspaceDetail}
            </p>
          </div>
          <span className="shrink-0 text-xs text-[var(--app-text-tertiary)]">
            {text.itemCount(detail.data?.items.length ?? 0)}
          </span>
        </div>

        <div
          aria-label={text.reportListLabel}
          className="mt-4 flex max-w-full gap-2 overflow-x-auto border-y border-[var(--app-divider)] py-2"
        >
          {filters.map((option) => (
            <button
              key={option.value}
              aria-pressed={filter === option.value}
              type="button"
              className={`min-h-10 shrink-0 rounded-[var(--app-radius-control)] border px-3 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                filter === option.value
                  ? 'border-[var(--app-accent)] bg-[var(--app-accent-bg)] text-[var(--app-text)]'
                  : 'border-[var(--app-divider)] text-[var(--app-text-secondary)]'
              }`}
              onClick={() => {
                setFilter(option.value);
                setShowMatchedItems(false);
              }}
            >
              {option[locale]}
            </button>
          ))}
        </div>

        {selectedReport ? (
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(230px,0.55fr)_minmax(0,1.45fr)]">
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
                {text.currentReport}
              </div>
              <div
                className="mt-2 border-l-2 border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] px-3 py-3"
                data-testid="account-truth-current-report"
              >
                <div className="flex min-w-0 items-center justify-between gap-2">
                  <StatusBadge tone={statusTone(selectedReport.status)}>
                    {formatCode(selectedReport.status, locale, 'status')}
                  </StatusBadge>
                  <span className="text-xs font-medium text-[var(--app-text-secondary)]">
                    {selectedReport.unresolved_count} {text.unresolved}
                  </span>
                </div>
                <div className="mt-2 truncate text-sm font-semibold text-[var(--app-text)]">
                  {selectedReport.source_name}
                </div>
                <div className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {text.cashDifference}{' '}
                  {formatReconciliationValue(
                    'cash',
                    selectedReport.cash_difference,
                    locale,
                  )}{' '}
                  · {text.feeDifference}{' '}
                  {formatReconciliationValue(
                    'fee',
                    selectedReport.fee_difference,
                    locale,
                  )}{' '}
                  · {text.taxDifference}{' '}
                  {formatReconciliationValue(
                    'tax',
                    selectedReport.tax_difference,
                    locale,
                  )}
                </div>
                <div className="mt-1 text-[11px] text-[var(--app-text-tertiary)]">
                  {formatDateTime(selectedReport.created_at)}
                </div>
              </div>

              {reportHistory.length > 0 ? (
                <details
                  className="mt-3 border-y border-[var(--app-divider)]"
                  data-testid="account-truth-report-history-disclosure"
                >
                  <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
                    <span>{text.reportHistoryCount(reportHistory.length)}</span>
                    <span aria-hidden="true">+</span>
                  </summary>
                  <div className="divide-y divide-[var(--app-divider)] border-t border-[var(--app-divider)]">
                    {reportHistory.map((report) => (
                      <button
                        key={report.import_run_id}
                        type="button"
                        className="grid min-h-12 w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                        onClick={() => selectReport(report.import_run_id)}
                      >
                        <StatusBadge tone={statusTone(report.status)}>
                          {formatCode(report.status, locale, 'status')}
                        </StatusBadge>
                        <span className="min-w-0">
                          <span className="block truncate text-xs font-semibold text-[var(--app-text)]">
                            {report.source_name}
                          </span>
                          <span className="block text-[11px] text-[var(--app-text-tertiary)]">
                            {formatDateTime(report.created_at)} ·{' '}
                            {report.unresolved_count} {text.unresolved}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>

            <div className="min-w-0">
              <div className="flex min-w-0 items-center justify-between gap-3 border-b border-[var(--app-divider)] pb-2">
                <h3 className="truncate text-sm font-semibold text-[var(--app-text)]">
                  {attentionItems.length > 0
                    ? text.attentionItems
                    : text.matchedItems}
                </h3>
                <StatusBadge
                  tone={attentionItems.length > 0 ? 'warning' : 'success'}
                >
                  {text.itemCount(
                    attentionItems.length > 0
                      ? attentionItems.length
                      : indexedItems.length,
                  )}
                </StatusBadge>
              </div>

              {attentionItems.length === 0 && indexedItems.length > 0 ? (
                <EvidenceState
                  kind="ready"
                  statusLabel={formatCode('pass', locale, 'status')}
                  title={text.matchedItems}
                  description={text.matchedItemsQuiet(indexedItems.length)}
                  action={
                    <button
                      type="button"
                      aria-expanded={showMatchedItems}
                      className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
                      onClick={() => setShowMatchedItems((current) => !current)}
                    >
                      {showMatchedItems
                        ? text.hideMatchedItems
                        : text.showMatchedItems(indexedItems.length)}
                    </button>
                  }
                />
              ) : null}

              {visibleItems.length > 0 && detail.data ? (
                <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(220px,0.62fr)_minmax(0,1.38fr)]">
                  <ReconciliationItemList
                    ariaLabel={text.itemListLabel}
                    entries={visibleItems}
                    locale={locale}
                    selectedIdentity={selectedItem?.id ?? null}
                    onSelect={(identity) => {
                      setSelectedItemIdentity(identity);
                      setSavedReviewStatus(null);
                    }}
                  />
                  {selectedItem ? (
                    <ReviewItemCard
                      item={selectedItem.item}
                      importRunId={detail.data.import_run_id}
                      locale={locale}
                      reviewPending={reviewMutation.isPending}
                      onReview={(reviewStatus) => {
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
                      }}
                    />
                  ) : null}
                </div>
              ) : indexedItems.length === 0 ? (
                <EvidenceState kind="empty" title={text.noItems} />
              ) : null}

              {savedReviewStatus ? (
                <EvidenceState
                  className="mt-3"
                  kind="ready"
                  title={`${text.reviewSaved}: ${formatPublicStatus(
                    savedReviewStatus,
                    locale,
                  )}`}
                />
              ) : null}
              {reviewMutation.isError ? (
                <EvidenceState
                  className="mt-3"
                  kind="error"
                  title={text.reviewFailed}
                />
              ) : null}
            </div>
          </div>
        ) : (
          <EvidenceState className="mt-4" kind="empty" title={text.noReports} />
        )}
      </section>

      <div className="grid min-w-0 gap-3">
        <AccountTruthDisclosure
          key={`score-${scoreNeedsAttention}`}
          defaultOpen={scoreNeedsAttention}
          detail={text.scoreEvidenceDetail}
          testId="account-truth-score-disclosure"
          title={text.scoreEvidenceTitle}
        >
          <section
            className="min-w-0 px-1 py-4 sm:px-4"
            data-testid="account-truth-score"
          >
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-base font-semibold text-[var(--app-text)]">
                {text.components}
              </h2>
              <StatusBadge
                tone={statusTone(scoreData?.gate_status ?? 'blocked')}
              >
                {formatCode(
                  scoreData?.gate_status ?? 'blocked',
                  locale,
                  'status',
                )}
              </StatusBadge>
            </div>
            {scoreIsMissing ? <MissingEvidenceCallout locale={locale} /> : null}
            <ul className="mt-4 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {componentEntries.map(([label, value]) => (
                <li
                  key={label}
                  className="flex items-center justify-between gap-3 py-2.5 text-xs font-medium text-[var(--app-text-secondary)]"
                >
                  <span>{label}</span>
                  <StatusBadge tone={statusTone(value ?? 'missing')}>
                    {formatCode(value ?? '--', locale, 'status')}
                  </StatusBadge>
                </li>
              ))}
            </ul>
            <ReasonList
              title={text.blockingReasons}
              values={scoreData?.blocking_reasons ?? []}
              locale={locale}
            />
            <ReasonList
              title={text.requiredActions}
              values={scoreData?.required_actions ?? []}
              locale={locale}
            />
          </section>
        </AccountTruthDisclosure>

        <AccountTruthDisclosure
          detail={text.importHistoryDetail((importRuns.data ?? []).length)}
          testId="account-truth-import-history-disclosure"
          title={text.importHistoryTitle}
        >
          <div className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {(importRuns.data ?? []).length > 0 ? (
              importRuns.data?.map((run) => (
                <button
                  key={run.import_run_id}
                  type="button"
                  className="grid min-h-12 w-full min-w-0 gap-1 py-2 text-left sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center sm:gap-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                  onClick={() => selectReport(run.import_run_id)}
                >
                  <span className="truncate text-sm font-semibold text-[var(--app-text)]">
                    {run.source_name}
                  </span>
                  <span className="text-xs text-[var(--app-text-secondary)]">
                    {text.rows} {run.row_count} · {text.duplicates}{' '}
                    {run.row_duplicate_count + run.file_duplicate_count}
                  </span>
                  <span className="flex items-center gap-2 text-[11px] text-[var(--app-text-tertiary)]">
                    <StatusBadge tone={statusTone(run.validation_status)}>
                      {formatCode(run.validation_status, locale, 'status')}
                    </StatusBadge>
                    {formatDateTime(run.created_at)}
                  </span>
                </button>
              ))
            ) : (
              <EmptyState
                title={text.notReadyTitle}
                body={text.noImports}
                locale={locale}
              />
            )}
          </div>
        </AccountTruthDisclosure>

        <AccountTruthDisclosure
          key={`ingest-${scoreIsMissing}`}
          defaultOpen={scoreIsMissing}
          detail={text.importToolsDetail}
          testId="account-truth-import-tools-disclosure"
          title={text.importToolsTitle}
        >
          <BrokerEvidenceImportWizard
            locale={locale}
            collectorStatus={collector.data}
            collectorStatusIsError={collector.isError}
            onImported={(importRunId) => {
              selectReport(importRunId);
              setFilter('all');
            }}
          />
        </AccountTruthDisclosure>
      </div>
    </section>
  );
}

function AccountTruthDisclosure({
  children,
  defaultOpen = false,
  detail,
  testId,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  detail: string;
  testId: string;
  title: string;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <details
      className="group min-w-0"
      data-testid={testId}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-start justify-between gap-4 border-y border-[var(--app-divider)] py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[var(--app-text)]">
            {title}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="shrink-0 text-sm text-[var(--app-text-tertiary)] group-open:rotate-45"
        >
          +
        </span>
      </summary>
      <div className="min-w-0 pt-3">{children}</div>
    </details>
  );
}

function ReconciliationItemList({
  ariaLabel,
  entries,
  locale,
  onSelect,
  selectedIdentity,
}: {
  ariaLabel: string;
  entries: IndexedReconciliationItem[];
  locale: 'en' | 'zh';
  onSelect: (identity: string) => void;
  selectedIdentity: string | null;
}) {
  const text = labels[locale];
  return (
    <div
      aria-label={ariaLabel}
      className="max-h-[34rem] min-w-0 divide-y divide-[var(--app-divider)] overflow-y-auto overscroll-y-contain border-y border-[var(--app-divider)]"
      role="list"
    >
      {entries.map(({ id, item }) => {
        const itemTitle = item.symbol
          ? formatInstrumentDisplayLabel({
              symbol: item.symbol,
              display_name: item.display_name ?? null,
            })
          : formatCode(item.category, locale, 'code');
        return (
          <div key={id} role="listitem">
            <button
              aria-label={`${text.selectItem}: ${itemTitle}`}
              aria-pressed={selectedIdentity === id}
              className={`grid min-h-14 w-full min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 gap-y-1 px-2 py-2.5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
                selectedIdentity === id ? 'bg-[var(--app-accent-bg)]' : ''
              }`}
              data-testid={`account-truth-item-selector-${item.item_key}`}
              onClick={() => onSelect(id)}
              type="button"
            >
              <StatusBadge tone={statusTone(item.status)}>
                {formatCode(item.status, locale, 'status')}
              </StatusBadge>
              <span className="min-w-0">
                <span className="block truncate text-xs font-semibold text-[var(--app-text)]">
                  {itemTitle}
                </span>
                <span className="mt-0.5 block truncate text-[11px] text-[var(--app-text-secondary)]">
                  {formatCode(item.category, locale, 'code')} ·{' '}
                  {text.difference}{' '}
                  {formatReconciliationValue(
                    item.category,
                    item.difference,
                    locale,
                  )}
                </span>
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function statusTone(status: string): StatusTone {
  const normalized = status.trim().toLowerCase();
  if (
    ['pass', 'available', 'healthy', 'fresh', 'imported', 'unchanged'].includes(
      normalized,
    )
  ) {
    return 'success';
  }
  if (
    ['warning', 'degraded', 'stale', 'partial', 'pending_stability'].includes(
      normalized,
    )
  ) {
    return 'warning';
  }
  if (
    ['mismatch', 'blocked', 'error', 'missing', 'unreconciled'].includes(
      normalized,
    )
  ) {
    return 'danger';
  }
  if (['waiting_for_file', 'checking'].includes(normalized)) {
    return 'info';
  }
  return 'neutral';
}

function BrokerEvidenceImportWizard({
  locale,
  collectorStatus,
  collectorStatusIsError,
  onImported,
}: {
  locale: 'en' | 'zh';
  collectorStatus: BrokerStatementCollectorStatus | undefined;
  collectorStatusIsError: boolean;
  onImported: (importRunId: string) => void;
}) {
  const text = labels[locale];
  const [sourceName, setSourceName] = useState('local-broker-statement.csv');
  const [content, setContent] = useState('');
  const [fileMessage, setFileMessage] = useState<string | null>(null);
  const previewMutation = useBrokerStatementPreviewMutation();
  const importMutation = useBrokerStatementImportMutation();
  const preview = previewMutation.data ?? importMutation.data?.preview ?? null;
  const canSubmit = content.trim().length > 0 && sourceName.trim().length > 0;
  const previewIsBlocked = preview?.validation_status === 'blocked';

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) {
      return;
    }
    setFileMessage(null);
    setSourceName(file.name || 'local-broker-statement.csv');
    try {
      setContent(await file.text());
      previewMutation.reset();
      importMutation.reset();
    } catch {
      setFileMessage(text.noFileContent);
    }
  }

  function previewStatement() {
    if (!canSubmit) {
      setFileMessage(text.noFileContent);
      return;
    }
    setFileMessage(null);
    previewMutation.mutate({
      content,
      source_name: sourceName,
    });
  }

  function importStatement() {
    if (!canSubmit) {
      setFileMessage(text.noFileContent);
      return;
    }
    setFileMessage(null);
    importMutation.mutate(
      {
        content,
        source_name: sourceName,
      },
      {
        onSuccess: (result) => {
          onImported(result.import_run.import_run_id);
        },
      },
    );
  }

  return (
    <ControlledActionZone
      title={text.importWizardTitle}
      description={text.importWizardBody}
      evidence={text.importBoundary}
      layout="stack"
      tone="info"
    >
      <div className="w-full min-w-0" data-testid="account-truth-import-wizard">
        <div className="app-product-mark">{text.importWizardKicker}</div>
        <BrokerStatementCollectorCallout
          locale={locale}
          status={collectorStatus}
          isError={collectorStatusIsError}
        />
        <div className="mt-4 grid gap-3">
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.sourceName}
            <input
              className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
              value={sourceName}
              onChange={(event) => setSourceName(event.currentTarget.value)}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.chooseFile}
            <input
              accept=".csv,text/csv,text/plain"
              className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-dashed border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
              type="file"
              onChange={handleFileChange}
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
            {text.csvContent}
            <textarea
              className="min-h-28 w-full resize-y rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 font-mono text-xs text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
              value={content}
              onChange={(event) => {
                setContent(event.currentTarget.value);
                previewMutation.reset();
                importMutation.reset();
              }}
            />
          </label>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSubmit || previewMutation.isPending}
            type="button"
            onClick={previewStatement}
          >
            {text.previewImport}
          </button>
          <button
            className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={
              !canSubmit ||
              previewIsBlocked ||
              importMutation.isPending ||
              previewMutation.isPending
            }
            type="button"
            onClick={importStatement}
          >
            {text.confirmImport}
          </button>
        </div>
        {fileMessage ? (
          <EvidenceState className="mt-3" kind="partial" title={fileMessage} />
        ) : null}
        {preview ? (
          <BrokerStatementPreviewPanel preview={preview} locale={locale} />
        ) : null}
        {importMutation.isSuccess ? (
          <EvidenceState
            className="mt-3"
            kind="ready"
            title={`${text.importReady}: ${importMutation.data.import_run.source_name}`}
          />
        ) : null}
        {previewMutation.isError || importMutation.isError ? (
          <EvidenceState
            className="mt-3"
            kind="error"
            title={text.importFailed}
          />
        ) : null}
      </div>
    </ControlledActionZone>
  );
}

function BrokerStatementCollectorCallout({
  locale,
  status,
  isError,
}: {
  locale: 'en' | 'zh';
  status: BrokerStatementCollectorStatus | undefined;
  isError: boolean;
}) {
  const text = labels[locale];
  const tone = statusTone(isError ? 'error' : (status?.state ?? 'checking'));
  const body = isError
    ? text.collectorUnavailable
    : status
      ? collectorStateBody(status, locale)
      : text.collectorLoading;

  return (
    <div
      className="mt-4 border-y border-[var(--app-divider)] py-3"
      data-testid="broker-statement-collector-status"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-[var(--app-text)]">
          {text.collectorTitle}
        </span>
        <StatusBadge tone={tone}>
          {collectorStateLabel(status?.state, locale)}
        </StatusBadge>
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
        {body}
      </p>
      {status?.configured_path ? (
        <EvidenceIdentityDisclosure
          className="app-button-ghost mt-2 inline-flex min-h-10 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold text-[var(--app-text-secondary)]"
          triggerLabel={text.openEvidence}
          title={text.collectorTitle}
          description={body}
          closeLabel={text.closeEvidence}
          copyLabel={text.copyEvidence}
          copiedLabel={text.copiedEvidence}
          fields={[
            {
              label: text.collectorPath,
              value: status.configured_path,
              mono: true,
            },
            ...(status.import_run_id
              ? [
                  {
                    label: text.collectorRun,
                    value: status.import_run_id,
                    mono: true,
                  },
                ]
              : []),
          ]}
        />
      ) : null}
      <p className="mt-2 text-[11px] leading-5 text-[var(--app-text-tertiary)]">
        {text.collectorFallback}
      </p>
    </div>
  );
}

function collectorStateLabel(
  state: BrokerStatementCollectorStatus['state'] | undefined,
  locale: 'en' | 'zh',
) {
  const values: Record<
    BrokerStatementCollectorStatus['state'],
    { en: string; zh: string }
  > = {
    disabled: { en: 'Disabled', zh: '未启用' },
    waiting_for_file: { en: 'Waiting for file', zh: '等待文件' },
    pending_stability: { en: 'Waiting for stable write', zh: '等待写入稳定' },
    imported: { en: 'Evidence staged', zh: '证据已暂存' },
    unchanged: { en: 'Up to date', zh: '已是最新' },
    blocked: { en: 'Blocked', zh: '已阻断' },
    error: { en: 'Error', zh: '异常' },
  };
  return state
    ? values[state][locale]
    : locale === 'zh'
      ? '检查中'
      : 'Checking';
}

function collectorStateBody(
  status: BrokerStatementCollectorStatus,
  locale: 'en' | 'zh',
) {
  const rows = status.row_count ?? 0;
  const values: Record<
    BrokerStatementCollectorStatus['state'],
    { en: string; zh: string }
  > = {
    disabled: {
      en: 'Disabled by startup configuration; no local file is read.',
      zh: '启动配置未启用，不会读取任何本地文件。',
    },
    waiting_for_file: {
      en: 'The configured file is absent; previous staged evidence is preserved.',
      zh: '配置文件当前不存在；此前已暂存证据仍会保留。',
    },
    pending_stability: {
      en: 'A change was detected. Collection waits for a complete stable file.',
      zh: '检测到文件变化，正在等待完整写入并保持稳定。',
    },
    imported: {
      en: `${rows} rows were staged for reconciliation review.`,
      zh: `已暂存 ${rows} 行证据，等待对账复核。`,
    },
    unchanged: {
      en: 'The fingerprint is unchanged; no duplicate run was created.',
      zh: '文件指纹未变化，没有创建重复导入批次。',
    },
    blocked: {
      en: 'Validation failed closed. No production account fact was changed.',
      zh: '校验已 fail closed，生产账户事实没有被修改。',
    },
    error: {
      en: 'The read-only collection attempt failed; no ledger action was taken.',
      zh: '只读采集失败；未执行任何账本操作。',
    },
  };
  return values[status.state][locale];
}

function BrokerStatementPreviewPanel({
  preview,
  locale,
}: {
  preview: BrokerStatementPreview;
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  return (
    <div className="mt-4 border-y border-[var(--app-divider)] py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {text.previewReady}
          </div>
          <div className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {preview.source_name}
          </div>
        </div>
        <StatusBadge tone={statusTone(preview.validation_status)}>
          {formatCode(preview.validation_status, locale, 'status')}
        </StatusBadge>
      </div>
      <div className="mt-3 grid grid-cols-3 divide-x divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
        <Metric
          label={text.validRows}
          value={String(preview.valid_row_count)}
        />
        <Metric
          label={text.invalidRows}
          value={String(preview.invalid_row_count)}
        />
        <Metric
          label={text.duplicateRows}
          value={String(preview.duplicate_row_count)}
        />
      </div>
      {preview.errors.length > 0 ? (
        <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {preview.errors.slice(0, 3).map((error) => (
            <div
              key={`${error.row_number ?? 'file'}-${error.code}`}
              className="border-l-2 border-[var(--app-danger-indicator)] px-3 py-2 text-xs font-medium text-[var(--app-danger-text)]"
            >
              {error.row_number ? `Row ${error.row_number}: ` : ''}
              {formatCode(error.code, locale, 'code')}
            </div>
          ))}
        </div>
      ) : null}
      {preview.events_preview.length > 0 ? (
        <div className="mt-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
            {text.eventPreview}
          </div>
          <div className="mt-2 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
            {preview.events_preview.slice(0, 3).map((event) => (
              <div
                key={`${event.row_number}-${event.event_id}`}
                className="grid min-w-0 gap-1 px-3 py-2 text-xs"
              >
                <div className="font-semibold text-[var(--app-text)]">
                  {formatCode(event.event_type, locale, 'code')}
                  {event.symbol ? ` · ${event.symbol}` : ''}
                </div>
                <div className="text-[var(--app-text-secondary)]">
                  {event.currency} {event.net_amount}
                  {event.cash_balance ? ` · cash ${event.cash_balance}` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="truncate text-[11px] font-medium text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div className="mt-0.5 text-base font-semibold text-[var(--app-text)] tabular-nums">
        {value}
      </div>
    </div>
  );
}

function MissingEvidenceCallout({ locale }: { locale: 'en' | 'zh' }) {
  const text = labels[locale];
  return (
    <div className="mt-4 border-l-2 border-[var(--app-warning-indicator)] py-1 pl-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {text.notReadyTitle}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {text.notReadyBody}
      </p>
      <div className="mt-3 border-t border-[var(--app-divider)] pt-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
          {text.workflowTitle}
        </div>
        <ol className="mt-2 grid gap-2 text-xs font-medium text-[var(--app-text-secondary)]">
          {text.workflowSteps.map((step, index) => (
            <li
              key={step}
              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2"
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-[var(--app-radius-control)] border border-[var(--app-accent-border)] text-[10px] font-semibold text-[var(--app-accent)]">
                {index + 1}
              </span>
              <span>{step}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function EmptyState({
  title,
  body,
  locale,
}: {
  title: string;
  body: string;
  locale: 'en' | 'zh';
}) {
  const text = labels[locale];
  return (
    <div className="border-l-2 border-[var(--app-warning-indicator)] px-3 py-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {title}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {body}
      </p>
      <div className="mt-2 text-xs font-medium text-[var(--app-text-secondary)]">
        {text.workflowSteps[0]} → {text.workflowSteps[1]}
      </div>
    </div>
  );
}

function ReasonList({
  title,
  values,
  locale,
}: {
  title: string;
  values: string[];
  locale: 'en' | 'zh';
}) {
  if (values.length === 0) {
    return null;
  }
  return (
    <div className="mt-4">
      <div className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--app-muted)]">
        {title}
      </div>
      <div className="mt-2 grid gap-2">
        {values.map((value) => (
          <div
            key={value}
            className="border-l-2 border-[var(--app-divider)] py-1 pl-3 text-xs font-medium leading-5 text-[var(--app-text-secondary)]"
          >
            {formatCode(value, locale, 'code')}
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewItemCard({
  item,
  importRunId,
  locale,
  reviewPending,
  onReview,
}: {
  item: ReconciliationItem;
  importRunId: string;
  locale: 'en' | 'zh';
  reviewPending: boolean;
  onReview: (status: ReviewStatus) => void;
}) {
  const text = labels[locale];
  const itemTitle = item.symbol
    ? formatInstrumentDisplayLabel({
        symbol: item.symbol,
        display_name: item.display_name ?? null,
      })
    : formatCode(item.category, locale, 'code');
  const latestReviewNote = formatPublicOperationalNote(
    item.latest_review?.note,
    locale,
  );
  const evidenceInstrumentNames =
    item.symbol && item.display_name
      ? new Map([[item.symbol.toLowerCase(), item.display_name]])
      : undefined;
  const detailContextEntries = Object.entries(item.detail_context ?? {}).filter(
    ([, value]) => value.trim().length > 0,
  );
  const reviewControls = (
    <ControlledActionZone
      title={text.auditDecision}
      description={text.auditDecisionDetail}
      evidence={text.safety}
      layout="stack"
      tone="info"
    >
      <div className="flex max-w-full flex-wrap gap-2">
        {reviewActions.map((action) => (
          <button
            key={action}
            type="button"
            className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={reviewPending}
            onClick={() => onReview(action)}
          >
            {formatPublicReviewActionLabel(action, locale)}
          </button>
        ))}
      </div>
    </ControlledActionZone>
  );
  return (
    <article
      className="min-w-0 rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 sm:p-4"
      data-testid={`account-truth-item-${item.item_key}`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <StatusBadge tone={statusTone(item.status)}>
              {formatCode(item.status, locale, 'status')}
            </StatusBadge>
            <span className="text-base font-semibold text-[var(--app-text)]">
              {itemTitle}
            </span>
            <span className="text-xs font-medium text-[var(--app-text-tertiary)]">
              {formatCode(item.category, locale, 'code')}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[var(--app-text-secondary)]">
            {formatPublicNote(item.detail_code ?? item.detail, locale)}
          </p>
        </div>
        <EvidenceIdentityDisclosure
          triggerLabel={text.openEvidence}
          title={text.evidenceDetail}
          description={itemTitle}
          closeLabel={text.closeEvidence}
          copyLabel={text.copyEvidence}
          copiedLabel={text.copiedEvidence}
          fields={[
            {
              label: text.importRunIdentity,
              value: importRunId,
              mono: true,
            },
            {
              label: text.itemIdentity,
              value: item.item_key,
              mono: true,
            },
            ...item.evidence_references.map((reference, index) => ({
              label: text.evidenceReference(index + 1),
              value: formatLedgerEvidenceReference(
                reference,
                locale,
                evidenceInstrumentNames,
              ),
              copyValue: reference,
              mono: true,
            })),
          ]}
        />
      </div>

      {detailContextEntries.length > 0 ? (
        <dl className="mt-3 grid divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs sm:grid-cols-2 sm:divide-y-0">
          {detailContextEntries.map(([key, value]) => (
            <div
              key={key}
              className="grid min-w-0 gap-1 py-2 sm:border-b sm:border-[var(--app-divider)] sm:px-2"
            >
              <dt className="text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--app-text-tertiary)]">
                {formatCode(key, locale, 'code')}
              </dt>
              <dd className="text-[var(--app-text-secondary)]">
                {formatCode(value, locale, 'code')}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="mt-4 grid grid-cols-1 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <Metric
          label={text.broker}
          value={`${text.broker} ${formatReconciliationValue(
            item.category,
            item.broker_value,
            locale,
          )}`}
        />
        <Metric
          label={text.karkinos}
          value={`${text.karkinos} ${formatReconciliationValue(
            item.category,
            item.karkinos_value,
            locale,
          )}`}
        />
        <Metric
          label={text.difference}
          value={`${text.difference} ${formatReconciliationValue(
            item.category,
            item.difference,
            locale,
          )}`}
        />
      </div>

      {item.suggested_review_action ? (
        <div className="border-t border-[var(--app-divider)] py-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--app-text-tertiary)]">
            {text.suggestedAction}
          </div>
          <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
            {formatCode(item.suggested_review_action || '--', locale, 'code')}
          </div>
        </div>
      ) : null}

      {item.latest_review ? (
        <EvidenceState
          className="mt-4"
          kind={item.latest_review.is_current === false ? 'stale' : 'ready'}
          title={`${text.latestReview}: ${formatPublicStatus(
            item.latest_review.review_status,
            locale,
          )}`}
          description={
            <>
              <span className="block">
                {item.latest_review.is_current === false
                  ? text.staleReview
                  : text.currentReview}
              </span>
              {latestReviewNote ? (
                <span className="mt-1 block">{latestReviewNote}</span>
              ) : null}
            </>
          }
        />
      ) : null}

      {item.status === 'pass' ? (
        <details className="mt-4 border-y border-[var(--app-divider)]">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
            {text.showAuditActions}
            <span aria-hidden="true">+</span>
          </summary>
          <div className="pb-3">{reviewControls}</div>
        </details>
      ) : (
        <div className="mt-4">{reviewControls}</div>
      )}
    </article>
  );
}

function formatCode(
  value: string,
  locale: 'en' | 'zh',
  kind: 'status' | 'code',
) {
  return kind === 'status'
    ? formatPublicStatus(value, locale)
    : formatPublicCode(value, locale);
}
