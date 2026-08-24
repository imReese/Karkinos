import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { PageHeader } from './decision-signal-queue-panel';
import { DECISION_GATE_IDS } from './decision-gate-model';

export function DecisionCockpitLoading() {
  const copy = useCopy();
  const labels = copy.decision;
  return (
    <section className="min-w-0 space-y-5 sm:space-y-6">
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
      />
      <div
        aria-busy="true"
        className="min-w-0 space-y-4"
        data-testid="decision-loading-workspace"
      >
        <EvidenceState
          kind="loading"
          statusLabel={copy.states.loading}
          title={labels.loading}
          description={labels.commandRegisterDetail}
        />

        <div data-testid="decision-loading-metrics">
          <MetricStrip
            ariaLabel={`${labels.commandRegisterTitle} · ${copy.states.loading}`}
            items={[
              {
                id: 'candidate-count',
                label: labels.candidateActions,
                value: copy.states.loading,
              },
              {
                id: 'manual-ready',
                label: labels.manualConfirmations,
                value: copy.states.loading,
              },
              {
                id: 'risk-blocked',
                label: labels.riskBlocks,
                value: copy.states.loading,
              },
              {
                id: 'market-evidence',
                label: labels.marketData,
                value: copy.states.loading,
              },
            ]}
          />
        </div>

        <section
          aria-labelledby="decision-loading-gates-title"
          className="min-w-0 space-y-2"
          data-testid="decision-loading-gates"
        >
          <div className="flex min-w-0 items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="app-kicker app-type-overline">
                {labels.workflowKicker}
              </div>
              <h2
                className="mt-1 app-type-section-title text-[var(--app-text)]"
                id="decision-loading-gates-title"
              >
                {labels.workflowTitle}
              </h2>
              <p className="mt-0.5 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
                {labels.workflowDetail}
              </p>
            </div>
            <span className="shrink-0">
              <StatusBadge tone="neutral">{copy.states.loading}</StatusBadge>
            </span>
          </div>
          <div
            aria-hidden="true"
            className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
            data-testid="decision-loading-gate-rows"
          >
            {DECISION_GATE_IDS.map((gateId) => (
              <div
                className="grid min-h-12 min-w-0 items-center gap-3 px-3 py-2.5 sm:grid-cols-[minmax(8rem,0.38fr)_minmax(0,1fr)]"
                key={gateId}
              >
                <span className="app-type-label font-semibold text-[var(--app-text)]">
                  {labels.workflowTaskLabel(gateId)}
                </span>
                <span className="justify-self-start">
                  <StatusBadge tone="info">{copy.states.loading}</StatusBadge>
                </span>
              </div>
            ))}
          </div>
        </section>

        <section
          className="min-w-0 border-y border-[var(--app-divider)] py-3"
          data-testid="decision-loading-plan"
        >
          <div className="app-kicker app-type-overline">
            {labels.tradingPlanKicker}
          </div>
          <h2 className="mt-1 app-type-section-title text-[var(--app-text)]">
            {labels.tradingPlanTitle}
          </h2>
          <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
            {labels.tradingPlanDetail}
          </p>
        </section>
      </div>
    </section>
  );
}

export function DecisionCockpitError({ error }: { error: unknown }) {
  const copy = useCopy();
  const labels = copy.decision;
  return (
    <section className="space-y-5">
      <PageHeader title={labels.title} subtitle={labels.subtitle} />
      <EvidenceState
        kind="error"
        title={copy.states.error}
        description={error instanceof Error ? error.message : labels.error}
      />
    </section>
  );
}
