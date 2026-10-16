import { useState } from 'react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  ResearchObservationsPanel,
  useBacktestResultQuery,
} from '../ai-research-feature-boundary';
import type { ShadowResearchCandidate } from '../api';
import { SHADOW_RESEARCH_COPY } from './shadow-research-copy';

export function ShadowResearchObservations({
  candidate,
  defaultOpen = false,
}: {
  candidate: ShadowResearchCandidate | undefined;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
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
      className="min-w-0 border-t border-[var(--app-divider)] py-4"
      data-testid="shadow-research-observations"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-semibold">
        {copy.observationTitle}
      </summary>
      {open ? (
        <div className="mt-3 min-w-0 space-y-3 text-xs leading-5">
          <p className="app-muted max-w-4xl">{copy.observationBoundary}</p>
          {bound ? (
            <>
              <CandidateObservations key={resultId} sourceResultId={resultId} />
              <details
                className="border-t border-[var(--app-divider)] pt-4"
                data-testid="research-observation-source-binding"
              >
                <summary className="min-h-11 cursor-pointer font-semibold">
                  {copy.observationSource}
                </summary>
                <dl className="mt-2 space-y-2">
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
              </details>
            </>
          ) : (
            <p role="status">{copy.observationUnavailable}</p>
          )}
        </div>
      ) : null}
    </details>
  );
}

function CandidateObservations({ sourceResultId }: { sourceResultId: number }) {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  const query = useBacktestResultQuery(sourceResultId);
  const report = query.data;

  if (!query.isError && report?.id === sourceResultId)
    return (
      <ResearchObservationsPanel
        key={sourceResultId}
        report={report}
        continuousStart
      />
    );

  return (
    <div className="min-w-0 space-y-3">
      <button
        className="app-button-secondary min-h-11 px-3 py-2 text-xs"
        disabled={query.isFetching}
        onClick={() => void query.refetch()}
        type="button"
      >
        {copy.observationReportRefresh}
      </button>
      {query.isPending ? (
        <p role="status">{copy.observationReportLoading}</p>
      ) : (
        <p role="alert">{copy.observationReportFailed}</p>
      )}
    </div>
  );
}
