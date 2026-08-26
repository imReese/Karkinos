import { useControlledTerminalClearanceOperatorController } from './controlled-terminal-clearance-operator-controller';
import type { ControlledTerminalClearanceOperatorPanelProps } from './controlled-terminal-clearance-operator-model';
import { ControlledTerminalClearanceOperatorView } from './controlled-terminal-clearance-operator-view';

export function ControlledTerminalClearanceOperatorPanel(
  props: ControlledTerminalClearanceOperatorPanelProps,
) {
  const controller = useControlledTerminalClearanceOperatorController(props);
  return <ControlledTerminalClearanceOperatorView controller={controller} />;
}
