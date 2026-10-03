import { useState } from 'react';

import { formatTimestamp } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import {
  observationCopy,
  ResearchObservationHealth,
  ResearchObservationHistory,
  useResearchObservations,
} from '../ai-research-feature-boundary';
import type { ShadowResearchCandidate } from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';

export function ShadowResearchObservations({
  candidate,
}: {
  candidate: ShadowResearchCandidate | undefined;
}) {
  const [open, setOpen] = useState(false);
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  const resultId = candidate?.candidate_result_id;
  const bound =
    candidate?.comparison.research_capital_mode === 'normalized_notional' &&
    typeof resultId === 'number' &&
    Number.isSafeInteger(resultId) &&
    resultId > 0;

  return (
    <details
      className="mt-4 min-w-0 border-y border-[var(--app-divider)] py-3"
      data-testid="shadow-research-observations"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {copy.observationTitle}
      </summary>
      {open ? (
        <div className="mt-3 min-w-0 space-y-3 text-xs leading-5">
          <p className="app-muted">{copy.observationBoundary}</p>
          <p className="app-muted">{observationCopy[locale].boundary}</p>
          {bound ? (
            <>
              <dl className="space-y-2">
                <div>
                  <dt className="app-muted">{copy.observationSource}</dt>
                  <dd className="break-all">
                    {candidate.candidate_id} / {candidate.run_id}
                  </dd>
                </div>
                <div>
                  <dt className="app-muted">{copy.observationReport}</dt>
                  <dd>#{resultId}</dd>
                </div>
              </dl>
              <SavedObservations key={resultId} sourceResultId={resultId} />
            </>
          ) : (
            <p role="status">{copy.observationUnavailable}</p>
          )}
        </div>
      ) : null}
    </details>
  );
}

function SavedObservations({ sourceResultId }: { sourceResultId: number }) {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  const labels = observationCopy[locale];
  const query = useResearchObservations(true, sourceResultId);
  const observations =
    query.data?.filter(
      (observation) => observation.source_backtest_result_id === sourceResultId,
    ) ?? [];

  return (
    <div className="min-w-0 space-y-3">
      <p className="app-muted">{copy.observationListDetail}</p>
      <button
        className="app-button-secondary min-h-11 px-3 py-2 text-xs"
        disabled={query.isFetching}
        onClick={() => void query.refetch()}
        type="button"
      >
        {labels.refresh}
      </button>
      {query.isError ? (
        <p role="alert">{labels.loadFailed}</p>
      ) : query.isPending ? (
        <p role="status">{labels.loading}</p>
      ) : !observations.length ? (
        <p>{labels.none}</p>
      ) : (
        observations.map((observation) => (
          <details
            className="min-w-0 border-t border-[var(--app-divider)] pt-3"
            key={observation.id}
            data-testid="shadow-research-observation-record"
          >
            <summary className="cursor-pointer break-words">
              <span className="font-semibold">
                {formatTimestamp(observation.started_at)} ·{' '}
                {observation.lifecycle === 'paused'
                  ? labels.paused
                  : labels.active}
              </span>
              <span className="mt-1 block break-all text-[var(--app-text-secondary)]">
                {observation.id} · v{observation.version}
              </span>
            </summary>
            <div className="mt-3 min-w-0 space-y-3">
              <dl>
                <dt className="app-muted">{copy.observationFrozenSource}</dt>
                <dd className="break-all">
                  {observation.source.strategy_kind} ·{' '}
                  {observation.source.start_date} ·{' '}
                  {observation.source.dataset_id}
                </dd>
              </dl>
              <p className="app-muted">
                {observation.source.source_code_verified
                  ? copy.observationCodeVerified
                  : copy.observationCodeUnverified}
              </p>
              {!observation.source.source_historical_pit_verified ? (
                <p className="app-muted">{labels.pitUnknown}</p>
              ) : null}
              {observation.last_blocker ? (
                <details className="min-w-0">
                  <summary className="cursor-pointer text-[var(--app-text-secondary)]">
                    {copy.observationLastBlocker}
                  </summary>
                  <p className="mt-2 break-all font-mono">
                    {observation.last_blocker.code}
                  </p>
                </details>
              ) : null}
              <ResearchObservationHealth observation={observation} />
              {observation.publications.length ? (
                <ResearchObservationHistory observation={observation} />
              ) : (
                <p className="app-muted">{copy.observationEmptyPublications}</p>
              )}
            </div>
          </details>
        ))
      )}
    </div>
  );
}
