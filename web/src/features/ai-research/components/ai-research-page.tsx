import { useState } from 'react';

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
  const [activeTab, setActiveTab] = useState<'all' | 'shadow' | 'tasks'>('all');
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
      className="app-workbench-route flex flex-col gap-4 pb-8 sm:gap-5"
      data-workbench-route="ai-research"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        className="app-ai-research-header"
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        actions={
          <a
            className="app-button-secondary min-h-11 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
            href="/backtest"
            onClick={(e) => handleClientNavigation(e, '/backtest')}
          >
            {labels.openStrategyLab} &rarr;
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
        </section>

        <div
          className="grid min-w-0 gap-5 xl:order-1"
          data-testid="ai-research-primary-canvas"
        >
          <div
            aria-label={labels.title}
            className="flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-1"
            role="tablist"
          >
            {(['all', 'shadow', 'tasks'] as const).map((tab, index, tabs) => (
              <button
                aria-controls="ai-research-tabpanel"
                aria-selected={activeTab === tab}
                className={`min-h-11 flex-1 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold transition-colors ${
                  activeTab === tab
                    ? 'bg-[var(--app-surface-raised)] text-[var(--app-text)] shadow-xs'
                    : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                }`}
                key={tab}
                id={`ai-research-tab-${tab}`}
                onClick={() => setActiveTab(tab)}
                onKeyDown={(event) => {
                  const nextIndex =
                    event.key === 'ArrowRight'
                      ? (index + 1) % tabs.length
                      : event.key === 'ArrowLeft'
                        ? (index - 1 + tabs.length) % tabs.length
                        : event.key === 'Home'
                          ? 0
                          : event.key === 'End'
                            ? tabs.length - 1
                            : null;
                  if (nextIndex === null) return;
                  event.preventDefault();
                  setActiveTab(tabs[nextIndex]);
                  event.currentTarget.parentElement
                    ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
                    [nextIndex]?.focus();
                }}
                role="tab"
                tabIndex={activeTab === tab ? 0 : -1}
                type="button"
              >
                {labels.tabs[tab]}
              </button>
            ))}
          </div>

          <div
            aria-labelledby={`ai-research-tab-${activeTab}`}
            className="grid min-w-0 gap-5"
            id="ai-research-tabpanel"
            role="tabpanel"
          >
            <div
              className={
                activeTab === 'all' || activeTab === 'tasks'
                  ? 'block'
                  : 'hidden'
              }
            >
              <ResearchTaskPanel
                backtestResultId={latestBacktest?.id ?? null}
                defaultOpen
                routePrimary
                strategyId={currentStrategy?.strategy_id ?? null}
              />
            </div>
            <div
              className={
                activeTab === 'all' || activeTab === 'shadow'
                  ? 'block'
                  : 'hidden'
              }
            >
              <ShadowResearchPanel />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
