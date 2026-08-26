import { useControlledLedgerCorrectionOperatorController } from './controlled-ledger-correction-operator-controller';
import type { ControlledLedgerCorrectionOperatorPanelProps } from './controlled-ledger-correction-operator-model';
import { ControlledLedgerCorrectionOperatorView } from './controlled-ledger-correction-operator-view';

export function ControlledLedgerCorrectionOperatorPanel(
  props: ControlledLedgerCorrectionOperatorPanelProps,
) {
  const controller = useControlledLedgerCorrectionOperatorController(props);
  return <ControlledLedgerCorrectionOperatorView controller={controller} />;
}
