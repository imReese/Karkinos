import { useControlledLedgerPostingOperatorController } from './controlled-ledger-posting-operator-controller';
import type { ControlledLedgerPostingOperatorPanelProps } from './controlled-ledger-posting-operator-model';
import { ControlledLedgerPostingOperatorView } from './controlled-ledger-posting-operator-view';

export function ControlledLedgerPostingOperatorPanel(
  props: ControlledLedgerPostingOperatorPanelProps,
) {
  const controller = useControlledLedgerPostingOperatorController(props);
  return <ControlledLedgerPostingOperatorView controller={controller} />;
}
