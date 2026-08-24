import { formatCurrency, formatTimestamp } from '../../../shared/format';
import { type Locale } from '../../../shared/preferences/context';
import {
  formatPublicEvidenceReference,
  formatPublicStatus,
} from '../../../shared/public-labels';
import type {
  OperationsTodayResponse,
  PaperShadowRunReviewResponse,
} from '../operations-boundary';

export type PaperShadowRunSummary = OperationsTodayResponse['paper_shadow'];
type PaperShadowReviewQueueItem = NonNullable<
  PaperShadowRunSummary['review_queue']
>[number];

export function paperShadowRunNeedsReview(run: PaperShadowRunSummary | null) {
  if (!run?.run_id) {
    return false;
  }
  if (run.review_status === 'accepted_for_manual_confirmation') {
    return false;
  }
  return (
    ['diverged', 'review_required'].includes(run.status) ||
    ['resolve_shadow_divergence', 'review_shadow_divergence'].includes(
      run.next_manual_review_step,
    )
  );
}

export function paperShadowAcceptedReviewEvidenceItems(
  review: PaperShadowRunReviewResponse | null,
  run: PaperShadowRunSummary | null,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          reviewedBy: '复核人',
          reviewedAt: '复核时间',
          reviewSafety: '复核安全边界',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          reviewedBy: 'Reviewed by',
          reviewedAt: 'Reviewed at',
          reviewSafety: 'Review safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const reviewer = review?.reviewer ?? run?.reviewer;
  const reviewedAt = review?.reviewed_at ?? run?.reviewed_at;
  const safetyItems = [
    (review?.does_not_submit_broker_order ??
    run?.divergence_summary?.does_not_submit_broker_order)
      ? labels.noBrokerSubmission
      : '',
    (review?.does_not_mutate_production_ledger ??
    run?.divergence_summary?.does_not_mutate_production_ledger)
      ? labels.noLedgerMutation
      : '',
  ].filter(Boolean);

  return [
    reviewer ? `${labels.reviewedBy}: ${reviewer}` : '',
    reviewedAt ? `${labels.reviewedAt}: ${formatTimestamp(reviewedAt)}` : '',
    safetyItems.length
      ? `${labels.reviewSafety}: ${safetyItems.join(' · ')}`
      : '',
  ].filter(Boolean);
}

function paperShadowNextStepLabel(
  value: string | null | undefined,
  locale: Locale,
) {
  const labels: Record<string, { en: string; zh: string }> = {
    none: { en: 'No additional action', zh: '无需额外处理' },
    review_shadow_divergence: {
      en: 'Review paper/shadow divergence evidence',
      zh: '复核模拟与影子检验的偏差证据',
    },
    resolve_shadow_divergence: {
      en: 'Resolve paper/shadow divergence before approval',
      zh: '批准前处理模拟与影子检验偏差',
    },
    review_manual_confirmation: {
      en: 'Review manual order confirmation',
      zh: '复核人工下单确认',
    },
    run_paper_shadow_daily: {
      en: 'Run paper/shadow simulation before manual confirmation',
      zh: '人工确认前先运行模拟与影子检验',
    },
    wait_for_paper_shadow_run: {
      en: 'Paper/shadow simulation is running; wait for completion',
      zh: '模拟与影子检验正在运行，等待完成',
    },
    inspect_failed_run: {
      en: 'Inspect failed paper/shadow run before approval',
      zh: '批准前检查失败的模拟与影子检验',
    },
  };
  const key = value || 'none';
  return labels[key]?.[locale] ?? formatPublicStatus(key, locale);
}

function numericPaperShadowValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function latestPaperShadowRunEvidenceItems(
  run: PaperShadowRunSummary,
  locale: Locale,
) {
  const labels =
    locale === 'zh'
      ? {
          run: 'Run',
          status: '状态',
          orderIntents: '订单意图',
          simOrders: '模拟订单',
          simFills: '模拟成交',
          next: '下一步',
          evidenceRefs: '证据引用',
          divergedOrders: '偏差订单',
          slippage: '模拟滑点',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          run: 'Run',
          status: 'Status',
          orderIntents: 'Order intents',
          simOrders: 'Sim orders',
          simFills: 'Sim fills',
          next: 'Next',
          evidenceRefs: 'Evidence refs',
          divergedOrders: 'Diverged orders',
          slippage: 'Sim slippage',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const summary = run.divergence_summary;
  const divergedRefs = (
    summary?.execution_comparison?.diverged_order_refs ?? []
  )
    .slice(0, 2)
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const evidenceRefs = selectPaperShadowRunEvidenceRefs(run.evidence_refs ?? [])
    .map((ref) => formatPublicEvidenceReference(ref, locale))
    .filter(Boolean);
  const reviewQueueItems = latestPaperShadowReviewQueueEvidenceItems(
    run,
    locale,
  );
  const inputSnapshotItems = paperShadowInputSnapshotEvidenceItems(
    run.input_snapshot,
    run.input_fingerprint,
    locale,
  );
  const slippage = numericPaperShadowValue(
    summary?.cost_summary?.simulated_slippage_cost,
  );
  return [
    `${labels.run}: ${run.run_id ?? '--'}`,
    `${labels.status}: ${formatPublicStatus(run.status, locale)}`,
    `${labels.orderIntents}: ${run.order_intent_count}`,
    `${labels.simOrders}: ${run.simulated_order_count}`,
    `${labels.simFills}: ${run.simulated_fill_count}`,
    ...inputSnapshotItems,
    `${labels.next}: ${paperShadowNextStepLabel(
      run.next_manual_review_step,
      locale,
    )}`,
    divergedRefs.length
      ? `${labels.divergedOrders}: ${divergedRefs.join(
          locale === 'zh' ? '；' : '; ',
        )}`
      : '',
    evidenceRefs.length
      ? `${labels.evidenceRefs}: ${evidenceRefs.join(
          locale === 'zh' ? '；' : '; ',
        )}`
      : '',
    ...reviewQueueItems,
    slippage !== null ? `${labels.slippage}: ${formatCurrency(slippage)}` : '',
    summary?.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    summary?.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);
}

function paperShadowInputSnapshotEvidenceItems(
  snapshot: Record<string, unknown> | undefined,
  fallbackFingerprint: string | null | undefined,
  locale: Locale,
) {
  const orderIntentCount = numericPaperShadowValue(
    snapshot?.order_intent_count,
  );
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot?.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot?.input_fingerprint) ??
    stringPaperShadowSnapshotValue(fallbackFingerprint);
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

function stringPaperShadowSnapshotValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function latestPaperShadowReviewQueueEvidenceItems(
  run: PaperShadowRunSummary,
  locale: Locale,
) {
  const item = run.review_queue?.[0];
  if (!item) {
    return [];
  }

  const labels =
    locale === 'zh'
      ? {
          reviewQueue: '复核队列',
          reason: '原因',
          terminalOutcome: '终态结果',
          omsPath: 'OMS 路径',
          latestTransition: '最新状态变更',
          reviewSafety: '复核安全边界',
          noBrokerSubmission: '不提交券商订单',
          noLedgerMutation: '不修改生产账本',
        }
      : {
          reviewQueue: 'Review queue',
          reason: 'Reason',
          terminalOutcome: 'Terminal outcome',
          omsPath: 'OMS path',
          latestTransition: 'Latest transition',
          reviewSafety: 'Review safety',
          noBrokerSubmission: 'No broker submission',
          noLedgerMutation: 'No production ledger mutation',
        };
  const target = item.symbol ?? item.order_id ?? item.review_id;
  const statusPath = paperShadowOmsStatusPath(item.oms_status_path, locale);
  const terminalOutcome = paperShadowTerminalOutcomeSummary(item, locale);
  const latestTransition = latestOmsTransitionEvidenceRef(
    item.oms_transition_refs ?? [],
  );
  const safetyItems = [
    item.does_not_submit_broker_order ? labels.noBrokerSubmission : '',
    item.does_not_mutate_production_ledger ? labels.noLedgerMutation : '',
  ].filter(Boolean);

  return [
    `${labels.reviewQueue}: ${target} · ${paperShadowNextStepLabel(
      item.required_action,
      locale,
    )}`,
    item.reason ? `${labels.reason}: ${item.reason}` : '',
    terminalOutcome ? `${labels.terminalOutcome}: ${terminalOutcome}` : '',
    statusPath ? `${labels.omsPath}: ${statusPath}` : '',
    latestTransition
      ? `${labels.latestTransition}: ${formatPublicEvidenceReference(
          latestTransition,
          locale,
        )}`
      : '',
    safetyItems.length
      ? `${labels.reviewSafety}: ${safetyItems.join(
          locale === 'zh' ? ' · ' : ' · ',
        )}`
      : '',
  ].filter(Boolean);
}

function paperShadowTerminalOutcomeSummary(
  item: PaperShadowReviewQueueItem,
  locale: Locale,
) {
  const status = item.terminal_status
    ? paperShadowOmsStatusLabel(item.terminal_status, locale)
    : '';
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
  values: PaperShadowReviewQueueItem['oms_status_path'],
  locale: Locale,
) {
  if (!values?.length) {
    return null;
  }
  return values
    .map((value) => paperShadowOmsStatusLabel(value, locale))
    .join(locale === 'zh' ? ' → ' : ' → ');
}

function paperShadowOmsStatusLabel(value: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    accepted: { en: 'Accepted', zh: '已接受模拟' },
    cancelled: { en: 'Cancelled', zh: '已取消' },
    canceled: { en: 'Cancelled', zh: '已取消' },
    expired: { en: 'Expired', zh: '已过期' },
    filled: { en: 'Filled', zh: '已成交' },
    partially_filled: { en: 'Partially Filled', zh: '部分成交' },
    reconciled: { en: 'Reconciled', zh: '已对账' },
    rejected: { en: 'Rejected', zh: '已拒绝' },
    staged: { en: 'Staged', zh: '已暂存' },
    submitted: { en: 'Submitted', zh: '已提交模拟' },
  };
  return labels[value]?.[locale] ?? formatPublicStatus(value, locale);
}

function selectPaperShadowRunEvidenceRefs(refs: string[]) {
  const selected: string[] = [];
  const seen = new Set<string>();
  const add = (ref: string | undefined) => {
    if (ref && !seen.has(ref) && selected.length < 3) {
      selected.push(ref);
      seen.add(ref);
    }
  };

  add(
    refs.find((ref) => /^(?:paper_shadow_order|paper_order|order):/.test(ref)),
  );
  add(refs.find((ref) => /^(?:paper_shadow_fill|paper_fill|fill):/.test(ref)));
  add(latestOmsTransitionEvidenceRef(refs));

  for (const ref of refs) {
    add(ref);
  }

  return selected;
}

function latestOmsTransitionEvidenceRef(refs: string[]) {
  return refs
    .filter((ref) => ref.startsWith('oms_transition:'))
    .reduce<string | undefined>((latest, ref) => {
      if (!latest) {
        return ref;
      }
      return omsTransitionSequence(ref) >= omsTransitionSequence(latest)
        ? ref
        : latest;
    }, undefined);
}

function omsTransitionSequence(ref: string) {
  const sequence = Number(ref.split(':')[2]);
  return Number.isFinite(sequence) ? sequence : -1;
}
