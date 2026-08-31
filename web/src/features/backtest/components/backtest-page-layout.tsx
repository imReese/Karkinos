import { BacktestGovernancePanels } from './backtest-governance-panels';
import { BacktestPageHeader } from './backtest-page-header';
import { BacktestRunResultsPanel } from './backtest-run-results-panel';
import { BacktestRunSetupPanel } from './backtest-run-setup-panel';

export function BacktestPageLayout() {
  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="backtest"
    >
      <BacktestPageHeader />
      <div
        className="grid min-w-0 items-start gap-6 xl:grid-cols-[minmax(360px,0.68fr)_minmax(0,1.32fr)]"
        data-testid="backtest-primary-workbench"
      >
        <BacktestRunSetupPanel />
        <BacktestRunResultsPanel />
      </div>
      <BacktestGovernancePanels />
    </section>
  );
}
