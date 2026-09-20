import type { Locale } from '../../../shared/locale';
import type { AccountStateResponse } from '../overview-feature-boundary';

export const overviewPresentation = {
  en: {
    cumulativePnl: 'Cumulative P&L',
    latestPnl: 'Latest trading-session P&L',
    todayDrivers: 'Today’s main contributors',
    previousDrivers: 'Previous session contributors',
    sessionDrivers: 'Session contributors',
    returnUnavailable: 'Return unavailable',
    pendingValuation: 'Awaiting valuation',
    marketAndData: 'Market & data',
    marketStatusLabel: 'Market',
    refreshStatusLabel: 'Refresh',
    attentionStatusLabel: 'To-dos',
    attentionAvailable: 'Available',
    attentionUnavailableShort: 'Unavailable',
    valuationStatus: 'Valuation status',
    cashRatioUnavailable: 'Cash ratio awaits valuation',
    stocksEvidence: 'Stock close',
    fundsEvidence: 'Fund NAV',
    pendingHoldingsLabel: 'Awaiting valuation',
    holdings: 'Holdings',
    holdingsDetail: 'Active positions',
    viewPortfolio: 'View portfolio',
    todayNarrative: 'What happened today',
    contributors: 'Contributors',
    detractors: 'Detractors',
    noPositiveDrivers: 'No positive position contribution is available.',
    noNegativeDrivers: 'No negative position contribution is available.',
    accountEvents: 'Account events',
    noAccountEvents: 'No new account events.',
    assetAllocation: 'Asset allocation',
    allocationUnavailable: 'Allocation awaits a complete valuation.',
    riskSummary: 'Risk summary',
    noOpenExposure: 'No open position exposure',
    unavailableShort: 'Unavailable',
    attention: 'Actions & to-dos',
    attentionUnavailable: 'To-do status unavailable',
    attentionUnavailableDetail: 'Open Operations to review the current state.',
    details: 'Data details',
    financialDetails: 'Performance details',
    usable: 'Current valuation usable',
    degraded: 'Valuation evidence needs review',
    unavailable: 'Valuation unavailable',
    closeBasis: 'close',
    asOf: 'Data as of',
    pre_open: 'Before market open',
    open: 'Market open',
    midday_break: 'Session break',
    after_close: 'Market closed',
    break: 'Session break',
    closed: 'Market closed',
    non_trading_day: 'Market closed',
    unknown: 'Market session unverified',
    latestSession: 'Latest completed session',
    nextSession: 'Next trading session',
    refreshHealth: 'Refresh health',
    healthy: 'Healthy',
    running: 'Refreshing',
    refreshDegraded: 'Latest refresh failed',
    unknownHealth: 'Unavailable',
    refreshAttempt: 'Latest attempt',
    decisionReadiness: 'Decision readiness',
    ready: 'Ready for review',
    blocked: 'Blocked',
    snapshot: 'Valuation snapshot',
    ledgerCutoff: 'Ledger cutoff',
    ledgerFingerprint: 'Ledger fingerprint',
    quoteFingerprint: 'Quote-set fingerprint',
    policy: 'Valuation policy',
    stateRefreshFailed:
      'Could not refresh this view. The last loaded portfolio remains visible.',
    cumulativeHelp: 'Realized and unrealized P&L',
  },
  zh: {
    cumulativePnl: '累计盈亏',
    latestPnl: '最近交易日盈亏',
    todayDrivers: '今日主要影响',
    previousDrivers: '上一交易日主要影响',
    sessionDrivers: '交易日主要影响',
    returnUnavailable: '收益率暂不可用',
    pendingValuation: '待估值',
    marketAndData: '市场与数据',
    marketStatusLabel: '行情',
    refreshStatusLabel: '刷新',
    attentionStatusLabel: '待办',
    attentionAvailable: '可用',
    attentionUnavailableShort: '暂不可用',
    valuationStatus: '估值状态',
    cashRatioUnavailable: '现金占比待估值',
    stocksEvidence: '股票收盘',
    fundsEvidence: '基金净值',
    pendingHoldingsLabel: '待估值持仓',
    holdings: '当前持仓',
    holdingsDetail: '当前持仓数量',
    viewPortfolio: '查看全部持仓',
    todayNarrative: '今天发生了什么',
    contributors: '收益贡献',
    detractors: '最大拖累',
    noPositiveDrivers: '暂无可归因的正向持仓贡献。',
    noNegativeDrivers: '暂无可归因的负向持仓贡献。',
    accountEvents: '账户事件',
    noAccountEvents: '暂无新的账户事件。',
    assetAllocation: '资产配置',
    allocationUnavailable: '完整估值形成后显示资产配置。',
    riskSummary: '风险摘要',
    noOpenExposure: '当前没有未平仓资产暴露',
    unavailableShort: '暂不可用',
    attention: '操作提醒 / 待办',
    attentionUnavailable: '待办状态暂不可用',
    attentionUnavailableDetail: '前往运行中心复核当前状态。',
    details: '数据详情',
    financialDetails: '收益详情',
    usable: '当前估值可用',
    degraded: '估值证据待复核',
    unavailable: '估值暂不可用',
    closeBasis: '收盘',
    asOf: '数据截至',
    pre_open: '市场开盘前',
    open: '市场交易中',
    midday_break: '午间休市',
    after_close: '市场休市',
    break: '午间休市',
    closed: '市场休市',
    non_trading_day: '市场休市',
    unknown: '交易日历待验证',
    latestSession: '最近完成交易日',
    nextSession: '下一交易日',
    refreshHealth: '刷新状态',
    healthy: '正常',
    running: '正在刷新',
    refreshDegraded: '最近刷新失败',
    unknownHealth: '暂不可用',
    refreshAttempt: '最近尝试',
    decisionReadiness: '决策就绪状态',
    ready: '可进入复核',
    blocked: '已阻断',
    snapshot: '估值快照',
    ledgerCutoff: '账本截止点',
    ledgerFingerprint: '账本指纹',
    quoteFingerprint: '价格集指纹',
    policy: '估值策略',
    stateRefreshFailed: '页面刷新失败，保留最近加载的组合状态。',
    cumulativeHelp: '已实现与未实现盈亏',
  },
} satisfies Record<Locale, Record<string, string>>;

export function overviewSessionLabels(
  state: AccountStateResponse,
  locale: Locale,
) {
  const labels = overviewPresentation[locale];
  const date = state.summary.latest_session_date;
  const session = state.overview.market_session;
  if (date && date === session.market_date) {
    return { drivers: labels.todayDrivers };
  }
  if (date && date === session.latest_completed_trade_date) {
    return { drivers: labels.previousDrivers };
  }
  return { drivers: labels.sessionDrivers };
}

export function shortDate(value: string | null | undefined) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat('en-US', {
    month: '2-digit',
    day: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(date);
}

export function pnlTone(value: number | null | undefined) {
  return typeof value !== 'number' || value === 0
    ? 'text-[var(--app-text)]'
    : value > 0
      ? 'text-[var(--app-pnl-positive)]'
      : 'text-[var(--app-pnl-negative)]';
}
