import { type Locale } from '../../../shared/preferences/context';
import { formatCurrency } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { numericCostSummaryValue } from './decision-status-model';
import { automationRecommendedActionLabel } from './decision-operator-action-labels';

export function controlledExecutionStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    no_session_evidence: {
      en: 'No session evidence · default off',
      zh: '无会话证据 · 默认关闭',
    },
    clear_read_only_evidence: {
      en: 'Read-only evidence clear',
      zh: '只读证据清晰',
    },
    order_journey_review_required: {
      en: 'Order journey review required',
      zh: '订单旅程需要复核',
    },
    order_journey_attention_required: {
      en: 'Order journey attention required',
      zh: '订单旅程需要优先处理',
    },
    blocked_order_journey_attention_required: {
      en: 'Session blocked · order evidence needs attention',
      zh: '会话已阻断 · 订单证据需要处理',
    },
    order_journey_closed: {
      en: 'Order journeys closed',
      zh: '订单旅程已闭环',
    },
    blocked: { en: 'Blocked', zh: '已阻断' },
    historical_sessions_only: {
      en: 'Historical sessions only',
      zh: '仅历史会话',
    },
    current_clear_evidence: {
      en: 'Current evidence clear',
      zh: '当前证据清晰',
    },
    paused: { en: 'Paused', zh: '已暂停' },
    expired: { en: 'Expired', zh: '已过期' },
    revoked: { en: 'Revoked', zh: '已撤销' },
    scheduled: { en: 'Scheduled', zh: '待生效' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

export function controlledOrderJourneyStageLabel(
  value: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    controlled_submission: {
      en: 'Controlled submission',
      zh: '受控提交',
    },
    controlled_submission_rejection_review: {
      en: 'Rejection review',
      zh: '拒绝人工复核',
    },
    execution_reconciliation: {
      en: 'Execution reconciliation',
      zh: '执行对账',
    },
    terminal_reconciliation_clearance: {
      en: 'Terminal clearance',
      zh: '终态清算',
    },
    reconciled_ledger_posting: {
      en: 'Reconciled ledger posting',
      zh: '对账后账本入账',
    },
    append_only_ledger_correction: {
      en: 'Append-only correction',
      zh: '追加式校正',
    },
    post_ledger_account_truth: {
      en: 'Post-ledger Account Truth',
      zh: '入账后账户事实',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

export function controlledOrderJourneyNextActionLabel(
  value: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    review_account_truth_after_ledger_correction: {
      en: 'review Account Truth after correction',
      zh: '校正后复核账户事实',
    },
    review_account_truth_after_ledger_posting: {
      en: 'review Account Truth after ledger posting',
      zh: '入账后复核账户事实',
    },
    no_action_order_journey_complete: {
      en: 'no action; order journey is evidence-complete',
      zh: '无需操作；订单旅程证据已闭环',
    },
    preview_reconciled_ledger_posting: {
      en: 'preview the separately signed ledger posting',
      zh: '预览需单独签名的账本入账',
    },
    query_submission_outcome_without_resubmit: {
      en: 'query the unknown outcome; do not resubmit',
      zh: '只查询未知结果，不得重提',
    },
    query_prepared_submission_outcome_without_resubmit: {
      en: 'query the prepared outcome; do not resubmit',
      zh: '查询已准备结果，不得重提',
    },
    review_rejection_evidence_without_retry: {
      en: 'review rejection evidence; no automatic retry',
      zh: '复核拒绝证据，不自动重试',
    },
    no_retry_create_new_decision_if_needed: {
      en: 'no retry; create a new Decision if the trade is still needed',
      zh: '不得重试；如仍需交易则新建 Decision',
    },
    run_or_review_execution_reconciliation: {
      en: 'run or review execution reconciliation',
      zh: '运行或复核执行对账',
    },
    review_execution_reconciliation: {
      en: 'review execution reconciliation',
      zh: '复核执行对账',
    },
    review_open_order_or_prepare_manual_cancel_ticket: {
      en: 'review the open order or prepare a human cancellation package',
      zh: '复核未终态订单，或准备人工撤单证据包',
    },
    preview_terminal_reconciliation_clearance: {
      en: 'preview the separately signed terminal clearance',
      zh: '预览需单独签名的终态清算',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

export function controlledOrderJourneyBlockerLabel(
  value: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    post_ledger_account_truth_not_clear: {
      en: 'Account Truth is not clear',
      zh: '账户事实尚未清晰',
    },
    post_ledger_account_truth_gate_not_pass: {
      en: 'Account Truth gate did not pass',
      zh: '账户事实门禁未通过',
    },
    post_ledger_account_truth_reconciliation_not_clear: {
      en: 'Account reconciliation is not clear',
      zh: '账户对账尚未清晰',
    },
    post_ledger_account_truth_mismatch_count_invalid: {
      en: 'Mismatch count is invalid',
      zh: '差异数量无效',
    },
    post_ledger_account_truth_mismatch_unresolved: {
      en: 'Account mismatches remain unresolved',
      zh: '账户差异仍未解决',
    },
    post_ledger_account_truth_not_fresh: {
      en: 'Account Truth evidence is not fresh',
      zh: '账户事实证据不新鲜',
    },
    post_ledger_account_truth_ledger_not_covered: {
      en: 'Current ledger is not covered',
      zh: '当前账本尚未被覆盖',
    },
    post_ledger_account_truth_import_identity_missing: {
      en: 'Account Truth import identity is missing',
      zh: '缺少账户事实导入标识',
    },
    post_ledger_account_truth_fingerprint_missing: {
      en: 'Account Truth fingerprint is missing',
      zh: '缺少账户事实指纹',
    },
    post_ledger_account_truth_ledger_boundary_invalid: {
      en: 'Account Truth ledger boundary is invalid',
      zh: '账户事实账本边界无效',
    },
    post_ledger_account_truth_authority_boundary_invalid: {
      en: 'Account Truth authority boundary is invalid',
      zh: '账户事实权限边界无效',
    },
    post_ledger_account_truth_submission_boundary_invalid: {
      en: 'Account Truth submission boundary is invalid',
      zh: '账户事实提交边界无效',
    },
    post_ledger_account_truth_timestamp_invalid: {
      en: 'Account Truth timestamp is invalid',
      zh: '账户事实时间无效',
    },
    post_ledger_fact_timestamp_invalid: {
      en: 'Post-ledger fact timestamp is invalid',
      zh: '入账后事实时间无效',
    },
    post_ledger_account_truth_predates_latest_fact: {
      en: 'Account Truth predates the latest ledger fact',
      zh: '账户事实早于最新账本事实',
    },
    post_ledger_cutoff_invalid: {
      en: 'Post-ledger cutoff is invalid',
      zh: '入账后账本截止标识无效',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

export function controlledExecutionCurrency(value: string | null | undefined) {
  const numeric = numericCostSummaryValue(value);
  return numeric === null ? '—' : formatCurrency(numeric);
}

export function brokerGatewayCapabilityLabel(
  label:
    | 'preview'
    | 'export'
    | 'dry_run'
    | 'query_orders'
    | 'query_fills'
    | 'read_positions'
    | 'read_cash'
    | 'submit'
    | 'cancel',
  enabled: boolean | undefined,
  locale: Locale,
) {
  const action =
    label === 'preview'
      ? locale === 'zh'
        ? '预览'
        : 'Preview'
      : label === 'export'
        ? locale === 'zh'
          ? '导出'
          : 'Export'
        : label === 'dry_run'
          ? locale === 'zh'
            ? '干跑'
            : 'Dry run'
          : label === 'query_orders'
            ? locale === 'zh'
              ? '查询订单'
              : 'Query orders'
            : label === 'query_fills'
              ? locale === 'zh'
                ? '查询成交'
                : 'Query fills'
              : label === 'read_positions'
                ? locale === 'zh'
                  ? '读取持仓'
                  : 'Read positions'
                : label === 'read_cash'
                  ? locale === 'zh'
                    ? '读取资金'
                    : 'Read cash'
                  : label === 'submit'
                    ? locale === 'zh'
                      ? '提交'
                      : 'Submit'
                    : locale === 'zh'
                      ? '撤单'
                      : 'Cancel';
  const state = enabled
    ? locale === 'zh'
      ? '可用'
      : 'available'
    : locale === 'zh'
      ? '阻断'
      : 'blocked';
  return `${action} ${state}`;
}

export function brokerConnectorCapabilityLabel(
  label:
    | 'read_account'
    | 'read_cash'
    | 'read_positions'
    | 'read_orders'
    | 'read_fills'
    | 'preview_orders'
    | 'export_tickets'
    | 'dry_run_orders'
    | 'submit'
    | 'cancel',
  enabled: boolean | undefined,
  locale: Locale,
) {
  const action =
    label === 'read_account'
      ? locale === 'zh'
        ? '读取账户'
        : 'Read account'
      : label === 'read_cash'
        ? locale === 'zh'
          ? '读取资金'
          : 'Read cash'
        : label === 'read_positions'
          ? locale === 'zh'
            ? '读取持仓'
            : 'Read positions'
          : label === 'read_orders'
            ? locale === 'zh'
              ? '读取订单'
              : 'Read orders'
            : label === 'read_fills'
              ? locale === 'zh'
                ? '读取成交'
                : 'Read fills'
              : label === 'preview_orders'
                ? locale === 'zh'
                  ? '预览订单'
                  : 'Preview orders'
                : label === 'export_tickets'
                  ? locale === 'zh'
                    ? '导出票据'
                    : 'Export tickets'
                  : label === 'dry_run_orders'
                    ? locale === 'zh'
                      ? 'Dry-run 订单'
                      : 'Dry-run orders'
                    : label === 'submit'
                      ? locale === 'zh'
                        ? '提交'
                        : 'Submit'
                      : locale === 'zh'
                        ? '撤单'
                        : 'Cancel';
  const state = enabled
    ? locale === 'zh'
      ? '可用'
      : 'available'
    : locale === 'zh'
      ? '阻断'
      : 'blocked';
  return `${action} ${state}`;
}

export function executionReconciliationStatusLabel(
  status: string,
  locale: Locale,
) {
  if (status === 'open_items') {
    return locale === 'zh' ? '存在未处理项' : 'Open items';
  }
  if (status === 'clear') {
    return locale === 'zh' ? '已清理' : 'Clear';
  }
  return formatPublicStatus(status, locale);
}

export function executionReconciliationItemStatusLabel(
  status: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    awaiting_manual_confirmation: {
      en: 'Awaiting manual confirmation',
      zh: '等待人工确认',
    },
    gateway_action_missing: {
      en: 'Gateway action missing',
      zh: '缺少网关动作',
    },
    broker_evidence_available: {
      en: 'Broker evidence available',
      zh: '券商证据可复核',
    },
    broker_evidence_mismatch: {
      en: 'Broker evidence mismatch',
      zh: '券商证据不匹配',
    },
    manual_execution_recorded: {
      en: 'Manual execution recorded',
      zh: '手工成交证据已记录',
    },
    awaiting_broker_evidence: {
      en: 'Awaiting broker evidence',
      zh: '等待券商证据',
    },
    cancelled: {
      en: 'Cancelled',
      zh: '已取消',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

export function omsOrderStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    awaiting_manual_confirmation: {
      en: 'Awaiting manual confirmation',
      zh: '等待人工确认',
    },
    manually_confirmed: {
      en: 'Manually confirmed',
      zh: '已人工确认',
    },
    manual_ticket_created: {
      en: 'Manual ticket created',
      zh: '已创建手工票据',
    },
    broker_submission_blocked: {
      en: 'Broker submission blocked',
      zh: '券商提交已阻断',
    },
    staged: {
      en: 'Staged',
      zh: '已暂存',
    },
    submitted: {
      en: 'Submitted',
      zh: '已提交',
    },
    accepted: {
      en: 'Accepted',
      zh: '已接受',
    },
    partially_filled: {
      en: 'Partially filled',
      zh: '部分成交',
    },
    filled: {
      en: 'Filled',
      zh: '已成交',
    },
    rejected: {
      en: 'Rejected',
      zh: '已拒绝',
    },
    cancelled: {
      en: 'Cancelled',
      zh: '已取消',
    },
    expired: {
      en: 'Expired',
      zh: '已过期',
    },
    reconciled: {
      en: 'Reconciled',
      zh: '已对账',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

export function executionReconciliationActionLabel(
  value: string,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    import_broker_statement_or_update_order: {
      en: 'Import broker statement or update order',
      zh: '导入券商交割单或更新订单',
    },
    create_manual_ticket_or_cancel: {
      en: 'Create manual ticket or cancel',
      zh: '创建手工票据或取消订单',
    },
    confirm_or_cancel_order: {
      en: 'Confirm or cancel order',
      zh: '确认或取消订单',
    },
    review_broker_evidence_match: {
      en: 'Review broker evidence match',
      zh: '复核券商证据匹配',
    },
    review_broker_evidence_mismatch: {
      en: 'Review broker evidence mismatch',
      zh: '复核券商证据不匹配',
    },
    review_manual_execution_and_import_broker_statement: {
      en: 'Review manual execution and import broker statement',
      zh: '复核手工成交并导入券商交割单',
    },
    review_order_state: {
      en: 'Review order state',
      zh: '复核订单状态',
    },
  };
  return (
    labels[value]?.[locale] ?? automationRecommendedActionLabel(value, locale)
  );
}
