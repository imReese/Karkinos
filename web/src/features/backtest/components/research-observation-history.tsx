import { formatPercent, formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { observationCopy } from '../copy-observations';
import type {
  ObservationPublication,
  ObservationOutcome,
  ResearchObservation,
} from '../observation-contracts';

function weight(value: string | null | undefined) {
  return value !== null &&
    value !== undefined &&
    value !== '' &&
    Number.isFinite(Number(value))
    ? formatPercent(Number(value))
    : '—';
}

export function ResearchObservationHistory({
  observation,
}: {
  observation: ResearchObservation;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  if (!observation.publications.length)
    return (
      <p className="app-muted text-xs leading-5">{labels.noPublications}</p>
    );
  return (
    <div className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
      {[...observation.publications].reverse().map((publication) => (
        <Publication
          key={publication.id}
          publication={publication}
          outcome={observation.outcomes.find(
            (item) => item.publication_id === publication.id,
          )}
        />
      ))}
    </div>
  );
}

function Publication({
  publication,
  outcome,
}: {
  publication: ObservationPublication;
  outcome?: ObservationOutcome;
}) {
  const { locale } = usePreferences();
  const labels = observationCopy[locale];
  const measured =
    outcome?.payload.status === 'measured' &&
    outcome.payload.return_basis === 'unadjusted_price_only';
  const payload = publication.payload;
  return (
    <details className="min-w-0 py-3">
      <summary className="cursor-pointer text-sm leading-6">
        <span className="font-semibold">
          {labels.decision} · {publication.decision_session}
        </span>
        <span className="ml-3 text-xs tabular-nums text-[var(--app-text-secondary)]">
          {measured
            ? `${labels.measured} · ${weight(outcome.payload.weighted_price_response)}`
            : labels.awaiting}
        </span>
      </summary>
      <div className="mt-3 min-w-0 space-y-3 text-xs">
        <p>
          {labels.published} · {formatTimestamp(publication.published_at)}
        </p>
        <p>
          {labels.endpoints} · {payload.reference_session} →{' '}
          {payload.end_session}
        </p>
        <p>
          {payload.risk_decision.status === 'allowed'
            ? labels.riskAllowed
            : labels.riskBlocked}
        </p>
        <div
          className="max-w-full overflow-x-auto"
          role="region"
          aria-label={`${labels.target} · ${publication.decision_session}`}
          tabIndex={0}
        >
          <table className="w-full min-w-[520px] text-left tabular-nums">
            <thead>
              <tr className="border-y border-[var(--app-divider)] text-[var(--app-text-secondary)]">
                <th className="px-2 py-2">{labels.symbol}</th>
                <th className="px-2 py-2">{labels.action}</th>
                <th className="px-2 py-2 text-right">{labels.target}</th>
                <th className="px-2 py-2 text-right">{labels.delta}</th>
                <th className="px-2 py-2 text-right">{labels.contribution}</th>
              </tr>
            </thead>
            <tbody>
              {payload.forecasts.map((forecast) => (
                <tr
                  className="border-b border-[var(--app-divider)]"
                  key={forecast.symbol}
                >
                  <th scope="row" className="px-2 py-2 font-mono font-medium">
                    {forecast.symbol}
                  </th>
                  <td className="px-2 py-2">{labels[forecast.action]}</td>
                  <td className="px-2 py-2 text-right">
                    {weight(payload.target_weights[forecast.symbol])}
                  </td>
                  <td className="px-2 py-2 text-right">
                    {weight(payload.rebalance_weight_deltas[forecast.symbol])}
                  </td>
                  <td className="px-2 py-2 text-right">
                    {measured
                      ? weight(
                          outcome.payload.observations.find(
                            (item) => item.symbol === forecast.symbol,
                          )?.weighted_price_response,
                        )
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {measured && outcome.payload.corporate_action_evidence ? (
          <p className="app-muted leading-5">{labels.actionsKnown}</p>
        ) : null}
        <details className="min-w-0">
          <summary className="cursor-pointer text-[var(--app-text-secondary)]">
            {labels.provenance}
          </summary>
          <dl className="mt-2 space-y-2">
            <div>
              <dt>{labels.publicationDataset}</dt>
              <dd className="mt-1 break-all font-mono">
                {publication.dataset_id}
              </dd>
            </div>
            {outcome ? (
              <>
                <div>
                  <dt>{labels.outcomeDataset}</dt>
                  <dd className="mt-1 break-all font-mono">
                    {outcome.dataset_id}
                  </dd>
                </div>
                <div>
                  <dt>{labels.measuredAt}</dt>
                  <dd>{formatTimestamp(outcome.measured_at)}</dd>
                </div>
              </>
            ) : null}
          </dl>
        </details>
      </div>
    </details>
  );
}
