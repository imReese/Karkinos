import { type GateMatrixItem } from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { type Locale } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { type DecisionResponse } from '../api';
import {
  gateBlockingReasonLabels,
  gateRequirementLabels,
} from './decision-workflow-model';

export const DECISION_GATE_IDS = [
  'account_truth',
  'strategy_evidence',
  'risk_review',
  'paper_shadow_review',
  'manual_confirmation',
] as const;

function decisionGateState(status: string | null | undefined) {
  if (
    status === 'pass' ||
    status === 'passed' ||
    status === 'healthy' ||
    status === 'ready' ||
    status === 'attached' ||
    status === 'live'
  ) {
    return 'pass' as const;
  }
  if (
    status === 'blocked' ||
    status === 'failed' ||
    status === 'missing' ||
    status === 'not_attached'
  ) {
    return 'block' as const;
  }
  if (!status || status === 'unknown' || status === 'skipped') {
    return 'unknown' as const;
  }
  return 'warning' as const;
}

export function decisionGateMatrixItems(
  lane: DecisionResponse | undefined,
  labels: ReturnType<typeof useCopy>['decision'],
  locale: Locale,
): GateMatrixItem[] {
  const workflowTasks = new Map(
    (lane?.summary.workflow_tasks ?? []).map((task) => [task.id, task]),
  );
  const missingEvidence =
    locale === 'zh'
      ? '权威投影未提供该闸门证据'
      : 'Canonical projection did not provide this gate evidence';

  return DECISION_GATE_IDS.map((gateId) => {
    const task = workflowTasks.get(gateId);
    if (task) {
      const stateLabel = formatPublicStatus(task.status, locale);
      const blockers = gateBlockingReasonLabels(task.blocking_reasons, locale);
      const requiredActions = gateRequirementLabels(
        task.required_actions,
        labels,
      );
      return {
        id: gateId,
        gate: labels.workflowTaskLabel(gateId),
        state: decisionGateState(task.status),
        stateLabel,
        reason: blockers.join(' · ') || stateLabel,
        evidence: lane
          ? `${locale === 'zh' ? '工作流投影' : 'Workflow projection'} · ${formatTimestamp(lane.generated_at)}`
          : missingEvidence,
        unblockCondition:
          requiredActions.length > 0 ? requiredActions.join(' · ') : undefined,
      };
    }

    const fallback =
      gateId === 'account_truth'
        ? lane?.summary.account_truth
        : gateId === 'strategy_evidence'
          ? lane?.summary.strategy_attribution
          : undefined;
    if (fallback) {
      const stateLabel = formatPublicStatus(fallback.gate_status, locale);
      const requiredActions = gateRequirementLabels(
        fallback.required_actions ?? [],
        labels,
      );
      const blockers = gateBlockingReasonLabels(
        fallback.blocking_reasons ?? [],
        locale,
      );
      return {
        id: gateId,
        gate: labels.workflowTaskLabel(gateId),
        state: decisionGateState(fallback.gate_status),
        stateLabel,
        reason: blockers.join(' · ') || stateLabel,
        evidence: lane
          ? `${locale === 'zh' ? '决策摘要' : 'Decision summary'} · ${formatTimestamp(lane.generated_at)}`
          : missingEvidence,
        unblockCondition:
          requiredActions.length > 0 ? requiredActions.join(' · ') : undefined,
      };
    }

    return {
      id: gateId,
      gate: labels.workflowTaskLabel(gateId),
      state: 'unknown',
      stateLabel: formatPublicStatus('unknown', locale),
      reason: missingEvidence,
      evidence: missingEvidence,
    };
  });
}
