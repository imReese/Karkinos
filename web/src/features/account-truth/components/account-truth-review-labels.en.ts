export const accountTruthReviewLabelsEn = {
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
  scopeReviewComplete: 'Reviewed scope is bound to the exact persisted import.',
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
} as const;
