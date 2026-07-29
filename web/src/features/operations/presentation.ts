import type { Locale } from '../../app/preferences';
import { formatPublicStatus } from '../../shared/public-labels';

export function operationsTargetHref(target: string | undefined) {
  switch (target) {
    case 'market':
      return '/market';
    case 'account-truth':
      return '/account-truth';
    case 'risk':
      return '/risk';
    case 'paper-shadow':
    case 'trading':
      return '/trading';
    case 'scheduler':
    case 'operations':
      return '/operations';
    case 'decision':
    default:
      return '/decision';
  }
}

export function operationsSubsystemLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    market_data: { en: 'Market data and NAV', zh: '行情与净值' },
    account_truth: { en: 'Account Truth', zh: '账户事实' },
    strategy_candidates: { en: 'Strategy evidence', zh: '策略证据' },
    risk: { en: 'Deterministic risk', zh: '确定性风控' },
    daily_trading_plan: { en: 'Daily trading plan', zh: '日度交易计划' },
    paper_shadow: { en: 'Paper/shadow', zh: '模拟与影子检验' },
    scheduler: { en: 'Scheduler', zh: '自动任务调度' },
    execution_reconciliation: {
      en: 'Execution reconciliation',
      zh: '执行对账',
    },
    acceptance_audit: { en: 'Acceptance audit', zh: '验收审计' },
    broker_adapter_evidence: {
      en: 'Broker adapter evidence',
      zh: '券商接入证据',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

export function operationsNextActionLabel(
  value: string | undefined,
  locale: Locale,
) {
  const key = value || 'none';
  const labels: Record<string, { en: string; zh: string }> = {
    none: { en: 'No additional action', zh: '无需额外处理' },
    run_paper_shadow_daily: {
      en: 'Run paper/shadow simulation before manual confirmation',
      zh: '人工确认前先运行模拟与影子检验',
    },
    review_shadow_divergence: {
      en: 'Review paper/shadow divergence evidence',
      zh: '复核模拟与影子检验的偏差证据',
    },
    wait_for_paper_shadow_run: {
      en: 'Paper/shadow simulation is running; wait for completion',
      zh: '模拟与影子检验正在运行，等待完成',
    },
    review_manual_confirmation: {
      en: 'Review manual order confirmation',
      zh: '复核人工下单确认',
    },
    resolve_shadow_divergence: {
      en: 'Resolve paper/shadow divergence before approval',
      zh: '批准前处理模拟与影子检验偏差',
    },
    inspect_failed_run: {
      en: 'Inspect failed paper/shadow run before approval',
      zh: '批准前检查失败的模拟与影子检验',
    },
    inspect_scheduler_failure: {
      en: 'Inspect scheduler failure evidence before manual review',
      zh: '人工复核前检查调度失败证据',
    },
    resolve_kill_switch: {
      en: 'Resolve kill switch state before continuing',
      zh: '继续前处理紧急停止状态',
    },
    review_scheduler_run: {
      en: 'Review scheduler run evidence',
      zh: '复核调度运行证据',
    },
    resolve_daily_plan_blockers: {
      en: 'Resolve daily trading plan blockers',
      zh: '处理日度交易计划阻断项',
    },
    review_manual_order_intents: {
      en: 'Review manual order intents',
      zh: '复核人工订单意图',
    },
    repair_market_data_source: {
      en: 'Repair market data source',
      zh: '修复行情数据源',
    },
    review_market_data_freshness: {
      en: 'Review market data freshness',
      zh: '复核行情新鲜度',
    },
    resolve_account_truth_mismatch: {
      en: 'Resolve account truth mismatch',
      zh: '处理账户事实不一致',
    },
    attach_account_truth_evidence: {
      en: 'Attach account truth evidence',
      zh: '补充账户事实证据',
    },
    review_strategy_evidence: {
      en: 'Review strategy evidence coverage',
      zh: '复核策略证据覆盖',
    },
    review_risk_blocks: {
      en: 'Review risk blocks',
      zh: '复核风控阻断',
    },
    review_ledger_items: {
      en: 'Review ledger items',
      zh: '复核账本流水',
    },
    review_execution_reconciliation: {
      en: 'Review execution reconciliation',
      zh: '复核执行对账',
    },
    review_manual_execution_and_import_broker_statement: {
      en: 'Review manual execution and import broker statement',
      zh: '复核手工成交并导入券商流水',
    },
  };
  return labels[key]?.[locale] ?? formatPublicStatus(key, locale);
}

export function operationsAttentionResolutionLabel(
  condition: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    new_complete_market_evidence_required: {
      en: 'new complete market evidence is persisted',
      zh: '新的完整行情证据已持久化',
    },
    new_complete_account_truth_evidence_required: {
      en: 'new complete Account Truth evidence is persisted',
      zh: '新的完整 Account Truth 证据已持久化',
    },
    candidate_strategy_evidence_must_pass: {
      en: 'candidate strategy evidence passes the canonical gate',
      zh: '候选策略证据通过权威门禁',
    },
    new_daily_plan_with_deterministic_risk_pass_required: {
      en: 'a new daily plan passes deterministic risk gates',
      zh: '新的日度计划通过确定性风控门禁',
    },
    new_daily_plan_without_blockers_required: {
      en: 'a new daily plan has no unresolved blockers',
      zh: '新的日度计划不再包含未解决阻断',
    },
    explicit_manual_order_review_evidence_required: {
      en: 'explicit manual order review evidence is recorded',
      zh: '显式人工订单复核证据已记录',
    },
    new_paper_shadow_run_evidence_required: {
      en: 'a new paper/shadow run is persisted',
      zh: '新的模拟与影子检验证据已持久化',
    },
    current_paper_shadow_run_must_reach_terminal_evidence: {
      en: 'the current paper/shadow run reaches a terminal evidence state',
      zh: '当前模拟与影子检验形成终态证据',
    },
    accepted_paper_shadow_review_evidence_required: {
      en: 'accepted paper/shadow review evidence is recorded',
      zh: '模拟与影子检验复核形成明确的接受证据',
    },
    new_terminal_paper_shadow_run_evidence_required: {
      en: 'a new terminal paper/shadow run is persisted',
      zh: '新的模拟与影子检验终态证据已持久化',
    },
    new_recognized_terminal_scheduler_run_required: {
      en: 'a new scheduler run reaches a recognized terminal status',
      zh: '新的调度运行形成可识别的终态证据',
    },
    kill_switch_clear_and_new_scheduler_evidence_required: {
      en: 'the kill switch is explicitly cleared and a new scheduler run is persisted',
      zh: '紧急停止状态经显式处理，且新的调度证据已持久化',
    },
    canonical_execution_reconciliation_must_close: {
      en: 'canonical execution reconciliation has no open item',
      zh: '权威执行对账不再有未关闭事项',
    },
    complete_acceptance_audit_evidence_required: {
      en: 'the required acceptance audit is complete',
      zh: '所需 acceptance audit 证据完整',
    },
    explicit_provider_authorization_and_new_release_evidence_required: {
      en: 'explicit provider authorization and new release evidence exist',
      zh: '具备明确接入方授权与新的放行证据',
    },
    new_canonical_evidence_required: {
      en: 'new canonical evidence resolves the source status',
      zh: '新的权威持久化证据解除来源状态',
    },
  };
  return labels[condition]?.[locale] ?? formatPublicStatus(condition, locale);
}
