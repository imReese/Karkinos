import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from 'react';

import { usePreferences, type Locale } from '../../../app/preferences';
import {
  ControlledActionZone,
  EvidenceIdentityDisclosure,
  EvidenceLoadingLayout,
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
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicOperationalNote,
  formatPublicReviewActionLabel,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  formatLedgerEntryTypeLabel,
  formatLedgerEvidenceReference,
} from '../../../shared/ledger-format';
import {
  useBrokerStatementImportMutation,
  useBrokerStatementPreviewMutation,
  useBrokerStatementCollectorStatusQuery,
  useCiticHistoryXlsDirectoryIntakeMutation,
  useCiticHistoryXlsDirectoryQueryWindowReviewMutation,
  useCiticHistoryXlsDirectoryScanMutation,
  useCiticHistoryXlsDirectoryStatusQuery,
  useCiticHistoryXlsIntakeMutation,
  useCiticHistoryXlsIntakesQuery,
  useCiticHistoryXlsPreviewMutation,
  useCiticHistoryXlsQueryWindowReviewMutation,
  useCiticHistoryXlsQueryWindowReviewRevokeMutation,
  useCiticHistoryXlsSourceScopeReviewMutation,
  useCiticHistoryXlsSourceScopeReviewRevokeMutation,
  hashAccountTruthAccountReference,
  useAccountTruthEvidenceReadinessQuery,
  useAccountTruthImportRunsQuery,
  useAccountTruthScoreQuery,
  useReconciliationReportDetailQuery,
  useReconciliationReportsQuery,
  useRecordReviewDecisionMutation,
  useRecordEvidenceScopeReviewMutation,
  useRevokeEvidenceScopeReviewMutation,
  type BrokerStatementPreview,
  type BrokerStatementCollectorStatus,
  type AccountTruthEvidenceReadiness,
  type CiticHistoryEventTypeCount,
  type CiticHistoryXlsPreview,
  type CiticSourceIntake,
  type CiticSourceQueryWindowReview,
  type CiticSourceScopeReview,
  type CiticSourceReviewStatus,
  type ReconciliationItem,
  type ReconciliationStatus,
  type ReviewStatus,
} from '../api';
import { FeeScheduleReviewPanel } from './fee-schedule-review-panel';

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

function formatCiticEventTypeCounts(
  counts: CiticHistoryEventTypeCount[],
  locale: Locale,
) {
  if (counts.length === 0) {
    return locale === 'zh' ? '无' : 'none';
  }
  return counts
    .map(
      ({ event_type: eventType, count }) =>
        `${formatLedgerEntryTypeLabel(eventType, locale)} ${count}`,
    )
    .join(' · ');
}

const labels = {
  en: {
    kicker: 'Account Truth',
    title: 'Account Truth Review Center',
    subtitle:
      'Review broker evidence, reconciliation gaps, and manual decisions before relying on account facts.',
    loading: 'Loading Account Truth evidence.',
    error: 'Failed to load Account Truth evidence.',
    score: 'Reconciliation score',
    scorePending: 'Not ready',
    gate: 'Reconciliation gate',
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
    reconciliationItems: 'Reconciliation detail',
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
    readinessTitle: 'Evidence readiness checklist',
    readinessDetail:
      'One persisted-only checklist of what is reviewed, what is still missing, and why the Account Truth gate passes or remains blocked.',
    readinessRequirements: 'Evidence requirements',
    readinessKnownSources: 'Persisted incomplete sources',
    readinessClear: 'Persisted evidence clear',
    readinessNextAction: 'Next safe action',
    readinessPriorityBlockedTitle: 'Account evidence is not ready',
    readinessPriorityReadyTitle: 'Reviewed account evidence is ready',
    readinessPriorityBlockedDetail:
      'The overall evidence gate remains blocked while reviewed account, coverage, asset-scope, or reconciliation evidence is missing.',
    readinessPriorityLocalPassDetail:
      'A passing reconciliation score does not clear those missing requirements.',
    readinessPriorityReadyDetail:
      'The persisted evidence checklist is complete. This does not grant execution or capital authority.',
    readinessPriorityAction: 'Review evidence requirements',
    readinessItemEvidence: 'Supporting evidence',
    readinessItemSafeAction: 'Safe next step',
    readinessItemNoEvidence: 'No persisted evidence',
    readinessScopeTitle: 'Provable evidence scope',
    readinessScopeDetail:
      'Observed rows show what is present, but do not prove that the export covers the whole account or period.',
    readinessAccountBinding: 'Reviewed account binding',
    readinessDeclaredWindow: 'Reviewed coverage window',
    readinessObservedWindow: 'Observed event span',
    readinessObservedRows: (count: number) =>
      `${count} persisted ${count === 1 ? 'row' : 'rows'}`,
    readinessObservedAssets: 'Observed asset classes',
    readinessSnapshotDates: 'Latest snapshot dates',
    readinessNoObservedAssets: 'No validated asset class observed',
    readinessCashSnapshotShort: 'Cash',
    readinessPositionSnapshotShort: 'Position',
    scopeReviewTitle: 'Review and bind this scope',
    scopeReviewDetail:
      'Bind the exact persisted import to a private account reference, reviewed period, and complete asset scope.',
    scopeReviewProvider: 'Broker provider code',
    scopeReviewAccountAlias: 'Local account alias',
    scopeReviewAccountIdentifier: 'Broker account identifier',
    scopeReviewAccountIdentifierHelp:
      'The identifier is hashed in this browser. The raw value is never sent to the API or persisted.',
    scopeReviewStartDate: 'Coverage start date',
    scopeReviewEndDate: 'Coverage end date',
    scopeReviewAssets: 'Reviewed asset classes',
    scopeReviewAttestation:
      'I reviewed this exact export and attest that it covers the full account for this period and these asset classes.',
    scopeReviewSubmit: 'Record scope review',
    scopeReviewRecording: 'Recording review…',
    scopeReviewRecorded: 'Scope review recorded',
    scopeReviewFailed: 'Scope review failed closed',
    scopeReviewRevoke: 'Revoke scope review',
    scopeReviewRevoking: 'Revoking review…',
    scopeReviewRevoked: 'Scope review revoked',
    scopeReviewBoundary:
      'This explicit action writes only an append-only scope-review record. It does not alter broker evidence, reconcile the account, change the ledger, contact the broker, or grant execution or capital authority.',
    scopeReviewComplete:
      'Reviewed scope is bound to the exact persisted import.',
    assetClassStock: 'Stock',
    assetClassEtf: 'ETF',
    assetClassFund: 'Fund',
    assetClassGold: 'Gold',
    assetClassBond: 'Bond',
    assetClassCash: 'Cash',
    readinessBoundary:
      'This checklist is read-only. It does not import evidence, contact a broker, reconcile the account, or grant execution or capital authority.',
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
    citicPreviewKicker: 'CITIC legacy XLS',
    citicPreviewTitle: 'Inspect CITIC history trades by month',
    citicPreviewBody:
      'Select up to 24 exported .xls files. They are checked one at a time in memory, and the response suppresses account and transaction details.',
    citicChooseFile: 'Choose CITIC history-trade XLS files',
    citicPreviewAction: 'Preview selected CITIC XLS files',
    citicDirectoryTitle: 'Configured local export directory',
    citicDirectoryBody:
      'An explicit scan reads stable direct-child XLS files under bounded limits. The API never returns the configured path or source names.',
    citicDirectoryScanAction: 'Scan configured directory',
    citicDirectoryDisabled:
      'Local directory scanning is disabled in startup configuration. Browser file selection remains available.',
    citicDirectoryUnavailable: 'Directory scan status is unavailable.',
    citicDirectoryEmpty: 'No readable CITIC .xls files were found.',
    citicDirectoryScanFailed: 'Configured directory scan failed closed.',
    citicDirectoryPartial: (count: number) =>
      `${count} local ${count === 1 ? 'source was' : 'sources were'} skipped safely; readable sources remain blocked previews.`,
    citicDirectorySummary: (
      candidates: number,
      previews: number,
      duplicates: number,
    ) =>
      `${candidates} candidates · ${previews} unique previews · ${duplicates} duplicates`,
    citicBatchAssessmentTitle: 'Batch integrity and coverage boundary',
    citicBatchIntegrityClear: 'File-set integrity clear; coverage unverified',
    citicBatchIntegrityBlocked: 'File-set integrity blocked',
    citicBatchObservedMonths: (months: string) =>
      `Observed event months: ${months || 'none'}`,
    citicBatchIntegritySummary: (
      uniqueEvents: number,
      crossFileDuplicates: number,
      identityConflicts: number,
      sourcesWithoutEvents: number,
    ) =>
      `${uniqueEvents} unique events · ${crossFileDuplicates} cross-file duplicates · ${identityConflicts} identity conflicts · ${sourcesWithoutEvents} sources without financial events`,
    citicBatchQueryWindowProgress: (reviewed: number, total: number) =>
      `${reviewed} of ${total} current source query windows explicitly reviewed`,
    citicQueryWindowBatchTitle: 'Declared query-window integrity',
    citicQueryWindowBatchUnavailable: 'No reviewed query windows',
    citicQueryWindowBatchPartial: 'Query-window reviews incomplete',
    citicQueryWindowBatchClear: 'Declared dates are contiguous',
    citicQueryWindowBatchBlocked: 'Declared dates need correction',
    citicQueryWindowBatchSummary: (
      startDate: string | null,
      endDate: string | null,
      coveredDays: number,
      gapDays: number,
      overlapDays: number,
    ) =>
      startDate && endDate
        ? `Declared span ${startDate} — ${endDate} · ${coveredDays} covered calendar days · ${gapDays} gap days · ${overlapDays} overlap days`
        : 'No current source has an explicitly reviewed query window.',
    citicQueryWindowBatchBoundary:
      'This checks only owner-declared export dates. Continuous dates do not prove full account or asset scope, settlement detail, current cash, or current positions.',
    citicSourceScopeBatchTitle: 'Declared source-scope integrity',
    citicSourceScopeBatchUnavailable: 'No reviewed source scopes',
    citicSourceScopeBatchPartial: 'Source-scope reviews incomplete',
    citicSourceScopeBatchClear: 'Declared source scopes are consistent',
    citicSourceScopeBatchBlocked: 'Declared source scopes conflict',
    citicSourceScopeBatchSummary: (
      reviewed: number,
      total: number,
      accountConsistent: boolean,
      scopeConsistent: boolean,
    ) =>
      `${reviewed} of ${total} sources reviewed · account binding ${accountConsistent ? 'consistent' : 'unverified or conflicting'} · declared scope ${scopeConsistent ? 'consistent' : 'unverified or conflicting'}`,
    citicSourceScopeBatchDeclared: (
      accountType: string | null,
      markets: string,
      assets: string,
      accountValueBand: string | null,
      businesses: string,
    ) =>
      `Account type ${accountType || 'unverified'} · markets ${markets || 'unverified'} · assets ${assets || 'unverified'} · account-value band ${accountValueBand || 'unverified'} · business types ${businesses || 'unverified'}`,
    citicSourceScopeBatchBoundary:
      'This is an owner declaration bound to exact file and query-window fingerprints. It does not prove complete account coverage, settlement detail, current cash, current positions, or trading authority.',
    citicBatchCoverageBoundary:
      'Observed months do not prove exported query windows or complete coverage. Reviewed query windows, itemized settlement or cash flow, current cash and positions, and account binding remain required.',
    citicCanonicalLineageTitle: 'Canonical source lineage',
    citicCanonicalLineageExact: 'Exact event identity preserved',
    citicCanonicalLineagePartial: 'Partial lineage; review required',
    citicCanonicalLineageUnavailable: 'Lineage unavailable',
    citicCanonicalLineageSummary: (
      matched: number,
      source: number,
      exactIdentity: number,
      brokerIdentity: number,
      sourceBrokerIdentity: number,
      canonicalUnmatched: number,
    ) =>
      `${matched} of ${source} source events match canonical financial semantics · ${exactIdentity} preserve exact event identity · ${brokerIdentity} of ${sourceBrokerIdentity} broker-order identities are preserved · ${canonicalUnmatched} comparable canonical events are outside this source batch`,
    citicCanonicalLineageObservedTypes: (
      sourceTypes: string,
      canonicalTypes: string,
    ) => `Source types: ${sourceTypes} · Canonical types: ${canonicalTypes}`,
    citicCanonicalLineageMismatchTypes: (
      matchedTypes: string,
      sourceUnmatchedTypes: string,
      canonicalUnmatchedTypes: string,
    ) =>
      `Matched types: ${matchedTypes} · unmatched source types: ${sourceUnmatchedTypes} · canonical types outside this batch: ${canonicalUnmatchedTypes}`,
    citicCanonicalLineageIdentityPresence: (
      sourceIdentityCount: number,
      canonicalIdentityCount: number,
    ) =>
      `Broker-order identity present in source ${sourceIdentityCount} · canonical ${canonicalIdentityCount}`,
    citicCanonicalLineageBoundary:
      'Read-only runtime comparison only. Semantic similarity without preserved event identity is not canonical provenance and cannot promote this XLS batch into Account Truth.',
    citicConfiguredSource: (index: number) => `Configured source ${index}`,
    citicLocalNameMonthHint: (month: string) =>
      `Local filename month hint: ${month}`,
    citicLocalNameMonthHintBoundary:
      'Identification aid only. It does not prefill or prove the broker query window.',
    citicConfiguredSourceUnidentified:
      'This configured source has no unambiguous YYYYMM filename token. Select the exact file in the browser before recording or rejecting it.',
    citicNoFile: 'Choose one or more CITIC .xls files first.',
    citicWrongFile: 'Use the legacy .xls export from CITIC History Trades.',
    citicFileTooLarge: 'The selected file exceeds the 10 MB preview limit.',
    citicTooManyFiles: 'Select no more than 24 files in one preview batch.',
    citicReadFailed: 'The local file could not be read for preview.',
    citicPreviewFailed: 'CITIC XLS preview failed',
    citicPreviewComplete: 'Read-only batch preview complete',
    citicSelectedFiles: (count: number) =>
      `${count} ${count === 1 ? 'file' : 'files'} selected`,
    citicPreviewProgress: (completed: number, total: number) =>
      `Checking file ${Math.min(completed + 1, total)} of ${total}`,
    citicFiles: 'Files',
    citicFailedFileCount: (count: number) =>
      `${count} ${count === 1 ? 'file' : 'files'} failed`,
    citicDuplicateFile: 'Duplicate file — excluded from totals',
    citicFilePreviewComplete: 'Checked',
    citicFilePreviewFailed: 'Preview failed',
    citicRecognizedEvents: 'Recognized events',
    citicRecognizedNonFinancialActivities: 'Non-financial activities',
    citicNonFinancialActivityNotice: (count: number) =>
      `${count} reviewed designated-trading ${count === 1 ? 'activity was' : 'activities were'} isolated without creating broker events.`,
    citicPrivacyBoundary:
      'Preview only: no evidence is persisted, no provider is contacted, and no ledger, broker submission, or capital authority is changed.',
    citicPrivacyResponse:
      'The response contains counts, validation issues, and a fingerprint only; it excludes account, security, amount, and local-path details.',
    citicReviewFollowUp: 'Review for follow-up record',
    citicRejectSource: 'Review and reject',
    citicConfirmReview: 'Confirm source review',
    citicConfirmFollowUpBody:
      'Record only this fingerprint, validation summary, and missing-evidence checklist. Parsed events remain excluded from Account Truth.',
    citicQueryWindowStart: 'Broker query start date',
    citicQueryWindowEnd: 'Broker query end date',
    citicQueryWindowAttestation:
      'I personally checked that this exact file was exported from the broker using the start and end dates above.',
    citicQueryWindowBoundary:
      'Dates stay blank until you enter them. They are not inferred from the file name or observed events. This review covers only this source query and does not prove complete account coverage.',
    citicSourceScopeAccountAlias: 'Local account alias',
    citicSourceScopeAccountIdentifier: 'Broker account identifier',
    citicSourceScopeAccountIdentifierBoundary:
      'Hashed in this browser; the raw identifier is never sent or stored.',
    citicSourceScopeAccountType: 'Account type code',
    citicSourceScopeMarkets: 'Market scopes (comma-separated codes)',
    citicSourceScopeAssets: 'Asset classes (comma-separated codes)',
    citicSourceScopeAccountValueBand:
      'Account-value band code (for example cny_0_20000)',
    citicSourceScopeAccountValueBandBoundary:
      'Query-scope metadata only; it is not a current balance, order limit, or capital authorization.',
    citicSourceScopeBusinessTypes: 'Business types (comma-separated codes)',
    citicSourceScopeNoOtherFiltersAttestation:
      'I confirm no other broker query filters applied to this exact export.',
    citicSourceScopeCompleteResultsAttestation:
      'I confirm this file contains every row returned by the declared broker query.',
    citicSourceScopeAttestation:
      'I confirm the account, account type, market, asset, account-value band, and business scope above applies to this exact export.',
    citicSourceScopeBoundary:
      'This source-scope review remains incomplete legacy evidence. It does not create Account Truth, reconciliation clearance, execution authority, or capital authority.',
    citicQueryWindowRequired:
      'Enter both broker query dates and confirm the explicit query-window attestation.',
    citicSourceScopeRequired:
      'Complete the query window, account binding, declared scopes, and all exact attestations.',
    citicQueryWindowFailed:
      'The source was recorded, but its query window was not recorded',
    citicSourceScopeFailed:
      'The source and query window were recorded, but the source scope was not recorded',
    citicQueryWindowSaved: 'Source query window recorded',
    citicQueryWindowStillBlocked:
      'Source scope only; Account Truth and reconciliation remain blocked.',
    citicSourceScopeSaved: 'Source scope recorded',
    citicSourceScopeLabel: 'Reviewed source scope',
    citicSourceScopeRevokeFailed: 'Source-scope revocation failed closed.',
    citicReviewQueryWindow: 'Review source query window',
    citicReviewSourceScope: 'Review source query and scope',
    citicIntakeStillSaved:
      'The sanitized source review remains saved; retry the explicit query-window review.',
    citicQueryWindowLabel: 'Reviewed broker query window',
    citicQueryWindowActive: 'Active source review',
    citicQueryWindowRevoked: 'Revoked',
    citicQueryWindowRevoke: 'Revoke query-window review',
    citicQueryWindowRevokeConfirm: 'Confirm query-window revocation',
    citicQueryWindowRevokeBody:
      'Append a revocation for this exact review. The source remains in the follow-up queue and its query window becomes unreviewed again.',
    citicQueryWindowRevokeConfirmAction: 'Confirm revocation',
    citicQueryWindowRevoking: 'Revoking…',
    citicQueryWindowRevokeFailed: 'Query-window revocation failed closed.',
    citicConfirmRejectBody:
      'Reject this exact fingerprint. Rejection is terminal; a changed file must be previewed as new evidence.',
    citicConfirmAction: 'Confirm review',
    citicCancelAction: 'Cancel',
    citicIntakeSaved: 'Follow-up source recorded',
    citicRejectionSaved: 'Source rejected',
    citicIntakeFailed: 'Source review was not recorded',
    citicClearBatch: 'Clear local batch',
    citicRetainedFileBoundary:
      'The original browser File reference is retained only until you record, reject, or clear this batch. Base64 content is cleared after every request.',
    citicDirectoryRetainedBoundary:
      'No browser File or path is retained. Final review re-scans the configured directory and must find the same full SHA-256 fingerprint.',
    citicIntakeHistory: 'Persisted source-review queue',
    citicNoIntakes: 'No CITIC source reviews have been persisted.',
    citicEvidenceBlocked: 'Evidence is still incomplete',
    citicEvidenceBlockedBody:
      'History Trades does not itemize all settlement charges and does not prove current cash or positions. These rows cannot enter Account Truth yet.',
    citicSoakBlocked: 'Not eligible for broker soak',
    citicSoakBlockedBody:
      'History Trades is incomplete Account Truth source material, not a versioned broker-connector snapshot. It cannot start or count toward the 20-day read-only soak.',
    citicSoakRequiredEvidence: 'Evidence required before soak',
    citicSoakProhibited:
      'This assessment does not register a connector, record soak evidence, contact the broker, or grant execution or capital authority.',
    citicInvalidRows: (count: number) =>
      `${count} ${count === 1 ? 'row or file issue remains' : 'row or file issues remain'}; no affected row was converted into evidence.`,
    citicNextSteps: [
      'Export an itemized delivery order or cash-flow statement covering the same period.',
      'Export a current cash and position snapshot for reconciliation.',
    ],
    citicNextStepTitle: 'Safe next evidence',
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
    score: '对账分数',
    scorePending: '待导入',
    gate: '对账门禁',
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
    reconciliationItems: '对账明细',
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
    readinessTitle: '证据就绪清单',
    readinessDetail:
      '用同一个只读持久事实清单说明哪些证据已审查、还缺什么，以及账户事实门禁为何通过或继续阻断。',
    readinessRequirements: '证据要求',
    readinessKnownSources: '持久化待补证来源',
    readinessClear: '持久证据已通过',
    readinessNextAction: '下一步安全动作',
    readinessPriorityBlockedTitle: '账户证据尚未就绪',
    readinessPriorityReadyTitle: '已复核账户证据已就绪',
    readinessPriorityBlockedDetail:
      '只要账户绑定、覆盖时段、资产范围或对账证据仍有缺失，整体证据门禁就会继续阻断。',
    readinessPriorityLocalPassDetail:
      '局部对账分数通过，不能清除这些证据缺失。',
    readinessPriorityReadyDetail:
      '持久化证据清单已完整；这不会授予执行或资本权限。',
    readinessPriorityAction: '查看证据要求',
    readinessItemEvidence: '支持证据',
    readinessItemSafeAction: '安全下一步',
    readinessItemNoEvidence: '暂无持久化证据',
    readinessScopeTitle: '可证明的证据范围',
    readinessScopeDetail:
      '已观察到的记录只能说明文件里有什么，不能证明它完整覆盖了整个账户或完整时段。',
    readinessAccountBinding: '已复核账户绑定',
    readinessDeclaredWindow: '已复核覆盖时段',
    readinessObservedWindow: '观察到的事件跨度',
    readinessObservedRows: (count: number) => `持久化记录 ${count} 条`,
    readinessObservedAssets: '观察到的资产类别',
    readinessSnapshotDates: '最新快照日期',
    readinessNoObservedAssets: '未观察到经过校验的资产类别',
    readinessCashSnapshotShort: '资金',
    readinessPositionSnapshotShort: '持仓',
    scopeReviewTitle: '复核并绑定这份证据范围',
    scopeReviewDetail:
      '把当前精确导入绑定到私有账户引用、已复核时段和完整资产范围。',
    scopeReviewProvider: '券商提供方代码',
    scopeReviewAccountAlias: '本地账户别名',
    scopeReviewAccountIdentifier: '券商账户标识',
    scopeReviewAccountIdentifierHelp:
      '账户标识只在当前浏览器中计算哈希，原值不会发送给 API，也不会持久化。',
    scopeReviewStartDate: '覆盖开始日期',
    scopeReviewEndDate: '覆盖结束日期',
    scopeReviewAssets: '已复核资产类别',
    scopeReviewAttestation:
      '我已复核这份精确导出，并确认它完整覆盖该时段内的整个账户及上述资产类别。',
    scopeReviewSubmit: '记录范围复核',
    scopeReviewRecording: '正在记录复核…',
    scopeReviewRecorded: '范围复核已记录',
    scopeReviewFailed: '范围复核已失败关闭',
    scopeReviewRevoke: '撤销范围复核',
    scopeReviewRevoking: '正在撤销复核…',
    scopeReviewRevoked: '范围复核已撤销',
    scopeReviewBoundary:
      '该显式动作只写入追加式范围复核记录；不会修改券商证据、执行对账、改写账本、联系券商，也不会授予执行或资本权限。',
    scopeReviewComplete: '已复核范围已绑定到当前精确持久化导入。',
    assetClassStock: '股票',
    assetClassEtf: 'ETF',
    assetClassFund: '基金',
    assetClassGold: '黄金',
    assetClassBond: '债券',
    assetClassCash: '现金',
    readinessBoundary:
      '该清单严格只读，不导入证据、不联系券商、不执行对账，也不授予执行或资本权限。',
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
    citicPreviewKicker: '中信旧版 XLS',
    citicPreviewTitle: '按月检查中信历史成交',
    citicPreviewBody:
      '一次选择最多 24 份已导出的 .xls 文件；系统只在内存中逐份检查，响应不会返回账户和成交明细。',
    citicChooseFile: '选择中信历史成交 XLS 文件',
    citicPreviewAction: '预览所选中信 XLS 文件',
    citicDirectoryTitle: '已配置的本地导出目录',
    citicDirectoryBody:
      '仅在人工触发时，按数量和字节上限读取目录直属且稳定的 XLS 文件；API 不返回配置路径或来源文件名。',
    citicDirectoryScanAction: '扫描已配置目录',
    citicDirectoryDisabled:
      '启动配置尚未启用本地目录扫描；仍可继续使用浏览器选择文件。',
    citicDirectoryUnavailable: '暂时无法读取目录扫描配置状态。',
    citicDirectoryEmpty: '目录中没有可读取的中信 .xls 文件。',
    citicDirectoryScanFailed: '目录扫描已安全阻断。',
    citicDirectoryPartial: (count: number) =>
      `${count} 个本地来源已被安全跳过；其余可读取来源仍然只是阻断预览。`,
    citicDirectorySummary: (
      candidates: number,
      previews: number,
      duplicates: number,
    ) => `候选 ${candidates} · 唯一预览 ${previews} · 重复 ${duplicates}`,
    citicBatchAssessmentTitle: '批次完整性与覆盖边界',
    citicBatchIntegrityClear: '文件集合完整性无冲突；覆盖范围尚未证明',
    citicBatchIntegrityBlocked: '文件集合完整性已阻断',
    citicBatchObservedMonths: (months: string) =>
      `观察到事件的月份：${months || '无'}`,
    citicBatchIntegritySummary: (
      uniqueEvents: number,
      crossFileDuplicates: number,
      identityConflicts: number,
      sourcesWithoutEvents: number,
    ) =>
      `唯一事件 ${uniqueEvents} · 跨文件重复 ${crossFileDuplicates} · 事件身份冲突 ${identityConflicts} · 无资金事件来源 ${sourcesWithoutEvents}`,
    citicBatchQueryWindowProgress: (reviewed: number, total: number) =>
      `当前来源查询区间已显式复核 ${reviewed} / ${total}`,
    citicQueryWindowBatchTitle: '声明查询区间完整性',
    citicQueryWindowBatchUnavailable: '尚无已复核查询区间',
    citicQueryWindowBatchPartial: '查询区间复核尚未完成',
    citicQueryWindowBatchClear: '声明日期连续且无重叠',
    citicQueryWindowBatchBlocked: '声明日期需要修正',
    citicQueryWindowBatchSummary: (
      startDate: string | null,
      endDate: string | null,
      coveredDays: number,
      gapDays: number,
      overlapDays: number,
    ) =>
      startDate && endDate
        ? `声明区间 ${startDate} — ${endDate} · 覆盖 ${coveredDays} 个自然日 · 缺口 ${gapDays} 天 · 重叠 ${overlapDays} 天`
        : '当前来源尚未记录显式复核的查询区间。',
    citicQueryWindowBatchBoundary:
      '这里只检查 owner 声明的导出日期。日期连续不能证明账户或资产范围完整，也不能补足逐项结算、当前资金或当前持仓。',
    citicSourceScopeBatchTitle: '声明来源范围完整性',
    citicSourceScopeBatchUnavailable: '尚无已复核来源范围',
    citicSourceScopeBatchPartial: '来源范围复核尚未完成',
    citicSourceScopeBatchClear: '声明来源范围一致',
    citicSourceScopeBatchBlocked: '声明来源范围存在冲突',
    citicSourceScopeBatchSummary: (
      reviewed: number,
      total: number,
      accountConsistent: boolean,
      scopeConsistent: boolean,
    ) =>
      `来源范围已复核 ${reviewed} / ${total} · 账户绑定${accountConsistent ? '一致' : '未证明或冲突'} · 声明范围${scopeConsistent ? '一致' : '未证明或冲突'}`,
    citicSourceScopeBatchDeclared: (
      accountType: string | null,
      markets: string,
      assets: string,
      accountValueBand: string | null,
      businesses: string,
    ) =>
      `账户类型 ${accountType || '未证明'} · 市场 ${markets || '未证明'} · 资产 ${assets || '未证明'} · 账户规模区间 ${accountValueBand || '未证明'} · 业务类型 ${businesses || '未证明'}`,
    citicSourceScopeBatchBoundary:
      '这是与精确文件和查询区间指纹绑定的 owner 声明；不能证明账户覆盖完整，也不能补足逐项结算、当前资金、当前持仓或交易授权。',
    citicBatchCoverageBoundary:
      '观察到事件的月份不能证明导出查询区间或月份覆盖完整。仍需逐份复核查询区间、逐项结算或资金流水、当前资金与持仓快照，以及账户绑定。',
    citicCanonicalLineageTitle: 'Canonical 来源链',
    citicCanonicalLineageExact: '事件身份已精确保留',
    citicCanonicalLineagePartial: '来源链不完整；需要复核',
    citicCanonicalLineageUnavailable: '来源链暂不可用',
    citicCanonicalLineageSummary: (
      matched: number,
      source: number,
      exactIdentity: number,
      brokerIdentity: number,
      sourceBrokerIdentity: number,
      canonicalUnmatched: number,
    ) =>
      `来源事件语义匹配 ${matched} / ${source} · 精确保留事件身份 ${exactIdentity} · 保留券商委托身份 ${brokerIdentity} / ${sourceBrokerIdentity} · 此批次之外的可比 canonical 事件 ${canonicalUnmatched}`,
    citicCanonicalLineageObservedTypes: (
      sourceTypes: string,
      canonicalTypes: string,
    ) => `来源事件类型：${sourceTypes} · Canonical 事件类型：${canonicalTypes}`,
    citicCanonicalLineageMismatchTypes: (
      matchedTypes: string,
      sourceUnmatchedTypes: string,
      canonicalUnmatchedTypes: string,
    ) =>
      `已匹配类型：${matchedTypes} · 来源未匹配类型：${sourceUnmatchedTypes} · 此批次之外的 canonical 类型：${canonicalUnmatchedTypes}`,
    citicCanonicalLineageIdentityPresence: (
      sourceIdentityCount: number,
      canonicalIdentityCount: number,
    ) =>
      `含券商委托身份：来源 ${sourceIdentityCount} · canonical ${canonicalIdentityCount}`,
    citicCanonicalLineageBoundary:
      '仅做只读运行时比对。财务语义相似但事件身份未保留，不构成 canonical 来源证明，也不能把这批 XLS 提升为 Account Truth。',
    citicConfiguredSource: (index: number) => `已配置来源 ${index}`,
    citicLocalNameMonthHint: (month: string) => `本地文件名月份提示：${month}`,
    citicLocalNameMonthHintBoundary:
      '仅用于辨认来源；不会自动填写，也不能证明券商查询区间。',
    citicConfiguredSourceUnidentified:
      '这一目录来源没有唯一的 YYYYMM 文件名标记。记录或拒绝前，请在浏览器中重新选择这份精确文件。',
    citicNoFile: '请先选择一份或多份中信 .xls 文件。',
    citicWrongFile: '请选择从中信“历史成交”导出的旧版 .xls 文件。',
    citicFileTooLarge: '所选文件超过 10 MB 预览上限。',
    citicTooManyFiles: '每个预检批次最多选择 24 个文件。',
    citicReadFailed: '无法读取所选本地文件。',
    citicPreviewFailed: '中信 XLS 预览失败',
    citicPreviewComplete: '只读批量预览完成',
    citicSelectedFiles: (count: number) => `已选择 ${count} 个文件`,
    citicPreviewProgress: (completed: number, total: number) =>
      `正在检查第 ${Math.min(completed + 1, total)} / ${total} 个文件`,
    citicFiles: '文件',
    citicFailedFileCount: (count: number) => `${count} 个文件预检失败`,
    citicDuplicateFile: '重复文件——不计入汇总',
    citicFilePreviewComplete: '已检查',
    citicFilePreviewFailed: '预检失败',
    citicRecognizedEvents: '识别事件',
    citicRecognizedNonFinancialActivities: '非资金活动',
    citicNonFinancialActivityNotice: (count: number) =>
      `已识别并隔离 ${count} 条指定交易类非资金活动，未生成券商事件。`,
    citicPrivacyBoundary:
      '仅做预览：不持久化证据、不联系券商，不修改账本、券商提交能力或资本授权。',
    citicPrivacyResponse:
      '响应只包含计数、校验问题和文件指纹；不包含账户、证券、金额和本地路径明细。',
    citicReviewFollowUp: '复核并记录待补证',
    citicRejectSource: '复核并拒绝',
    citicConfirmReview: '确认来源复核',
    citicConfirmFollowUpBody:
      '只记录文件指纹、校验摘要和缺失证据清单；解析事件仍不会进入账户事实。',
    citicQueryWindowStart: '券商查询起始日期',
    citicQueryWindowEnd: '券商查询结束日期',
    citicQueryWindowAttestation:
      '我已亲自核对：这一精确文件确实是使用上述起止日期从券商查询并导出的。',
    citicQueryWindowBoundary:
      '日期默认留空，系统不会从文件名或观察到的事件月份推断。该复核只证明这一来源的查询区间，不能证明账户覆盖完整。',
    citicSourceScopeAccountAlias: '本地账户别名',
    citicSourceScopeAccountIdentifier: '券商账户标识',
    citicSourceScopeAccountIdentifierBoundary:
      '仅在当前浏览器内散列；原始标识不会发送或保存。',
    citicSourceScopeAccountType: '账户类型代码',
    citicSourceScopeMarkets: '市场范围（逗号分隔代码）',
    citicSourceScopeAssets: '资产类别（逗号分隔代码）',
    citicSourceScopeAccountValueBand: '账户规模区间代码（例如 cny_0_20000）',
    citicSourceScopeAccountValueBandBoundary:
      '仅为查询范围元数据；不是当前余额、订单额度或资本授权。',
    citicSourceScopeBusinessTypes: '业务类型（逗号分隔代码）',
    citicSourceScopeNoOtherFiltersAttestation:
      '我确认这一精确导出没有使用其他券商查询筛选条件。',
    citicSourceScopeCompleteResultsAttestation:
      '我确认该文件包含上述券商查询返回的全部记录。',
    citicSourceScopeAttestation:
      '我确认上述账户、账户类型、市场、资产、账户规模区间和业务范围适用于这一精确导出。',
    citicSourceScopeBoundary:
      '该来源范围复核仍是证据不完整的旧版来源；不会创建账户事实、对账放行、执行权限或资本授权。',
    citicQueryWindowRequired:
      '请填写券商查询的起止日期，并明确勾选查询区间证明。',
    citicSourceScopeRequired:
      '请完整填写查询区间、账户绑定和声明范围，并勾选全部精确证明。',
    citicQueryWindowFailed: '来源已记录，但查询区间未能记录',
    citicSourceScopeFailed: '来源及查询区间已记录，但来源范围未能记录',
    citicQueryWindowSaved: '来源查询区间已记录',
    citicQueryWindowStillBlocked:
      '仅证明来源查询区间；账户事实与对账仍保持阻断。',
    citicSourceScopeSaved: '来源范围已记录',
    citicSourceScopeLabel: '已复核来源范围',
    citicSourceScopeRevokeFailed: '来源范围撤销已安全失败。',
    citicReviewQueryWindow: '复核来源查询区间',
    citicReviewSourceScope: '复核来源查询与范围',
    citicIntakeStillSaved: '脱敏来源复核仍已保存；请重新执行显式查询区间复核。',
    citicQueryWindowLabel: '已复核券商查询区间',
    citicQueryWindowActive: '来源复核有效',
    citicQueryWindowRevoked: '已撤销',
    citicQueryWindowRevoke: '撤销查询区间复核',
    citicQueryWindowRevokeConfirm: '确认撤销查询区间复核',
    citicQueryWindowRevokeBody:
      '为这一精确复核追加撤销记录。来源仍留在待补证队列，查询区间会重新变为未复核。',
    citicQueryWindowRevokeConfirmAction: '确认撤销',
    citicQueryWindowRevoking: '正在撤销…',
    citicQueryWindowRevokeFailed: '查询区间撤销已安全失败。',
    citicConfirmRejectBody:
      '拒绝这一精确文件指纹。拒绝为终态；内容变化后必须作为新证据重新预览。',
    citicConfirmAction: '确认复核',
    citicCancelAction: '取消',
    citicIntakeSaved: '已记录待补证来源',
    citicRejectionSaved: '已拒绝该来源',
    citicIntakeFailed: '来源复核未能记录',
    citicClearBatch: '清除本地批次',
    citicRetainedFileBoundary:
      '浏览器只在你记录、拒绝或清除该批次前保留原始 File 引用；每次请求结束都会清除 base64 内容。',
    citicDirectoryRetainedBoundary:
      '浏览器不保留 File 或路径；最终复核会重新扫描已配置目录，并且必须匹配同一完整 SHA-256 指纹。',
    citicIntakeHistory: '已持久化来源复核队列',
    citicNoIntakes: '还没有持久化的中信来源复核。',
    citicEvidenceBlocked: '证据仍不完整',
    citicEvidenceBlockedBody:
      '“历史成交”没有逐项列出全部结算费用，也不能证明当前现金和持仓；这些记录目前不能进入账户事实。',
    citicSoakBlocked: '不能计入券商只读 soak',
    citicSoakBlockedBody:
      '“历史成交”只是待补全的账户事实来源，不是版本化券商连接器快照；它不能启动或计入 20 个交易日只读 soak。',
    citicSoakRequiredEvidence: '进入 soak 前仍需的来源证据',
    citicSoakProhibited:
      '该评估不会注册连接器、记录 soak 证据、联系券商，也不会授予执行或资本权限。',
    citicInvalidRows: (count: number) =>
      `仍有 ${count} 个文件或行级问题；受影响记录没有被转换为证据。`,
    citicNextSteps: [
      '导出覆盖同一期间、逐项列出费用的交割单或资金流水。',
      '导出当前资金和持仓快照，用于对账。',
    ],
    citicNextStepTitle: '下一份安全证据',
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

  const selectReport = (importRunId: string) => {
    setSelectedImportRunId(importRunId);
    setSelectedItemIdentity(null);
    setShowMatchedItems(false);
    setSavedReviewStatus(null);
  };

  if (!hasSummaryEvidence) {
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
        {hasError ? (
          <EvidenceState kind="error" title={text.error} />
        ) : (
          <EvidenceLoadingLayout
            title={text.loading}
            metricCount={4}
            rowCount={4}
          />
        )}
      </section>
    );
  }

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

      {readiness.data ? (
        <div data-testid="account-truth-readiness-priority">
          <EvidenceState
            kind={readiness.data.status === 'ready' ? 'ready' : 'partial'}
            statusLabel={
              readiness.data.status === 'ready'
                ? text.readinessClear
                : formatCode(readiness.data.status, locale, 'status')
            }
            title={
              readiness.data.status === 'ready'
                ? text.readinessPriorityReadyTitle
                : text.readinessPriorityBlockedTitle
            }
            description={
              <>
                {readiness.data.status === 'ready'
                  ? text.readinessPriorityReadyDetail
                  : text.readinessPriorityBlockedDetail}
                {readiness.data.status !== 'ready' &&
                readiness.data.account_truth_gate_status === 'pass'
                  ? ` ${text.readinessPriorityLocalPassDetail}`
                  : null}
                {readiness.data.next_manual_action !== 'none'
                  ? ` ${text.readinessNextAction}: ${formatCode(
                      readiness.data.next_manual_action,
                      locale,
                      'code',
                    )}`
                  : null}
              </>
            }
            action={
              <a
                aria-controls="account-truth-evidence-readiness-disclosure"
                className="app-button-secondary inline-flex min-h-10 items-center rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
                href="#account-truth-evidence-readiness-disclosure"
                onClick={() =>
                  openAccountTruthReadinessTarget(
                    'account-truth-evidence-readiness-disclosure',
                  )
                }
              >
                {text.readinessPriorityAction}
              </a>
            }
          />
        </div>
      ) : null}

      <div className="flex min-w-0 flex-col gap-5 sm:gap-6">
        <section
          className="app-workbench-section order-1 min-w-0 px-1 py-4 sm:order-2 sm:px-4"
          data-testid="account-truth-review-workspace"
          id="account-truth-review-workspace"
        >
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="app-product-mark">{text.reports}</div>
              <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
                {text.reviewWorkspace}
              </h2>
              <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
                {text.reviewWorkspaceDetail}
              </p>
            </div>
            <span className="shrink-0 text-xs text-[var(--app-text-tertiary)]">
              {detail.isLoading || (!selectedReport && reports.isLoading)
                ? text.loading
                : text.itemCount(detail.data?.items.length ?? 0)}
            </span>
          </div>

          <div
            aria-label={text.reportListLabel}
            className="app-account-truth-filter-rail app-horizontal-scroll-cue mt-4 flex max-w-full gap-1.5 overflow-x-auto overscroll-x-contain border-y border-[var(--app-divider)] py-2 sm:gap-2"
          >
            {filters.map((option) => (
              <button
                key={option.value}
                aria-pressed={filter === option.value}
                type="button"
                className={`min-h-10 shrink-0 rounded-[var(--app-radius-control)] border px-2.5 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:px-3 ${
                  filter === option.value
                    ? 'border-[var(--app-accent)] bg-[var(--app-accent-bg)] text-[var(--app-text)]'
                    : 'border-[var(--app-divider)] text-[var(--app-text-secondary)]'
                }`}
                onClick={() => {
                  setFilter(option.value);
                  setSelectedImportRunId(null);
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
                <div className="app-type-overline text-[var(--app-text-tertiary)]">
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
                  <div className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {formatDateTime(selectedReport.created_at)}
                  </div>
                </div>

                {reportHistory.length > 0 ? (
                  <details
                    className="mt-3 border-y border-[var(--app-divider)]"
                    data-testid="account-truth-report-history-disclosure"
                  >
                    <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
                      <span>
                        {text.reportHistoryCount(reportHistory.length)}
                      </span>
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
                            <span className="app-type-micro block text-[var(--app-text-tertiary)]">
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
                  <h3 className="app-type-subsection-title truncate text-[var(--app-text)]">
                    {attentionItems.length > 0
                      ? text.attentionItems
                      : text.reconciliationItems}
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
                        onClick={() =>
                          setShowMatchedItems((current) => !current)
                        }
                      >
                        {showMatchedItems
                          ? text.hideMatchedItems
                          : text.showMatchedItems(indexedItems.length)}
                      </button>
                    }
                  />
                ) : null}

                {detail.isLoading ? (
                  <div
                    className="mt-3"
                    data-testid="account-truth-report-detail-loading"
                  >
                    <EvidenceState kind="loading" title={text.loading} />
                  </div>
                ) : detail.isError ? (
                  <EvidenceState
                    className="mt-3"
                    kind="error"
                    title={text.error}
                  />
                ) : visibleItems.length > 0 && detail.data ? (
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
          ) : reports.isLoading ? (
            <div className="mt-4" data-testid="account-truth-reports-loading">
              <EvidenceState kind="loading" title={text.loading} />
            </div>
          ) : reports.isError ? (
            <EvidenceState className="mt-4" kind="error" title={text.error} />
          ) : (
            <EvidenceState
              className="mt-4"
              kind="empty"
              title={text.noReports}
            />
          )}
        </section>

        <div className="order-2 min-w-0 sm:order-1">
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
                tone:
                  scoreData?.gate_status === 'blocked' ? 'warning' : 'neutral',
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
        </div>
      </div>

      <div className="grid min-w-0 gap-3">
        {readiness.data ? (
          <FeeScheduleReviewPanel locale={locale} readiness={readiness.data} />
        ) : null}

        <AccountTruthDisclosure
          key={`readiness-${readiness.data?.evidence_fingerprint ?? 'missing'}`}
          defaultOpen={readiness.data?.status !== 'ready'}
          detail={text.readinessDetail}
          id="account-truth-evidence-readiness-disclosure"
          testId="account-truth-evidence-readiness-disclosure"
          title={text.readinessTitle}
        >
          <EvidenceReadinessChecklist
            locale={locale}
            readiness={readiness.data}
          />
        </AccountTruthDisclosure>

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
              <h2 className="app-type-section-title text-[var(--app-text)]">
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
                  <span className="app-type-micro flex items-center gap-2 text-[var(--app-text-tertiary)]">
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
          id="account-truth-import-tools"
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

const accountTruthReadinessEvidenceLabels = {
  en: {
    account_truth_import: 'Account Truth import',
    account_truth_evidence_scope: 'Reviewed evidence scope',
    account_truth_score: 'Account Truth score',
    evidence_fingerprint: 'Evidence fingerprint',
    cash_status: 'Cash component',
    position_status: 'Position component',
    fee_status: 'Fee and tax component',
    cost_basis_status: 'Cost-basis component',
    ledger_coverage: 'Freshness and ledger coverage',
    latest: 'Overall gate',
  },
  zh: {
    account_truth_import: '账户事实导入',
    account_truth_evidence_scope: '已复核证据范围',
    account_truth_score: '账户事实评分',
    evidence_fingerprint: '证据指纹',
    cash_status: '现金分项',
    position_status: '持仓分项',
    fee_status: '费用与税费分项',
    cost_basis_status: '成本基础分项',
    ledger_coverage: '新鲜度与账本覆盖',
    latest: '整体门禁',
  },
} as const;

function formatAccountTruthReadinessEvidenceReference(
  value: string | null,
  locale: 'en' | 'zh',
  missingLabel: string,
) {
  if (!value) {
    return missingLabel;
  }
  const [referenceType, ...identityParts] = value.split(':');
  const identity = identityParts.join(':').trim();
  const typeLabels = accountTruthReadinessEvidenceLabels[locale];
  if (referenceType === 'account_truth_score' && identity) {
    const componentLabel =
      typeLabels[identity as keyof typeof typeLabels] ?? identity;
    return `${typeLabels.account_truth_score} · ${componentLabel}`;
  }
  if (
    (referenceType === 'account_truth_import' ||
      referenceType === 'account_truth_evidence_scope') &&
    identity
  ) {
    return `${typeLabels[referenceType]} · ${identity}`;
  }
  if (referenceType === 'sha256' && identity) {
    return `${typeLabels.evidence_fingerprint} · sha256:${identity}`;
  }
  return formatPublicEvidenceReference(value, locale);
}

const accountTruthEvidenceIntakeActions = new Set([
  'import_and_reconcile_broker_evidence',
  'provide_cash_snapshot',
  'provide_position_snapshot',
  'provide_itemized_settlement_or_cash_flow',
  'provide_position_cost_basis_evidence',
  'refresh_broker_evidence_covering_latest_ledger',
  'provide_citic_account_truth_evidence_or_reject_source',
  'review_citic_source_query_windows',
]);

const accountTruthEvidenceScopeActions = new Set([
  'record_reviewed_account_truth_evidence_scope',
  'bind_account_truth_evidence_to_reviewed_account_scope',
  'record_reviewed_account_truth_coverage_window',
  'review_account_truth_asset_scope_completeness',
]);

const accountTruthReconciliationActions = new Set([
  'resolve_account_truth_blockers',
]);

function accountTruthReadinessActionTarget(
  action: string,
  hasCanonicalImport: boolean,
) {
  if (accountTruthEvidenceIntakeActions.has(action)) {
    return 'account-truth-import-tools';
  }
  if (accountTruthEvidenceScopeActions.has(action)) {
    return hasCanonicalImport
      ? 'account-truth-evidence-scope-review'
      : 'account-truth-import-tools';
  }
  if (accountTruthReconciliationActions.has(action)) {
    return 'account-truth-review-workspace';
  }
  return null;
}

function openAccountTruthReadinessTarget(targetId: string) {
  const target = document.getElementById(targetId);
  if (target instanceof HTMLDetailsElement) {
    target.open = true;
  }
}

function legacySourceResolutionStatusLabel(
  status: string | undefined,
  locale: 'en' | 'zh',
) {
  const labels: Record<string, { en: string; zh: string }> = {
    legacy_source_review_state_unavailable: {
      en: 'review state unavailable',
      zh: '复核状态不可用',
    },
    no_legacy_source_resolution_pending: {
      en: 'no pending legacy source',
      zh: '没有待处理历史来源',
    },
    legacy_query_window_review_required: {
      en: 'query-window review required',
      zh: '仍需查询区间复核',
    },
    legacy_source_scope_review_required: {
      en: 'source-scope review required',
      zh: '仍需来源范围复核',
    },
    legacy_attestations_complete_canonical_resolution_required: {
      en: 'legacy attestations complete; canonical resolution required',
      zh: '历史声明已完成；仍需 canonical 处理',
    },
  };
  const key = status || 'legacy_source_review_state_unavailable';
  return labels[key]?.[locale] ?? formatCode(key, locale, 'status');
}

function EvidenceReadinessChecklist({
  locale,
  readiness,
}: {
  locale: 'en' | 'zh';
  readiness: AccountTruthEvidenceReadiness | undefined;
}) {
  const text = labels[locale];
  if (!readiness) {
    return <EvidenceState kind="error" title={text.error} />;
  }
  const scope = readiness.evidence_scope;
  const observedWindow = scope.observed_event_window;
  const observedRange =
    observedWindow.occurred_start_date && observedWindow.occurred_end_date
      ? `${observedWindow.occurred_start_date} – ${observedWindow.occurred_end_date}`
      : '--';
  const observedAssets = scope.asset_scope.observed_asset_classes.length
    ? scope.asset_scope.observed_asset_classes
        .map((assetClass) => formatAssetClassLabel(assetClass, text))
        .join(' · ')
    : text.readinessNoObservedAssets;
  const snapshotDates = [
    `${text.readinessCashSnapshotShort} ${scope.snapshot_evidence.latest_cash_snapshot_date ?? '--'}`,
    `${text.readinessPositionSnapshotShort} ${scope.snapshot_evidence.latest_position_snapshot_date ?? '--'}`,
  ].join(' · ');
  const sourceFollowUp = readiness.citic_source_follow_up;
  const queryWindowIntegrityStatus =
    sourceFollowUp?.query_window_batch_integrity_status || 'missing';
  const queryWindowGapDays = Math.max(
    0,
    sourceFollowUp?.query_window_gap_calendar_day_count ?? 0,
  );
  const queryWindowOverlapDays = Math.max(
    0,
    sourceFollowUp?.query_window_overlap_calendar_day_count ?? 0,
  );
  const sourceResolution = sourceFollowUp?.resolution;
  const legacyAttestationsComplete =
    sourceResolution?.legacy_source_attestations_complete === true;
  return (
    <section
      className="min-w-0 px-1 py-4 sm:px-4"
      data-testid="account-truth-evidence-readiness"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {text.readinessRequirements}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {text.readinessKnownSources}:{' '}
            {readiness.known_incomplete_source_count}
          </p>
          <p
            className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]"
            data-testid="account-truth-citic-query-window-integrity"
          >
            {locale === 'zh' ? '查询区间完整性' : 'Query-window integrity'}:{' '}
            {formatCode(queryWindowIntegrityStatus, locale, 'status')} ·{' '}
            {locale === 'zh' ? '缺口天数' : 'gap days'} {queryWindowGapDays} ·{' '}
            {locale === 'zh' ? '重叠天数' : 'overlap days'}{' '}
            {queryWindowOverlapDays}
          </p>
          <p
            className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]"
            data-testid="account-truth-citic-source-resolution"
          >
            {legacyAttestationsComplete
              ? locale === 'zh'
                ? `历史 XLS 声明：${sourceResolution.pending_source_count}/${sourceResolution.pending_source_count} 已复核；无需重做，但仍需单独完成 canonical Account Truth 证据或明确拒绝来源。`
                : `Historical XLS attestations: ${sourceResolution.pending_source_count}/${sourceResolution.pending_source_count} reviewed; no redo is needed, but separate canonical Account Truth evidence or explicit source rejection is still required.`
              : `${locale === 'zh' ? '历史 XLS 声明阶段' : 'Historical XLS attestation stage'}: ${legacySourceResolutionStatusLabel(
                  sourceResolution?.status,
                  locale,
                )}`}
          </p>
        </div>
        <StatusBadge tone={statusTone(readiness.status)}>
          {readiness.status === 'ready'
            ? text.readinessClear
            : formatCode(readiness.status, locale, 'status')}
        </StatusBadge>
      </div>
      <ul className="mt-4 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
        {readiness.items.map((item) => {
          const actionTarget = item.required_action
            ? accountTruthReadinessActionTarget(
                item.required_action,
                Boolean(readiness.account_truth_import_run_id),
              )
            : null;
          return (
            <li
              key={item.requirement}
              className="grid min-h-11 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 py-3"
              data-testid={`account-truth-readiness-item-${item.requirement}`}
            >
              <div className="min-w-0">
                <div className="text-xs font-semibold text-[var(--app-text)]">
                  {formatCode(item.requirement, locale, 'code')}
                </div>
                <dl className="mt-2 grid min-w-0 gap-2 text-xs sm:grid-cols-2">
                  <div className="min-w-0">
                    <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                      {text.readinessItemEvidence}
                    </dt>
                    <dd className="mt-0.5 break-all leading-5 text-[var(--app-text-secondary)]">
                      {formatAccountTruthReadinessEvidenceReference(
                        item.evidence_reference,
                        locale,
                        text.readinessItemNoEvidence,
                      )}
                    </dd>
                  </div>
                  {item.required_action ? (
                    <div className="min-w-0">
                      <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                        {text.readinessItemSafeAction}
                      </dt>
                      <dd className="mt-0.5 leading-5 text-[var(--app-text-secondary)]">
                        {actionTarget ? (
                          <a
                            aria-controls={actionTarget}
                            className="app-button-ghost inline-flex min-h-9 max-w-full items-center rounded-[var(--app-radius-control)] px-2.5 text-left text-xs font-semibold"
                            href={`#${actionTarget}`}
                            onClick={() =>
                              openAccountTruthReadinessTarget(actionTarget)
                            }
                          >
                            {formatCode(item.required_action, locale, 'code')}
                          </a>
                        ) : (
                          formatCode(item.required_action, locale, 'code')
                        )}
                      </dd>
                    </div>
                  ) : null}
                </dl>
              </div>
              <StatusBadge tone={statusTone(item.status)}>
                {formatCode(item.status, locale, 'status')}
              </StatusBadge>
            </li>
          );
        })}
      </ul>
      <section
        className="mt-5 border-l-2 border-[var(--app-warning-border)] pl-3"
        data-testid="account-truth-evidence-scope"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-xs font-semibold text-[var(--app-text)]">
              {text.readinessScopeTitle}
            </h3>
            <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
              {text.readinessScopeDetail}
            </p>
          </div>
          <StatusBadge tone={statusTone(scope.status)}>
            {formatCode(scope.status, locale, 'status')}
          </StatusBadge>
        </div>
        <dl className="mt-3 divide-y divide-[var(--app-divider)] text-xs">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="text-[var(--app-text-secondary)]">
              {text.readinessAccountBinding}
            </dt>
            <dd>
              <StatusBadge tone={statusTone(scope.account_binding.status)}>
                {formatCode(scope.account_binding.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="text-[var(--app-text-secondary)]">
              {text.readinessDeclaredWindow}
            </dt>
            <dd>
              <StatusBadge
                tone={statusTone(scope.declared_coverage_window.status)}
              >
                {formatCode(
                  scope.declared_coverage_window.status,
                  locale,
                  'status',
                )}
              </StatusBadge>
            </dd>
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2">
            <dt className="min-w-0 text-[var(--app-text-secondary)]">
              <span className="block">{text.readinessObservedWindow}</span>
              <span className="mt-0.5 block text-[var(--app-text-tertiary)]">
                {observedRange} ·{' '}
                {text.readinessObservedRows(observedWindow.unique_event_count)}
              </span>
            </dt>
            <dd>
              <StatusBadge tone={statusTone(observedWindow.status)}>
                {formatCode(observedWindow.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2"
            data-testid="account-truth-evidence-scope-assets"
          >
            <dt className="min-w-0 text-[var(--app-text-secondary)]">
              <span className="block">{text.readinessObservedAssets}</span>
              <span className="mt-0.5 block text-[var(--app-text-tertiary)]">
                {observedAssets}
              </span>
            </dt>
            <dd>
              <StatusBadge tone={statusTone(scope.asset_scope.status)}>
                {formatCode(scope.asset_scope.status, locale, 'status')}
              </StatusBadge>
            </dd>
          </div>
          <div className="py-2 text-[var(--app-text-secondary)]">
            <dt>{text.readinessSnapshotDates}</dt>
            <dd className="mt-0.5 text-[var(--app-text-tertiary)]">
              {snapshotDates}
            </dd>
          </div>
        </dl>
        <EvidenceScopeReviewControl locale={locale} readiness={readiness} />
      </section>
      <ReasonList
        title={text.blockingReasons}
        values={readiness.blockers}
        locale={locale}
      />
      <ReasonList
        title={text.requiredActions}
        values={readiness.required_actions}
        locale={locale}
      />
      <div className="mt-4 border-l-2 border-[var(--app-accent-border)] pl-3">
        {readiness.next_manual_action !== 'none' ? (
          <>
            <div className="app-type-overline text-[var(--app-text-tertiary)]">
              {text.readinessNextAction}
            </div>
            <p className="mt-1 text-xs font-semibold text-[var(--app-text)]">
              {formatCode(readiness.next_manual_action, locale, 'code')}
            </p>
          </>
        ) : null}
        <p className="mt-2 text-xs leading-5 text-[var(--app-text-secondary)]">
          {text.readinessBoundary}
        </p>
      </div>
    </section>
  );
}

function EvidenceScopeReviewControl({
  locale,
  readiness,
}: {
  locale: 'en' | 'zh';
  readiness: AccountTruthEvidenceReadiness;
}) {
  const text = labels[locale];
  const scope = readiness.evidence_scope;
  const recordMutation = useRecordEvidenceScopeReviewMutation();
  const revokeMutation = useRevokeEvidenceScopeReviewMutation();
  const [provider, setProvider] = useState(scope.review?.provider ?? 'citic');
  const [accountAlias, setAccountAlias] = useState('');
  const [accountIdentifier, setAccountIdentifier] = useState('');
  const [coverageStartDate, setCoverageStartDate] = useState('');
  const [coverageEndDate, setCoverageEndDate] = useState('');
  const [reviewedAssets, setReviewedAssets] = useState('');
  const [attested, setAttested] = useState(false);

  useEffect(() => {
    setCoverageStartDate(scope.observed_event_window.occurred_start_date ?? '');
    setCoverageEndDate(scope.observed_event_window.occurred_end_date ?? '');
    setReviewedAssets(scope.asset_scope.observed_asset_classes.join(', '));
    setAccountIdentifier('');
    setAttested(false);
    recordMutation.reset();
    revokeMutation.reset();
  }, [scope.observed_scope_fingerprint]);

  const importRunId = readiness.account_truth_import_run_id;
  const parsedAssets = reviewedAssets
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  const canRecord = Boolean(
    importRunId &&
    provider.trim() &&
    accountAlias.trim() &&
    accountIdentifier.trim() &&
    coverageStartDate &&
    coverageEndDate &&
    parsedAssets.length &&
    attested &&
    !recordMutation.isPending,
  );

  const handleRecord = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canRecord || !importRunId) return;
    try {
      const accountReferenceHash = await hashAccountTruthAccountReference(
        provider,
        accountIdentifier,
      );
      setAccountIdentifier('');
      await recordMutation.mutateAsync({
        importRunId,
        expectedObservedScopeFingerprint: scope.observed_scope_fingerprint,
        provider,
        accountAlias,
        accountReferenceHash,
        coverageStartDate,
        coverageEndDate,
        assetClasses: parsedAssets,
        fullAccountScopeAttested: true,
      });
    } catch {
      setAccountIdentifier('');
      // The mutation exposes a sanitized fail-closed state below.
    }
  };

  const inputClass =
    'min-h-10 w-full rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text)] outline-none focus-visible:border-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]';

  if (!importRunId) return null;
  if (scope.status === 'complete') {
    return (
      <div
        className="mt-4 rounded-[var(--app-radius-control)] border border-[var(--app-success-border)] bg-[var(--app-success-bg)] p-3"
        data-testid="account-truth-evidence-scope-review-complete"
        id="account-truth-evidence-scope-review"
      >
        <p className="text-xs font-semibold text-[var(--app-text)]">
          {text.scopeReviewComplete}
        </p>
        <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
          {scope.account_binding.account_alias} ·{' '}
          {scope.declared_coverage_window.start_date} –{' '}
          {scope.declared_coverage_window.end_date}
        </p>
        <p className="mt-2 text-xs leading-5 text-[var(--app-text-tertiary)]">
          {text.scopeReviewBoundary}
        </p>
        <button
          className="mt-3 min-h-10 rounded-[var(--app-radius-control)] border border-[var(--app-danger-border)] px-3 py-2 text-xs font-semibold text-[var(--app-danger)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] disabled:opacity-50"
          disabled={revokeMutation.isPending}
          type="button"
          onClick={() =>
            revokeMutation.mutate({
              importRunId,
              expectedObservedScopeFingerprint:
                scope.observed_scope_fingerprint,
            })
          }
        >
          {revokeMutation.isPending
            ? text.scopeReviewRevoking
            : text.scopeReviewRevoke}
        </button>
        {revokeMutation.isError ? (
          <p className="mt-2 text-xs text-[var(--app-danger)]">
            {text.scopeReviewFailed}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <form
      className="mt-4 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3"
      data-testid="account-truth-evidence-scope-review-form"
      id="account-truth-evidence-scope-review"
      onSubmit={handleRecord}
    >
      <h4 className="text-xs font-semibold text-[var(--app-text)]">
        {text.scopeReviewTitle}
      </h4>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {text.scopeReviewDetail}
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewProvider}
          <input
            className={inputClass}
            data-testid="account-truth-scope-provider"
            maxLength={64}
            value={provider}
            onChange={(event) => setProvider(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewAccountAlias}
          <input
            className={inputClass}
            data-testid="account-truth-scope-account-alias"
            maxLength={128}
            value={accountAlias}
            onChange={(event) => setAccountAlias(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)] sm:col-span-2">
          {text.scopeReviewAccountIdentifier}
          <input
            autoComplete="off"
            className={inputClass}
            data-testid="account-truth-scope-account-identifier"
            maxLength={256}
            type="password"
            value={accountIdentifier}
            onChange={(event) =>
              setAccountIdentifier(event.currentTarget.value)
            }
          />
          <span className="font-normal leading-5 text-[var(--app-text-tertiary)]">
            {text.scopeReviewAccountIdentifierHelp}
          </span>
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewStartDate}
          <input
            className={inputClass}
            data-testid="account-truth-scope-start-date"
            type="date"
            value={coverageStartDate}
            onChange={(event) =>
              setCoverageStartDate(event.currentTarget.value)
            }
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.scopeReviewEndDate}
          <input
            className={inputClass}
            data-testid="account-truth-scope-end-date"
            type="date"
            value={coverageEndDate}
            onChange={(event) => setCoverageEndDate(event.currentTarget.value)}
          />
        </label>
        <label className="grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)] sm:col-span-2">
          {text.scopeReviewAssets}
          <input
            className={inputClass}
            data-testid="account-truth-scope-assets"
            value={reviewedAssets}
            onChange={(event) => setReviewedAssets(event.currentTarget.value)}
          />
        </label>
      </div>
      <label className="mt-3 flex items-start gap-2 text-xs leading-5 text-[var(--app-text-secondary)]">
        <input
          checked={attested}
          className="mt-1 size-4 shrink-0 accent-[var(--app-accent)]"
          data-testid="account-truth-scope-attestation"
          type="checkbox"
          onChange={(event) => setAttested(event.currentTarget.checked)}
        />
        <span>{text.scopeReviewAttestation}</span>
      </label>
      <button
        className="mt-3 min-h-10 rounded-[var(--app-radius-control)] bg-[var(--app-accent)] px-4 py-2 text-xs font-semibold text-[var(--app-text-inverse)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50"
        disabled={!canRecord}
        type="submit"
      >
        {recordMutation.isPending
          ? text.scopeReviewRecording
          : text.scopeReviewSubmit}
      </button>
      {recordMutation.isSuccess ? (
        <p className="mt-2 text-xs font-semibold text-[var(--app-success)]">
          {text.scopeReviewRecorded}
        </p>
      ) : null}
      {recordMutation.isError ? (
        <p className="mt-2 text-xs font-semibold text-[var(--app-danger)]">
          {text.scopeReviewFailed}
        </p>
      ) : null}
      <p className="mt-3 text-xs leading-5 text-[var(--app-text-tertiary)]">
        {text.scopeReviewBoundary}
      </p>
    </form>
  );
}

function AccountTruthDisclosure({
  children,
  defaultOpen = false,
  detail,
  id,
  testId,
  title,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  detail: string;
  id?: string;
  testId: string;
  title: string;
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <details
      className="group min-w-0"
      data-testid={testId}
      id={id}
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
                <span className="app-type-micro mt-0.5 block truncate text-[var(--app-text-secondary)]">
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
    [
      'pass',
      'ready',
      'available',
      'healthy',
      'fresh',
      'imported',
      'unchanged',
    ].includes(normalized)
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

const CITIC_HISTORY_XLS_MAX_BYTES = 10 * 1024 * 1024;
const CITIC_HISTORY_XLS_MAX_FILES = 24;

type CiticHistoryXlsPreviewResult = {
  id: string;
  localFileName: string;
  localNameMonthHint: string | null;
  sourceKind: 'browser_file' | 'configured_directory';
  status: 'pending' | 'complete' | 'error';
  errorKind: 'read' | 'preview' | null;
  preview: CiticHistoryXlsPreview | null;
  intakeState: 'idle' | 'pending' | 'saved' | 'error';
  intake: CiticSourceIntake | null;
  queryWindowState: 'idle' | 'pending' | 'saved' | 'error';
  queryWindowReview: CiticSourceQueryWindowReview | null;
  sourceScopeState: 'idle' | 'pending' | 'saved' | 'error';
  sourceScopeReview: CiticSourceScopeReview | null;
};

type CiticSourceReviewIntent = {
  resultId: string;
  reviewStatus: CiticSourceReviewStatus;
  queryStartDate: string;
  queryEndDate: string;
  queryWindowAttested: boolean;
  accountAlias: string;
  accountIdentifier: string;
  accountType: string;
  marketScopes: string;
  assetClasses: string;
  accountValueBand: string;
  businessTypes: string;
  noOtherFiltersAttested: boolean;
  completeReturnedResultsAttested: boolean;
  sourceScopeAttested: boolean;
};

function parseCiticSourceScopeCodes(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(',')
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    ),
  );
}

function readFileAsBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () =>
      reject(reader.error ?? new Error('file read failed'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('file read failed'));
        return;
      }
      const separatorIndex = reader.result.indexOf(',');
      if (separatorIndex < 0) {
        reject(new Error('file read failed'));
        return;
      }
      resolve(reader.result.slice(separatorIndex + 1));
    };
    reader.readAsDataURL(file);
  });
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
    <div className="grid gap-5">
      <CiticHistoryXlsPreviewTool locale={locale} />
      <ControlledActionZone
        title={text.importWizardTitle}
        description={text.importWizardBody}
        evidence={text.importBoundary}
        layout="stack"
        tone="info"
      >
        <div
          className="w-full min-w-0"
          data-testid="account-truth-import-wizard"
        >
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
            <EvidenceState
              className="mt-3"
              kind="partial"
              title={fileMessage}
            />
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
    </div>
  );
}

function CiticHistoryXlsPreviewTool({ locale }: { locale: 'en' | 'zh' }) {
  const text = labels[locale];
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
  const previewMutation = useCiticHistoryXlsPreviewMutation();
  const intakeMutation = useCiticHistoryXlsIntakeMutation();
  const intakesQuery = useCiticHistoryXlsIntakesQuery();
  const directoryStatusQuery = useCiticHistoryXlsDirectoryStatusQuery();
  const directoryScanMutation = useCiticHistoryXlsDirectoryScanMutation();
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
  const scanPending = isBatchPending || directoryScanMutation.isPending;

  useEffect(
    () => () => {
      sourceFilesRef.current.clear();
    },
    [],
  );

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    if (files.length === 0) {
      return;
    }
    previewMutation.reset();
    intakeMutation.reset();
    directoryScanMutation.reset();
    directoryIntakeMutation.reset();
    queryWindowMutation.reset();
    directoryQueryWindowMutation.reset();
    sourceScopeMutation.reset();
    sourceScopeRevokeMutation.reset();
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
        contentBase64 = await readFileAsBase64(file);
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
    intakeMutation.reset();
    directoryIntakeMutation.reset();
    queryWindowMutation.reset();
    directoryQueryWindowMutation.reset();
    sourceScopeMutation.reset();
    sourceScopeRevokeMutation.reset();
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

  function startSourceReview(
    resultId: string,
    reviewStatus: CiticSourceReviewStatus,
  ) {
    setFileMessage(null);
    intakeMutation.reset();
    directoryIntakeMutation.reset();
    queryWindowMutation.reset();
    directoryQueryWindowMutation.reset();
    sourceScopeMutation.reset();
    setReviewIntent({
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
    });
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
        contentBase64 = await readFileAsBase64(sourceFile as File);
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

  function clearLocalBatch() {
    sourceFilesRef.current.clear();
    setSelectedFiles([]);
    setBatchResults([]);
    setReviewIntent(null);
    setFileMessage(null);
    previewMutation.reset();
    intakeMutation.reset();
    directoryScanMutation.reset();
    directoryIntakeMutation.reset();
    queryWindowMutation.reset();
    directoryQueryWindowMutation.reset();
    queryWindowRevokeMutation.reset();
    sourceScopeMutation.reset();
    sourceScopeRevokeMutation.reset();
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }

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
        <div className="mt-4 border-y border-[var(--app-divider)] py-3">
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {text.citicDirectoryTitle}
          </div>
          <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
            {text.citicDirectoryBody}
          </p>
          {directoryStatusQuery.isPending ? (
            <EvidenceState
              className="mt-3"
              kind="partial"
              title={text.collectorLoading}
            />
          ) : directoryStatusQuery.isError || !directoryStatusQuery.data ? (
            <EvidenceState
              className="mt-3"
              kind="error"
              title={text.citicDirectoryUnavailable}
            />
          ) : directoryStatusQuery.data.enabled ? (
            <button
              className="app-button-secondary mt-3 min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              disabled={scanPending || intakePending}
              type="button"
              onClick={previewConfiguredDirectory}
            >
              {text.citicDirectoryScanAction}
            </button>
          ) : (
            <EvidenceState
              className="mt-3"
              kind="partial"
              title={text.citicDirectoryDisabled}
            />
          )}
          {directoryScanMutation.data ? (
            <>
              <p
                className="app-type-micro mt-2 text-[var(--app-text-tertiary)]"
                data-testid="citic-directory-scan-summary"
              >
                {text.citicDirectorySummary(
                  directoryScanMutation.data.candidate_file_count,
                  directoryScanMutation.data.preview_count,
                  directoryScanMutation.data.duplicate_file_count,
                )}
              </p>
              <div
                className="mt-3 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3"
                data-testid="citic-directory-batch-assessment"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-[var(--app-text)]">
                    {text.citicBatchAssessmentTitle}
                  </div>
                  <StatusBadge tone={statusTone('blocked')}>
                    {directoryScanMutation.data.batch_assessment
                      .integrity_status === 'clear'
                      ? text.citicBatchIntegrityClear
                      : text.citicBatchIntegrityBlocked}
                  </StatusBadge>
                </div>
                <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
                  {text.citicBatchObservedMonths(
                    directoryScanMutation.data.batch_assessment.observed_event_months.join(
                      ', ',
                    ),
                  )}
                </p>
                <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
                  {text.citicBatchIntegritySummary(
                    directoryScanMutation.data.batch_assessment
                      .unique_event_count,
                    directoryScanMutation.data.batch_assessment
                      .cross_file_duplicate_event_count,
                    directoryScanMutation.data.batch_assessment
                      .conflicting_event_identity_count,
                    directoryScanMutation.data.batch_assessment
                      .source_without_financial_events_count,
                  )}
                </p>
                <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
                  {text.citicBatchQueryWindowProgress(
                    directoryScanMutation.data.query_window_review_summary
                      .reviewed_source_count,
                    directoryScanMutation.data.preview_count,
                  )}
                </p>
                <div
                  className="mt-3 border-t border-[var(--app-border)] pt-3"
                  data-testid="citic-query-window-batch-assessment"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-[var(--app-text)]">
                      {text.citicQueryWindowBatchTitle}
                    </div>
                    <StatusBadge
                      tone={
                        directoryScanMutation.data.query_window_batch_assessment
                          .integrity_status === 'clear'
                          ? 'info'
                          : directoryScanMutation.data
                                .query_window_batch_assessment
                                .integrity_status === 'partial'
                            ? 'warning'
                            : directoryScanMutation.data
                                  .query_window_batch_assessment
                                  .integrity_status === 'blocked'
                              ? 'danger'
                              : 'neutral'
                      }
                    >
                      {directoryScanMutation.data.query_window_batch_assessment
                        .integrity_status === 'clear'
                        ? text.citicQueryWindowBatchClear
                        : directoryScanMutation.data
                              .query_window_batch_assessment
                              .integrity_status === 'partial'
                          ? text.citicQueryWindowBatchPartial
                          : directoryScanMutation.data
                                .query_window_batch_assessment
                                .integrity_status === 'blocked'
                            ? text.citicQueryWindowBatchBlocked
                            : text.citicQueryWindowBatchUnavailable}
                    </StatusBadge>
                  </div>
                  <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
                    {text.citicQueryWindowBatchSummary(
                      directoryScanMutation.data.query_window_batch_assessment
                        .declared_window_start_date,
                      directoryScanMutation.data.query_window_batch_assessment
                        .declared_window_end_date,
                      directoryScanMutation.data.query_window_batch_assessment
                        .covered_calendar_day_count,
                      directoryScanMutation.data.query_window_batch_assessment
                        .gap_calendar_day_count,
                      directoryScanMutation.data.query_window_batch_assessment
                        .overlap_calendar_day_count,
                    )}
                  </p>
                  <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {text.citicQueryWindowBatchBoundary}
                  </p>
                </div>
                <div
                  className="mt-3 border-t border-[var(--app-border)] pt-3"
                  data-testid="citic-source-scope-batch-assessment"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-[var(--app-text)]">
                      {text.citicSourceScopeBatchTitle}
                    </div>
                    <StatusBadge
                      tone={
                        directoryScanMutation.data.source_scope_batch_assessment
                          .integrity_status === 'clear'
                          ? 'info'
                          : directoryScanMutation.data
                                .source_scope_batch_assessment
                                .integrity_status === 'partial'
                            ? 'warning'
                            : directoryScanMutation.data
                                  .source_scope_batch_assessment
                                  .integrity_status === 'blocked'
                              ? 'danger'
                              : 'neutral'
                      }
                    >
                      {directoryScanMutation.data.source_scope_batch_assessment
                        .integrity_status === 'clear'
                        ? text.citicSourceScopeBatchClear
                        : directoryScanMutation.data
                              .source_scope_batch_assessment
                              .integrity_status === 'partial'
                          ? text.citicSourceScopeBatchPartial
                          : directoryScanMutation.data
                                .source_scope_batch_assessment
                                .integrity_status === 'blocked'
                            ? text.citicSourceScopeBatchBlocked
                            : text.citicSourceScopeBatchUnavailable}
                    </StatusBadge>
                  </div>
                  <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
                    {text.citicSourceScopeBatchSummary(
                      directoryScanMutation.data.source_scope_batch_assessment
                        .reviewed_source_count,
                      directoryScanMutation.data.source_scope_batch_assessment
                        .source_count,
                      directoryScanMutation.data.source_scope_batch_assessment
                        .account_binding_consistent,
                      directoryScanMutation.data.source_scope_batch_assessment
                        .declared_scope_consistent,
                    )}
                  </p>
                  <p className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
                    {text.citicSourceScopeBatchDeclared(
                      directoryScanMutation.data.source_scope_batch_assessment
                        .declared_account_type,
                      directoryScanMutation.data.source_scope_batch_assessment.declared_market_scopes.join(
                        ', ',
                      ),
                      directoryScanMutation.data.source_scope_batch_assessment.declared_asset_classes.join(
                        ', ',
                      ),
                      directoryScanMutation.data.source_scope_batch_assessment
                        .declared_account_value_band,
                      directoryScanMutation.data.source_scope_batch_assessment.declared_business_types.join(
                        ', ',
                      ),
                    )}
                  </p>
                  <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {text.citicSourceScopeBatchBoundary}
                  </p>
                </div>
                <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
                  {text.citicBatchCoverageBoundary}
                </p>
                <div
                  className="mt-3 border-t border-[var(--app-border)] pt-3"
                  data-testid="citic-canonical-lineage-assessment"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-semibold text-[var(--app-text)]">
                      {text.citicCanonicalLineageTitle}
                    </div>
                    <StatusBadge
                      tone={statusTone(
                        directoryScanMutation.data.canonical_lineage_assessment
                          .event_lineage_status === 'exact'
                          ? 'pass'
                          : 'blocked',
                      )}
                    >
                      {directoryScanMutation.data.canonical_lineage_assessment
                        .event_lineage_status === 'exact'
                        ? text.citicCanonicalLineageExact
                        : directoryScanMutation.data
                              .canonical_lineage_assessment
                              .event_lineage_status === 'partial'
                          ? text.citicCanonicalLineagePartial
                          : text.citicCanonicalLineageUnavailable}
                    </StatusBadge>
                  </div>
                  <p className="app-type-micro mt-2 text-[var(--app-text-secondary)]">
                    {text.citicCanonicalLineageSummary(
                      directoryScanMutation.data.canonical_lineage_assessment
                        .semantically_matched_event_count,
                      directoryScanMutation.data.canonical_lineage_assessment
                        .source_supported_event_count,
                      directoryScanMutation.data.canonical_lineage_assessment
                        .exact_event_identity_matched_event_count,
                      directoryScanMutation.data.canonical_lineage_assessment
                        .broker_order_identity_matched_event_count,
                      directoryScanMutation.data.canonical_lineage_assessment
                        .source_events_with_broker_order_identity_count,
                      directoryScanMutation.data.canonical_lineage_assessment
                        .canonical_unmatched_event_count,
                    )}
                  </p>
                  <div
                    className="app-type-micro mt-1 grid gap-1 text-[var(--app-text-secondary)]"
                    data-testid="citic-canonical-lineage-type-diagnostics"
                  >
                    <p>
                      {text.citicCanonicalLineageObservedTypes(
                        formatCiticEventTypeCounts(
                          directoryScanMutation.data
                            .canonical_lineage_assessment
                            .source_event_type_counts,
                          locale,
                        ),
                        formatCiticEventTypeCounts(
                          directoryScanMutation.data
                            .canonical_lineage_assessment
                            .canonical_event_type_counts,
                          locale,
                        ),
                      )}
                    </p>
                    <p>
                      {text.citicCanonicalLineageMismatchTypes(
                        formatCiticEventTypeCounts(
                          directoryScanMutation.data
                            .canonical_lineage_assessment
                            .semantically_matched_event_type_counts,
                          locale,
                        ),
                        formatCiticEventTypeCounts(
                          directoryScanMutation.data
                            .canonical_lineage_assessment
                            .source_unmatched_event_type_counts,
                          locale,
                        ),
                        formatCiticEventTypeCounts(
                          directoryScanMutation.data
                            .canonical_lineage_assessment
                            .canonical_unmatched_event_type_counts,
                          locale,
                        ),
                      )}
                    </p>
                    <p>
                      {text.citicCanonicalLineageIdentityPresence(
                        directoryScanMutation.data.canonical_lineage_assessment
                          .source_events_with_broker_order_identity_count,
                        directoryScanMutation.data.canonical_lineage_assessment
                          .canonical_events_with_broker_order_identity_count,
                      )}
                    </p>
                  </div>
                  <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {text.citicCanonicalLineageBoundary}
                  </p>
                </div>
              </div>
            </>
          ) : null}
        </div>
        <label className="mt-4 grid gap-1 text-xs font-semibold text-[var(--app-text-secondary)]">
          {text.citicChooseFile}
          <input
            accept=".xls,application/vnd.ms-excel"
            className="min-h-10 w-full rounded-[var(--app-radius-control)] border border-dashed border-[var(--app-border)] bg-[var(--app-surface)] px-3 py-2 text-sm text-[var(--app-text-secondary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
            disabled={scanPending || intakePending}
            multiple
            ref={fileInputRef}
            type="file"
            onChange={handleFileChange}
          />
        </label>
        {selectedFiles.length > 0 ? (
          <div className="mt-2 text-xs text-[var(--app-text-secondary)]">
            <div className="font-semibold">
              {text.citicSelectedFiles(selectedFiles.length)}
            </div>
            <ul
              className="mt-1 grid gap-0.5"
              data-testid="citic-selected-files"
            >
              {selectedFiles.map((file, index) => (
                <li key={`${index}-${file.name}-${file.size}`}>{file.name}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <button
          className="app-button-secondary mt-4 min-h-10 rounded-[var(--app-radius-control)] px-4 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={selectedFiles.length === 0 || scanPending || intakePending}
          type="button"
          onClick={previewStatements}
        >
          {text.citicPreviewAction}
        </button>
        {fileMessage ? (
          <EvidenceState className="mt-3" kind="partial" title={fileMessage} />
        ) : null}
        {batchResults.length > 0 ? (
          <>
            <CiticHistoryXlsPreviewPanel
              intakePending={intakePending}
              locale={locale}
              reviewIntent={reviewIntent}
              results={batchResults}
              onCancelReview={() => setReviewIntent(null)}
              onConfirmReview={confirmSourceReview}
              onStartReview={startSourceReview}
              onUpdateReviewIntent={updateReviewIntent}
            />
            <p className="app-type-micro mt-3 text-[var(--app-text-tertiary)]">
              {batchResults.some(
                (result) => result.sourceKind === 'configured_directory',
              )
                ? text.citicDirectoryRetainedBoundary
                : text.citicRetainedFileBoundary}
            </p>
            <button
              className="app-button-ghost mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
              disabled={scanPending || intakePending}
              type="button"
              onClick={clearLocalBatch}
            >
              {text.citicClearBatch}
            </button>
          </>
        ) : null}
        <CiticSourceIntakeHistory
          intakes={intakesQuery.data ?? []}
          isError={intakesQuery.isError}
          isPending={intakesQuery.isPending}
          locale={locale}
          revokePending={
            queryWindowRevokeMutation.isPending ||
            sourceScopeRevokeMutation.isPending
          }
          onRevokeQueryWindow={revokeQueryWindowReview}
        />
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
      <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
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
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
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

function CiticHistoryXlsPreviewPanel({
  intakePending,
  locale,
  reviewIntent,
  results,
  onCancelReview,
  onConfirmReview,
  onStartReview,
  onUpdateReviewIntent,
}: {
  intakePending: boolean;
  locale: 'en' | 'zh';
  reviewIntent: CiticSourceReviewIntent | null;
  results: CiticHistoryXlsPreviewResult[];
  onCancelReview: () => void;
  onConfirmReview: () => void;
  onStartReview: (
    resultId: string,
    reviewStatus: CiticSourceReviewStatus,
  ) => void;
  onUpdateReviewIntent: (
    updates: Partial<
      Omit<CiticSourceReviewIntent, 'resultId' | 'reviewStatus'>
    >,
  ) => void;
}) {
  const text = labels[locale];
  const seenFingerprints = new Set<string>();
  const duplicateResultIds = new Set<string>();
  const uniquePreviews: CiticHistoryXlsPreview[] = [];
  for (const result of results) {
    if (!result.preview) {
      continue;
    }
    if (seenFingerprints.has(result.preview.file_fingerprint)) {
      duplicateResultIds.add(result.id);
      continue;
    }
    seenFingerprints.add(result.preview.file_fingerprint);
    uniquePreviews.push(result.preview);
  }
  const completedCount = results.filter(
    (result) => result.status !== 'pending',
  ).length;
  const failedCount = results.filter(
    (result) => result.status === 'error',
  ).length;
  const isPending = completedCount < results.length;
  const totals = uniquePreviews.reduce(
    (current, preview) => ({
      validRows: current.validRows + preview.valid_row_count,
      invalidRows: current.invalidRows + preview.invalid_row_count,
      recognizedEvents: current.recognizedEvents + preview.total_event_count,
      nonFinancialActivities:
        current.nonFinancialActivities +
        preview.recognized_non_financial_activity_count,
    }),
    {
      validRows: 0,
      invalidRows: 0,
      recognizedEvents: 0,
      nonFinancialActivities: 0,
    },
  );
  const brokerSoakCandidate = uniquePreviews[0]?.broker_soak_candidate ?? null;

  return (
    <div className="mt-4 border-y border-[var(--app-divider)] py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {isPending
            ? text.citicPreviewProgress(completedCount, results.length)
            : text.citicPreviewComplete}
        </div>
        <StatusBadge tone={statusTone(isPending ? 'checking' : 'blocked')}>
          {formatCode(isPending ? 'checking' : 'blocked', locale, 'status')}
        </StatusBadge>
      </div>
      <div className="mt-3 grid grid-cols-2 divide-x divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] sm:grid-cols-4 sm:divide-y-0">
        <Metric label={text.citicFiles} value={String(results.length)} />
        <Metric label={text.validRows} value={String(totals.validRows)} />
        <Metric label={text.invalidRows} value={String(totals.invalidRows)} />
        <Metric
          label={text.citicRecognizedEvents}
          value={String(totals.recognizedEvents)}
        />
      </div>
      <div
        className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
        data-testid="citic-preview-results"
      >
        {results.map((result) => {
          const isDuplicate = duplicateResultIds.has(result.id);
          const sourceIsOwnerIdentifiable =
            result.sourceKind === 'browser_file' ||
            Boolean(result.localNameMonthHint);
          const blockingErrors =
            result.preview?.errors.filter(
              (error) =>
                error.code !==
                'citic_history_xls_non_financial_activity_ignored',
            ) ?? [];
          const statusLabel =
            result.status === 'pending'
              ? formatCode('checking', locale, 'status')
              : result.status === 'error'
                ? result.errorKind === 'read'
                  ? text.citicReadFailed
                  : text.citicFilePreviewFailed
                : isDuplicate
                  ? text.citicDuplicateFile
                  : text.citicFilePreviewComplete;
          return (
            <div
              className="grid min-w-0 gap-1 px-3 py-2.5 text-xs sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-3"
              data-testid={`citic-preview-result-${result.id}`}
              key={result.id}
            >
              <div className="min-w-0">
                <div className="truncate font-semibold text-[var(--app-text)]">
                  {result.localFileName}
                </div>
                {result.preview ? (
                  <div className="app-type-micro mt-1 break-all font-mono text-[var(--app-text-tertiary)]">
                    SHA-256 {result.preview.file_fingerprint}
                  </div>
                ) : null}
                {result.sourceKind === 'configured_directory' &&
                result.localNameMonthHint ? (
                  <div className="app-type-micro mt-1 text-[var(--app-text-secondary)]">
                    {text.citicLocalNameMonthHint(result.localNameMonthHint)} ·{' '}
                    {text.citicLocalNameMonthHintBoundary}
                  </div>
                ) : null}
              </div>
              <StatusBadge
                tone={statusTone(
                  result.status === 'pending'
                    ? 'checking'
                    : result.status === 'error'
                      ? 'error'
                      : 'blocked',
                )}
              >
                {statusLabel}
              </StatusBadge>
              {result.preview ? (
                <div className="sm:col-span-2">
                  <div className="app-type-micro flex flex-wrap gap-x-3 gap-y-1 text-[var(--app-text-secondary)]">
                    <span>
                      {text.validRows}: {result.preview.valid_row_count}
                    </span>
                    <span>
                      {text.invalidRows}: {result.preview.invalid_row_count}
                    </span>
                    <span>
                      {text.citicRecognizedEvents}:{' '}
                      {result.preview.total_event_count}
                    </span>
                    {result.preview.recognized_non_financial_activity_count >
                    0 ? (
                      <span>
                        {text.citicRecognizedNonFinancialActivities}:{' '}
                        {result.preview.recognized_non_financial_activity_count}
                      </span>
                    ) : null}
                  </div>
                  {blockingErrors.length > 0 ? (
                    <div className="app-type-micro mt-1 flex flex-wrap gap-1.5 text-[var(--app-danger-text)]">
                      {blockingErrors.slice(0, 3).map((error) => (
                        <span
                          key={`${error.row_number ?? 'file'}-${error.code}`}
                        >
                          {error.row_number ? `#${error.row_number} ` : ''}
                          {formatCode(error.code, locale, 'code')}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {!isDuplicate && !sourceIsOwnerIdentifiable ? (
                    <EvidenceState
                      className="mt-2"
                      kind="partial"
                      title={text.citicConfiguredSourceUnidentified}
                    />
                  ) : null}
                  {!isDuplicate &&
                  sourceIsOwnerIdentifiable &&
                  result.intakeState === 'idle' ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {result.preview.recordable_for_follow_up ? (
                        <button
                          className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={intakePending}
                          type="button"
                          onClick={() =>
                            onStartReview(result.id, 'follow_up_required')
                          }
                        >
                          {text.citicReviewFollowUp}
                        </button>
                      ) : null}
                      <button
                        className="app-button-ghost min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={intakePending}
                        type="button"
                        onClick={() => onStartReview(result.id, 'rejected')}
                      >
                        {text.citicRejectSource}
                      </button>
                    </div>
                  ) : null}
                  {reviewIntent?.resultId === result.id ? (
                    <ControlledActionZone
                      className="mt-3"
                      description={
                        reviewIntent.reviewStatus === 'follow_up_required'
                          ? text.citicConfirmFollowUpBody
                          : text.citicConfirmRejectBody
                      }
                      evidence={`SHA-256 ${result.preview.file_fingerprint}`}
                      layout="stack"
                      title={text.citicConfirmReview}
                      tone={
                        reviewIntent.reviewStatus === 'rejected'
                          ? 'danger'
                          : 'info'
                      }
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
                                  queryWindowAttested:
                                    event.currentTarget.checked,
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
                                  noOtherFiltersAttested:
                                    event.currentTarget.checked,
                                })
                              }
                            />
                            <span>
                              {text.citicSourceScopeNoOtherFiltersAttestation}
                            </span>
                          </label>
                          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
                            <input
                              checked={
                                reviewIntent.completeReturnedResultsAttested
                              }
                              className="mt-0.5 h-4 w-4"
                              type="checkbox"
                              onChange={(event) =>
                                onUpdateReviewIntent({
                                  completeReturnedResultsAttested:
                                    event.currentTarget.checked,
                                })
                              }
                            />
                            <span>
                              {text.citicSourceScopeCompleteResultsAttestation}
                            </span>
                          </label>
                          <label className="flex items-start gap-2 text-xs text-[var(--app-text-secondary)] sm:col-span-2">
                            <input
                              checked={reviewIntent.sourceScopeAttested}
                              className="mt-0.5 h-4 w-4"
                              type="checkbox"
                              onChange={(event) =>
                                onUpdateReviewIntent({
                                  sourceScopeAttested:
                                    event.currentTarget.checked,
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
                            (reviewIntent.reviewStatus ===
                              'follow_up_required' &&
                              (!reviewIntent.queryStartDate ||
                                !reviewIntent.queryEndDate ||
                                !reviewIntent.queryWindowAttested ||
                                !reviewIntent.accountAlias.trim() ||
                                !reviewIntent.accountIdentifier.trim() ||
                                !reviewIntent.accountType.trim() ||
                                parseCiticSourceScopeCodes(
                                  reviewIntent.marketScopes,
                                ).length === 0 ||
                                parseCiticSourceScopeCodes(
                                  reviewIntent.assetClasses,
                                ).length === 0 ||
                                !reviewIntent.accountValueBand.trim() ||
                                parseCiticSourceScopeCodes(
                                  reviewIntent.businessTypes,
                                ).length === 0 ||
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
                  ) : null}
                  {result.intakeState === 'saved' && result.intake ? (
                    <EvidenceState
                      className="mt-2"
                      kind={
                        result.intake.review_status === 'rejected'
                          ? 'stale'
                          : 'partial'
                      }
                      title={
                        result.intake.review_status === 'rejected'
                          ? text.citicRejectionSaved
                          : result.sourceScopeState === 'saved'
                            ? text.citicSourceScopeSaved
                            : result.queryWindowState === 'saved'
                              ? text.citicQueryWindowSaved
                              : text.citicIntakeSaved
                      }
                      description={
                        result.sourceScopeState === 'saved' &&
                        result.sourceScopeReview
                          ? `${result.sourceScopeReview.account_alias} · ${result.sourceScopeReview.account_type} · ${result.sourceScopeReview.market_scopes.join(', ')} · ${result.sourceScopeReview.asset_classes.join(', ')} · ${result.sourceScopeReview.account_value_band || 'unverified'} · ${text.citicQueryWindowStillBlocked}`
                          : result.queryWindowState === 'saved' &&
                              result.queryWindowReview
                            ? `${result.queryWindowReview.query_start_date} — ${result.queryWindowReview.query_end_date} · ${text.citicQueryWindowStillBlocked}`
                            : result.intake.intake_id
                      }
                    />
                  ) : null}
                  {result.intakeState === 'saved' &&
                  result.intake?.review_status === 'follow_up_required' &&
                  (result.queryWindowState !== 'saved' ||
                    result.sourceScopeState !== 'saved') &&
                  sourceIsOwnerIdentifiable &&
                  reviewIntent?.resultId !== result.id ? (
                    <button
                      className="app-button-secondary mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={intakePending}
                      type="button"
                      onClick={() =>
                        onStartReview(result.id, 'follow_up_required')
                      }
                    >
                      {result.queryWindowState === 'saved'
                        ? text.citicReviewSourceScope
                        : text.citicReviewQueryWindow}
                    </button>
                  ) : null}
                  {result.queryWindowState === 'error' ? (
                    <EvidenceState
                      className="mt-2"
                      kind="error"
                      title={text.citicQueryWindowFailed}
                      description={text.citicIntakeStillSaved}
                    />
                  ) : null}
                  {result.sourceScopeState === 'error' ? (
                    <EvidenceState
                      className="mt-2"
                      kind="error"
                      title={text.citicSourceScopeFailed}
                      description={text.citicQueryWindowStillBlocked}
                    />
                  ) : null}
                  {result.intakeState === 'error' ? (
                    <EvidenceState
                      className="mt-2"
                      kind="error"
                      title={text.citicIntakeFailed}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      {!isPending && failedCount > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="error"
          title={`${text.citicPreviewFailed}: ${text.citicFailedFileCount(failedCount)}`}
        />
      ) : null}
      {!isPending && totals.invalidRows > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.citicInvalidRows(totals.invalidRows)}
        />
      ) : null}
      {!isPending && totals.nonFinancialActivities > 0 ? (
        <EvidenceState
          className="mt-3"
          kind="partial"
          title={text.citicNonFinancialActivityNotice(
            totals.nonFinancialActivities,
          )}
        />
      ) : null}
      {!isPending ? (
        <>
          <EvidenceState
            className="mt-3"
            kind="partial"
            statusLabel={formatCode('blocked', locale, 'status')}
            title={text.citicEvidenceBlocked}
            description={
              <>
                <p>{text.citicEvidenceBlockedBody}</p>
                <div className="app-type-overline mt-3 text-[var(--app-text-tertiary)]">
                  {text.citicNextStepTitle}
                </div>
                <ol className="mt-2 grid gap-1.5">
                  {text.citicNextSteps.map((step, index) => (
                    <li
                      key={step}
                      className="grid grid-cols-[auto_minmax(0,1fr)] gap-2"
                    >
                      <span className="font-semibold tabular-nums">
                        {index + 1}.
                      </span>
                      <span>{step}</span>
                    </li>
                  ))}
                </ol>
              </>
            }
            evidence={`${uniquePreviews.length} unique SHA-256 fingerprints`}
          />
          {brokerSoakCandidate ? (
            <EvidenceState
              className="mt-3"
              kind="partial"
              statusLabel={formatCode('blocked', locale, 'status')}
              title={text.citicSoakBlocked}
              description={
                <>
                  <p>{text.citicSoakBlockedBody}</p>
                  <details className="mt-2 border-y border-[var(--app-divider)] py-2">
                    <summary className="cursor-pointer text-xs font-semibold text-[var(--app-text-secondary)]">
                      {text.citicSoakRequiredEvidence}
                    </summary>
                    <ul className="mt-2 grid gap-1 text-xs text-[var(--app-text-secondary)] sm:grid-cols-2">
                      {brokerSoakCandidate.required_source_evidence.map(
                        (evidenceCode) => (
                          <li key={evidenceCode}>
                            {formatCode(evidenceCode, locale, 'code')}
                          </li>
                        ),
                      )}
                    </ul>
                  </details>
                  <p className="app-type-micro mt-2 text-[var(--app-text-tertiary)]">
                    {text.citicSoakProhibited}
                  </p>
                </>
              }
              evidence={brokerSoakCandidate.assessment_fingerprint}
            />
          ) : null}
          <p className="app-type-micro mt-3 text-[var(--app-text-tertiary)]">
            {text.citicPrivacyResponse}
          </p>
        </>
      ) : null}
    </div>
  );
}

function CiticSourceIntakeHistory({
  intakes,
  isError,
  isPending,
  locale,
  onRevokeQueryWindow,
  revokePending,
}: {
  intakes: CiticSourceIntake[];
  isError: boolean;
  isPending: boolean;
  locale: 'en' | 'zh';
  onRevokeQueryWindow: (intake: CiticSourceIntake) => Promise<void>;
  revokePending: boolean;
}) {
  const text = labels[locale];
  const [revokeIntentId, setRevokeIntentId] = useState<string | null>(null);
  if (isPending) {
    return (
      <EvidenceState className="mt-4" kind="loading" title={text.loading} />
    );
  }
  if (isError) {
    return (
      <EvidenceState
        className="mt-4"
        kind="error"
        title={text.citicIntakeFailed}
      />
    );
  }
  return (
    <details className="mt-4 border-y border-[var(--app-divider)] py-3">
      <summary className="app-button-ghost flex min-h-10 cursor-pointer items-center justify-between rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold text-[var(--app-text-secondary)]">
        <span>{text.citicIntakeHistory}</span>
        <span className="tabular-nums">{intakes.length}</span>
      </summary>
      {intakes.length === 0 ? (
        <p className="mt-2 px-2.5 text-xs text-[var(--app-text-secondary)]">
          {text.citicNoIntakes}
        </p>
      ) : (
        <div className="mt-2 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
          {intakes.map((intake) => (
            <div
              className="grid gap-1 px-3 py-2.5 text-xs"
              key={intake.intake_id}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="font-semibold text-[var(--app-text)]">
                  {intake.review_status === 'rejected'
                    ? text.citicRejectionSaved
                    : text.citicIntakeSaved}
                </span>
                <StatusBadge
                  tone={
                    intake.review_status === 'rejected' ? 'danger' : 'warning'
                  }
                >
                  {formatCode(intake.review_status, locale, 'status')}
                </StatusBadge>
              </div>
              <div className="app-type-micro break-all font-mono text-[var(--app-text-tertiary)]">
                SHA-256 {intake.file_fingerprint}
              </div>
              <div className="app-type-micro text-[var(--app-text-secondary)]">
                {text.validRows}: {intake.valid_row_count} · {text.invalidRows}:{' '}
                {intake.invalid_row_count} · {text.citicRecognizedEvents}:{' '}
                {intake.recognized_event_count}
                {intake.recognized_non_financial_activity_count > 0
                  ? ` · ${text.citicRecognizedNonFinancialActivities}: ${intake.recognized_non_financial_activity_count}`
                  : ''}
              </div>
              {intake.query_window_review ? (
                <div className="mt-1 border-t border-[var(--app-divider)] pt-2">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="app-type-micro text-[var(--app-text-secondary)]">
                      {text.citicQueryWindowLabel}:{' '}
                      {intake.query_window_review.query_start_date} —{' '}
                      {intake.query_window_review.query_end_date}
                    </div>
                    <StatusBadge
                      tone={
                        intake.query_window_review.effective_status === 'active'
                          ? 'info'
                          : 'neutral'
                      }
                    >
                      {intake.query_window_review.effective_status === 'active'
                        ? text.citicQueryWindowActive
                        : text.citicQueryWindowRevoked}
                    </StatusBadge>
                  </div>
                  {intake.source_scope_review ? (
                    <div className="mt-2 flex flex-wrap items-start justify-between gap-2 border-t border-[var(--app-divider)] pt-2">
                      <div className="app-type-micro text-[var(--app-text-secondary)]">
                        {text.citicSourceScopeLabel}:{' '}
                        {intake.source_scope_review.account_alias} ·{' '}
                        {intake.source_scope_review.account_type} ·{' '}
                        {intake.source_scope_review.market_scopes.join(', ')} ·{' '}
                        {intake.source_scope_review.asset_classes.join(', ')} ·{' '}
                        {intake.source_scope_review.account_value_band ||
                          'unverified'}
                      </div>
                      <StatusBadge
                        tone={
                          intake.source_scope_review.effective_status ===
                          'active'
                            ? 'info'
                            : 'neutral'
                        }
                      >
                        {intake.source_scope_review.effective_status ===
                        'active'
                          ? text.citicQueryWindowActive
                          : text.citicQueryWindowRevoked}
                      </StatusBadge>
                    </div>
                  ) : null}
                  <p className="app-type-micro mt-1 text-[var(--app-text-tertiary)]">
                    {text.citicQueryWindowStillBlocked}
                  </p>
                  {intake.query_window_review.effective_status === 'active' &&
                  revokeIntentId !== intake.intake_id ? (
                    <button
                      className="app-button-ghost mt-2 min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={revokePending}
                      type="button"
                      onClick={() => setRevokeIntentId(intake.intake_id)}
                    >
                      {text.citicQueryWindowRevoke}
                    </button>
                  ) : null}
                  {revokeIntentId === intake.intake_id ? (
                    <ControlledActionZone
                      className="mt-2"
                      description={text.citicQueryWindowRevokeBody}
                      evidence={intake.query_window_review.review_fingerprint}
                      layout="stack"
                      title={text.citicQueryWindowRevokeConfirm}
                      tone="danger"
                    >
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={revokePending}
                          type="button"
                          onClick={async () => {
                            await onRevokeQueryWindow(intake);
                            setRevokeIntentId(null);
                          }}
                        >
                          {revokePending
                            ? text.citicQueryWindowRevoking
                            : text.citicQueryWindowRevokeConfirmAction}
                        </button>
                        <button
                          className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={revokePending}
                          type="button"
                          onClick={() => setRevokeIntentId(null)}
                        >
                          {text.citicCancelAction}
                        </button>
                      </div>
                    </ControlledActionZone>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="app-type-micro truncate font-medium text-[var(--app-text-secondary)]">
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
        <div className="app-type-overline text-[var(--app-text-tertiary)]">
          {text.workflowTitle}
        </div>
        <ol className="mt-2 grid gap-2 text-xs font-medium text-[var(--app-text-secondary)]">
          {text.workflowSteps.map((step, index) => (
            <li
              key={step}
              className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2"
            >
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-[var(--app-radius-control)] border border-[var(--app-accent-border)] text-[length:var(--app-font-size-micro)] font-semibold text-[var(--app-accent)]">
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
      <div className="app-type-overline text-[var(--app-muted)]">{title}</div>
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
              <dt className="app-type-overline text-[var(--app-text-tertiary)]">
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
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
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
