import type { RiskPageController } from '../model/use-risk-page-controller';
import { RiskAnalysisDisclosure } from './risk-analysis-disclosure';
import { RiskCommandWorkspace } from './risk-command-workspace';
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
        <div
          role="status"
          className="rounded-[var(--app-radius-surface)] border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
        >
          {controller.copy.riskPage.refreshError}
        </div>
      ) : null}
      <RiskCommandWorkspace controller={controller} />
      <RiskDecisionHandoff controller={controller} />
      <RiskThresholdEvidence controller={controller} />
      <RiskAnalysisDisclosure controller={controller} />
      <RiskHistoryDisclosure controller={controller} />
    </div>
  );
}
