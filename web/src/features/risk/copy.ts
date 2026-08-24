import type { Locale } from '../../shared/locale';

export const riskPageCopy = {
  en: {
    kicker: 'Risk',
    title: 'Risk control center',
    subtitle:
      'Review current alerts, capital pressure, and equity attribution in one place.',
    loadingTitle: 'Checking risk evidence',
    loading:
      'Reading saved account and risk evidence. No external refresh or account fact is changed.',
    error: 'Failed to load risk control center.',
    refreshError:
      'Some risk data could not be refreshed. Showing the latest successful risk record; review data status before acting.',
    decisionHandoffKicker: 'Decision handoff',
    decisionHandoffTitle: 'Run pre-trade risk gate for candidates',
    decisionHandoffDetail: (candidates: number, checked: number) =>
      `${candidates} candidates are waiting for risk checks; ${checked} have been checked.`,
    batchRunnerMissing: 'Batch risk gate is ready',
    runBatchRiskGate: 'Run batch risk gate',
    runningBatchRiskGate: 'Running risk gate...',
    batchRiskGateDone: (passed: number, blocked: number) =>
      `Batch risk gate complete: ${passed} passed, ${blocked} blocked.`,
    batchRiskGateFailed: 'Batch risk gate failed.',
    decisionHandoffWhat: 'What to handle: candidate risk gate',
    decisionHandoffHow:
      'How: wait for the batch runner or use a single-instrument preview',
    decisionHandoffDoNot:
      'Do not inspect every candidate or submit orders directly',
    returnToDecision: 'Return to decision platform',
    alerts: 'Active alerts',
    blockingRegister: 'Active risk priorities',
    blockingRegisterDetail:
      'Only warning and blocked risk states appear here; normal boundaries stay quiet.',
    noBlockingItems: 'No warning or blocked risk states are recorded.',
    clearsWithNewProjection:
      'A newer risk record confirms a lower-severity state.',
    nextStep: 'Suggested next step',
    equityBridge: 'Equity bridge',
    recentDrivers: 'Recent impact events',
    positionDrivers: 'Position drivers',
    emptyDrivers: 'No explainability drivers available yet.',
    metrics: 'Risk metrics',
    currentDrawdown: 'Current drawdown',
    currentDrawdownDetail:
      'Distance between current equity and the latest portfolio peak.',
    maxDrawdown: 'Max drawdown',
    maxDrawdownDetail:
      'Largest observed peak-to-trough loss across the equity curve.',
    grossExposure: 'Gross exposure',
    grossExposureDetail: 'Capital currently deployed in non-cash positions.',
    cashRatio: 'Cash ratio',
    cashRatioDetail: 'Immediate liquidity buffer for rebalance or defense.',
    largestPosition: 'Largest position',
    largestPositionDetail:
      'Single-name concentration of the biggest active holding.',
    top3Concentration: 'Top 3 concentration',
    top3ConcentrationDetail:
      'Aggregate concentration across the three largest holdings.',
    drawdown: 'Drawdown path',
    exposure: 'Exposure buckets',
    bucketHeavy: 'Heavy conviction',
    bucketCore: 'Core',
    bucketStarter: 'Starter',
    bucketSmall: 'Small / tracking',
    bucketCash: 'Cash reserve',
    concentration: 'Concentration drill-down',
    noConcentration:
      'No active positions available for concentration analysis.',
  },
  zh: {
    kicker: '风险',
    title: '风控中心',
    subtitle: '统一查看风险提示、资金压力与净值归因。',
    loadingTitle: '正在核对风险证据',
    loading: '正在读取已保存的账户与风控证据；不会刷新外部数据或改写账户事实。',
    error: '风控中心加载失败。',
    refreshError:
      '部分风控数据暂时无法刷新。当前显示最近一次成功记录；继续操作前请复核数据状态。',
    decisionHandoffKicker: '决策交接',
    decisionHandoffTitle: '候选动作需要下单前风控',
    decisionHandoffDetail: (candidates: number, checked: number) =>
      `${candidates} 个候选等待风控检查；当前已检查 ${checked} 个。`,
    batchRunnerMissing: '批量风控入口已接入',
    runBatchRiskGate: '运行批量风控',
    runningBatchRiskGate: '正在运行风控…',
    batchRiskGateDone: (passed: number, blocked: number) =>
      `批量风控完成：通过 ${passed}，阻断 ${blocked}。`,
    batchRiskGateFailed: '批量风控运行失败。',
    decisionHandoffWhat: '要处理什么：候选动作风控闸门',
    decisionHandoffHow: '怎么处理：等待批量运行器，或先用单标的风控预检',
    decisionHandoffDoNot: '不要逐个翻候选，也不要直接下单。',
    returnToDecision: '回到决策平台',
    alerts: '当前风险提示',
    blockingRegister: '当前风险优先项',
    blockingRegisterDetail: '这里只展示警告与阻断状态；正常边界保持安静。',
    noBlockingItems: '当前没有已记录的警告或阻断状态。',
    clearsWithNewProjection: '更新后的风险记录确认严重度已降低时解除。',
    nextStep: '建议动作',
    equityBridge: '净值桥',
    recentDrivers: '最近影响事件',
    positionDrivers: '持仓驱动',
    emptyDrivers: '当前还没有可解释的驱动数据。',
    metrics: '风险指标',
    currentDrawdown: '当前回撤',
    currentDrawdownDetail: '当前净值距离最近峰值的回撤幅度。',
    maxDrawdown: '最大回撤',
    maxDrawdownDetail: '净值曲线历史上最大的峰谷回撤。',
    grossExposure: '总暴露',
    grossExposureDetail: '当前配置在非现金资产中的资金比例。',
    cashRatio: '现金占比',
    cashRatioDetail: '用于再平衡或防守的可用流动性缓冲。',
    largestPosition: '最大单一持仓',
    largestPositionDetail: '当前最大活跃持仓带来的单标的集中度。',
    top3Concentration: '前三集中度',
    top3ConcentrationDetail: '前三大持仓合计带来的集中度。',
    drawdown: '回撤路径',
    exposure: '暴露分桶',
    bucketHeavy: '高信念仓位',
    bucketCore: '核心仓位',
    bucketStarter: '起始仓位',
    bucketSmall: '小仓位 / 跟踪仓',
    bucketCash: '现金储备',
    concentration: '集中度拆解',
    noConcentration: '当前暂无活跃持仓，无法拆解集中度。',
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type RiskPageCopy = (typeof riskPageCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    riskPage: RiskPageCopy;
  }
}
