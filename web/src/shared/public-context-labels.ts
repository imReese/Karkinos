import type { Locale } from './locale';

type LabelMap = Record<string, string>;

export const STATUS_LABELS: Record<Locale, LabelMap> = {
  en: {
    all: 'All',
    accepted: 'Accepted',
    acknowledged_no_retry: 'Acknowledged — no retry',
    active: 'Active',
    attached: 'Attached',
    available: 'Available',
    benchmark_passed: 'Benchmark passed',
    blocked: 'Blocked',
    blocked_by_data_quality: 'Blocked by data quality',
    buy: 'Buy',
    cache: 'Cached quotes',
    cache_only: 'Cache only',
    cache_only_after_market_data_permission_fallback:
      'Cache only after data-permission fallback',
    canceled: 'Canceled',
    complete: 'Complete',
    completed: 'Completed',
    confirmed: 'Confirmed',
    confirmed_nav_missing: 'Confirmed NAV missing',
    data_review_required: 'Data review required',
    degraded: 'Degraded',
    error: 'Error',
    estimated: 'Estimated',
    estimated_from_research_costs: 'Estimated from research costs',
    failed: 'Failed',
    filled: 'Filled',
    fresh: 'Fresh',
    healthy: 'Healthy',
    hold: 'Hold',
    ignored: 'Ignored',
    incomplete: 'Incomplete',
    known_difference: 'Known difference',
    ledger_candidate: 'Ledger correction candidate',
    live: 'Live',
    manual: 'Manual',
    manual_confirm: 'Manual confirmation',
    mismatch: 'Mismatch',
    missing: 'Missing',
    needs_investigation: 'Needs investigation',
    no_action: 'No action',
    not_attached: 'Not attached',
    not_configured: 'Not configured',
    not_evaluated: 'Review not evaluated yet',
    not_recorded: 'Not recorded',
    not_promotable: 'Not ready for review',
    not_started: 'Not started',
    ok: 'OK',
    partial: 'Partial',
    pass: 'Pass',
    passed: 'Passed',
    pending: 'Pending',
    pending_confirm: 'Pending approval',
    ready: 'Ready for review',
    ready_for_manual_confirmation: 'Ready for manual confirmation',
    promotable_for_paper_review: 'Ready for simulation review',
    rejected: 'Rejected',
    research_only: 'Research only',
    refreshed: 'Refreshed',
    review_required: 'Review required',
    order_journey_closed: 'Order journey closed',
    submission_rejection_reviewed: 'Submission rejection reviewed',
    sell: 'Sell',
    shadow_review: 'Simulation review',
    skipped: 'Skipped',
    stale: 'Stale quotes',
    unavailable: 'Unavailable',
    unknown: 'Unknown',
    warning: 'Warning',
    account_truth_review_required: 'Account truth review required',
    strategy_attribution_review_required:
      'Strategy attribution review required',
  },
  zh: {
    all: '全部',
    accepted: '已接受',
    acknowledged_no_retry: '已确认不得重试',
    active: '已启用',
    attached: '已关联',
    available: '可用',
    benchmark_passed: '基准验证通过',
    blocked: '阻断',
    blocked_by_data_quality: '数据质量阻断',
    buy: '买入',
    cache: '缓存行情',
    cache_only: '仅使用缓存',
    cache_only_after_market_data_permission_fallback:
      '数据权限回退后仅使用缓存',
    canceled: '已取消',
    complete: '已完成',
    completed: '已完成',
    confirmed: '已确认',
    confirmed_nav_missing: '确认净值缺失',
    data_review_required: '需要数据复核',
    degraded: '降级',
    error: '错误',
    estimated: '估算中',
    estimated_from_research_costs: '基于研究成本估算',
    failed: '失败',
    filled: '已成交',
    fresh: '已更新',
    healthy: '健康',
    hold: '持有',
    ignored: '已忽略',
    incomplete: '未完成',
    known_difference: '已知差异',
    ledger_candidate: '账本修正候选',
    live: '实时行情',
    manual: '手动',
    manual_confirm: '人工确认',
    mismatch: '不一致',
    missing: '缺失',
    needs_investigation: '需要继续调查',
    no_action: '不操作',
    not_attached: '未关联',
    not_configured: '未配置',
    not_evaluated: '尚未完成复核评估',
    not_recorded: '尚未记录',
    not_promotable: '暂不满足复核条件',
    not_started: '尚未开始',
    ok: '正常',
    partial: '部分可用',
    pass: '通过',
    passed: '已通过',
    pending: '待处理',
    pending_confirm: '待审批',
    ready: '可进入复核',
    ready_for_manual_confirmation: '可人工确认',
    promotable_for_paper_review: '可进入模拟复核',
    rejected: '已拒绝',
    research_only: '仅研究',
    refreshed: '已刷新',
    review_required: '需要复核',
    order_journey_closed: '订单旅程已收敛',
    submission_rejection_reviewed: '提交拒绝已复核',
    sell: '卖出',
    shadow_review: '模拟复核',
    skipped: '已跳过',
    stale: '行情过期',
    unavailable: '不可用',
    unknown: '未知',
    warning: '警告',
    account_truth_review_required: '需要账户事实复核',
    strategy_attribution_review_required: '需要策略归因复核',
  },
};

export const REVIEW_ACTION_LABELS: Record<Locale, LabelMap> = {
  en: {
    accepted: 'Mark accepted',
    ignored: 'Ignore difference',
    known_difference: 'Mark known difference',
    ledger_candidate: 'Create ledger candidate',
    needs_investigation: 'Mark needs investigation',
  },
  zh: {
    accepted: '标记为已接受',
    ignored: '忽略该差异',
    known_difference: '标记为已知差异',
    ledger_candidate: '列为账本修正候选',
    needs_investigation: '标记为需要调查',
  },
};

export const EVIDENCE_SOURCE_LABELS: Record<Locale, LabelMap> = {
  en: {
    broker_event: 'Broker evidence',
  },
  zh: {
    broker_event: '券商证据',
  },
};

export const EVIDENCE_REFERENCE_TYPE_LABELS: Record<Locale, LabelMap> = {
  en: {
    action: 'Candidate action',
    dataset_snapshot: 'Dataset snapshot',
    fill: 'Fill evidence',
    order: 'Order evidence',
    paper_fill: 'Simulation review fill',
    paper_order: 'Simulation review order',
    paper_shadow_fill: 'Simulation review fill',
    paper_shadow_order: 'Simulation review order',
    review: 'Manual review',
    risk: 'Risk check',
    risk_decision: 'Risk check',
    risk_gate: 'Risk gate',
    signal: 'Signal evidence',
    signal_preview: 'Signal preview',
    strategy: 'Strategy',
    strategy_signal: 'Strategy signal',
  },
  zh: {
    action: '候选动作',
    dataset_snapshot: '数据快照',
    fill: '成交证据',
    order: '订单证据',
    paper_fill: '模拟复核成交',
    paper_order: '模拟复核订单',
    paper_shadow_fill: '模拟复核成交',
    paper_shadow_order: '模拟复核订单',
    review: '人工复核',
    risk: '风控检查',
    risk_decision: '风控检查',
    risk_gate: '风控闸门',
    signal: '信号证据',
    signal_preview: '信号预览',
    strategy: '策略',
    strategy_signal: '策略信号',
  },
};

export const BROKER_EVIDENCE_TYPE_LABELS: Record<Locale, LabelMap> = {
  en: {
    cash_snapshot: 'Cash snapshot',
    dividend: 'Dividend',
    fee: 'Fee',
    position_snapshot: 'Position snapshot',
    tax: 'Tax',
    trade_buy: 'Buy trade',
    trade_sell: 'Sell trade',
    transfer: 'Transfer',
  },
  zh: {
    cash_snapshot: '现金快照',
    dividend: '分红',
    fee: '费用',
    position_snapshot: '持仓快照',
    tax: '税费',
    trade_buy: '买入成交',
    trade_sell: '卖出成交',
    transfer: '转账',
  },
};

export const NOTE_LABELS: Record<Locale, LabelMap> = {
  en: {
    'account_truth.no_broker_evidence':
      'No broker evidence has been imported for reconciliation.',
    'account_truth.cash_snapshot_missing':
      'Broker cash snapshot is missing, so cash reconciliation is incomplete.',
    'account_truth.cash_compared':
      'Broker cash snapshot was compared with the Karkinos cash balance.',
    'account_truth.position_snapshot_missing':
      'Broker position snapshot is missing, so position reconciliation is incomplete.',
    'account_truth.position_snapshot_scope_incomplete':
      'Broker position snapshots cover only part of the portfolio; positions from other platforms remain unverified.',
    'account_truth.position_quantity_compared':
      'Broker position quantity was compared with the Karkinos position quantity.',
    'account_truth.fees_compared':
      'Broker fees were compared with Karkinos ledger fees.',
    'account_truth.taxes_compared':
      'Broker taxes were compared with Karkinos ledger taxes.',
    'account_truth.trade_gross_amount_compared':
      'Broker trade gross amount was compared with the Karkinos gross amount before fees and taxes.',
    'account_truth.net_cash_impact_compared':
      'Broker signed net cash impact was compared with the Karkinos net cash impact after fees and taxes.',
    'account_truth.trade_commission_compared':
      'Broker trade commission was compared with Karkinos trade commission.',
    'account_truth.trade_tax_compared':
      'Broker trade tax was compared with Karkinos trade tax.',
    'account_truth.transfer_fee_compared':
      'Broker transfer fee was compared with Karkinos transfer fee.',
    'account_truth.cost_basis_compared':
      'Broker cost basis was compared with Karkinos cost basis.',
    'Broker cost basis does not match local ledger.':
      'Broker cost basis does not match the Karkinos local ledger.',
    'P/L contribution is not calculated until fills are reconciled with position and valuation history.':
      'P/L contribution is waiting for fills to be reconciled with position and valuation history.',
    'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.':
      'Contribution is estimated from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
    'Local valuation is missing for linked evidence.':
      'Local valuation is missing for linked evidence.',
    'Order evidence is present, but fills are blocked.':
      'Order evidence is present, but fills are blocked.',
    'Preview evidence is not production attribution evidence.':
      'Preview evidence is not production attribution evidence.',
    'Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.':
      'Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.',
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.':
      'This assignment only sets research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.':
      'This assignment only sets research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.',
    'Requires paper/shadow review before promotion.':
      'Requires simulation review before manual review.',
    'Candidate actions should be compared against paper/shadow evidence.':
      'Candidate actions should be compared with simulation evidence.',
    'Research evidence is not a profitability guarantee.':
      'Research evidence is not a profitability guarantee.',
    'Backtest evidence is not a profitability claim.':
      'Backtest evidence is not a profitability claim.',
    'Validation evidence is not investment advice or a profitability guarantee.':
      'Validation evidence is not investment advice or a profitability guarantee.',
    'Review status is an audit signal only.':
      'Review status is an audit signal only.',
    'Account Truth review requires staged broker evidence before trusted use.':
      'Stage broker evidence and review it before account facts are used in decisions.',
    'Unresolved reconciliation items require review.':
      'Unresolved reconciliation differences need manual review.',
    'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.':
      'Multiple tests can overfit historical data; require out-of-sample and after-cost review.',
    'Parameter sweep rankings are research evidence, not investment advice.':
      'Parameter sweep rankings are research evidence, not investment advice.',
    'Strategy comparison results are research evidence, not investment advice.':
      'Strategy comparison results are research evidence, not investment advice.',
    'Reviewed from Account Truth center.':
      'Recorded from the Account Truth review center.',
  },
  zh: {
    'account_truth.no_broker_evidence': '尚未导入可用于复核的券商证据。',
    'account_truth.cash_snapshot_missing':
      '缺少券商现金快照，现金复核尚不完整。',
    'account_truth.cash_compared':
      '券商现金快照已与 Karkinos 本地现金余额对比。',
    'account_truth.position_snapshot_missing':
      '缺少券商持仓快照，持仓复核尚不完整。',
    'account_truth.position_snapshot_scope_incomplete':
      '券商持仓快照仅覆盖部分资产类别；其他平台持仓仍待补充证据。',
    'account_truth.position_quantity_compared':
      '券商持仓数量已与 Karkinos 本地持仓数量对比。',
    'account_truth.fees_compared': '券商费用已与 Karkinos 本地账本费用对比。',
    'account_truth.taxes_compared': '券商税费已与 Karkinos 本地账本税费对比。',
    'account_truth.trade_gross_amount_compared':
      '券商成交总额已与 Karkinos 费税前成交总额对比。',
    'account_truth.net_cash_impact_compared':
      '券商含费税净现金影响已与 Karkinos 本地账本净现金影响对比。',
    'account_truth.trade_commission_compared':
      '券商交易佣金已与 Karkinos 本地交易佣金对比。',
    'account_truth.trade_tax_compared':
      '券商交易税费已与 Karkinos 本地交易税费对比。',
    'account_truth.transfer_fee_compared':
      '券商过户费已与 Karkinos 本地过户费对比。',
    'account_truth.cost_basis_compared':
      '券商成本价已与 Karkinos 本地成本价对比。',
    'No broker evidence events are available for reconciliation.':
      '尚未导入可用于复核的券商证据。',
    'Broker cash snapshot is missing; cash reconciliation is incomplete.':
      '缺少券商现金快照，现金复核尚不完整。',
    'Broker cash snapshot compared with Karkinos cash balance.':
      '券商现金快照已与 Karkinos 本地现金余额对比。',
    'Broker position snapshot is missing; position reconciliation is incomplete.':
      '缺少券商持仓快照，持仓复核尚不完整。',
    'Broker position does not match local ledger projection.':
      '券商持仓与 Karkinos 本地账本推算不一致。',
    'Broker cost basis does not match local ledger.':
      '券商成本价与 Karkinos 本地账本不一致。',
    'Broker position quantity compared with Karkinos position quantity.':
      '券商持仓数量已与 Karkinos 本地持仓数量对比。',
    'Broker fees compared with Karkinos ledger fees.':
      '券商费用已与 Karkinos 本地账本费用对比。',
    'Broker taxes compared with Karkinos ledger taxes.':
      '券商税费已与 Karkinos 本地账本税费对比。',
    'Broker trade gross amount compared with Karkinos trade gross amount before fees and taxes.':
      '券商成交总额已与 Karkinos 费税前成交总额对比。',
    'Broker signed net cash impact compared with Karkinos signed ledger cash impact after fees and taxes.':
      '券商含费税净现金影响已与 Karkinos 本地账本净现金影响对比。',
    'Broker trade commission compared with Karkinos trade commission.':
      '券商交易佣金已与 Karkinos 本地交易佣金对比。',
    'Broker trade tax compared with Karkinos trade tax.':
      '券商交易税费已与 Karkinos 本地交易税费对比。',
    'Broker transfer fee component compared with Karkinos transfer fee component.':
      '券商过户费已与 Karkinos 本地过户费对比。',
    'Broker cost basis compared with Karkinos cost basis.':
      '券商成本价已与 Karkinos 本地成本价对比。',
    'P/L contribution is not calculated until fills are reconciled with position and valuation history.':
      '收益贡献需要先把成交、持仓和估值历史对齐后再计算。',
    'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.':
      '收益贡献仅基于已归属成交和本地最新行情估算；手工交易与现金流水暂不计入。',
    'Local valuation is missing for linked evidence.':
      '已归属证据缺少本地估值。',
    'Order evidence is present, but fills are blocked.':
      '已有订单证据，但成交证据仍被阻断。',
    'Preview evidence is not production attribution evidence.':
      '当前只是预览证据，还不是可用于正式归因的生产证据。',
    'Strategy P/L stays unavailable until signal, review, order, and fill facts are linked.':
      '只有信号、复核、订单和成交事实全部关联后，才允许计算策略收益。',
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.':
      '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
    'Strategy assignment is research context; contribution is shown only when current signals, reviews, orders, and fills have traceable references.':
      '策略绑定只设置研究上下文；只有当前账户具备可追溯的信号、复核、订单与成交引用后，才展示策略收益。',
    'Requires paper/shadow review before promotion.':
      '进入人工复核前，需要完成模拟复核。',
    'Candidate actions should be compared against paper/shadow evidence.':
      '候选动作需要先和模拟复核证据对比。',
    'Research evidence is not a profitability guarantee.':
      '研究证据不代表收益保证。',
    'Backtest evidence is not a profitability claim.':
      '研究证据不代表收益保证。',
    'Validation evidence is not investment advice or a profitability guarantee.':
      '验证证据不构成投资建议，也不保证收益。',
    'Review status is an audit signal only.':
      '复核状态只是审计信号，不会自动上线或下单。',
    'Account Truth review requires staged broker evidence before trusted use.':
      '需要先暂存券商证据并完成复核，才能把账户事实用于决策。',
    'Unresolved reconciliation items require review.':
      '仍有对账差异需要人工复核。',
    'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.':
      '多次参数测试可能过拟合历史数据，需要样本外与成本后复核。',
    'Parameter sweep rankings are research evidence, not investment advice.':
      '参数扫描排名只是研究证据，不构成投资建议。',
    'Strategy comparison results are research evidence, not investment advice.':
      '策略对比结果只是研究证据，不构成投资建议。',
    'Reviewed from Account Truth center.': '已从账户事实复核中心记录人工处理。',
  },
};
