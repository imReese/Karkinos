import type { ControlledOrderJourney } from './api';
import type { OperationsLocale } from './controlled-operation-panel-primitives';

export interface ControlledLedgerPostingOperatorPanelProps {
  journey: ControlledOrderJourney;
  locale: OperationsLocale;
}

export function controlledLedgerPostingContext(
  journey: ControlledOrderJourney,
) {
  const clearanceId =
    journey.stages.find(
      (stage) => stage.key === 'terminal_reconciliation_clearance',
    )?.evidence_id ?? '';
  return {
    clearanceId,
    actionable:
      journey.next_operator_action === 'preview_reconciled_ledger_posting' &&
      Boolean(clearanceId),
  };
}
