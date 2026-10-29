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
        actions={
          <a
            className="app-button app-button-secondary inline-flex min-h-11 items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="/backtest"
            onClick={(e) => handleClientNavigation(e, '/backtest')}
          >
            <span>{labels.openStrategyLab}</span>
            <span aria-hidden="true">&rarr;</span>
          </a>
        }
      />

      <div className="min-w-0 space-y-8" data-testid="ai-research-command-grid">
        <div
          className="min-w-0 space-y-8"
          data-testid="ai-research-primary-canvas"
        >
          <ShadowResearchPanel />
          <div className="relative pt-4">
            <div className="flex items-center gap-2 border-t border-[var(--app-divider)] pt-4 text-xs font-mono font-medium text-[var(--app-text-tertiary)] uppercase tracking-wider">
              <span className="size-1.5 rounded-full bg-[var(--app-text-tertiary)] opacity-60" />
              <span>
                人工复核工单与已冻结证据工作区 / Human Research & Evidence Audit
              </span>
            </div>
          </div>
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
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between py-2 text-sm font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)] transition-colors">
            <h2
              className="inline text-sm font-semibold text-[var(--app-text)]"
              id="ai-research-context-title"
            >
              {labels.contextTitle}
            </h2>
            <span className="app-type-micro font-mono text-[var(--app-text-tertiary)]">
              {latestBacktest ? `#${latestBacktest.id}` : '—'} ·{' '}
              {currentStrategy?.strategy_id ?? '—'}
            </span>
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
              className="app-button app-button-secondary mt-3 min-h-9 px-3 py-1.5 text-xs font-semibold"
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
