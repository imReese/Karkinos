import { type Locale } from '../../../shared/preferences/context';
import { formatCurrency } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  type OperationsTodayResponse,
  type PaperShadowReviewQueueItem,
} from '../decision-feature-boundary';
import type { DecisionCopy } from './decision-status-model';
import {
  formatPaperShadowRefs,
  formatPaperShadowStatusCountMap,
  numericCostSummaryValue,
} from './decision-status-model';

export function tradingPlanConclusionLabel(
  status: string | null | undefined,
  labels: DecisionCopy,
) {
  if (status === 'manual_confirmation_ready') {
    return labels.tradingPlanManualConfirmationReady;
  }
  if (status === 'account_truth_blocked') {
    return labels.tradingPlanAccountTruthBlocked;
  }
  if (status === 'risk_blocked') {
    return labels.tradingPlanRiskBlocked;
  }
  if (status === 'data_unavailable') {
    return labels.tradingPlanDataUnavailable;
  }
  if (status === 'portfolio_blocked') {
    return labels.tradingPlanPortfolioBlocked;
  }
  if (status === 'market_blocked') {
    return labels.tradingPlanMarketBlocked;
  }
  if (status === 'cash_shortfall') {
    return labels.tradingPlanCashShortfall;
  }
  return labels.tradingPlanNoManualAction;
}

export function tradingPlanBlockerLabel(reason: string, locale: Locale) {
  if (reason === 'awaiting_risk_gate') {
    return locale === 'zh' ? '等待风控门禁' : 'Awaiting risk gate';
  }
  return formatPublicNote(reason, locale);
}

const TRADING_PLAN_CONSTRAINT_LABELS: Record<
  string,
  { en: string; zh: string }
> = {
  trading_unit: { en: 'Trading unit', zh: '交易单位' },
  fee_tax_preview: { en: 'Fee and tax preview', zh: '费用税费预览' },
  cash_buffer: { en: 'Cash buffer', zh: '现金缓冲' },
  concentration: { en: 'Concentration', zh: '集中度' },
  t1_available_quantity: { en: 'T+1 sellable quantity', zh: 'T+1 可卖数量' },
  limit_up: { en: 'Limit up', zh: '涨停' },
  limit_down: { en: 'Limit down', zh: '跌停' },
  limit_move: { en: 'Price-limit status', zh: '涨跌停状态' },
  suspension: { en: 'Suspension', zh: '停牌' },
  special_treatment: { en: 'Special-treatment risk', zh: 'ST 风险' },
  drawdown: { en: 'Drawdown', zh: '回撤' },
  fund_nav_latency: { en: 'Fund NAV latency', zh: '基金净值延迟' },
};

export function tradingPlanConstraintLabel(id: string, locale: Locale) {
  const label = TRADING_PLAN_CONSTRAINT_LABELS[id];
  return label?.[locale] ?? formatPublicCode(id, locale);
}

export function paperShadowStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    not_required: { en: 'Not required', zh: '无需模拟' },
    not_run: { en: 'Not run', zh: '尚未运行' },
    review_required: { en: 'Review required', zh: '需要复核' },
    running: { en: 'Running', zh: '运行中' },
    within_expectations: { en: 'Within expectations', zh: '符合预期' },
    accepted_for_manual_confirmation: {
      en: 'Accepted for manual confirmation',
      zh: '已接受，可人工确认',
    },
    diverged: { en: 'Diverged', zh: '存在偏差' },
    failed: { en: 'Failed', zh: '运行失败' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

export function paperShadowNextStepLabel(value: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    none: { en: 'No additional simulation review', zh: '无需额外模拟复核' },
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
      en: 'Simulation reviewed; continue with manual confirmation',
      zh: '模拟已复核，可继续人工确认',
    },
    resolve_shadow_divergence: {
      en: 'Resolve simulation divergence before approval',
      zh: '批准前先处理模拟偏差',
    },
    inspect_failed_run: {
      en: 'Inspect failed paper/shadow run before approval',
      zh: '批准前先检查失败的模拟与影子检验',
    },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function paperShadowManualHandoffStatusLabel(status: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    ready_after_accepted_review: {
      en: 'Ready after accepted simulation review',
      zh: '已接受模拟复核，可人工确认',
    },
    ready_after_clean_simulation: {
      en: 'Ready after clean simulation',
      zh: '模拟无偏差，可人工确认',
    },
    blocked_by_unresolved_divergence: {
      en: 'Blocked by unresolved simulation divergence',
      zh: '模拟偏差未处理，暂不可人工确认',
    },
    blocked_by_failed_run: {
      en: 'Blocked by failed simulation run',
      zh: '模拟运行失败，暂不可人工确认',
    },
    blocked_by_review_requested_rerun: {
      en: 'Blocked until simulation reruns',
      zh: '需要重新运行模拟后再确认',
    },
    paper_shadow_required: {
      en: 'Simulation required before manual confirmation',
      zh: '人工确认前需要模拟复核',
    },
    waiting_for_paper_shadow_run: {
      en: 'Waiting for simulation result',
      zh: '等待模拟复核结果',
    },
    not_required: {
      en: 'No manual handoff required',
      zh: '无需人工确认交接',
    },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

export function paperShadowManualHandoffEvidenceItems(
  handoff: NonNullable<
    OperationsTodayResponse['paper_shadow']['manual_handoff']
  >,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          title: '人工确认交接',
          next: '下一步',
          queue: '复核队列',
          item: '项',
          items: '项',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          title: 'Manual handoff',
          next: 'Next',
          queue: 'Review queue',
          item: 'item',
          items: 'items',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const actions = (handoff.required_actions ?? [])
    .filter((action) => action && action !== 'none')
    .map((action) => paperShadowNextStepLabel(action, locale));
  const queueCount = handoff.review_queue_count ?? 0;
  return [
    `${labels.title}: ${paperShadowManualHandoffStatusLabel(
      handoff.status,
      locale,
    )}`,
    actions.length ? `${labels.next}: ${actions.join(' · ')}` : '',
    queueCount > 0
      ? `${labels.queue}: ${queueCount} ${
          queueCount === 1 ? labels.item : labels.items
        }`
      : '',
    handoff.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    handoff.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);
}

export function paperShadowInputSnapshotEvidenceItems(
  snapshot: Record<string, unknown> | undefined,
  fallbackFingerprint: string | null | undefined,
  locale: Locale,
) {
  const orderIntentCount = numericSnapshotValue(snapshot?.order_intent_count);
  const sourceDecision = stringSnapshotValue(snapshot?.source_decision);
  const fingerprint =
    stringSnapshotValue(snapshot?.input_fingerprint) ??
    stringSnapshotValue(fallbackFingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
          safety: '快照安全边界',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
          safety: 'Snapshot safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const inputParts = [
    orderIntentCount === null
      ? ''
      : `${orderIntentCount} ${labels.orderIntent}${
          locale === 'en' && orderIntentCount !== 1 ? 's' : ''
        }`,
    sourceDecision
      ? `${labels.source} ${formatPublicStatus(sourceDecision, locale)}`
      : '',
    fingerprint ? `${labels.fingerprint} ${fingerprint.slice(0, 12)}` : '',
  ].filter(Boolean);
  const safetyParts = [
    snapshot?.does_not_submit_broker_order === true
      ? labels.noBrokerSubmission
      : '',
    snapshot?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ].filter(Boolean);
  return [
    inputParts.length ? `${labels.input}: ${inputParts.join(' · ')}` : '',
    safetyParts.length ? `${labels.safety}: ${safetyParts.join(' · ')}` : '',
  ].filter(Boolean);
}

export function numericSnapshotValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function stringSnapshotValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function paperShadowReviewQueueItemTitle(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const primary =
    item.symbol?.trim() ||
    (item.order_id
      ? formatPublicEvidenceReference(
          `paper_shadow_order:${item.order_id}`,
          locale,
        )
      : '');
  return [primary, paperShadowNextStepLabel(item.required_action, locale)]
    .filter(Boolean)
    .join(' · ');
}

export function paperShadowReviewQueueSafetyText(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const labels: string[] = [];
  if (item.does_not_submit_broker_order) {
    labels.push(locale === 'zh' ? '不会提交券商订单' : 'No broker submission');
  }
  if (item.does_not_mutate_production_ledger) {
    labels.push(
      locale === 'zh' ? '不会修改生产账本' : 'No production ledger mutation',
    );
  }
  return labels.join(' · ');
}

export function paperShadowReviewQueueDetailItems(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          risk: '风控',
          manual: '人工确认',
          accountTruth: '账户事实',
          cash: '现金',
          constraints: '约束',
          projectedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          simulatedSlippage: '模拟滑点',
          expected: '预期',
          fill: '成交',
          terminalOutcome: '终态结果',
          omsPath: 'OMS 路径',
          omsTransition: 'OMS 状态变更',
          evidence: '证据',
        }
      : {
          risk: 'Risk',
          manual: 'Manual',
          accountTruth: 'Account truth',
          cash: 'Cash',
          constraints: 'Constraints',
          projectedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          simulatedSlippage: 'Sim slippage',
          expected: 'Expected',
          fill: 'Fill',
          terminalOutcome: 'Terminal outcome',
          omsPath: 'OMS path',
          omsTransition: 'OMS transition',
          evidence: 'Evidence',
        };
  const riskManual = [
    item.risk_gate_status
      ? `${labels.risk} ${formatPublicStatus(item.risk_gate_status, locale)}`
      : '',
    item.manual_confirmation_status
      ? `${labels.manual} ${reviewQueueManualStatusLabel(
          item.manual_confirmation_status,
          locale,
        )}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const accountCash = [
    item.account_truth?.gate_status
      ? `${labels.accountTruth} ${formatPublicStatus(
          item.account_truth.gate_status,
          locale,
        )}`
      : '',
    item.cash_status
      ? `${labels.cash} ${formatPublicStatus(item.cash_status, locale)}`
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const constraints = formatPaperShadowStatusCountMap(
    item.constraint_status_counts,
    locale,
  );
  const costEvidence = [
    reviewQueueCurrencyItem(
      labels.projectedFee,
      item.cost_evidence?.estimated_total_fee,
    ),
    reviewQueueCurrencyItem(
      labels.simulatedFeeTax,
      item.cost_evidence?.simulated_fee_tax_cost,
    ),
    reviewQueueCurrencyItem(
      labels.simulatedSlippage,
      item.cost_evidence?.simulated_slippage_cost,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const marketContext = [
    reviewQueueCurrencyItem(
      labels.expected,
      item.market_context?.expected_price,
    ),
    reviewQueueFillPriceItem(
      labels.fill,
      item.market_context?.simulated_fill_prices,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const omsStatusPath = reviewQueueOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = reviewQueueTerminalOutcomeSummary(item, locale);
  const omsTransition = reviewQueueLatestOmsTransition(item, locale);
  const evidenceRefs = formatPaperShadowRefs(
    item.evidence_refs ?? [
      ...(item.strategy_refs ?? []),
      ...(item.risk_refs ?? []),
      ...(item.signal_refs ?? []),
    ],
    locale,
  );
  return [
    riskManual,
    accountCash,
    constraints ? `${labels.constraints} ${constraints}` : '',
    costEvidence,
    marketContext,
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    omsStatusPath ? `${labels.omsPath}: ${omsStatusPath}` : '',
    omsTransition ? `${labels.omsTransition}: ${omsTransition}` : '',
    evidenceRefs ? `${labels.evidence}: ${evidenceRefs}` : '',
  ].filter(Boolean);
}

function reviewQueueTerminalOutcomeSummary(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = reviewQueueOmsStatusLabel(
    item.terminal_status ?? undefined,
    locale,
  );
  const reason = reviewQueueTerminalReasonLabel(
    item.terminal_reason ?? undefined,
    locale,
  );
  const transition = item.terminal_oms_transition_ref
    ? formatPublicEvidenceReference(item.terminal_oms_transition_ref, locale)
    : '';
  return [status, reason, transition].filter(Boolean).join(' · ');
}

function reviewQueueTerminalReasonLabel(
  reason: string | undefined,
  locale: Locale,
) {
  const normalized = String(reason ?? '').trim();
  if (!normalized) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    operator_cancelled: {
      en: 'Operator cancelled simulation before fill',
      zh: '操作员在模拟成交前取消',
    },
    paper_session_closed: {
      en: 'Paper session closed before fill',
      zh: '模拟交易时段结束，未成交前过期',
    },
  };
  return labels[normalized]?.[locale] ?? formatPublicStatus(normalized, locale);
}

function reviewQueueOmsStatusPath(
  values: string[] | undefined,
  locale: Locale,
) {
  if (!values || values.length === 0) {
    return '';
  }
  return values
    .map((value) => reviewQueueOmsStatusLabel(value, locale))
    .filter(Boolean)
    .join(' > ');
}

function reviewQueueLatestOmsTransition(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const transition = [...(item.oms_transitions ?? [])]
    .reverse()
    .find((entry) => entry.to_status);
  if (!transition?.to_status) {
    return '';
  }
  const orderId = item.order_id ? `${item.order_id} ` : '';
  const sequence =
    transition.sequence !== null && transition.sequence !== undefined
      ? `#${transition.sequence} `
      : '';
  return `${orderId}${sequence}${reviewQueueOmsStatusLabel(
    transition.to_status,
    locale,
  )}`;
}

function reviewQueueOmsStatusLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const status = String(value ?? '').trim();
  if (!status) {
    return '';
  }
  const labels: Record<string, Record<Locale, string>> = {
    staged: { en: 'Staged', zh: '已暂存' },
    submitted: { en: 'Submitted', zh: '已提交模拟' },
    accepted: { en: 'Accepted', zh: '已接受模拟' },
    partially_filled: { en: 'Partially Filled', zh: '部分成交' },
    filled: { en: 'Filled', zh: '已成交' },
    rejected: { en: 'Rejected', zh: '已拒绝' },
    cancelled: { en: 'Cancelled', zh: '已取消' },
    expired: { en: 'Expired', zh: '已过期' },
    reconciled: { en: 'Reconciled', zh: '已对账' },
  };
  return labels[status]?.[locale] ?? formatPublicStatus(status, locale);
}

function reviewQueueManualStatusLabel(value: string, locale: Locale) {
  if (value === 'ready_for_manual_confirmation') {
    return locale === 'zh' ? '可人工确认' : 'Ready';
  }
  return formatPublicStatus(value, locale);
}

function reviewQueueCurrencyItem(label: string, value: unknown) {
  const numeric = numericCostSummaryValue(value);
  return numeric === null ? '' : `${label} ${formatCurrency(numeric)}`;
}

function reviewQueueFillPriceItem(
  label: string,
  values: unknown[] | undefined,
) {
  const prices = (values ?? [])
    .map((value) => numericCostSummaryValue(value))
    .filter((value): value is number => value !== null)
    .map((value) => formatCurrency(value));
  return prices.length ? `${label} ${prices.join(', ')}` : '';
}
