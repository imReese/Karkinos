import { useCurrentPerOrderDossierOperatorController } from './current-per-order-dossier-operator-controller';
import type { CurrentPerOrderDossierOperatorPanelProps } from './current-per-order-dossier-operator-model';
import { CurrentPerOrderDossierOperatorView } from './current-per-order-dossier-operator-view';

export function CurrentPerOrderDossierOperatorPanel(
  props: CurrentPerOrderDossierOperatorPanelProps,
) {
  const controller = useCurrentPerOrderDossierOperatorController(props);
  return <CurrentPerOrderDossierOperatorView controller={controller} />;
}
