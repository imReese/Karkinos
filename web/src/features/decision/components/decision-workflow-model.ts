import { useCopy } from '../../../shared/i18n/context';
import { type Locale } from '../../../shared/preferences/context';
import {
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  type ActionCard,
  type DecisionCandidate,
  type DecisionResponse,
  type DecisionWorkflowTask,
  type SignalResponse,
} from '../api';

export function gateRequirementLabels(
  values: string[],
  labels: ReturnType<typeof useCopy>['decision'],
) {
  return values.map((value) => labels.gateRequirementLabel(value));
}

export function gateBlockingReasonLabels(values: string[], locale: Locale) {
  return values.map((value) => formatPublicNote(value, locale));
}

export function decisionGateDetailLabels({
  requiredActions,
  blockingReasons,
  labels,
  locale,
}: {
  requiredActions: string[];
  blockingReasons: string[];
  labels: ReturnType<typeof useCopy>['decision'];
  locale: Locale;
}) {
  return requiredActions.length > 0
    ? gateRequirementLabels(requiredActions, labels)
    : gateBlockingReasonLabels(blockingReasons, locale);
}

export function decisionWorkflowTarget(
  taskId: string,
  labels: ReturnType<typeof useCopy>['decision'],
) {
  switch (taskId) {
    case 'data_refresh':
      return { href: '/market', label: labels.workflowOpenMarket };
    case 'risk_review':
      return { href: '/risk', label: labels.workflowOpenRisk };
    case 'strategy_evidence':
    case 'paper_shadow_review':
      return { href: '/backtest', label: labels.workflowOpenBacktest };
    case 'manual_confirmation':
      return { href: '/trading', label: labels.workflowOpenTrading };
    default:
      return null;
  }
}

type DecisionNextActionGuide = {
  title: string;
  reason: string;
  status: string;
  unblockCondition: string;
  note: string;
  cta: string | null;
  href: string | null;
};

function decisionNeedsAction(task: DecisionWorkflowTask) {
  return task.status !== 'pass' && task.status !== 'passed';
}

function decisionActionRank(task: DecisionWorkflowTask) {
  if (task.status === 'blocked') {
    return 0;
  }
  if (task.status === 'review_required') {
    return 1;
  }
  if (task.status === 'degraded') {
    return 2;
  }
  return 3;
}

export function decisionNextActionGuide(
  lanes: DecisionResponse[],
  labels: ReturnType<typeof useCopy>['decision'],
  locale: Locale,
): DecisionNextActionGuide | null {
  const rankedTasks = lanes.flatMap((lane, laneIndex) =>
    (lane.summary.workflow_tasks ?? []).map((task) => ({
      lane,
      laneIndex,
      task,
    })),
  );
  const actionableTasks = rankedTasks
    .filter(({ task }) => decisionNeedsAction(task))
    .sort((left, right) => {
      const actionRank =
        decisionActionRank(left.task) - decisionActionRank(right.task);
      if (actionRank !== 0) {
        return actionRank;
      }
      const priority = left.task.priority - right.task.priority;
      return priority === 0 ? left.laneIndex - right.laneIndex : priority;
    });
  const primary =
    actionableTasks.find(({ task }) => task.id !== 'manual_confirmation') ??
    actionableTasks[0];

  if (!primary) {
    return null;
  }

  const { lane, task } = primary;
  const taskLabel = labels.workflowTaskLabel(task.id);
  const actionLabels = decisionGateDetailLabels({
    requiredActions: task.required_actions,
    blockingReasons: task.blocking_reasons,
    labels,
    locale,
  });
  const actionLabel =
    actionLabels[0] ?? formatPublicStatus(task.status, locale);
  const target = decisionWorkflowTarget(task.id, labels);
  const isRiskGateNext =
    task.id === 'risk_review' &&
    task.required_actions.includes('run_pre_trade_risk_gate');
  const title = isRiskGateNext
    ? labels.nextActionRiskTitle
    : labels.nextActionDefaultTitle(taskLabel);

  return {
    title,
    reason: isRiskGateNext
      ? labels.nextActionRiskDetail(
          lane.summary.candidate_count,
          lane.summary.ready_for_manual_confirmation_count,
        )
      : labels.nextActionDefaultDetail(actionLabel),
    status: formatPublicStatus(task.status, locale),
    unblockCondition: actionLabel,
    note:
      lane.summary.candidate_count >
      lane.summary.ready_for_manual_confirmation_count
        ? labels.nextActionCandidatePoolNote
        : labels.nextActionManualReadyNote,
    cta: target ? labels.workflowOpenSurfaceLabel(target.label, title) : null,
    href: target?.href ?? null,
  };
}

export function decisionCandidateBacktestHref(candidate: DecisionCandidate) {
  const params = new URLSearchParams();
  const symbol = candidate.symbol.trim();
  const assetClass = candidate.asset_class?.trim() ?? '';
  const strategyId = candidate.evidence.strategy.strategy_id?.trim() ?? '';
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

export function signalActionBacktestHref(action: ActionCard) {
  const params = new URLSearchParams();
  const symbol = action.symbol.trim();
  const assetClass = action.asset_class.trim();
  const strategyId = action.strategy_id.trim();
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

export function decisionCandidateHoldingAttributionHref(
  candidate: DecisionCandidate,
) {
  return `/portfolio/${encodeURIComponent(
    candidate.symbol,
  )}#holding-strategy-attribution-boundary`;
}

export function signalActionHoldingAttributionHref(action: ActionCard) {
  return `/portfolio/${encodeURIComponent(
    action.symbol,
  )}#holding-strategy-attribution-boundary`;
}

export function signalBacktestHref(signal: SignalResponse) {
  const params = new URLSearchParams();
  const symbol = signal.symbol.trim();
  const assetClass = signal.asset_class.trim();
  const strategyId = signal.strategy_id.trim();
  if (symbol) {
    params.set('symbol', symbol);
  }
  if (assetClass) {
    params.set('assetClass', assetClass);
  }
  if (strategyId) {
    params.set('strategy', strategyId);
  }
  const query = params.toString();
  return query ? `/backtest?${query}` : '/backtest';
}

export function signalHoldingAttributionHref(signal: SignalResponse) {
  return `/portfolio/${encodeURIComponent(
    signal.symbol,
  )}#holding-strategy-attribution-boundary`;
}
