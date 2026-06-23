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
    ledger_candidate: 'Ledger candidate',
    live: 'Live',
    manual: 'Manual',
    manual_confirm: 'Manual confirmation',
    mismatch: 'Mismatch',
    missing: 'Missing',
    needs_investigation: 'Needs investigation',
    no_action: 'No action',
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
    ledger_candidate: '账本候选',
    live: '实时行情',
    manual: '手动',
    manual_confirm: '人工确认',
    mismatch: '不一致',
    missing: '缺失',
    needs_investigation: '需要继续调查',
    no_action: '不操作',
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
    stale: '行情过期',
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
    account_truth: 'Account truth',
    cash: 'Cash',
    cash_missing: 'Cash evidence is missing',
    cost_basis: 'Cost basis',
    cost_basis_method: 'Cost-basis method',
    cost_basis_missing: 'Cost-basis evidence is missing',
    data_refresh: 'Data refresh',
    evidence_linked_pnl_pending: 'Evidence linked, P/L pending',
    fee: 'Fee',
    estimated_from_linked_fills: 'Estimated from linked fills',
    fee_missing: 'Fee evidence is missing',
    import_and_reconcile_broker_evidence:
      'Import broker evidence and run reconciliation',
    link_strategy_signals_orders_fills_and_contribution:
      'Link strategy signals, reviews, orders, fills, and contribution evidence',
    manual_confirm_candidate_actions: 'Manually confirm candidate actions',
    manual_confirmation: 'Manual confirmation',
    market_data_missing: 'Market data is missing',
    market_data_not_fully_live: 'Market data needs confirmation',
    no_intraday_stock_or_etf_action_tasks:
      'No intraday stock or ETF action candidates',
    no_linked_fills: 'No linked fills',
    out_of_sample_validation: 'Out-of-sample validation',
    paper_shadow_divergence_review: 'Paper/simulation divergence review',
    paper_shadow_evidence: 'Paper/simulation evidence',
    paper_shadow_review: 'Paper/simulation review',
    paper_shadow_evidence_required_before_manual_confirmation:
      'Paper/simulation evidence required before manual confirmation',
    broker_remaining_cost: 'Broker remaining-position cost',
    position: 'Position',
    position_missing: 'Position evidence is missing',
    preview_import_and_reconcile_broker_evidence:
      'Preview broker evidence import and run reconciliation',
    quote_older_than_expected_session:
      'Quote is older than the expected trading session',
    refresh_market_data: 'Refresh market data',
    refresh_or_confirm_market_data: 'Refresh or confirm market data',
    refresh_quotes_or_check_source: 'Refresh quotes or check data source',
    resolve_upstream_workflow_blockers: 'Resolve upstream workflow blockers',
    review_position_difference: 'Review position difference',
    review_cash_difference: 'Review cash difference',
    review_cost_basis_difference: 'Review cost-basis difference',
    review_fee_difference: 'Review fee difference',
    review_net_cash_impact_difference: 'Review net cash impact difference',
    review_tax_difference: 'Review tax difference',
    review_trade_gross_amount_difference:
      'Review trade gross amount difference',
    review_transfer_fee_difference: 'Review transfer-fee difference',
    review_paper_shadow_evidence: 'Review paper/simulation evidence',
    review_risk_blockers: 'Review risk blockers',
    risk_gate_blocked: 'Risk gate is blocking action',
    risk_gate_not_checked: 'Risk gate has not checked every action',
    risk_review: 'Risk review',
    'risk.signal.recorded': 'Risk signal recorded',
    run_pre_trade_risk_gate: 'Run pre-trade risk gate',
    run_first_sync: 'Configure a data source or run the first sync',
    risk_block_evidence: 'Risk block evidence',
    strategy_evidence: 'Strategy evidence',
    strategy_attribution_evidence: 'Strategy attribution evidence',
    strategy_attribution_not_ready:
      'Strategy attribution evidence is not ready',
    upstream_workflow_blockers: 'Upstream workflow blockers remain unresolved',
    unresolved_position_difference: 'Unresolved position difference',
    valuation_missing: 'Valuation missing',
  },
  zh: {
    account_truth_gate_pass: '账户事实闸门需要通过',
    account_truth_score_unavailable:
      '缺少已暂存的券商证据，暂时无法计算账户事实分',
    after_cost_report: '成本后报告',
    account_truth: '账户事实',
    cash: '现金',
    cash_missing: '缺少现金凭证',
    cost_basis: '成本价',
    cost_basis_method: '成本口径',
    cost_basis_missing: '缺少成本价凭证',
    data_refresh: '数据刷新',
    evidence_linked_pnl_pending: '证据已串联，收益待确认',
    fee: '费用',
    estimated_from_linked_fills: '基于已归属成交估算',
    fee_missing: '缺少费用凭证',
    import_and_reconcile_broker_evidence: '导入券商凭证并完成对账',
    link_strategy_signals_orders_fills_and_contribution:
      '串联策略信号、复核、订单、成交与收益归因证据',
    manual_confirm_candidate_actions: '人工确认候选动作',
    manual_confirmation: '人工确认',
    market_data_missing: '缺少行情数据',
    market_data_not_fully_live: '行情需要确认',
    no_intraday_stock_or_etf_action_tasks: '暂无盘中股票或 ETF 候选动作',
    no_linked_fills: '暂无可归属成交',
    out_of_sample_validation: '样本外验证',
    paper_shadow_divergence_review: '纸面/模拟差异复核',
    paper_shadow_evidence: '纸面/模拟证据',
    paper_shadow_review: '模拟复盘',
    paper_shadow_evidence_required_before_manual_confirmation:
      '人工确认前需要补齐纸面/模拟证据',
    broker_remaining_cost: '券商剩余持仓成本',
    position: '持仓',
    position_missing: '缺少持仓凭证',
    preview_import_and_reconcile_broker_evidence: '预览券商凭证导入并完成对账',
    quote_older_than_expected_session: '行情早于预期交易时段',
    refresh_market_data: '刷新行情',
    refresh_or_confirm_market_data: '刷新或确认行情',
    refresh_quotes_or_check_source: '刷新行情或检查数据源',
    resolve_upstream_workflow_blockers: '先处理上游阻断',
    review_position_difference: '复核持仓差异',
    review_cash_difference: '复核现金差异',
    review_cost_basis_difference: '复核成本价差异',
    review_fee_difference: '复核费用差异',
    review_net_cash_impact_difference: '复核净现金影响差异',
    review_tax_difference: '复核税费差异',
    review_trade_gross_amount_difference: '复核成交总额差异',
    review_transfer_fee_difference: '复核过户费差异',
    review_paper_shadow_evidence: '复核纸面/模拟证据',
    review_risk_blockers: '复核风控阻断',
    risk_gate_blocked: '风控闸门正在阻断动作',
    risk_gate_not_checked: '仍有动作未完成风控检查',
    risk_review: '风险复核',
    'risk.signal.recorded': '风控信号已记录',
    run_pre_trade_risk_gate: '运行下单前风控',
    run_first_sync: '配置数据源或执行首次同步',
    risk_block_evidence: '风控阻断证据',
    strategy_evidence: '策略证据',
    strategy_attribution_evidence: '策略归因证据',
    strategy_attribution_not_ready: '策略归因证据尚未就绪',
    upstream_workflow_blockers: '仍有上游阻断未处理',
    unresolved_position_difference: '存在未解决的持仓差异',
    valuation_missing: '缺少估值',
  },
};

const EVIDENCE_SOURCE_LABELS: Record<Locale, LabelMap> = {
  en: {
    broker_event: 'Broker evidence',
  },
  zh: {
    broker_event: '券商证据',
  },
};

const BROKER_EVIDENCE_TYPE_LABELS: Record<Locale, LabelMap> = {
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

const NOTE_LABELS: Record<Locale, LabelMap> = {
  en: {
    'account_truth.no_broker_evidence':
      'No broker evidence has been imported for reconciliation.',
    'account_truth.cash_snapshot_missing':
      'Broker cash snapshot is missing, so cash reconciliation is incomplete.',
    'account_truth.cash_compared':
      'Broker cash snapshot was compared with the Karkinos cash balance.',
    'account_truth.position_snapshot_missing':
      'Broker position snapshot is missing, so position reconciliation is incomplete.',
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
    'Backtest evidence is not a profitability claim.':
      'Backtest evidence is not a profitability claim.',
    'Validation evidence is not investment advice or a profitability guarantee.':
      'Validation evidence is not investment advice or a profitability guarantee.',
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
    'account_truth.no_broker_evidence': '尚未导入可用于复核的券商证据。',
    'account_truth.cash_snapshot_missing':
      '缺少券商现金快照，现金复核尚不完整。',
    'account_truth.cash_compared':
      '券商现金快照已与 Karkinos 本地现金余额对比。',
    'account_truth.position_snapshot_missing':
      '缺少券商持仓快照，持仓复核尚不完整。',
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
    'Strategy assignment is research evidence only until signals, reviews, and fills are attributed.':
      '当前策略只作为研究上下文；需要先完成信号、复核与成交归因后，才展示策略贡献。',
    'Requires paper/shadow review before promotion.':
      '进入人工复核前，需要完成纸面/模拟复盘。',
    'Research evidence is not a profitability guarantee.':
      '研究证据不代表收益保证。',
    'Backtest evidence is not a profitability claim.':
      '研究证据不代表收益保证。',
    'Validation evidence is not investment advice or a profitability guarantee.':
      '验证证据不构成投资建议，也不保证收益。',
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
  if (value.includes('_')) {
    if (locale === 'zh') {
      if (kind === 'status') {
        return '待确认状态';
      }
      if (kind === 'note') {
        return '待人工复核说明';
      }
      return '待人工复核项';
    }
    if (kind === 'status') {
      return 'Status needs review';
    }
    if (kind === 'note') {
      return 'Review note';
    }
    return 'Review item';
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

export function formatPublicOperationalNote(
  value: string | null | undefined,
  locale: Locale,
) {
  const text = value?.trim();
  if (!text) {
    return null;
  }

  if (/^Prepared from signal action \d+\.$/.test(text)) {
    return locale === 'zh'
      ? '已从决策待办生成手工确认订单。'
      : 'Prepared from Decision action queue.';
  }

  return (
    NOTE_LABELS[locale][text] ??
    CODE_LABELS[locale][text] ??
    STATUS_LABELS[locale][text] ??
    (text.includes('_') ? fallbackLabel(text, locale, 'note') : text)
  );
}

export function formatPublicCodeList(values: string[], locale: Locale) {
  return values.map((value) => formatPublicCode(value, locale));
}

export function formatPublicEvidenceReference(
  value: string | null | undefined,
  locale: Locale,
) {
  const key = normalized(value);
  if (key === '--') {
    return key;
  }

  const brokerReference = parseBrokerEvidenceReference(key);
  if (brokerReference) {
    const source =
      EVIDENCE_SOURCE_LABELS[locale][brokerReference.sourceType] ??
      formatPublicCode(brokerReference.sourceType, locale);
    const eventType =
      BROKER_EVIDENCE_TYPE_LABELS[locale][brokerReference.eventType] ??
      formatPublicCode(brokerReference.eventType, locale);
    return [
      source,
      brokerReference.subject,
      eventType,
      brokerReference.importRunId,
    ]
      .filter(Boolean)
      .join(' · ');
  }

  return formatPublicCode(key, locale);
}

function parseBrokerEvidenceReference(reference: string) {
  const [sourceType, importRunId, subject, ...eventTypeParts] =
    reference.split(':');
  if (
    sourceType !== 'broker_event' ||
    !importRunId ||
    !subject ||
    eventTypeParts.length === 0
  ) {
    return null;
  }
  const eventType = eventTypeParts.join(':');
  return {
    sourceType,
    importRunId,
    subject,
    eventType,
  };
}
