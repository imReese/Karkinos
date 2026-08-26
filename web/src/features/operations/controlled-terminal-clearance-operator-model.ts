import type { ControlledOrderJourney } from './api';
import type { OperationsLocale } from './controlled-operation-panel-primitives';

export interface ControlledTerminalClearanceOperatorPanelProps {
  journey: ControlledOrderJourney;
  locale: OperationsLocale;
}

export function controlledTerminalClearanceContext(
  journey: ControlledOrderJourney,
) {
  const reconciliationRunId =
    journey.stages.find((stage) => stage.key === 'execution_reconciliation')
      ?.evidence_id ?? '';
  return {
    reconciliationRunId,
    actionable:
      journey.next_operator_action === 'preview_terminal_clearance' &&
      Boolean(journey.submit_intent_id) &&
      Boolean(reconciliationRunId),
  };
}
