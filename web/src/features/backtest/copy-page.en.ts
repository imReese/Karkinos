export const backtestPageEn = {
  kicker: 'Backtest lab',
  title: 'Strategy replay',
  subtitle:
    'Run a controlled historical simulation, then inspect risk, costs, equity path, and fill coverage.',
  formKicker: 'Run setup',
  formTitle: 'Backtest configuration',
  formDetail:
    'Choose an explicit asset list, or leave it blank to use the saved research universe.',
  decisionHandoffKicker: 'Decision handoff',
  decisionHandoffTitle: 'Decision handoff context',
  decisionHandoffDetail:
    'This form was prefilled from a candidate action. Run the backtest, then inspect dataset, after-cost result, signal preview, risk preview, and simulation evidence before any manual step.',
  decisionHandoffResearchOnly: 'Research only; no broker order is created.',
  holdingHandoffKicker: 'Holding research handoff',
  holdingHandoffTitle: 'Holding research context',
  holdingHandoffDetail:
    'This form was opened from a holding detail page. Run the backtest for this instrument, then inspect dataset, after-cost result, signal preview, risk preview, and simulation evidence before any manual step.',
  runContextKicker: 'Run context',
  runContextTitle: 'Single-instrument research context',
  runContextDetail:
    'This context follows the run through dataset, signal, risk, simulation review, and attribution review.',
  runContextSource: 'Source',
  runContextSourcePortfolio: 'From holding detail',
  runContextSourceDecision: 'From decision candidate',
  runContextSourceManual: 'Manual Backtest setup',
  runContextInstrument: 'Instrument',
  runContextAssetClass: 'Asset class',
  runContextStrategy: 'Strategy',
  runContextReviewHolding: 'Review holding detail',
  startDate: 'Start date',
  endDate: 'End date',
  initialCash: 'Initial cash',
  strategy: 'Strategy',
  strategyNames: {
    dual_ma: 'Dual Moving Average',
    monthly_rebalance: 'Monthly Rebalance',
    bollinger: 'Bollinger Mean Reversion',
    rsi: 'RSI Momentum / Reversion',
    time_series_momentum: 'Time Series Momentum',
    donchian_breakout: 'Donchian Channel Breakout',
    volatility_target_trend: 'Volatility Target Trend',
    pairs_ratio_mean_reversion: 'Pairs Ratio Mean Reversion',
  },
  strategyDescriptions: {
    dual_ma: 'Dual moving-average crossover baseline.',
    monthly_rebalance: 'Scheduled allocation rebalance baseline.',
    bollinger: 'Bollinger band mean-reversion baseline.',
    rsi: 'RSI momentum/reversion baseline.',
    time_series_momentum:
      'Paper-inspired trend baseline using trailing return persistence.',
    donchian_breakout:
      'Common channel-breakout trend baseline using prior highs and lows.',
    volatility_target_trend:
      'Trend baseline that scales long-only exposure by realized volatility.',
    pairs_ratio_mean_reversion:
      'Long-only relative-value pair rotation using A/B ratio z-scores.',
  },
  benchmarkRoleNames: {
    trend_following: 'Trend-following benchmark',
    etf_rotation_trend_following: 'ETF trend-following benchmark',
    allocation_rebalance: 'Allocation rebalance benchmark',
    a_share_or_etf_mean_reversion: 'A-share / ETF mean-reversion benchmark',
    custom_momentum_research: 'Custom momentum research benchmark',
    time_series_momentum: 'Time-series momentum benchmark',
    channel_breakout_trend_following: 'Channel-breakout trend benchmark',
    volatility_target_trend_following: 'Volatility-targeted trend benchmark',
    pair_relative_value_mean_reversion:
      'Pair relative-value mean-reversion benchmark',
  },
  validationNotes: {
    'Requires after-cost, out-of-sample ETF trend-following validation before promotion.':
      'Requires after-cost, out-of-sample ETF trend-following validation before promotion.',
    'Requires after-cost, out-of-sample validation across equity ETF, bond, gold, and cash proxy allocations.':
      'Requires after-cost, out-of-sample validation across equity ETF, bond, gold, and cash proxy allocations.',
    'Requires after-cost, out-of-sample mean-reversion validation on A-share or ETF fixtures before promotion.':
      'Requires after-cost, out-of-sample mean-reversion validation on A-share or ETF fixtures before promotion.',
    'Inspired by time-series momentum literature; requires after-cost, out-of-sample validation before promotion.':
      'Inspired by time-series momentum literature; requires after-cost, out-of-sample validation before promotion.',
    'Long-only implementation exits to cash instead of using leverage or short futures exposure.':
      'Long-only implementation exits to cash instead of using leverage or short futures exposure.',
    'Common channel-breakout trend-following baseline; requires turnover, whipsaw, and after-cost review.':
      'Common channel-breakout trend-following baseline; requires turnover, whipsaw, and after-cost review.',
    'Uses prior high/low channels only and does not approve execution without risk gates.':
      'Uses prior high/low channels only and does not approve execution without risk gates.',
    'Trend-following baseline with realized-volatility sizing; requires volatility-regime and turnover review.':
      'Trend-following baseline with realized-volatility sizing; requires volatility-regime and turnover review.',
    'Long-only volatility targeting caps weight at 1.0 and never implies leverage.':
      'Long-only volatility targeting caps weight at 1.0 and never implies leverage.',
    'Inspired by pairs-trading literature but constrained to long-only target weights.':
      'Inspired by pairs-trading literature but constrained to long-only target weights.',
    'Requires pair-selection, liquidity, co-movement, and transaction-cost review before promotion.':
      'Requires pair-selection, liquidity, co-movement, and transaction-cost review before promotion.',
  },
  parameterLabels: {
    short_period: 'Short moving-average window',
    long_period: 'Long moving-average window',
    bb_period: 'Bollinger lookback window',
    num_std: 'Standard-deviation multiplier',
    rsi_period: 'RSI smoothing window',
    oversold: 'Oversold threshold',
    overbought: 'Overbought threshold',
    lookback_period: 'Lookback window',
    min_return: 'Entry return threshold',
    exit_return: 'Exit return threshold',
    target_weight: 'Target weight',
    entry_window: 'Breakout entry window',
    exit_window: 'Breakout exit window',
    volatility_window: 'Volatility window',
    target_annual_volatility: 'Target annual volatility',
    max_weight: 'Maximum weight',
    min_momentum: 'Minimum momentum',
    rebalance_threshold: 'Rebalance threshold',
    symbol_a: 'Pair leg A',
    symbol_b: 'Pair leg B',
    entry_z: 'Entry z-score',
    exit_z: 'Exit z-score',
    pair_weight: 'Pair leg weight',
    neutral_weight: 'Neutral leg weight',
  },
  parameterDescriptions: {
    short_period: 'Fast-average lookback, counted in trading bars.',
    long_period: 'Slow-average lookback, counted in trading bars.',
    bb_period: 'Lookback window used to calculate Bollinger bands.',
    num_std:
      'Number of standard deviations used to place the upper and lower bands.',
    rsi_period: 'Wilder-smoothed RSI lookback, counted in trading bars.',
    oversold: 'RSI level crossed upward to emit a long target.',
    overbought: 'RSI level crossed downward to emit an exit target.',
    lookback_period:
      'Trailing window used to measure return, trend, or spread state.',
    min_return: 'Minimum trailing return required before entering.',
    exit_return: 'Trailing return threshold that exits to cash.',
    target_weight: 'Long-only target weight emitted by the strategy.',
    entry_window: 'Prior high channel window used for breakout entries.',
    exit_window: 'Prior low channel window used for breakout exits.',
    volatility_window:
      'Rolling return window used to estimate realized volatility.',
    target_annual_volatility:
      'Annualized volatility target used to scale exposure.',
    max_weight: 'Maximum long-only target weight. Leverage is not used.',
    min_momentum: 'Minimum trailing return required to hold risk.',
    rebalance_threshold:
      'Minimum target-weight change required before emitting a signal.',
    symbol_a: 'First pair leg. Empty value uses the first run symbol.',
    symbol_b: 'Second pair leg. Empty value uses the second run symbol.',
    entry_z: 'Absolute ratio z-score that rotates into one pair leg.',
    exit_z: 'Absolute ratio z-score that returns the pair to neutral.',
    pair_weight: 'Target weight assigned to the cheap relative-value leg.',
    neutral_weight: 'Target weight for each leg after the ratio normalizes.',
  },
  parameterCode: (name: string) => `API field: ${name}`,
  strategyMetadata: 'Strategy metadata',
  assetUniverse: 'Asset universe',
  supportedFrequencies: 'Frequencies',
  benchmarkRole: 'Benchmark role',
  validationRequirements: 'Validation',
  oosRequired: 'OOS required',
  afterCostRequired: 'After-cost required',
  notDeclared: 'Not declared',
  strategyRegistryLoading: 'Loading strategy registry.',
  strategyRegistryFailed:
    'Strategy registry unavailable; using the default baseline.',
  strategyCatalogKicker: 'Strategy catalog',
  strategyCatalogTitle: 'Available strategies',
  strategyCatalogDetail:
    'Choose the research strategy first, then run it on a target and inspect after-cost evidence.',
  strategySourceBuiltin: 'Built-in strategy',
  strategySourceExtension: 'Local extension',
  selectStrategy: (name: string) => `Select ${name}`,
  selectedStrategy: 'Selected',
  runReadinessTitle: 'Run readiness summary',
  runReadinessDetail:
    'Review the research inputs before freezing data and running the after-cost backtest.',
  runReadinessStrategy: 'Strategy',
  runReadinessStrategySource: 'Strategy source',
  runReadinessInstrument: 'Instrument',
  runReadinessAssetClass: 'Asset class',
  runReadinessParams: 'Parameters',
  runReadinessDataset: 'Dataset snapshot',
  runReadinessDatasetPending:
    'Dataset snapshot will be frozen when this backtest runs.',
  runReadinessParameterCount: (count: number) =>
    `${count} configured ${count === 1 ? 'parameter' : 'parameters'}`,
  promotionRequirementsCount: (count: number) =>
    `${count} unmet ${count === 1 ? 'gate' : 'gates'}`,
  promotionEvidenceUnavailable: 'No promotion evidence for this strategy',
  advancedToolsTitle: 'Advanced experiment tools',
  advancedToolsDetail:
    'Parameter sweeps and same-snapshot comparisons are secondary research tools.',
  researchGovernanceTitle: 'Research governance',
  researchGovernanceDetail:
    'Account and symbol assignments plus reviewed learning remain separate from execution authority.',
  promotionEvidenceTitle: 'Promotion evidence',
  promotionEvidenceDetail:
    'Review after-cost, OOS, risk, simulation, Account Truth, and attribution gates.',
  researchArchiveTitle: 'AI research and saved reports',
  researchArchiveDetail:
    'AI tasks start only when you request them, and saved experiments remain research evidence only.',
  accountStrategyKicker: 'Account strategy',
  accountStrategyTitle: 'Current account strategy',
  accountStrategyDetail:
    'Tracks which strategy is currently assigned for research and manual-review context. It does not authorize broker orders.',
  accountStrategyLoading: 'Loading account strategy assignment.',
  accountStrategyUnavailable:
    'Account strategy assignment is unavailable; backtests still run as research evidence.',
  accountStrategyStatus: {
    research_only: 'Research only',
    paper_review: 'Simulation review',
    shadow_review: 'Simulation review',
    manual_confirm: 'Manual confirmation',
    disabled: 'Disabled',
  },
  accountStrategyAttribution: {
    not_started: 'Attribution not started',
    assignment_only: 'Assignment only',
    signal_chain_pending: 'Signal chain pending',
    orders_linked_no_fills: 'Orders linked, no fills',
    evidence_linked_pnl_pending: 'Evidence linked, P/L pending',
    partial: 'Partial attribution',
    blocked: 'Attribution blocked',
    failed: 'Attribution failed',
    complete: 'Attributed',
    attributed: 'Attributed',
  },
  accountStrategyScope: {
    account: 'Whole account',
    symbol: 'Single symbol',
    asset_class: 'Asset class',
  },
  accountStrategyAutoTradeOff: 'Auto trading off',
  accountStrategyPnlPending:
    'The current account strategy does not yet have a complete P/L attribution evidence chain; strategy P/L is shown only after traceable signal, review, order, and fill references are available.',
  accountStrategyPnlAttributionStatus: 'P/L attribution status',
  accountStrategyPnlAttributionTier: {
    not_started: 'Attribution not started',
    partial: 'Partial attribution',
    stale: 'Stale attribution',
    blocked: 'Blocked attribution',
    complete: 'Complete attribution',
  },
  accountStrategyPnlAttributionTierDetail: {
    not_started:
      'No strategy-linked signals, reviews, orders, or fills are available yet.',
    partial:
      'Some evidence is linked, but the strategy P/L chain is not complete.',
    stale: 'Linked evidence exists, but valuation data is stale or missing.',
    blocked:
      'Attribution blocked until missing or invalid evidence is reviewed.',
    complete:
      'Strategy-linked evidence is complete enough to show contribution.',
  },
  accountStrategyAttributionSourceStatus: 'Source status',
  accountStrategyContributionSourceStatus: 'Contribution status',
  accountStrategyValuationStale: 'Valuation stale / missing',
  accountStrategySelectedHint: (name: string) =>
    `Selected backtest strategy: ${name}. Assigning it only changes research context.`,
  accountStrategyAssignSelected: 'Set as account research strategy',
  accountStrategyAssignSelectedSymbol: 'Set for current symbol',
  accountStrategyAssigning: 'Saving assignment',
  accountStrategyAssigned: 'Already assigned',
  accountStrategySymbolAssigned: 'Symbol assigned',
  accountStrategySymbolNeedsInput: 'Enter symbol first',
  accountStrategyAssignFailed:
    'Could not save the account strategy assignment.',
  accountStrategyScopedAssignFailed:
    'Could not save the symbol strategy assignment.',
  accountStrategyScopedAssignmentsTitle: 'Symbol strategy bindings',
  accountStrategyScopedAssignmentsEmpty:
    'No symbol-specific strategy bindings yet.',
  accountStrategyScopedAssignmentsLoading: 'Loading symbol strategy bindings.',
  accountStrategyScopedAssignmentsUnavailable:
    'Symbol strategy bindings are unavailable.',
  accountStrategyAttributionEvidence: 'Attribution evidence',
  accountStrategyAttributionLoading: 'Loading attribution evidence.',
  accountStrategyAttributionUnavailable: 'Attribution evidence is unavailable.',
  accountStrategySignalActionRisk: 'Signal / action / risk',
  accountStrategyOrdersFills: 'Orders / fills',
  accountStrategyPnlStatus: 'P/L status',
  accountStrategyContributionReport: 'Contribution report',
  accountStrategyContributionPublicTitle: 'Strategy contribution',
  accountStrategyContributionLoading: 'Loading contribution report.',
  accountStrategyContributionUnavailable: 'Contribution report is unavailable.',
  accountStrategyContributionExplanation:
    'Contribution is shown only for strategy fills posted to the production ledger and bound to one persisted valuation snapshot. Manual trades and cash flows stay separate.',
  accountStrategyEvidenceLinked: 'Evidence-linked',
  accountStrategyEvidenceRequired: 'Evidence required',
  accountStrategyEvidenceNotApplicable: 'No contribution due yet',
  accountStrategyContributionHiddenUntilEvidence:
    'Contribution stays hidden until the listed ledger and valuation evidence is complete.',
  accountStrategyEvidenceRefs: 'Evidence refs',
  accountStrategyAuditId: 'Audit id',
  accountStrategyContributionStatus: 'Contribution status',
  accountStrategyEvidenceBinding: 'Evidence binding',
  accountStrategyLedgerPostedFills: 'Posted / linked fills',
  accountStrategyValuationSnapshot: 'Valuation snapshot',
  accountStrategyLedgerCutoff: 'Ledger cutoff',
  accountStrategyNextManualAction: 'Next manual action',
  accountStrategyBlockers: 'Blocking evidence',
  accountStrategyHealthStatus: 'Strategy health',
  accountStrategyHealthStatusMap: {
    healthy: 'Healthy',
    degraded: 'Degraded',
    stale: 'Stale',
    paused: 'Paused',
    needs_review: 'Needs review',
    not_applicable: 'Not applicable yet',
  },
  accountStrategyEvidenceBindingStatusMap: {
    bound: 'Bound and replayable',
    blocked: 'Blocked',
    not_applicable: 'Not applicable yet',
  },
  accountStrategyContributionStatusMap: {
    no_linked_fills: 'No linked fills',
    valuation_missing: 'Valuation missing',
    evidence_bound_from_posted_fills: 'Ledger and valuation bound',
    ledger_posting_pending: 'Ledger posting pending',
    ledger_evidence_drift: 'Fill / ledger mismatch',
    valuation_snapshot_missing: 'Valuation snapshot missing',
    valuation_snapshot_invalid: 'Valuation snapshot invalid',
    valuation_identity_drift: 'Valuation scope changed',
    inventory_lineage_incomplete: 'Inventory lineage incomplete',
  },
  accountStrategyNextActionMap: {
    no_action_until_strategy_linked_fill_exists:
      'No action is needed until a strategy-linked fill exists.',
    review_unattributed_strategy_fill_lineage:
      'Review fills that name the strategy but lack a complete signal/order lineage.',
    complete_execution_reconciliation_and_explicit_ledger_posting:
      'Complete execution reconciliation and explicitly post the fill to the production ledger.',
    review_strategy_fill_and_ledger_identity:
      'Compare the fill with its recorded ledger entry and resolve the mismatch.',
    publish_or_repair_persisted_valuation_snapshot:
      'Review persisted market/NAV facts, then publish or repair the valuation snapshot.',
    publish_persisted_valuation_snapshot:
      'Publish a persisted valuation snapshot after market/NAV evidence is confirmed.',
    repair_persisted_valuation_snapshot:
      'Repair the invalid persisted valuation snapshot before retrying attribution.',
    review_strategy_inventory_lineage:
      'Review the strategy-owned buy/sell inventory lineage.',
    sync_confirmed_market_or_nav_evidence:
      'Ingest and confirm persisted market or NAV evidence, then publish a new snapshot.',
    review_evidence_bound_strategy_contribution:
      'Review the replayable strategy contribution evidence.',
  },
  accountStrategyGrossRealizedPnl: 'Gross realized P/L',
  accountStrategyGrossUnrealizedPnl: 'Gross unrealized P/L',
  accountStrategyCommissionSlippage: 'Commission / slippage',
  accountStrategyTax: 'Tax',
  accountStrategyManualCashFlowMovement: 'Manual / cash-flow movement',
  accountStrategyTaxExcludedMovement: 'Tax / excluded movement',
  accountStrategyNetContribution: 'Net contribution',
  accountStrategyMissingValuation: (symbols: string) =>
    `Missing local valuation for: ${symbols}.`,
  shortPeriod: 'Short period',
  longPeriod: 'Long period',
  symbol: 'Symbol',
  symbolPlaceholder: '600002',
  assetClass: 'Asset class',
  singleSymbolHint:
    'Leave the symbol blank to test the saved research universe. A single-symbol run remains research evidence only.',
  assets: 'Assets',
  assetsPlaceholder: 'SYMBOL Stock\nSYMBOL Fund',
  assetsHint:
    'One asset per line: symbol plus asset class such as Stock, ETF, Fund, Gold, or Bond.',
  run: 'Run backtest',
  running: 'Running backtest',
  currentKicker: 'Current run',
  currentTitle: 'Run output',
  resultsWorkspaceTab: 'Results and evidence',
  emptyCurrent:
    'Run a backtest to inspect the current result. Saved reports remain available below.',
  signalPreviewKicker: 'Strategy signal',
  signalPreviewTitle: 'Strategy signal preview',
  signalPreviewDetail:
    'Uses the selected strategy and the same server-side market-data path to preview the latest research signal for this single-symbol run.',
  signalPreviewResearchOnly: 'Research only',
  signalPreviewSkipped:
    'Signal preview is available after running a single-symbol backtest.',
  signalPreviewLoading: 'Loading strategy signal preview.',
  signalPreviewUnavailable:
    'Strategy signal preview is unavailable; the backtest result remains research evidence.',
  signalPreviewPending:
    'Run a single-symbol backtest to preview the latest strategy signal.',
  signalPreviewAction: 'Action',
  signalPreviewActions: {
    buy: 'Buy candidate',
    sell: 'Sell candidate',
    rebalance: 'Rebalance candidate',
    no_action: 'No action',
  },
  signalPreviewReason: 'Why',
  signalPreviewReasons: {
    buy: 'Strategy generated a buy candidate from the selected backtest data.',
    sell: 'Strategy generated a sell candidate from the selected backtest data.',
    rebalance:
      'Strategy generated a rebalance candidate from the selected backtest data.',
    no_action:
      'Strategy did not generate a candidate action from the selected backtest data.',
  },
  signalPreviewDataQualityLabel: 'Data quality',
  signalPreviewDataQuality: (status: string) => `Data quality: ${status}`,
  signalPreviewBars: 'Bars',
  signalPreviewBarCount: (count: number) => `${count} bars`,
  signalPreviewReferencePriceLabel: 'Reference price',
  signalPreviewReferencePrice: (price: string) => `Reference price ${price}`,
  signalPreviewDataBasis: 'Signal data basis',
  signalPreviewDataset: 'Dataset snapshot',
  signalPreviewReviewGates: 'Review gates',
  signalPreviewRiskQuantity: 'Risk quantity',
  signalPreviewRiskPreviewButton: 'Preview risk',
  signalPreviewRiskPreviewLoading: 'Checking risk',
  signalPreviewRiskPreviewUnavailable:
    'Risk preview is unavailable; no order was created.',
  signalPreviewRiskPreviewTitle: 'Risk preview',
  signalPreviewRiskPassed: 'Risk passed',
  signalPreviewRiskBlocked: 'Blocked by risk',
  signalPreviewRiskNoOrder: 'No order created',
  signalPreviewRiskPending:
    'Enter a quantity to run a read-only pre-trade risk preview.',
  signalPreviewRiskReasonLabels: {
    approved: 'Approved for manual review',
    killSwitch: 'Kill switch enabled',
    dataQuality: 'Market data needs review',
    cashReserve: 'Cash reserve would be breached',
    orderNotional: 'Order amount exceeds policy',
    positionWeight: 'Position concentration exceeds policy',
  },
  signalPreviewPaperShadowTitle: 'Simulation review preview',
  signalPreviewPaperShadowNextStep: 'Simulation review next step',
  signalPreviewPaperShadowReady:
    'Risk preview passed. Run the simulation review before any manual step.',
  signalPreviewPaperShadowBlocked:
    'Simulation review waits for a passed risk preview.',
  signalPreviewPaperShadowButton: 'Preview simulation review',
  signalPreviewPaperShadowLoading: 'Running simulation review',
  signalPreviewPaperShadowUnavailable:
    'Simulation review is unavailable; no ledger entry was created.',
  signalPreviewPaperShadowResultTitle: 'Simulation review preview',
  signalPreviewPaperShadowSimulatedFill: 'Simulated fill',
  signalPreviewPaperShadowBlockedResult: 'Waiting for risk pass',
  signalPreviewPaperShadowNoLedgerMutation: 'No ledger mutation',
  signalPreviewPaperShadowFill: 'Simulated execution',
  signalPreviewPaperShadowFillSummary: (quantity: string, price: string) =>
    `Filled ${quantity} @ ${price}`,
  signalPreviewPaperShadowFee: 'Estimated cost',
  signalPreviewPaperShadowEstimatedFee: (fee: string) => `Estimated fee ${fee}`,
  signalPreviewAttributionTitle: 'Attribution evidence preview',
  signalPreviewAttributionLoading: 'Checking attribution evidence',
  signalPreviewAttributionUnavailable:
    'Attribution preview is unavailable; no P/L was attributed.',
  signalPreviewAttributionReady: 'Ready for review linkage',
  signalPreviewAttributionIncomplete: 'Evidence still incomplete',
  signalPreviewAttributionNoPnl: 'Preview only, P/L not attributed',
  signalPreviewAttributionEvidence: 'Evidence boundary',
  signalPreviewAttributionEvidenceSummary: (
    previewEvidence: number,
    productionFacts: number,
  ) =>
    `Preview evidence ${previewEvidence} / Production facts ${productionFacts}`,
  signalPreviewAttributionBoundary: 'Attribution boundary',
  signalPreviewAttributionPreviewOnly:
    'Signal, review, order, and fill facts must be linked before strategy P/L attribution.',
  signalPreviewAttributionNoLinkedFillsTitle: 'No linked production fills',
  signalPreviewAttributionNoLinkedFillsDetail:
    'Strategy P/L is unavailable until signal, review, order, and fill evidence are linked.',
  signalPreviewEvidenceChainTitle: 'Evidence chain',
  signalPreviewEvidenceChainDetail:
    'Readable audit steps for this preview. Raw evidence references stay hidden from the workflow UI.',
  signalPreviewEvidenceChainPresent: 'Linked',
  signalPreviewEvidenceChainMissing: 'Missing',
  signalPreviewEvidenceChainSignal: 'Strategy signal',
  signalPreviewEvidenceChainDataset: 'Dataset snapshot',
  signalPreviewEvidenceChainRisk: 'Risk gate preview',
  signalPreviewEvidenceChainPaperOrder: 'Simulation review order',
  signalPreviewEvidenceChainPaperFill: 'Simulation review fill',
  signalPreviewReviewLinkageTitle: 'Review linkage candidate',
  signalPreviewReviewLinkageManual: 'Manual review required',
  signalPreviewReviewLinkageNoWrite: 'No order or ledger write',
  signalPreviewReviewLinkageDetail:
    'Signal, risk, and simulation review evidence can be reviewed and linked manually.',
  signalPreviewReviewHoldingAttribution: 'Review holding attribution',
  signalPreviewHoldingAttributionReadiness: 'Holding attribution readiness',
  signalPreviewGateLabels: {
    dataReady: 'Data ready',
    dataNeedsReview: 'Data needs review',
    dataBlocked: 'Data blocked',
    accountTruthRequired: 'Account truth required',
    riskRequired: 'Risk gate required',
    paperShadowWaiting: 'Simulation review waiting',
    manualReviewRequired: 'Manual review required',
    notRequired: 'Not required',
    unknown: 'Review required',
  },
  signalPreviewGateRequired:
    'Requires risk, account-truth, simulation review, and manual review before any live-like workflow.',
  signalPreviewNoGateRequired:
    'No candidate action was generated; no downstream trade gate is required.',
  signalPreviewExecutionBoundary:
    'This preview does not create signals, action tasks, orders, fills, ledger entries, or broker submissions.',
  singleInstrumentLoopKicker: 'Single-symbol evidence loop',
  singleInstrumentLoopTitle: 'Single-instrument loop readiness',
  singleInstrumentLoopDetail:
    'Track the read-only path from frozen data to signal, risk, simulation review, and attribution boundary.',
  singleInstrumentLoopReady: 'Ready for manual review',
  singleInstrumentLoopWaiting: 'Waiting for evidence',
  singleInstrumentLoopBlocked: 'Blocked by review gates',
  singleInstrumentLoopNextStep: 'Next review step',
  singleInstrumentLoopNextBacktest:
    'Review the after-cost backtest evidence before generating signals.',
  singleInstrumentLoopNextSignal:
    'Wait for the strategy signal preview for this single-instrument run.',
  singleInstrumentLoopNextRisk:
    'Run the risk preview before simulation review.',
  singleInstrumentLoopNextBlocked:
    'Risk preview is blocked; review the risk reasons before simulation.',
  singleInstrumentLoopNextPaper:
    'Run simulation review after the risk preview passes.',
  singleInstrumentLoopNextAttribution:
    'Review the attribution boundary; strategy P/L stays unavailable until signal, review, order, and fill evidence is linked.',
  singleInstrumentLoopNextComplete:
    'All research evidence is ready for manual review; no broker order is created here.',
  singleInstrumentLoopAuditCoverage: 'Acceptance audit coverage',
  singleInstrumentLoopAuditVerified: 'criteria verified',
  singleInstrumentLoopAuditLoading: 'Loading audit coverage',
  singleInstrumentLoopAuditUnavailable: 'Audit coverage unavailable',
  singleInstrumentLoopAuditFallbackKey: 'acceptance audit',
  singleInstrumentLoopAuditBoundary:
    'Product-readiness proof only; it does not enable broker execution or investment advice.',
  singleInstrumentLoopEvidenceCta: 'Review evidence',
  singleInstrumentLoopDatasetEvidence: 'Review dataset snapshot evidence',
  singleInstrumentLoopStrategyEvidence: 'Review strategy registry evidence',
  singleInstrumentLoopBacktestEvidence: 'Review after-cost backtest evidence',
  singleInstrumentLoopSignalEvidence: 'Review signal preview evidence',
  singleInstrumentLoopRiskEvidence: 'Review risk gate evidence',
  singleInstrumentLoopPaperEvidence: 'Review simulation evidence',
  singleInstrumentLoopAttributionEvidence:
    'Review attribution boundary evidence',
  singleInstrumentLoopDatasetReady: 'Dataset snapshot ready',
  singleInstrumentLoopDatasetWaiting: 'Waiting for dataset snapshot',
  singleInstrumentLoopStrategyReady: 'Strategy registry ready',
  singleInstrumentLoopStrategyWaiting: 'Waiting for strategy registry',
  singleInstrumentLoopBacktestReady: 'After-cost backtest ready',
  singleInstrumentLoopBacktestWaiting: 'Waiting for after-cost backtest',
  singleInstrumentLoopSignalReady: 'Signal preview ready',
  singleInstrumentLoopSignalWaiting: 'Waiting for signal preview',
  singleInstrumentLoopRiskPassed: 'Risk gate passed',
  singleInstrumentLoopRiskBlocked: 'Risk gate blocked',
  singleInstrumentLoopRiskWaiting: 'Waiting for risk gate',
  singleInstrumentLoopPaperReady: 'Simulation review ready',
  singleInstrumentLoopPaperWaiting: 'Waiting for simulation review',
  singleInstrumentLoopAttributionReady: 'Attribution boundary ready',
  singleInstrumentLoopAttributionWaiting: 'Waiting for attribution boundary',
  totalReturn: 'Total return',
  maxDrawdown: 'Max drawdown',
  totalCost: 'Total cost',
  fillsCount: 'Fills',
  evidenceGate: 'Research gates',
  evidenceGateTitle: 'Strategy validation and review status',
  evidenceGateDetail:
    'Review after-cost, out-of-sample, risk, simulation-review, and account-truth evidence before a strategy can enter manual review or simulation review. This does not enable trading.',
  evidenceGateLoading: 'Loading strategy evidence gates.',
  evidenceGateFailed: 'Strategy evidence gates are unavailable.',
  validationMatrix: 'Validation coverage',
  promotionReadiness: 'Review status',
  accountTruthGate: 'Account truth gate',
  accountTruthEvidencePresent: 'Evidence available',
  accountTruthEvidenceMissing: 'Evidence missing',
  strategyAttributionGate: 'Strategy attribution gate',
  strategyAttributionReady: 'Attribution ready',
  strategyAttributionPending: 'Attribution pending',
  missingRequirements: 'Missing requirements',
  complete: 'Complete',
  incomplete: 'Incomplete',
  noEvidenceRows: 'No strategy evidence rows are available yet.',
  none: 'None',
};
