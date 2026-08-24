import type { AppCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  operationsAttentionResolutionLabel,
  operationsNextActionLabel,
  operationsTargetHref,
  type DailyTradingPlanResponse,
  type OperationsTodayResponse,
} from '../overview-feature-boundary';
import {
  numericPaperShadowValue,
  paperShadowOverviewEvidenceSummary,
  stringPaperShadowSnapshotValue,
} from './today-queue-paper-shadow';
import type { TodayQueueItem } from './today-queue-types';

type OperationsSubsystem = OperationsTodayResponse['subsystems'][number];
type DailyPlanBlocker = NonNullable<
  OperationsTodayResponse['daily_plan']['blocker_summary']
>[number];

function primaryOperationsDailyPlanBlocker(
  operations: OperationsTodayResponse | null | undefined,
): DailyPlanBlocker | null {
  const summary = operations?.daily_plan.blocker_summary ?? [];
  if (!operations || operations.daily_plan.blocked_count <= 0) {
    return null;
  }
  return summary[0] ?? null;
}

function isAwaitingRiskGateBlocker(blocker: DailyPlanBlocker | null) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'evidence_not_ready' ||
      reasons.includes('awaiting_risk_gate') ||
      reasons.includes('risk_gate_not_checked'))
  );
}

function isRiskBlockedBlocker(blocker: DailyPlanBlocker | null) {
  if (!blocker) {
    return false;
  }
  const reasons = blocker.reasons ?? [];
  return (
    blocker.target === 'risk' &&
    (blocker.category === 'risk_blocked' ||
      reasons.includes('risk_gate_blocked') ||
      reasons.some((reason) =>
        [
          'cash reserve would fall below min_cash_reserve',
          'projected position weight exceeds max_position_weight',
          'cash_buffer_breached',
          'concentration_limit_breached',
        ].includes(reason),
      ))
  );
}

function operationsQueueTarget(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsSubsystem | undefined,
) {
  const primaryTarget = primarySubsystem?.target ?? operations?.primary_target;
  if (primaryTarget === 'market' || primaryTarget === 'account-truth') {
    return primaryTarget;
  }
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker) || isRiskBlockedBlocker(blocker)) {
    return 'risk';
  }
  return primaryTarget;
}

function operationsDuplicatesTradingPlanReview(
  operations: OperationsTodayResponse | null | undefined,
  tradingPlan: DailyTradingPlanResponse | null | undefined,
  primarySubsystem: OperationsSubsystem | undefined,
) {
  if (!operations || !tradingPlan) {
    return false;
  }
  const operationsManualReady = operations.daily_plan.manual_ready_count;
  const nextAction = operationsPrimaryNextAction(operations, primarySubsystem);
  return (
    operations.conclusion_status === 'manual_action_required' &&
    operationsQueueTarget(operations, primarySubsystem) === 'trading' &&
    (nextAction === 'review_manual_order_intents' ||
      nextAction === 'review_manual_confirmation') &&
    operations.daily_plan.blocked_count === 0 &&
    tradingPlan.blocked_count === 0 &&
    operationsManualReady > 0 &&
    tradingPlan.manual_ready_count === operationsManualReady
  );
}

function operationsStatusTitle(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const status = operations?.conclusion_status;
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh' ? '风险闸门待检查' : 'Risk gate checks pending';
  }
  if (isRiskBlockedBlocker(blocker)) {
    return locale === 'zh' ? '风控阻断待复核' : 'Risk blocks need review';
  }
  if (locale === 'zh') {
    if (!operations) return '运营状态加载中';
    if (status === 'blocked') return '今日待办存在阻断';
    if (status === 'manual_action_required') return '今日待办需要人工复核';
    if (status === 'degraded') return '今日待办存在降级项';
    return '今日运行状态正常';
  }
  if (!operations) return 'Operations status loading';
  if (status === 'blocked') return 'Today runbook has blockers';
  if (status === 'manual_action_required') {
    return 'Today runbook needs manual review';
  }
  if (status === 'degraded') return 'Today runbook has degraded checks';
  return 'Today runbook is healthy';
}

function riskBlockReasonLabel(reason: string, locale: Locale) {
  const labels: Record<string, { en: string; zh: string }> = {
    'cash reserve would fall below min_cash_reserve': {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    cash_buffer_breached: {
      en: 'cash buffer would be breached',
      zh: '现金缓冲不足',
    },
    'projected position weight exceeds max_position_weight': {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    concentration_limit_breached: {
      en: 'single-name weight would exceed policy',
      zh: '单标的仓位过高',
    },
    risk_gate_blocked: {
      en: 'risk gate blocked the action',
      zh: '风控闸门阻断动作',
    },
  };
  return labels[reason]?.[locale] ?? formatPublicStatus(reason, locale);
}

function riskBlockerDetailText(
  blocker: DailyPlanBlocker | null,
  locale: Locale,
) {
  if (!blocker) {
    return null;
  }
  const reasons = Array.from(
    new Set(
      (blocker.reasons ?? []).map((reason) =>
        riskBlockReasonLabel(reason, locale),
      ),
    ),
  ).slice(0, 3);
  const symbols = (blocker.sample_symbols ?? []).slice(0, 3);
  const reasonText = reasons.length
    ? reasons.join(locale === 'zh' ? '、' : ', ')
    : locale === 'zh'
      ? '风控规则'
      : 'risk policy';
  if (locale === 'zh') {
    const symbolText = symbols.length ? `；涉及 ${symbols.join('、')}` : '';
    return `${blocker.count} 个候选被风控阻断：${reasonText}${symbolText}。先复核原因，不进入人工确认。`;
  }
  const symbolText = symbols.length ? ` Symbols: ${symbols.join(', ')}.` : '';
  return `${blocker.count} candidates are blocked by risk: ${reasonText}.${symbolText} Review the reasons before manual confirmation.`;
}

function operationsDetailText(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
  fallback: string,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    if (locale === 'zh') {
      return `${blocker.count} 个候选等待风险闸门检查；当前 ${operations?.daily_plan.manual_ready_count ?? 0} 个可人工确认。`;
    }
    return `${blocker.count} candidates are waiting for risk-gate checks; ${operations?.daily_plan.manual_ready_count ?? 0} are ready for manual confirmation.`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return riskBlockerDetailText(blocker, locale) ?? fallback;
  }
  const schedulerSummary = operationsSchedulerEvidenceSummary(
    operations,
    locale,
  );
  if (schedulerSummary) {
    return `${fallback} · ${schedulerSummary}`;
  }
  const reconciliationSummary = executionReconciliationOverviewSummary(
    operations,
    locale,
  );
  if (reconciliationSummary) {
    return `${fallback} · ${reconciliationSummary}`;
  }
  const paperShadowSummary = paperShadowOverviewEvidenceSummary(
    operations,
    locale,
  );
  return paperShadowSummary ? `${fallback} · ${paperShadowSummary}` : fallback;
}

function executionReconciliationOverviewSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const reconciliation = operations?.execution_reconciliation;
  if (!reconciliation || reconciliation.open_item_count <= 0) {
    return '';
  }
  const first = reconciliation.first_open_item;
  const manualSummary = first?.manual_execution_evidence_summary;
  const labels =
    locale === 'zh'
      ? {
          reviewCount: '对账复核',
          item: '项',
          items: '项',
          manualExecution: '手工成交',
          preview: '预览',
          noBrokerSubmission: '不会提交券商订单',
          noOmsMutation: '不会修改 OMS',
          noLedgerMutation: '不会修改生产账本',
        }
      : {
          reviewCount: 'Reconciliation review',
          item: 'item',
          items: 'items',
          manualExecution: 'Manual execution',
          preview: 'Preview',
          noBrokerSubmission: 'No broker submission',
          noOmsMutation: 'No OMS mutation',
          noLedgerMutation: 'No production ledger mutation',
        };
  const countLabel =
    reconciliation.open_item_count === 1 ? labels.item : labels.items;
  return [
    `${labels.reviewCount}: ${reconciliation.open_item_count} ${countLabel}`,
    operationsNextActionLabel(
      reconciliation.next_review_step || first?.suggested_action || 'none',
      locale,
    ),
    first?.order_id ? `${labels.manualExecution}: ${first.order_id}` : '',
    manualSummary?.preview_fingerprint
      ? `${labels.preview} ${manualSummary.preview_fingerprint}`
      : '',
    reconciliation.does_not_submit_broker_order ||
    manualSummary?.submitted_to_broker === false
      ? labels.noBrokerSubmission
      : '',
    reconciliation.does_not_mutate_oms ||
    manualSummary?.does_not_mutate_oms === true
      ? labels.noOmsMutation
      : '',
    reconciliation.does_not_mutate_production_ledger ||
    manualSummary?.does_not_mutate_production_ledger === true
      ? labels.noLedgerMutation
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function operationsSchedulerEvidenceSummary(
  operations: OperationsTodayResponse | null | undefined,
  locale: Locale,
) {
  const scheduler = operations?.scheduler;
  if (!scheduler) {
    return '';
  }
  const status = String(scheduler.status ?? '')
    .trim()
    .toLowerCase();
  const isFailure =
    status.endsWith('_failed') || status === 'failed' || status === 'error';
  if (!isFailure && operations?.primary_target !== 'scheduler') {
    return '';
  }
  return [
    scheduler.run_id
      ? locale === 'zh'
        ? `运行 ${scheduler.run_id}`
        : `Run ${scheduler.run_id}`
      : '',
    schedulerInputSnapshotSummary(scheduler, locale),
    schedulerRerunKeySummary(scheduler.idempotency_key, locale),
    schedulerRetrySummary(scheduler.retry_state, locale),
    schedulerErrorSummary(scheduler.error),
    scheduler.does_not_submit_broker_order
      ? locale === 'zh'
        ? '不会提交券商订单'
        : 'No broker submission'
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

function schedulerInputSnapshotSummary(
  scheduler: NonNullable<OperationsTodayResponse['scheduler']>,
  locale: Locale,
) {
  const snapshot = scheduler.input_snapshot;
  if (!snapshot) {
    return '';
  }
  const orderIntentCount = numericPaperShadowValue(snapshot.order_intent_count);
  const sourceDecision = stringPaperShadowSnapshotValue(
    snapshot.source_decision,
  );
  const fingerprint =
    stringPaperShadowSnapshotValue(snapshot.input_fingerprint) ??
    stringPaperShadowSnapshotValue(scheduler.input_fingerprint);
  const labels =
    locale === 'zh'
      ? {
          input: '输入快照',
          orderIntent: '订单意图',
          source: '源决策',
          fingerprint: '指纹',
        }
      : {
          input: 'Input snapshot',
          orderIntent: 'order intent',
          source: 'Source',
          fingerprint: 'Fingerprint',
        };
  const parts = [
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
  return parts.length ? `${labels.input}: ${parts.join(' · ')}` : '';
}

function schedulerRerunKeySummary(
  idempotencyKey: string | null | undefined,
  locale: Locale,
) {
  const key = stringPaperShadowSnapshotValue(idempotencyKey);
  if (!key) {
    return '';
  }
  return locale === 'zh' ? `重跑键: ${key}` : `Rerun key: ${key}`;
}

function schedulerRetrySummary(
  retryState: Record<string, unknown> | undefined,
  locale: Locale,
) {
  if (!retryState) {
    return '';
  }
  const attempt = numericRetryValue(retryState.attempt);
  if (attempt <= 0) {
    return '';
  }
  const maxAttempts = Math.max(
    numericRetryValue(retryState.max_attempts),
    attempt,
  );
  const previousAttempts = numericRetryValue(retryState.previous_attempts);
  if (locale === 'zh') {
    return previousAttempts > 0
      ? `重试 ${attempt}/${maxAttempts}；此前 ${previousAttempts} 次`
      : `重试 ${attempt}/${maxAttempts}`;
  }
  return previousAttempts > 0
    ? `Retry ${attempt}/${maxAttempts}; previous attempts ${previousAttempts}`
    : `Retry ${attempt}/${maxAttempts}`;
}

function schedulerErrorSummary(error: Record<string, unknown> | undefined) {
  if (!error) {
    return '';
  }
  const type = String(error.type ?? '').trim();
  const message = String(error.message ?? '').trim();
  if (type && message) {
    return `${type}: ${message}`;
  }
  return type || message;
}

function numericRetryValue(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Math.trunc(numberValue) : 0;
}

function operationsPrimaryNextAction(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsSubsystem | undefined,
) {
  if (
    operations?.paper_shadow.review_status ===
      'accepted_for_manual_confirmation' ||
    operations?.paper_shadow.status === 'within_expectations' ||
    operations?.paper_shadow.divergence_status === 'within_expectations'
  ) {
    return operations.paper_shadow.next_manual_review_step;
  }
  return (
    primarySubsystem?.next_action ??
    operations?.paper_shadow.next_manual_review_step
  );
}

function operationsStatusMeta(
  operations: OperationsTodayResponse,
  locale: Locale,
) {
  const blocker = primaryOperationsDailyPlanBlocker(operations);
  if (blocker && isAwaitingRiskGateBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 待检查`
      : `${blocker.count} pending checks`;
  }
  if (blocker && isRiskBlockedBlocker(blocker)) {
    return locale === 'zh'
      ? `${blocker.count} 风控阻断`
      : `${blocker.count} risk blocked`;
  }
  const { blocked, manual_action_required, degraded, pass, total } =
    operations.health;
  if (locale === 'zh') {
    if (blocked > 0) return `${blocked} 阻断`;
    if (operations.conclusion_status === 'degraded' && degraded > 0) {
      return `${degraded} 降级`;
    }
    if (manual_action_required > 0) return `${manual_action_required} 人工复核`;
    if (degraded > 0) return `${degraded} 降级`;
    return `${pass}/${total} 通过`;
  }
  if (blocked > 0) return `${blocked} blocked`;
  if (operations.conclusion_status === 'degraded' && degraded > 0) {
    return `${degraded} degraded`;
  }
  if (manual_action_required > 0) {
    return `${manual_action_required} manual review`;
  }
  if (degraded > 0) return `${degraded} degraded`;
  return `${pass}/${total} passed`;
}

function operationsActionLabel(
  operations: OperationsTodayResponse | null | undefined,
  primarySubsystem: OperationsSubsystem | undefined,
  labels: AppCopy['overview']['dashboard'],
  locale: Locale,
) {
  const target = operationsQueueTarget(operations, primarySubsystem);
  if (target === 'risk') return labels.operationsViewRisk;
  if (target === 'account-truth') return labels.operationsViewAccountTruth;
  if (target === 'market') return labels.operationsViewMarket;
  if (target === 'trading') return labels.operationsViewTrading;
  if (target === 'paper-shadow') return labels.operationsViewPaperShadow;
  return locale === 'zh' ? '查看运行证据' : 'View run evidence';
}

export function decisionQueueResolution(
  operations: OperationsTodayResponse | null | undefined,
  copy: AppCopy,
  locale: Locale,
) {
  const attention =
    operations?.attention_items?.find(
      (item) => item.subsystem_id === 'daily_trading_plan',
    ) ??
    operations?.attention_items?.find(
      (item) => item.subsystem_id === 'strategy_candidates',
    );
  return attention
    ? copy.overview.dashboard.resolutionCondition(
        operationsAttentionResolutionLabel(
          attention.resolution_condition,
          locale,
        ),
      )
    : undefined;
}

export function buildOperationsQueueItem({
  operations,
  loading,
  error,
  tradingPlan,
  copy,
  locale,
}: {
  operations?: OperationsTodayResponse | null;
  loading: boolean;
  error: boolean;
  tradingPlan?: DailyTradingPlanResponse | null;
  copy: AppCopy;
  locale: Locale;
}) {
  const labels = copy.overview.dashboard;
  const primarySubsystem =
    operations?.subsystems.find(
      (item) =>
        item.target === operations.primary_target &&
        item.status === operations.conclusion_status,
    ) ??
    operations?.subsystems.find(
      (item) => item.status === operations.conclusion_status,
    );
  const primaryTarget = operationsQueueTarget(operations, primarySubsystem);
  const primaryAttention =
    operations?.attention_items?.find(
      (item) => item.subsystem_id === primarySubsystem?.id,
    ) ??
    operations?.attention_items?.find((item) => item.target === primaryTarget);
  const resolution = primaryAttention
    ? labels.resolutionCondition(
        operationsAttentionResolutionLabel(
          primaryAttention.resolution_condition,
          locale,
        ),
      )
    : undefined;
  const tone = error
    ? 'danger'
    : operations?.conclusion_status === 'blocked'
      ? 'danger'
      : operations?.conclusion_status === 'manual_action_required' ||
          operations?.conclusion_status === 'degraded'
        ? 'warning'
        : 'success';
  const priority =
    error ||
    operations?.conclusion_status === 'blocked' ||
    operations?.conclusion_status === 'manual_action_required'
      ? 'first'
      : operations?.conclusion_status === 'degraded'
        ? 'watch'
        : 'normal';
  const item: TodayQueueItem = {
    key: 'operations',
    title: error
      ? locale === 'zh'
        ? '运营状态不可用'
        : 'Operations status unavailable'
      : operationsStatusTitle(operations, locale),
    detail: loading
      ? copy.states.loading
      : operations
        ? operationsDetailText(
            operations,
            locale,
            operationsNextActionLabel(
              operationsPrimaryNextAction(operations, primarySubsystem),
              locale,
            ),
          )
        : copy.states.loading,
    meta: loading
      ? copy.states.loading
      : operations
        ? operationsStatusMeta(operations, locale)
        : '--',
    href: operationsTargetHref(primaryTarget),
    actionLabel: operationsActionLabel(
      operations,
      primarySubsystem,
      labels,
      locale,
    ),
    tone,
    priority,
    resolution,
  };
  return {
    item,
    primaryTarget,
    duplicatesTradingPlanReview: operationsDuplicatesTradingPlanReview(
      operations,
      tradingPlan,
      primarySubsystem,
    ),
  };
}
