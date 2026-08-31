import { DecisionCockpitContent } from './decision-cockpit-content';
import {
  DecisionCockpitError,
  DecisionCockpitLoading,
} from './decision-cockpit-states';
import { useDecisionCockpitWorkspace } from './use-decision-cockpit-workspace';

export function DecisionCockpitPage() {
  const model = useDecisionCockpitWorkspace();
  if (model.loading) return <DecisionCockpitLoading />;
  if (model.error) return <DecisionCockpitError error={model.error} />;
  return <DecisionCockpitContent model={model} />;
}
