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
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="ai-research"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={labels.context}
        actions={
          <a
            className="app-button-secondary min-h-9 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="/backtest"
          >
            {labels.openStrategyLab}
          </a>
        }
      />

      <MetricStrip
        ariaLabel={labels.title}
        items={[
          {
            id: 'activation',
            label: labels.activation,
            value: labels.manualOnly,
            detail: labels.noImplicitModel,
          },
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
              : savedBacktests.isError
                ? labels.backtestLoadFailed
                : labels.noSavedBacktest,
            tone:
              savedBacktests.isError || !latestBacktest ? 'warning' : 'neutral',
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
              : accountStrategy.isError
                ? labels.strategyLoadFailed
                : labels.noStrategyAssignment,
            tone:
              accountStrategy.isError || !accountStrategy.data
                ? 'warning'
                : 'neutral',
          },
          {
            id: 'authority',
            label: labels.authority,
            value: labels.none,
            detail: labels.noBrokerOrCapital,
          },
        ]}
      />

      <div data-testid="ai-research-primary-canvas">
        <ResearchTaskPanel
          backtestResultId={latestBacktest?.id ?? null}
          defaultOpen
          strategyId={accountStrategy.data?.strategy_id ?? null}
        />
      </div>
    </section>
  );
}
