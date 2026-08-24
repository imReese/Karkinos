import { formatPublicStatus } from '../../../shared/public-labels';
import { ExceptionList } from '../../../shared/ui/workbench';
import type { RiskPageController } from '../model/use-risk-page-controller';
import { riskExceptionLabels } from './risk-loading-workspace';

export function RiskDecisionHandoff({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, locale, riskReviewTask } = controller;
  if (!riskReviewTask) return null;

  return (
    <section data-testid="risk-decision-handoff" className="min-w-0 space-y-2">
      <h2 className="app-type-section-title text-[var(--app-text)]">
        {copy.riskPage.decisionHandoffKicker}
      </h2>
      <ExceptionList
        ariaLabel={copy.riskPage.decisionHandoffKicker}
        emptyState={copy.riskPage.noBlockingItems}
        density="compact"
        labels={riskExceptionLabels(locale)}
        items={[
          {
            id: riskReviewTask.id,
            severity: 'warning',
            statusLabel: formatPublicStatus(riskReviewTask.status, locale),
            title: copy.riskPage.decisionHandoffTitle,
            reason: copy.riskPage.decisionHandoffDetail(
              controller.riskCandidateCount,
              controller.riskCheckedCount,
            ),
            unblockCondition: copy.riskPage.decisionHandoffHow,
            nextAction: copy.riskPage.decisionHandoffWhat,
            evidence: copy.riskPage.decisionHandoffDoNot,
          },
        ]}
        className="[&>li>dl]:grid-cols-2 lg:[&>li>dl]:grid-cols-4"
      />
      <div className="flex min-w-0 flex-col gap-2 border-b border-[var(--app-divider)] pb-3 sm:flex-row sm:justify-end">
        <button
          type="button"
          className="app-button-primary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55 sm:min-h-9"
          disabled={controller.batchPreTradeRisk.isPending}
          onClick={() => void controller.runBatchRiskGate()}
        >
          {controller.batchPreTradeRisk.isPending
            ? copy.riskPage.runningBatchRiskGate
            : copy.riskPage.runBatchRiskGate}
        </button>
        <a
          className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
          href="/decision"
        >
          {copy.riskPage.returnToDecision}
        </a>
      </div>
      {controller.batchRiskMessage ? (
        <div className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-3 py-2 text-sm font-semibold text-[var(--app-success-text)]">
          {controller.batchRiskMessage}
        </div>
      ) : null}
      {controller.batchRiskBlockedMessage ? (
        <div
          role="status"
          className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-2 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
        >
          {controller.batchRiskBlockedMessage}
        </div>
      ) : null}
      {controller.batchRiskError ? (
        <div className="app-error-text mt-3 text-sm">
          {controller.batchRiskError}
        </div>
      ) : null}
    </section>
  );
}
