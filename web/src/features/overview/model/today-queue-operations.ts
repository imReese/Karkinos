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
import { paperShadowOverviewEvidenceSummary } from './today-queue-paper-shadow';
import {
  executionReconciliationOverviewSummary,
  operationsSchedulerEvidenceSummary,
} from './today-queue-operations-evidence';
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
