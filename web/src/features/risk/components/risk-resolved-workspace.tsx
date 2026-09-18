import { EvidenceState } from '../../../shared/ui/workbench';
import type { RiskPageController } from '../model/use-risk-page-controller';
import { RiskAnalysisDisclosure } from './risk-analysis-disclosure';
import { RiskCommandWorkspace } from './risk-command-workspace';
import { RiskControlledActionDisclosure } from './risk-controlled-action-disclosure';
import { RiskDecisionHandoff } from './risk-decision-handoff';
import { RiskHistoryDisclosure } from './risk-history-disclosure';
import { RiskThresholdEvidence } from './risk-threshold-evidence';

export function RiskResolvedWorkspace({
  controller,
}: {
  controller: RiskPageController;
}) {
  return (
    <div className="space-y-5 sm:space-y-6">
      {controller.hasRiskRefreshError ? (
        <EvidenceState
          kind="partial"
          title={controller.copy.riskPage.refreshError}
        />
      ) : null}
      <RiskCommandWorkspace controller={controller} />
      <RiskThresholdEvidence controller={controller} />
      <RiskControlledActionDisclosure controller={controller} />
      <RiskDecisionHandoff controller={controller} />
      <RiskAnalysisDisclosure controller={controller} />
      <RiskHistoryDisclosure controller={controller} />
    </div>
  );
}
