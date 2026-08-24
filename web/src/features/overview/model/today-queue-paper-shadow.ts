import { formatCurrency as formatCurrencyValue } from '../../../shared/format';
import type { Locale } from '../../../shared/preferences/context';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  operationsNextActionLabel,
  type OperationsTodayResponse,
} from '../overview-feature-boundary';

export function numericPaperShadowValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function overviewCountLabel(count: number, singular: string, locale: Locale) {
  if (locale === 'zh') {
    return `${count} ${singular}`;
  }
  return `${count} ${singular}${count === 1 ? '' : 's'}`;
}

export function paperShadowOverviewEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const paperShadow = operations?.paper_shadow;
  if (!paperShadow) {
    return null;
  }
  const nextStep = paperShadow.next_manual_review_step;
  const shouldSummarize =
    Boolean(paperShadow.manual_handoff) ||
    nextStep === 'review_shadow_divergence' ||
    nextStep === 'resolve_shadow_divergence' ||
    paperShadow.status === 'review_required' ||
    paperShadow.status === 'diverged' ||
    paperShadow.divergence_status === 'review_required' ||
    paperShadow.divergence_status === 'diverged';
  if (!shouldSummarize) {
    return null;
  }
  const summary = paperShadow.divergence_summary;
  const labels =
    locale === 'zh'
      ? {
          prefix: 'Paper/shadow',
          orderIntent: '订单意图',
          simOrder: '模拟订单',
          simFill: '模拟成交',
          diverged: '偏差',
          slippage: '模拟滑点',
          noBrokerSubmission: '不会提交券商订单',
        }
      : {
          prefix: 'Paper/shadow',
          orderIntent: 'order intent',
          simOrder: 'sim order',
          simFill: 'sim fill',
          diverged: 'Diverged',
          slippage: 'Sim slippage',
          noBrokerSubmission: 'No broker submission',
        };
  const countText = [
    overviewCountLabel(
      paperShadow.order_intent_count,
      labels.orderIntent,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_order_count,
      labels.simOrder,
      locale,
    ),
    overviewCountLabel(
      paperShadow.simulated_fill_count,
      labels.simFill,
      locale,
    ),
  ].join(locale === 'zh' ? '，' : ', ');
  const divergedRefs = (
    summary?.execution_comparison?.diverged_order_refs ?? []
  )
    .slice(0, 2)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const slippage = numericPaperShadowValue(
    summary?.cost_summary?.simulated_slippage_cost,
  );
  return [
    `${labels.prefix}: ${countText}`,
    ...paperShadowInputSnapshotSummary(paperShadow, locale),
    divergedRefs.length
      ? `${labels.diverged}: ${divergedRefs.join(locale === 'zh' ? '；' : '; ')}`
      : '',
    paperShadowManualHandoffSummary(paperShadow, locale),
    paperShadowReviewQueueSummary(paperShadow, locale),
    slippage !== null
      ? `${labels.slippage}: ${formatCurrencyValue(slippage)}`
      : '',
    summary?.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowInputSnapshotSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const snapshot = paperShadow.input_snapshot;
  const orderIntentCount = numericPaperShadowValue(
    snapshot?.order_intent_count,
  );
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot?.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot?.input_fingerprint) ??
    stringPaperShadowSnapshotValue(paperShadow.input_fingerprint);
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

export function stringPaperShadowSnapshotValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function paperShadowManualHandoffSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const handoff = paperShadow.manual_handoff;
  if (!handoff) {
    return null;
  }
  const labels =
    locale === 'zh'
      ? {
          prefix: '人工确认交接',
          queue: '复核队列',
          item: '项',
          items: '项',
          noBrokerSubmission: '不会提交券商订单',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          prefix: 'Manual handoff',
          queue: 'Review queue',
          item: 'item',
          items: 'items',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const queueCount = handoff.review_queue_count ?? 0;
  return [
    `${labels.prefix}: ${paperShadowManualHandoffStatusLabel(
      handoff.status,
      locale,
    )}`,
    queueCount > 0
      ? `${labels.queue}: ${queueCount} ${
          queueCount === 1 ? labels.item : labels.items
        }`
      : '',
    handoff.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    handoff.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ]
    .filter(Boolean)
    .join(' · ');
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

function paperShadowReviewQueueSummary(
  paperShadow: OperationsTodayResponse['paper_shadow'],
  locale: Locale,
) {
  const queue = paperShadow.review_queue ?? [];
  if (queue.length === 0) {
    return null;
  }
  const firstAction = queue[0]?.required_action
    ? operationsNextActionLabel(queue[0].required_action, locale)
    : '';
  const firstDetail = paperShadowReviewQueueItemSummary(queue[0], locale);
  if (locale === 'zh') {
    return [`复核队列：${queue.length} 项`, firstAction, firstDetail]
      .filter(Boolean)
      .join(' · ');
  }
  return [
    `Review queue: ${queue.length} item${queue.length === 1 ? '' : 's'}`,
    firstAction,
    firstDetail,
  ]
    .filter(Boolean)
    .join(' · ');
}

type OverviewPaperShadowReviewQueueItem = NonNullable<
  OperationsTodayResponse['paper_shadow']['review_queue']
>[number];

function paperShadowReviewQueueItemSummary(
  item: OverviewPaperShadowReviewQueueItem | undefined,
  locale: Locale,
) {
  if (!item) {
    return '';
  }
  const labels =
    locale === 'zh'
      ? {
          risk: '风控',
          manual: '人工确认',
          manualReady: '可确认',
          accountTruth: '账户事实',
          cash: '现金',
          constraints: '约束',
          projectedFee: '计划费用',
          simulatedFeeTax: '模拟费税',
          queueSlippage: '队列滑点',
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
          manualReady: 'Ready',
          accountTruth: 'Account truth',
          cash: 'Cash',
          constraints: 'Constraints',
          projectedFee: 'Projected fee',
          simulatedFeeTax: 'Sim fee/tax',
          queueSlippage: 'Queue slippage',
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
      ? `${labels.manual} ${
          item.manual_confirmation_status === 'ready_for_manual_confirmation'
            ? labels.manualReady
            : formatPublicStatus(item.manual_confirmation_status, locale)
        }`
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
  const constraints = paperShadowStatusCountSummary(
    item.constraint_status_counts,
    locale,
  );
  const costs = [
    paperShadowCurrencySummary(
      labels.projectedFee,
      item.cost_evidence?.estimated_total_fee,
    ),
    paperShadowCurrencySummary(
      labels.simulatedFeeTax,
      item.cost_evidence?.simulated_fee_tax_cost,
    ),
    paperShadowCurrencySummary(
      labels.queueSlippage,
      item.cost_evidence?.simulated_slippage_cost,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const marketContext = [
    paperShadowCurrencySummary(
      labels.expected,
      item.market_context?.expected_price,
    ),
    paperShadowFillPriceSummary(
      labels.fill,
      item.market_context?.simulated_fill_prices,
    ),
  ]
    .filter(Boolean)
    .join(' · ');
  const omsStatusPath = paperShadowOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = paperShadowTerminalOutcomeSummary(item, locale);
  const omsTransition = paperShadowLatestOmsTransition(item, locale);
  const evidence = (item.evidence_refs ?? [])
    .slice(0, 6)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean)
    .join(locale === 'zh' ? '；' : '; ');
  return [
    riskManual,
    accountCash,
    constraints ? `${labels.constraints} ${constraints}` : '',
    costs,
    marketContext,
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    omsStatusPath ? `${labels.omsPath}: ${omsStatusPath}` : '',
    omsTransition ? `${labels.omsTransition}: ${omsTransition}` : '',
    evidence ? `${labels.evidence}: ${evidence}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function paperShadowTerminalOutcomeSummary(
  item: OverviewPaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = paperShadowOmsStatusLabel(
    item.terminal_status ?? undefined,
    locale,
  );
  const reason = paperShadowTerminalReasonLabel(
    item.terminal_reason ?? undefined,
    locale,
  );
  const transition = item.terminal_oms_transition_ref
    ? formatPublicEvidenceReference(item.terminal_oms_transition_ref, locale)
    : '';
  return [status, reason, transition].filter(Boolean).join(' · ');
}

function paperShadowTerminalReasonLabel(
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

function paperShadowOmsStatusPath(
  values: string[] | undefined,
  locale: Locale,
) {
  if (!values || values.length === 0) {
    return '';
  }
  return values
    .map((value) => paperShadowOmsStatusLabel(value, locale))
    .filter(Boolean)
    .join(' > ');
}

function paperShadowLatestOmsTransition(
  item: OverviewPaperShadowReviewQueueItem,
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
  return `${orderId}${sequence}${paperShadowOmsStatusLabel(
    transition.to_status,
    locale,
  )}`;
}

function paperShadowOmsStatusLabel(
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

function paperShadowStatusCountSummary(
  values: Record<string, number> | undefined,
  locale: Locale,
) {
  return Object.entries(values ?? {})
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
    .map(([key, value]) => `${formatPublicStatus(key, locale)}: ${value}`)
    .join(locale === 'zh' ? '；' : '; ');
}

function paperShadowCurrencySummary(label: string, value: unknown) {
  const numeric = numericPaperShadowValue(value);
  return numeric === null ? '' : `${label} ${formatCurrencyValue(numeric)}`;
}

function paperShadowFillPriceSummary(
  label: string,
  values: unknown[] | undefined,
) {
  const prices = (values ?? [])
    .map((value) => numericPaperShadowValue(value))
    .filter((value): value is number => value !== null)
    .map((value) => formatCurrencyValue(value));
  return prices.length ? `${label} ${prices.join(', ')}` : '';
}
