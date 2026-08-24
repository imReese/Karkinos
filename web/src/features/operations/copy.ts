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
    providerFree: '未联系外部服务',
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
      '本页只读取已记录事实；不会联系外部服务、提交或撤销订单，也不会改动账本、风控、紧急停止或资本授权。',
  },
} satisfies Record<Locale, Record<string, unknown>>;

export type OperationsPageCopy = (typeof operationsPageCopy)[Locale];

declare module '../../shared/i18n/context' {
  interface ApplicationCopy {
    operationsPage: OperationsPageCopy;
  }
}
