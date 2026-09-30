import type { Locale } from '../../shared/locale';

export const operationsPageCopy = {
  en: {
    kicker: 'Operations',
    title: 'Operations review',
    subtitle:
      'Review recorded system evidence, the next safe action, and what will clear each item.',
    loading: 'Loading Operations evidence.',
    error: 'Operations evidence could not be loaded.',
    retry: 'Retry read',
    projectionBlocked: 'Operations evidence is unavailable',
    projectionBlockedDetail:
      'The returned evidence did not meet the read-only safety checks, so details remain unavailable.',
    readOnly: 'Read only',
    providerFree: 'No external connection',
    noAuthority: 'No execution authority',
    attentionQueue: 'Evidence review queue',
    attentionEmpty: 'No subsystem currently requires evidence review.',
    healthOverview: 'Health overview',
    subsystemHealth: 'Subsystem health',
    subsystemRegister: 'Subsystem evidence register',
    subsystem: 'Subsystem',
    status: 'Status',
    evidenceStatus: 'Evidence status',
    observedAt: 'Observed at',
    projectedAt: 'Recorded at',
    nextAction: 'Safe next action',
    resolution: 'Clears when',
    fingerprint: 'Task fingerprint',
    openEvidence: 'Open evidence',
    reviewDetails: 'Review details',
    evidenceDetail: 'Evidence detail',
    evidenceDetailDescription:
      'Review why this item is open, what will clear it, the next safe action, and its audit references.',
    closeEvidenceDetail: 'Close evidence detail',
    technicalIdentity: 'Technical evidence ID',
    noTimestamp: 'No observation time recorded',
    viewingDoesNotClear:
      'Viewing or acknowledging this item does not clear its source status.',
    limitations: 'Limitations',
    noLimitations: 'No additional limitations recorded.',
    total: 'Total',
    passed: 'Passed',
    degraded: 'Degraded',
    blocked: 'Blocked',
    manualReview: 'Manual review',
    skipped: 'Skipped',
    sourceBoundary:
      'This page reads recorded facts only. It cannot contact an external service, place or cancel an order, change the ledger or risk controls, or grant capital authority.',
    modeResearch: 'Local-First · Strategy Research Mode',
    modeResearchDesc:
      'Operating in a local-first sandbox. Live broker trading is locked (no capital risk). Blockers below reflect live-connection admission gates and do not affect local research, factor exploration, or backtesting.',
    safetyLockActive: 'Active (Locked)',
    safetyPillCapital: 'Zero Capital Risk · Read-Only',
    safetyPillResearch: 'Research & Backtest Fully Available',
    safetyPillSnapshot: 'Local Data Snapshot',
    filterAll: 'All',
    filterAttention: 'Attention',
    filterNormal: 'Normal',
    attentionHint:
      'The following subsystems currently lack complete evidence and are blocked according to safety rules. Click "Review details" for unblock conditions.',
    impactAssessment: 'Impact Assessment',
    impactDesc:
      'This missing evidence only pauses automated live routines for this module. Local factor research, backtests, and parameter evaluations are unaffected.',
  },
  zh: {
    kicker: '运营',
    title: '运行证据中心',
    subtitle:
      '查看各子系统已记录的证据、安全下一步，以及每个复核项的解除条件。',
    loading: '正在加载运行证据。',
    error: '运行证据加载失败。',
    retry: '重新读取',
    projectionBlocked: '运行证据暂不可用',
    projectionBlockedDetail: '返回的证据未通过只读安全校验，因此暂不提供详情。',
    readOnly: '仅查看',
    providerFree: '未连接外部服务',
    noAuthority: '无执行权限',
    attentionQueue: '证据复核队列',
    attentionEmpty: '当前没有需要证据复核的子系统。',
    healthOverview: '健康概览',
    subsystemHealth: '子系统健康度',
    subsystemRegister: '子系统证据台账',
    subsystem: '子系统',
    status: '状态',
    evidenceStatus: '证据状态',
    observedAt: '证据时间',
    projectedAt: '记录时间',
    nextAction: '安全下一步',
    resolution: '解除条件',
    fingerprint: '任务指纹',
    openEvidence: '打开证据',
    reviewDetails: '查看详情',
    evidenceDetail: '证据详情',
    evidenceDetailDescription:
      '查看该事项为何未解除、解除条件、安全下一步和审计标识。',
    closeEvidenceDetail: '关闭证据详情',
    technicalIdentity: '技术证据标识',
    noTimestamp: '暂无记录时间',
    viewingDoesNotClear: '仅查看或确认该事项不会清除源状态。',
    limitations: '限制',
    noLimitations: '未记录额外限制。',
    total: '总数',
    passed: '通过',
    degraded: '降级',
    blocked: '阻断',
    manualReview: '人工复核',
    skipped: '跳过',
    sourceBoundary:
      '本页只读取已记录事实；不会发起外部网络请求、提交或撤销订单，也不会改动账本、风控、紧急停止或资本授权。',
    modeResearch: '本地离线 · 策略研究模式',
    modeResearchDesc:
      '当前运行于本地离线沙盒，实盘交易严格锁定（无资金风险）。下方标红的阻断项属于实盘接口前置门禁，不影响本地因子挖掘、策略研究与历史回测。',
    safetyLockActive: '已启用 (已锁定)',
    safetyPillCapital: '零资金风险 · 仅本地只读',
    safetyPillResearch: '策略研究与回测完全可用',
    safetyPillSnapshot: '本地数据快照',
    filterAll: '全部',
    filterAttention: '需关注',
    filterNormal: '正常',
    attentionHint:
      '以下子系统目前缺少完整凭据，已按风控规则阻断相关在线计算。点击「查看详情」可了解原因及解除条件。',
    impactAssessment: '影响评估',
    impactDesc:
      '此项缺少证据仅影响该模块的自动化实盘计算，不影响本地因子研究、历史回测及参数寻优。',
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type OperationsPageCopy = (typeof operationsPageCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    operationsPage: OperationsPageCopy;
  }
}
