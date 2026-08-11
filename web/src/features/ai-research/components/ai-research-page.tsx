import { useCopy } from '../../../app/copy';
import {
  MetricStrip,
  WorkspaceHeader,
} from '../../../app/components/workbench';
import {
  useAccountStrategyAssignmentQuery,
  useBacktestResultsQuery,
} from '../../backtest/api';
import { ResearchTaskPanel } from './research-task-panel';

export function AiResearchPage() {
  const copy = useCopy();
  const labels = copy.aiResearchPage;
  const savedBacktests = useBacktestResultsQuery();
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const latestBacktest = savedBacktests.data?.[0] ?? null;

  return (
    <section
      className="app-workbench-route flex flex-col gap-5 sm:gap-6"
      data-workbench-route="ai-research"
    >
      <WorkspaceHeader
        className="app-ai-research-header"
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={labels.context}
        actions={
          <a
            className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="/backtest"
          >
            {labels.openStrategyLab}
          </a>
        }
      />

      <div
        className="app-ai-research-command-grid min-w-0"
        data-testid="ai-research-command-grid"
      >
        <section
          aria-labelledby="ai-research-context-title"
          className="min-w-0 border-t border-[var(--app-divider)] pt-4 xl:order-2"
          data-testid="ai-research-context-metrics"
        >
          <div className="mb-3 min-w-0">
            <h2
              className="app-type-section-title text-[var(--app-text)]"
              id="ai-research-context-title"
            >
              {labels.contextTitle}
            </h2>
            <p className="app-muted mt-1 text-xs leading-5">
              {labels.contextDetail}
            </p>
          </div>
          <MetricStrip
            ariaLabel={labels.contextTitle}
            className="app-ai-research-context-strip"
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
                  : accountStrategy.data
                    ? labels.available
                    : labels.unavailable,
                detail: accountStrategy.data
                  ? labels.persistedAssignment
                  : accountStrategy.isLoading
                    ? copy.shell.checking
                    : accountStrategy.isError
                      ? labels.strategyLoadFailed
                      : labels.noStrategyAssignment,
                tone:
                  !accountStrategy.isLoading &&
                  (accountStrategy.isError || !accountStrategy.data)
                    ? 'warning'
                    : 'neutral',
              },
            ]}
          />
        </section>

        <div
          className="min-w-0 xl:order-1"
          data-testid="ai-research-primary-canvas"
        >
          <ResearchTaskPanel
            backtestResultId={latestBacktest?.id ?? null}
            defaultOpen
            routePrimary
            strategyId={accountStrategy.data?.strategy_id ?? null}
          />
        </div>
      </div>
    </section>
  );
}
