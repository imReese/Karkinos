import type { Locale } from '../../../shared/preferences/context';
import type { StatusTone } from '../../../shared/ui/workbench';
import { formatPublicCode } from '../../../shared/public-labels';

export const FEE_SCHEDULE_REVIEW_COPY = {
  en: {
    kicker: 'Account-bound research cost',
    title: 'Reviewed fee schedule',
    detail:
      'Compare stock fees with persisted stock buy and sell settlement components before they can become the only eligible daily-candidate research cost model. ETF and fund trades stay in Account Truth but are excluded from this strategy scope.',
    boundary:
      'This review is append-only and revocable. It cannot place an order, register a production strategy, or change capital authority.',
    current: 'Current review',
    statusMissing: 'Missing',
    statusActive: 'Active for research',
    statusBlocked: 'Blocked',
    statusRevoked: 'Revoked',
    noReview: 'No reviewed fee schedule',
    noReviewDetail:
      'Research, promotion, and manual order-ticket generation remain no-action until a current preview passes and a human accepts its exact fingerprint.',
    currentBlocked: 'Stored acceptance is currently blocked',
    currentBlockedDetail:
      'The accepted record remains auditable, but current Account Truth or fee evidence no longer matches it. Downstream use is denied.',
    currentActive: 'Current review is active for research',
    currentActiveDetail:
      'Downstream consumers still recheck this exact review, evidence binding, covered dates, and source drift before every use.',
    currentRevoked: 'Review revoked',
    currentRevokedDetail:
      'The recorded fee schedule is no longer eligible for research, promotion, or tickets.',
    unavailable: 'Reviewed fee schedule evidence is unavailable',
    unavailableDetail:
      'Preview, acceptance, and revocation remain disabled until the persisted review can be read.',
    effectiveWindow: 'Evidence window',
    startDate: 'Effective start date',
    endDate: 'Effective end date',
    preview: 'Recompute preview',
    previewing: 'Recomputing…',
    invalidWindow: 'Choose a valid start and end date.',
    previewReady: 'Exact fee evidence matches',
    previewBlocked: 'Fee evidence remains blocked',
    previewFailed: 'Fee preview failed closed',
    trades: 'Persisted trades',
    matched: 'Component matches',
    buys: 'Buys',
    sells: 'Sells',
    tolerance: 'Tolerance',
    reviewedScope: 'Daily-candidate fee scope: stocks only',
    excludedTrades: 'Out-of-scope ETF/fund trades excluded',
    stockTerms: 'Stock commission',
    sellTax: 'Sell stamp tax',
    stockTransfer: 'Stock transfer fee',
    mismatchBreakdown: 'Mismatch breakdown by asset and side',
    feeMismatch: 'fee',
    taxMismatch: 'tax',
    transferMismatch: 'transfer',
    min: 'minimum',
    reviewer: 'Reviewer',
    approval: 'Accept exact preview for research only',
    approvalDetail:
      'Type the exact confirmation phrase and reviewer identity. The server recomputes the preview and rejects stale fingerprints.',
    confirmation: 'Exact approval confirmation',
    approve: 'Accept reviewed fee schedule',
    approving: 'Accepting…',
    approved: 'Review recorded. Current evidence is rechecked before use.',
    approvalFailed: 'Acceptance failed closed. Recompute and review again.',
    revoke: 'Revoke this exact review',
    revokeDetail:
      'Revocation immediately makes the review ineligible. It does not alter Account Truth, ledger facts, orders, or capital authority.',
    revocationConfirmation: 'Exact revocation confirmation',
    revokeAction: 'Revoke reviewed fee schedule',
    revoking: 'Revoking…',
    revoked: 'Review revoked. Downstream use is denied.',
    revocationFailed: 'Revocation failed closed. Refresh the current review.',
    reviewIdentity: 'Review identity',
    previewIdentity: 'Preview fingerprint',
    scheduleIdentity: 'Schedule fingerprint',
    recordedAt: 'Recorded',
    issues: 'Blocking evidence',
  },
  zh: {
    kicker: '账户绑定的研究成本',
    title: '经审查费率表',
    detail:
      '仅将股票费率与已持久化的股票买卖结算分项逐项比较，通过后才可成为每日候选策略唯一合格的研究成本模型。ETF/基金仍保留在 Account Truth，但排除在策略范围外。',
    boundary: '该审查仅追加、可撤销；不能下单、注册生产策略或改变资金额度。',
    current: '当前审查',
    statusMissing: '缺失',
    statusActive: '仅研究可用',
    statusBlocked: '已阻断',
    statusRevoked: '已撤销',
    noReview: '尚无经审查费率表',
    noReviewDetail:
      '在当前预览通过且人工接受其精确指纹前，研究、晋级和人工订单票据均保持 no-action。',
    currentBlocked: '已接受记录当前被阻断',
    currentBlockedDetail:
      '原记录仍可审计，但当前 Account Truth 或费率证据已不再匹配，下游使用被拒绝。',
    currentActive: '当前审查可用于研究',
    currentActiveDetail:
      '每次使用前，下游仍会复核该精确审查、证据绑定、覆盖日期和来源漂移。',
    currentRevoked: '审查已撤销',
    currentRevokedDetail: '该费率表不再可用于研究、晋级或订单票据。',
    unavailable: '经审查费率证据不可用',
    unavailableDetail: '恢复读取已持久化审查前，预览、接受和撤销均保持禁用。',
    effectiveWindow: '证据窗口',
    startDate: '生效开始日期',
    endDate: '生效结束日期',
    preview: '重新计算预览',
    previewing: '正在重算…',
    invalidWindow: '请选择有效的开始和结束日期。',
    previewReady: '精确费率证据匹配',
    previewBlocked: '费率证据仍被阻断',
    previewFailed: '费率预览已 fail-closed',
    trades: '已持久化成交',
    matched: '分项匹配',
    buys: '买入',
    sells: '卖出',
    tolerance: '容差',
    reviewedScope: '每日候选费用范围：仅股票',
    excludedTrades: '已排除范围外 ETF/基金成交',
    stockTerms: '股票佣金',
    sellTax: '卖出印花税',
    stockTransfer: '股票过户费',
    mismatchBreakdown: '按资产与方向拆分的差异',
    feeMismatch: '佣金',
    taxMismatch: '税费',
    transferMismatch: '过户费',
    min: '最低',
    reviewer: '复核人',
    approval: '仅为研究接受该精确预览',
    approvalDetail:
      '输入完整确认短语和复核人身份；服务端会重新计算预览，并拒绝过期指纹。',
    confirmation: '完整接受确认短语',
    approve: '接受经审查费率表',
    approving: '正在接受…',
    approved: '审查已记录；每次使用前仍会复核当前证据。',
    approvalFailed: '接受已 fail-closed，请重新计算并复核。',
    revoke: '撤销该精确审查',
    revokeDetail:
      '撤销会立即使审查失去资格，但不会改动 Account Truth、账本事实、订单或资金额度。',
    revocationConfirmation: '完整撤销确认短语',
    revokeAction: '撤销经审查费率表',
    revoking: '正在撤销…',
    revoked: '审查已撤销，下游使用被拒绝。',
    revocationFailed: '撤销已 fail-closed，请刷新当前审查。',
    reviewIdentity: '审查身份',
    previewIdentity: '预览指纹',
    scheduleIdentity: '费率表指纹',
    recordedAt: '记录时间',
    issues: '阻断证据',
  },
};

const feeScheduleIssueLabels: Record<string, { en: string; zh: string }> = {
  reviewed_fee_schedule_account_truth_not_ready: {
    en: 'Account Truth is not ready',
    zh: 'Account Truth 尚未就绪',
  },
  reviewed_fee_schedule_account_truth_promotion_blocked: {
    en: 'Account Truth promotion evidence is blocked',
    zh: 'Account Truth 晋级证据被阻断',
  },
  reviewed_fee_schedule_component_mismatch: {
    en: 'Reviewed fee schedule component mismatch',
    zh: '经审查费率分项不匹配',
  },
  reviewed_fee_schedule_buy_coverage_missing: {
    en: 'Persisted buy coverage is missing',
    zh: '缺少已持久化买入覆盖',
  },
  reviewed_fee_schedule_sell_coverage_missing: {
    en: 'Persisted sell coverage is missing',
    zh: '缺少已持久化卖出覆盖',
  },
  reviewed_fee_schedule_source_drift: {
    en: 'Reviewed Account Truth source has drifted',
    zh: '已审查 Account Truth 来源发生漂移',
  },
};

export function formatFeeScheduleIssue(issue: string, locale: Locale) {
  return (
    feeScheduleIssueLabels[issue]?.[locale] ?? formatPublicCode(issue, locale)
  );
}

export function reviewTone(status: string): StatusTone {
  if (status === 'active' || status === 'ready' || status === 'pass') {
    return 'success';
  }
  if (status === 'missing' || status === 'blocked') return 'warning';
  if (status === 'revoked') return 'danger';
  return 'neutral';
}

export function reviewStatusLabel(
  status: 'missing' | 'active' | 'blocked' | 'revoked',
  locale: Locale,
) {
  const text = FEE_SCHEDULE_REVIEW_COPY[locale];
  return {
    missing: text.statusMissing,
    active: text.statusActive,
    blocked: text.statusBlocked,
    revoked: text.statusRevoked,
  }[status];
}
