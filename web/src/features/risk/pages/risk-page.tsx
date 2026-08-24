import { createLazyRoute } from '@tanstack/react-router';

import { formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { EvidenceState, WorkspaceHeader } from '../../../shared/ui/workbench';
import { RiskLoadingWorkspace } from '../components/risk-loading-workspace';
import { RiskResolvedWorkspace } from '../components/risk-resolved-workspace';
import { useRiskPageController } from '../model/use-risk-page-controller';

export function RiskPage() {
  const controller = useRiskPageController();
  const { copy, locale, state } = controller;

  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="risk"
    >
      <WorkspaceHeader
        eyebrow={copy.riskPage.kicker}
        title={copy.riskPage.title}
        description={copy.riskPage.subtitle}
        context={
          state.data
            ? copy.common.valuationEvidenceAsOf(
                formatTimestamp(
                  state.data.summary.valuation_as_of ??
                    state.data.summary.valuation_timestamp,
                ),
                formatPublicStatus(
                  state.data.summary.valuation_status ??
                    state.data.summary.quote_status,
                  locale,
                ),
              )
            : undefined
        }
      />
      {controller.isInitialRiskLoad ? (
        <RiskLoadingWorkspace controller={controller} />
      ) : controller.isRiskWorkspaceUnavailable ? (
        <EvidenceState
          kind="error"
          title={copy.states.error}
          description={copy.riskPage.error}
        />
      ) : (
        <RiskResolvedWorkspace controller={controller} />
      )}
    </section>
  );
}

export const Route = createLazyRoute('/risk')({
  component: RiskPage,
});
