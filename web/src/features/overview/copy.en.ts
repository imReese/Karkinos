export const overviewCopyEn = {
  kicker: 'Overview',
  title: 'Portfolio overview',
  subtitle:
    'Start with account facts, then review performance, holdings, risk, and research.',
  modeHelper:
    'Account view focuses on capital structure. Strategy view focuses on return quality.',
  loading: 'Loading account facts and current holdings.',
  error: 'Failed to load account overview or holdings.',
  curveLoading: 'Loading equity curve.',
  curveError: 'Failed to load equity curve.',
  curveSnapshotPending:
    'Valuation inputs changed, but their immutable snapshot is still publishing. Unbound financial reads remain blocked; retry shortly.',
  curveRefreshError:
    'Refresh failed. The last published, identity-bound equity curve remains visible while retry is available.',
  empty: 'No account data available yet.',
  cards: {
    totalAssets: 'Total Assets',
    availableCash: 'Available Cash',
    todayPnl: 'Today PnL',
    latestTradingDayPnl: 'Latest trading-day PnL',
    marketClosedPnlContext:
      'Market is closed today; showing the latest available PnL.',
    todayStocks: 'Stocks',
    todayFunds: 'Funds',
    todayTotal: 'Total',
    todayContributors: 'Top contributors',
    exposureSummary: 'Portfolio exposure',
    stockExposure: 'Stock value',
    fundExposure: 'Fund value',
    cashExposure: 'Cash',
    largestHolding: 'Largest holding',
    largestHoldingUnavailable: 'No open holding exposure.',
    exposureUnavailable:
      'Portfolio exposure is unavailable because total equity is zero or missing.',
    exposurePartial: 'Partial valuation',
    cumulativePnl: 'Cumulative P&L',
    cumulativeReturn: 'Cumulative Return',
    netDeposits: 'Net Deposits',
    unrealizedPnl: 'Unrealized PnL',
    cashRatio: 'Cash Ratio',
    currentDrawdown: 'Current Drawdown',
    drawdownBasis: 'Adjusted for deposits and withdrawals',
    drawdownUnavailable: 'Drawdown evidence incomplete',
    drawdownHistoricalCorrection:
      'Historical correction performance basis is unverified',
    positionsCount: 'Active Positions',
    cachedValuation: 'Cached quotes · valuation time',
    valuationStatus: (status: string) => `Valuation status: ${status}`,
    evidenceReady: 'Evidence complete',
    supportingMetrics: 'Supporting account metrics',
    evidenceIdentity: (asOf: string) => `Valuation as of ${asOf}`,
  },
  dashboard: {
    equityPanel: 'Portfolio value',
    dataTrust: 'Data trust / system status',
    valuationCoverage: 'Valuation coverage',
    valuationCoverageDetail:
      'Authoritative total equity and P&L require evidence-gated valuation coverage across every current holding.',
    valuationCoverageAssetClasses: {
      stock: 'Stocks',
      fund: 'Funds',
      etf: 'ETFs',
      other: 'Other',
    },
    valuationCoverageReview: (count: number) =>
      `${count} holding${count === 1 ? '' : 's'} need evidence`,
    valuationCoverageComplete: 'Valuation complete for this asset class',
    opsPanel: 'Review queue',
    dailyWorkbench: "Today's to-dos",
    todayToReview: 'Today to review',
    additionalReviewItems: (count: number) =>
      count === 1 ? '1 more review item' : `${count} more review items`,
    noActionItems: 'No items need your attention today.',
    noActionItemsDetail:
      'Market data, approvals, and strategy evidence do not need immediate action.',
    operationsTower: 'Execution status',
    operationsConclusion: 'Today status',
    operationsNoManualAction: 'No manual trading action needed today',
    operationsPendingManual: (count: number) =>
      count === 1
        ? '1 item needs manual confirmation'
        : `${count} items need manual confirmation`,
    operationsPlanIntentsReady: (count: number) =>
      count === 1
        ? '1 plan intent needs decision review'
        : `${count} plan intents need decision review`,
    operationsRiskBlocked: (count: number) =>
      count === 1
        ? '1 risk block needs review'
        : `${count} risk blocks need review`,
    operationsAccountTruthBlocked:
      'Account truth is blocked; pause execution review',
    operationsDataUnavailable:
      'Market data is unavailable; pause candidate review',
    operationsExecutionException: (count: number) =>
      `${count} execution exception${count === 1 ? '' : 's'} need review`,
    operationsCandidatePool: 'Candidate pool',
    operationsEvidencePassed: 'Evidence passed',
    operationsRiskPassed: 'Risk passed',
    operationsManualReady: 'Plan intents to review',
    operationsPendingOrders: 'Pending order intents',
    operationsExecutionRecords: 'Execution records',
    operationsLedgerReview: 'Ledger review',
    operationsDefaultMode: 'Default mode',
    operationsBrokerBridge: 'Broker bridge',
    operationsManualConfirmation: 'Manual confirmation',
    operationsBrokerDisabled: 'Disabled',
    operationsViewCandidates: 'Review decision plan',
    operationsViewRisk: 'View risk reasons',
    operationsViewTrading: 'Enter manual confirmation',
    operationsViewLedger: 'Review ledger',
    operationsViewAccountTruth: 'Review account truth',
    operationsViewMarket: 'Review market data',
    operationsViewPaperShadow: 'Review simulation evidence',
    queuePriorityFirst: 'Handle first',
    queuePriorityWatch: 'Watch today',
    queuePriorityNormal: 'Normal status',
    resolutionCondition: (condition: string) =>
      `Clears when: ${condition}. Viewing or acknowledging alone does not clear it.`,
    dataResolutionCondition:
      'Newer confirmed quote or NAV evidence covers every current holding and shares one valuation and activity scope.',
    quoteResolutionCondition:
      'Run explicit quote ingestion for the listed symbols and replace each blocker with newer confirmed quote evidence.',
    confirmedFundNavResolutionCondition:
      'The target-date confirmed fund NAV is published and recorded through Sync confirmed NAV. Ordinary quote refresh and intraday estimates cannot clear it.',
    mixedDataResolutionCondition:
      'Complete explicit quote ingestion for ordinary quote blockers and record target-date confirmed fund NAV, then rebuild the full-account authoritative valuation.',
    strategyNoLinkedFillsResolution:
      'No action required: contribution appears only after a reconciled fill is explicitly linked to strategy evidence.',
    strategyEvidenceResolution:
      'The signal, review, order, fill, activity record, and valuation references form one auditable evidence chain.',
    dataUsable: 'Market data and NAV are usable.',
    dataNeedsReview: 'Market data or NAV needs review.',
    stockDataNeedsReview: 'Stock quote evidence needs review.',
    mixedAssetDataNeedsReview:
      'Stock quotes and confirmed fund NAV need separate review.',
    confirmedFundNavNeedsReview:
      'Confirmed fund NAV is pending; stock research that does not depend on account equity may continue.',
    confirmedFundNavReviewDetail: (count: number) =>
      `${count} fund holding${count === 1 ? '' : 's'} still lack target-date confirmed NAV. This does not block stock research that does not depend on account equity, but full-account authoritative valuation and risk remain blocked and no order is authorized.`,
    dataReviewLoading: 'Loading the current-holding evidence review.',
    dataReviewUnavailable:
      'Current-holding evidence is unavailable; interpretation remains blocked.',
    dataReviewIdentityBlocked:
      'The account valuation or activity scope is incomplete; restore the evidence link first.',
    dataReviewConfirmedCount: (count: number) =>
      `${count} current holding${count === 1 ? '' : 's'} confirmed`,
    dataReviewSummary: (
      fundNav: number,
      stale: number,
      missing: number,
      estimated: number,
      unknown: number,
    ) =>
      [
        fundNav > 0 ? `${fundNav} fund NAV` : null,
        stale > 0 ? `${stale} stale/cache` : null,
        missing > 0 ? `${missing} missing/error` : null,
        estimated > 0 ? `${estimated} estimated` : null,
        unknown > 0 ? `${unknown} unknown status` : null,
      ]
        .filter(Boolean)
        .join(' · '),
    pendingOrdersReady: 'Orders awaiting manual confirmation',
    pendingOrdersClear: 'No orders awaiting confirmation',
    strategyCandidateAction: 'Strategy candidate signal',
    strategyCandidateClear: 'No strategy candidate signals',
    strategyCandidateLoading: 'Loading strategy candidate signals',
    strategyDecisionUnavailable: 'Strategy candidate signals are unavailable',
    strategyCandidateEmptyDetail:
      'No buy, sell, hold, or rebalance signals have entered the queue.',
    strategyRecommendationTitle: 'Latest strategy recommendation',
    strategyRecommendationQuantity: 'Est. qty',
    strategyRecommendationCurrentWeight: 'Current',
    strategyRecommendationTargetWeight: 'Target',
    strategyRecommendationBuy: 'Buy',
    strategyRecommendationSell: 'Sell',
    strategyRecommendationRebalance: 'Rebalance',
    strategyRecommendationReview: 'Manual review',
    strategyRecommendationReadOnly:
      'Read-only recommendation · manual confirmation required · no broker order is created or submitted',
    accountRecommendationUnavailableDetail:
      'Current evidence is not sufficient for a reviewable account recommendation. Complete the pending items before reassessing.',
    decisionBlockers: 'Needs attention',
    decisionBlocked: 'Needs review',
    decisionEvidence: 'Current status',
    decisionStrategyResearch: 'Research strategy',
    decisionStrategyNotReady: 'Research pending',
    decisionStrategyNextStep: 'Open evidence research',
    decisionTaskLabels: {
      data_refresh: 'Market data',
      account_truth: 'Account truth',
      risk_review: 'Risk review',
      strategy_evidence: 'Strategy evidence',
      paper_shadow_review: 'Paper/shadow review',
      manual_confirmation: 'Manual confirmation',
    },
    decisionReasonLabels: {
      promoted_strategy_not_configured:
        'No evidence-bound strategy is promoted to Paper Shadow',
      promoted_strategy_scan_missing:
        "A promoted strategy exists but today's scan is missing",
      decision_generation_time_not_bound_to_plan_date:
        'Decision generation is not bound to the plan date',
      plan_generation_time_not_bound_to_plan_date:
        'Trading-plan generation is not bound to the plan date',
      account_truth_promotion_status_not_clear:
        'Account-truth promotion status is not clear',
      account_truth_gate_not_pass: 'Account-truth gate did not pass',
      account_truth_not_fresh: 'Account truth is stale',
      account_truth_not_bound_to_plan_date:
        'Account truth is not bound to the current plan date',
      account_truth_age_exceeds_reviewed_limit:
        'Account truth exceeds the reviewed age limit',
      account_truth_too_old_for_decision:
        "Account truth is too old for today's decision",
      valuation_snapshot_not_complete:
        'Portfolio valuation snapshot is incomplete',
      market_data_not_trusted: 'Market evidence is not trusted',
      market_quote_too_old_for_decision:
        "Market quotes are too old for today's decision",
      account_qualification_not_evaluated:
        'Account qualification was not evaluated',
      market_data_not_fully_live: 'Market data is not fully refreshed',
      account_truth_snapshot_stale: 'Account-truth snapshot is stale',
      'account_truth_gate_not_pass:degraded':
        'Account truth is currently degraded',
    },
    decisionRequiredActionLabels: {
      refresh_or_confirm_market_data:
        'Refresh or confirm current market evidence',
      account_truth_snapshot_stale: 'Refresh the account-truth snapshot',
      'account_truth_gate_not_pass:degraded':
        'Restore account truth to a passable state',
      restore_complete_portfolio_valuation_snapshot:
        'Restore a complete portfolio valuation snapshot',
      review_current_holding_market_evidence:
        'Review current holding prices and fund NAV evidence',
    },
    accountRecommendationPaperShadow: 'Paper shadow evaluation',
    accountRecommendationPaperShadowDetail:
      'This enters paper-shadow evaluation only and does not create an executable order.',
    accountRecommendationNoAction: 'No action',
    accountRecommendationNoActionDetail:
      'The daily promoted-strategy scan completed without an account action signal.',
    accountRecommendationBlocked: 'Strategy recommendation unavailable',
    accountRecommendationUnavailable: 'Strategy recommendation unavailable',
    accountRecommendationReason: (reasons: string) =>
      `Current reason: ${reasons || 'no verifiable account recommendation is available'}.`,
    researchOperationCandidate:
      'Quant research operation candidates (non-executable; account qualification not evaluated)',
    researchOperationDetail: (summary: string) =>
      `Frozen-close Formula conditions: ${summary}. For next-session research only.`,
    researchOperationMeta: (
      count: number,
      marketDate: string,
      targetMarketDate: string,
    ) =>
      `${marketDate} frozen close → ${targetMarketDate} next verified session · ${count} research candidates · non-executable`,
    researchOperationResolution:
      'Review Formula evidence in AI Research only; do not create an order or place a manual trade from this preview.',
    tradingPlanUnavailable: 'Daily trading plan is unavailable',
    tradingPlanLoading: 'Loading daily trading plan',
    tradingPlanNeedsReview: 'Daily trading plan needs review',
    tradingPlanCashShortfall: 'Cash shortfall blocks buy preview',
    tradingPlanManualReady: (count: number) =>
      count === 1
        ? '1 action awaits confirmation'
        : `${count} actions await confirmation`,
    tradingPlanManualReadyDetail: (count: number) =>
      count === 1
        ? 'Review the evidence-linked order intent before preparing a manual order.'
        : `Review ${count} evidence-linked order intents before preparing manual orders.`,
    tradingPlanManualIntentDetail: (
      side: string,
      symbol: string,
      quantity: number,
    ) => `${side} · ${symbol} · ${quantity}`,
    tradingPlanBlockedDetail: (count: number) =>
      count === 1
        ? '1 blocker must be cleared before manual confirmation.'
        : `${count} blockers must be cleared before manual confirmation.`,
    tradingPlanCashShortfallDetail: (amount: string) =>
      `Review cash allocation before confirming. Shortfall: ${amount}.`,
    tradingPlanMeta: (
      manualReady: number,
      candidates: number,
      blockers: number | string,
    ) =>
      typeof blockers === 'number'
        ? `${manualReady} plan review · ${candidates} pool · ${blockers} blocked`
        : `${manualReady} plan review · ${candidates} pool · ${blockers}`,
    strategyEvidenceLinked: 'Strategy contribution is evidence-linked',
    strategyNoLinkedFills: 'No attributable strategy fills yet',
    strategyEvidenceRequired: 'Strategy contribution needs linked evidence',
    strategyUnavailable: 'Strategy contribution is temporarily unavailable',
    viewData: 'View data status',
    viewDecision: 'Review decision evidence',
    viewOperations: 'Review operations evidence',
    viewTrading: 'Review trading queue',
    viewStrategy: 'Review strategy evidence',
    viewAiResearch: 'Review AI strategy research',
    candidateCount: (count: number) =>
      `${count} candidate signal${count === 1 ? '' : 's'}`,
    decisionActionLabels: {
      buy: 'Buy',
      sell: 'Sell',
      hold: 'Hold',
      rebalance: 'Rebalance',
      no_action: 'No action',
      review_required: 'Review',
    },
    marketPulse: 'Market pulse',
    marketPulseDetail:
      'Broad-market quote context for today. It is background only, not a trading instruction.',
    marketPulseMissing:
      'No broad-market index quotes are available yet. Add or refresh index data on the Market page.',
    marketPulsePositive: 'Broad market positive',
    marketPulseNegative: 'Broad market weak',
    marketPulseMixed: 'Mixed market',
    marketPulsePending: 'Index data pending',
    marketPulseNoSignal: 'Trend unavailable',
    marketPulseDisclosure: 'Market context only',
    marketPulseMoveMissing: 'Move missing',
    marketPulseMissingChanges: (count: number) =>
      `${count} index move${count === 1 ? '' : 's'} missing`,
    marketPulseChangeCoverage: (available: number, total: number) =>
      `${available}/${total} moves available`,
    marketHeatmapUnavailable: 'Market heatmap awaiting evidence',
    marketHeatmapUnavailableDetail:
      'Saved data currently covers index levels only. Market-wide and sector breadth data is unavailable, so no heatmap is shown.',
    viewMarket: 'Open Market page',
    viewHoldingDetail: 'Open holding detail',
    todayMove: 'Today move',
    sinceBuyMove: 'Since buy',
    quoteStatusLabel: 'Quote status',
    pendingApprovals: 'Pending approvals',
    pendingEmpty: 'No orders require approval.',
    pendingEmptyDetail: 'Approved orders will appear here before execution.',
    pendingCount: (count: number) => `${count} pending`,
    ledgerPanel: 'Latest ledger',
    ledgerCount: (count: number) => `${count} entries`,
    ledgerEmpty: 'No ledger entries yet.',
    positionsPanel: 'Current positions',
    positionsDetail:
      'Quote price, cost basis, market value, and floating PnL from the current account view.',
    quickActions: 'Quick actions',
    refreshQuotes: 'Refresh quotes',
    refreshingQuotes: 'Refreshing',
    addLedger: 'Add ledger entry',
    tradingDesk: 'Trading desk',
    dataSettings: 'Data settings',
    dataStatus: 'Data status',
    valuationTime: 'Valuation time',
    quoteAge: 'Quote age',
    staleReason: 'Stale reason',
    refreshPolicy: 'Refresh policy',
    quoteSource: 'Quote source',
    affectedHoldings: 'Affected holdings',
    affectedCount: (count: number) =>
      `${count} holding${count === 1 ? ' needs' : 's need'} review`,
    usingEstimate: 'Using estimate',
    waitingConfirmedNav: 'Waiting for confirmed NAV',
    checkDataSource: 'Check data source',
    refreshFailed: 'Quote refresh failed',
    refreshDone: 'Quote refresh completed',
    tradeBuy: 'Buy',
    tradeSell: 'Sell',
    cashDeposit: 'Deposit',
    cashWithdrawal: 'Withdrawal',
    dividend: 'Dividend',
    adjustment: 'Adjustment',
    unknownActivity: 'Ledger entry',
  },
  equityCurve: {
    title: 'Performance Analysis',
    range: 'Range',
    series: 'Asset class',
    total: 'Total',
    stocks: 'Stocks',
    funds: 'Funds',
    others: 'Others',
    cash: 'Cash',
    allSeries: 'All series',
    oneDay: '1D',
    fiveDays: '5D',
    oneMonth: '1M',
    sixMonths: '6M',
    oneYear: '1Y',
    yearToDate: 'YTD',
    all: 'ALL',
    empty: 'No equity history yet.',
    emptyTitle: 'No Equity History Yet',
    unverifiedPeriod: 'No verified valuation points in this period.',
    emptyPeriod: 'No data available for this period.',
    insufficientData: 'Insufficient data for this range.',
    emptyDetail:
      'Record the first cash flow or trade to start building the equity curve.',
    emptyHint:
      'The curve appears after the account has recorded history over time.',
    currentPoint: 'Current valuation point',
    categoryDailyChange: (label: string) => `${label} change at this point`,
    unconfirmedCategoryDailyChange: (label: string) =>
      `${label} change needs confirmation`,
    portfolioTotal: 'Portfolio total',
    confirmedPortfolioTotal: 'Confirmed valuation',
    indicativePortfolioTotal: 'Indicative valuation',
    indicativeSeries: (label: string) => `${label} · indicative valuation`,
    historyStart: (date: string) =>
      `Reconstructable account history starts on ${date}.`,
    indicativeHistoryNote:
      'The same-color dashed line marks history outside the complete valuation gate or bridges missing evidence for continuity; missing dates are not treated as confirmed account valuations.',
    rangeHigh: 'Range high',
    quoteStatus: 'Quote status',
    realtimeUnrealizedPnl: 'Portfolio unrealized P/L',
    cachedValuation: 'Valuation uses cached quotes',
    valuationStatus: (status: string) => `Valuation status: ${status}`,
  },
  livePulse: {
    title: 'Asset pulse',
    subtitle:
      'Review grouped holdings by asset class with quote move and since-buy return.',
    loading: 'Loading grouped holdings.',
    error: 'Failed to load grouped holdings.',
    empty: 'No active holdings yet.',
    marketValue: 'Market value',
    todayMove: 'Today move',
    sinceBuyReturn: 'Since-buy return',
  },
  risk: {
    registerKicker: 'Risk boundary',
    title: 'Risk boundary register',
    subtitle:
      'Read-only operating boundaries for concentration, liquidity, deployment, and execution posture.',
    concentration: 'Top Holding Weight',
    concentrationBoundary: 'Single-name concentration review',
    cashBuffer: 'Cash Buffer',
    cashBoundary: 'Liquidity floor before new exposure',
    deployment: 'Capital Deployment',
    deploymentBoundary: 'Capital-at-work pressure',
    positions: 'Active Positions',
    positionsBoundary: 'Open risk surface',
    positionsHint: (count: number) =>
      `${count} open ${count === 1 ? 'position' : 'positions'}`,
    boundary: 'Boundary',
    current: 'Current',
    cashHealthy: 'Healthy reserve',
    cashWatch: 'Cash reserve is getting thin',
    deploymentBalanced: 'Deployment is balanced',
    deploymentHigh: 'Portfolio is running hot',
    executionBoundary: 'Execution boundary',
    executionBoundaryDetail:
      'Live-like workflows stay gated until an operator reviews the order and confirms it manually.',
    manualConfirmationRequired: 'Manual confirmation required',
  },
  breakdown: {
    accountKicker: 'Account breakdown',
    strategyKicker: 'Strategy breakdown',
    accountTitle: 'Capital structure and deployment',
    strategyTitle: 'Returns and execution outcome',
    marketValue: 'Market Value',
    activePositions: (count: number) => `${count} active positions`,
    cashReserve: 'Cash Reserve',
    netDeposits: 'Net Deposits',
    capitalBase: 'Capital base',
    deployment: 'Deployment',
    capitalAtWork: 'Capital at work',
    unrealizedPnl: 'Unrealized PnL',
    openPositions: 'Open positions',
    realizedPnl: 'Realized PnL',
    closedActivity: 'Closed activity',
    totalPnl: 'Total PnL',
    totalPnlHint: 'Realized + unrealized',
    payoutBuffer: 'Payout Buffer',
    payoutBufferHint: 'Cash available for redeploy',
  },
} as const;
