import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { observationHealthCopy } from '../copy-observation-health';
import type { ResearchObservation } from '../observation-contracts';

export function ResearchObservationHealth({
  observation,
}: {
  observation: ResearchObservation;
}) {
  const { locale } = usePreferences();
  const labels = observationHealthCopy[locale];
  const policy = observation.policy.health_policy;
  const decision = observation.health_decision;
  return (
    <section
      aria-label={labels.title}
      className="min-w-0 space-y-3 border-t border-[var(--app-divider)] pt-3 text-xs"
    >
      <h4 className="font-semibold">{labels.title}</h4>
      {!policy ? (
        <p className="app-muted">{labels.not_configured}</p>
      ) : (
        <>
          <p className="leading-5">
            {labels[policy.mode]} · {labels.window}: {policy.window_intervals} ·{' '}
            {labels.minimum}: {policy.minimum_eligible_intervals} ·{' '}
            {labels.threshold}: {policy.minimum_mean_relative_price_response}
          </p>
          <p className="app-muted leading-5">{labels.metric}</p>
          <p className="app-muted leading-5">{labels.selection}</p>
          <p className="font-medium" role="status">
            {decision ? labels[decision.status] : labels.notEvaluated}
          </p>
          {decision ? (
            <>
              <p className="app-muted leading-5">
                {labels.evaluated}: {formatTimestamp(decision.evaluated_at)} ·{' '}
                {labels.marketAsOf}: {decision.market_as_of ?? labels.noValue}
              </p>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
                <div>
                  <dt className="app-muted">{labels.mean}</dt>
                  <dd className="font-medium tabular-nums">
                    {decision.mean_relative_price_response ?? labels.noValue}
                  </dd>
                </div>
                <div>
                  <dt className="app-muted">{labels.comparisonThreshold}</dt>
                  <dd className="font-medium tabular-nums">
                    {decision.threshold ?? labels.noValue}
                  </dd>
                </div>
                {(
                  [
                    'scheduled_matured',
                    'pending',
                    'missing_matured',
                    'zero_exposure',
                    'corporate_action_excluded',
                    'unresolved',
                    'eligible',
                  ] as const
                ).map((key) => (
                  <div className="flex justify-between gap-3" key={key}>
                    <dt className="app-muted">{labels[key]}</dt>
                    <dd className="tabular-nums">{decision.counts[key]}</dd>
                  </div>
                ))}
              </dl>
              <p className="leading-5">
                {decision.action === 'pause_observation'
                  ? observation.lifecycle === 'paused'
                    ? labels.paused
                    : labels.pauseDecision
                  : labels.recordOnly}
              </p>
              {decision.status === 'unavailable' ? (
                <p className="leading-5">{labels.unavailableDetail}</p>
              ) : decision.status === 'insufficient_evidence' ? (
                <p className="leading-5">{labels.insufficientDetail}</p>
              ) : null}
              <details className="min-w-0">
                <summary className="cursor-pointer text-[var(--app-text-secondary)]">
                  {labels.provenance}
                </summary>
                <dl className="mt-2 space-y-2">
                  {[
                    [labels.inputs, decision.input_fingerprint],
                    [labels.source, decision.source_fingerprint],
                    [labels.code, decision.code_fingerprint],
                    [labels.policy, decision.policy_fingerprint],
                    [
                      labels.publications,
                      decision.selected_publication_ids.join(', '),
                    ],
                    [labels.blockers, decision.blockers.join(', ')],
                    [labels.limitations, decision.limitations.join(' ')],
                  ].map(([label, value]) =>
                    value ? (
                      <div key={label}>
                        <dt className="app-muted">{label}</dt>
                        <dd className="break-all leading-5">{value}</dd>
                      </div>
                    ) : null,
                  )}
                </dl>
              </details>
            </>
          ) : null}
          <p className="app-muted leading-5">{labels.boundary}</p>
        </>
      )}
    </section>
  );
}
