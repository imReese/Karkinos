import { useCopy } from '../../../shared/i18n/context';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import {
  ResearchTaskPanel,
  useAccountStrategyAssignmentQuery,
  useBacktestResultsQuery,
} from '../ai-research-feature-boundary';
import { ShadowResearchPanel } from './shadow-research-panel';

export function AiResearchPage() {
  const copy = useCopy();
  const labels = copy.aiResearchPage;
  const savedBacktests = useBacktestResultsQuery();
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const latestBacktest = savedBacktests.isError
    ? null
    : (savedBacktests.data?.[0] ?? null);
  const currentStrategy = accountStrategy.isError ? null : accountStrategy.data;

  return (
    <section
      className="app-workbench-route min-w-0 space-y-8 pb-8"
      data-workbench-route="ai-research"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        actions={
          <a
            className="app-button-secondary inline-flex min-h-11 items-center rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-semibold"
            href="/backtest"
            onClick={(e) => handleClientNavigation(e, '/backtest')}
          >
            {labels.openStrategyLab} &rarr;
          </a>
        }
      />

      <div className="min-w-0 space-y-8" data-testid="ai-research-command-grid">
        <div
          className="min-w-0 space-y-8"
          data-testid="ai-research-primary-canvas"
        >
          <ShadowResearchPanel />
          <ResearchTaskPanel
            backtestResultId={latestBacktest?.id ?? null}
            defaultOpen
            routePrimary
            strategyId={currentStrategy?.strategy_id ?? null}
          />
        </div>
        <details
          aria-labelledby="ai-research-context-title"
          className="min-w-0 border-t border-[var(--app-divider)] py-4"
          data-testid="ai-research-context-metrics"
        >
          <summary className="min-h-11 cursor-pointer py-2">
            <h2
              className="inline text-sm font-semibold text-[var(--app-text)]"
              id="ai-research-context-title"
            >
              {labels.contextTitle}
            </h2>
          </summary>
          <MetricStrip
            ariaLabel={labels.contextTitle}
            className="mt-4"
            items={[
              {
                id: 'backtest-context',
                label: labels.backtestContext,
                value: savedBacktests.isLoading
                  ? copy.shell.checking
                  : latestBacktest
                    ? labels.available
                    : labels.unavailable,
                detail: latestBacktest
                  ? labels.savedBacktest(latestBacktest.id)
                  : savedBacktests.isLoading
                    ? copy.shell.checking
                    : savedBacktests.isError
                      ? labels.backtestLoadFailed
                      : labels.noSavedBacktest,
                tone:
                  !savedBacktests.isLoading &&
                  (savedBacktests.isError || !latestBacktest)
                    ? 'warning'
                    : 'neutral',
              },
              {
                id: 'strategy-context',
                label: labels.strategyContext,
                value: accountStrategy.isLoading
                  ? copy.shell.checking
                  : currentStrategy
                    ? labels.available
                    : labels.unavailable,
                detail: currentStrategy
                  ? labels.persistedAssignment
                  : accountStrategy.isLoading
                    ? copy.shell.checking
                    : accountStrategy.isError
                      ? labels.strategyLoadFailed
                      : labels.noStrategyAssignment,
                tone:
                  !accountStrategy.isLoading &&
                  (accountStrategy.isError || !currentStrategy)
                    ? 'warning'
                    : 'neutral',
              },
            ]}
          />
          {savedBacktests.isError || accountStrategy.isError ? (
            <button
              className="app-button-secondary mt-3 min-h-11 px-3 py-2 text-xs font-semibold"
              disabled={savedBacktests.isFetching || accountStrategy.isFetching}
              onClick={() => {
                if (savedBacktests.isError) void savedBacktests.refetch();
                if (accountStrategy.isError) void accountStrategy.refetch();
              }}
              type="button"
            >
              {copy.states.retry}
            </button>
          ) : null}
        </details>
      </div>
    </section>
  );
}
