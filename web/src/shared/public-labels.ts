import type { Locale } from '../app/preferences';

type LabelMap = Record<string, string>;

const STATUS_LABELS: Record<Locale, LabelMap> = {
  en: {
    all: 'All',
    accepted: 'Accepted',
    active: 'Active',
    attached: 'Attached',
    available: 'Available',
    benchmark_passed: 'Benchmark passed',
    blocked: 'Blocked',
    buy: 'Buy',
    cache_only: 'Cache only',
    cache_only_after_market_data_permission_fallback:
      'Cache only after data-permission fallback',
    canceled: 'Canceled',
    complete: 'Complete',
    completed: 'Completed',
    confirmed: 'Confirmed',
    degraded: 'Degraded',
    error: 'Error',
    failed: 'Failed',
    filled: 'Filled',
    fresh: 'Fresh',
    healthy: 'Healthy',
    hold: 'Hold',
    ignored: 'Ignored',
    incomplete: 'Incomplete',
    known_difference: 'Known difference',
    ledger_candidate: 'Ledger candidate',
    live: 'Live',
    manual: 'Manual',
    manual_confirm: 'Manual confirmation',
    mismatch: 'Mismatch',
    missing: 'Missing',
    needs_investigation: 'Needs investigation',
    not_attached: 'Not attached',
    not_configured: 'Not configured',
    not_evaluated: 'Not evaluated',
    not_started: 'Not started',
    ok: 'OK',
    partial: 'Partial',
    pass: 'Pass',
    passed: 'Passed',
    pending: 'Pending',
    pending_confirm: 'Pending approval',
    ready: 'Ready for review',
    ready_for_manual_confirmation: 'Ready for manual confirmation',
    rejected: 'Rejected',
    research_only: 'Research only',
    refreshed: 'Refreshed',
    review_required: 'Review required',
    sell: 'Sell',
    shadow_review: 'Simulation review',
    skipped: 'Skipped',
    stale: 'Cached / stale',
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
    active: '已启用',
    attached: '已关联',
    available: '可用',
    benchmark_passed: '基准验证通过',
    blocked: '阻断',
    buy: '买入',
    cache_only: '仅使用缓存',
    cache_only_after_market_data_permission_fallback:
      '数据权限回退后仅使用缓存',
    canceled: '已取消',
    complete: '已完成',
    completed: '已完成',
    confirmed: '已确认',
    degraded: '降级',
    error: '错误',
    failed: '失败',
    filled: '已成交',
    fresh: '已更新',
    healthy: '健康',
    hold: '持有',
    ignored: '已忽略',
    incomplete: '未完成',
    known_difference: '已知差异',
    ledger_candidate: '账本候选',
    live: '实时可用',
    manual: '手动',
    manual_confirm: '人工确认',
    mismatch: '不一致',
    missing: '缺失',
    needs_investigation: '需要继续调查',
    not_attached: '未关联',
    not_configured: '未配置',
    not_evaluated: '未评估',
    not_started: '尚未开始',
    ok: '正常',
    partial: '部分可用',
    pass: '通过',
    passed: '已通过',
    pending: '待处理',
    pending_confirm: '待审批',
    ready: '可进入复核',
    ready_for_manual_confirmation: '可人工确认',
    rejected: '已拒绝',
    research_only: '仅研究',
    refreshed: '已刷新',
    review_required: '需要复核',
    sell: '卖出',
    shadow_review: '模拟复盘',
    skipped: '已跳过',
    stale: '缓存 / 陈旧',
    unavailable: '不可用',
    unknown: '未知',
    warning: '警告',
    account_truth_review_required: '需要账户事实复核',
    strategy_attribution_review_required: '需要策略归因复核',
  },
};

const CODE_LABELS: Record<Locale, LabelMap> = {
  en: {
    account_truth_gate_pass: 'Account truth gate must pass',
    account_truth_score_unavailable:
      'Account truth score is unavailable because no broker evidence has been staged',
    after_cost_report: 'After-cost report',
    cash_missing: 'Cash evidence is missing',
    cost_basis_missing: 'Cost-basis evidence is missing',
    evidence_linked_pnl_pending: 'Evidence linked, P/L pending',
    estimated_from_linked_fills: 'Estimated from linked fills',
    fee_missing: 'Fee evidence is missing',
    import_and_reconcile_broker_evidence:
      'Import broker evidence and run reconciliation',
    link_strategy_signals_orders_fills_and_contribution:
      'Link strategy signals, reviews, orders, fills, and contribution evidence',
    no_intraday_stock_or_etf_action_tasks:
      'No intraday stock or ETF action candidates',
    no_linked_fills: 'No linked fills',
    out_of_sample_validation: 'Out-of-sample validation',
    paper_shadow_divergence_review: 'Paper/simulation divergence review',
    paper_shadow_evidence: 'Paper/simulation evidence',
    position_missing: 'Position evidence is missing',
    preview_import_and_reconcile_broker_evidence:
      'Preview broker evidence import and run reconciliation',
    refresh_quotes_or_check_source: 'Refresh quotes or check data source',
    review_position_difference: 'Review position difference',
    run_first_sync: 'Configure a data source or run the first sync',
    risk_block_evidence: 'Risk block evidence',
    strategy_attribution_evidence: 'Strategy attribution evidence',
    strategy_attribution_not_ready:
      'Strategy attribution evidence is not ready',
    unresolved_position_difference: 'Unresolved position difference',
    valuation_missing: 'Valuation missing',
  },
  zh: {
    account_truth_gate_pass: '账户事实闸门需要通过',
    account_truth_score_unavailable:
      '缺少已暂存的券商证据，暂时无法计算账户事实分',
    after_cost_report: '成本后报告',
    cash_missing: '缺少现金凭证',
    cost_basis_missing: '缺少成本价凭证',
    evidence_linked_pnl_pending: '证据已串联，收益待确认',
    estimated_from_linked_fills: '基于已归属成交估算',
    fee_missing: '缺少费用凭证',
    import_and_reconcile_broker_evidence: '导入券商凭证并完成对账',
    link_strategy_signals_orders_fills_and_contribution:
      '串联策略信号、复核、订单、成交与收益归因证据',
    no_intraday_stock_or_etf_action_tasks: '暂无盘中股票或 ETF 候选动作',
    no_linked_fills: '暂无可归属成交',
    out_of_sample_validation: '样本外验证',
    paper_shadow_divergence_review: '纸面/模拟差异复核',
    paper_shadow_evidence: '纸面/模拟证据',
    position_missing: '缺少持仓凭证',
    preview_import_and_reconcile_broker_evidence: '预览券商凭证导入并完成对账',
    refresh_quotes_or_check_source: '刷新行情或检查数据源',
    review_position_difference: '复核持仓差异',
    run_first_sync: '配置数据源或执行首次同步',
    risk_block_evidence: '风控阻断证据',
    strategy_attribution_evidence: '策略归因证据',
    strategy_attribution_not_ready: '策略归因证据尚未就绪',
    unresolved_position_difference: '存在未解决的持仓差异',
    valuation_missing: '缺少估值',
  },
};

const NOTE_LABELS: Record<Locale, LabelMap> = {
  en: {
    'P/L contribution is not calculated until fills are reconciled with position and valuation history.':
      'P/L contribution is waiting for fills to be reconciled with position and valuation history.',
    'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.':
      'Contribution is estimated from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.',
    'Local valuation is missing for linked evidence.':
      'Local valuation is missing for linked evidence.',
    'Order evidence is present, but fills are blocked.':
      'Order evidence is present, but fills are blocked.',
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.':
      'The selected strategy is only research context until signals, reviews, and fills are attributed.',
    'Requires paper/shadow review before promotion.':
      'Requires paper/simulation review before manual review.',
    'Research evidence is not a profitability guarantee.':
      'Research evidence is not a profitability guarantee.',
    'Review status is an audit signal only.':
      'Review status is an audit signal only.',
    'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.':
      'Multiple tests can overfit historical data; require out-of-sample and after-cost review.',
    'Parameter sweep rankings are research evidence, not investment advice.':
      'Parameter sweep rankings are research evidence, not investment advice.',
    'Strategy comparison results are research evidence, not investment advice.':
      'Strategy comparison results are research evidence, not investment advice.',
  },
  zh: {
    'P/L contribution is not calculated until fills are reconciled with position and valuation history.':
      '收益贡献需要先把成交、持仓和估值历史对齐后再计算。',
    'Contribution is estimated only from linked strategy fills and latest local quotes; manual trades and cash flows are excluded.':
      '收益贡献仅基于已归属成交和本地最新行情估算；手工交易与现金流水暂不计入。',
    'Local valuation is missing for linked evidence.':
      '已归属证据缺少本地估值。',
    'Order evidence is present, but fills are blocked.':
      '已有订单证据，但成交证据仍被阻断。',
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.':
      '当前策略只作为研究上下文；需要先完成信号、复核与成交归因后，才展示策略贡献。',
    'Requires paper/shadow review before promotion.':
      '进入人工复核前，需要完成纸面/模拟复盘。',
    'Research evidence is not a profitability guarantee.':
      '研究证据不代表收益保证。',
    'Review status is an audit signal only.':
      '复核状态只是审计信号，不会自动上线或下单。',
    'Multiple testing can overfit historical data; require OOS and after-cost review before promotion.':
      '多次参数测试可能过拟合历史数据，需要样本外与成本后复核。',
    'Parameter sweep rankings are research evidence, not investment advice.':
      '参数扫描排名只是研究证据，不构成投资建议。',
    'Strategy comparison results are research evidence, not investment advice.':
      '策略对比结果只是研究证据，不构成投资建议。',
  },
};

function normalized(value: string | null | undefined) {
  const text = value?.trim();
  return text && text.length > 0 ? text : '--';
}

function fallbackLabel(value: string, locale: Locale, kind: string) {
  if (value === '--') {
    return value;
  }
  if (locale === 'zh' && value.includes('_')) {
    return kind === 'status' ? '未映射状态' : '未映射原因';
  }
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(' ');
}

export function formatPublicStatus(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    STATUS_LABELS[locale][key] ??
    CODE_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'status')
  );
}

export function formatPublicCode(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    CODE_LABELS[locale][key] ??
    STATUS_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'code')
  );
}

export function formatPublicNote(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  return (
    NOTE_LABELS[locale][key] ??
    CODE_LABELS[locale][key] ??
    STATUS_LABELS[locale][key] ??
    fallbackLabel(key, locale, 'note')
  );
}

export function formatPublicCodeList(values: string[], locale: Locale) {
  return values.map((value) => formatPublicCode(value, locale));
}
