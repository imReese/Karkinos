import { BacktestGovernancePanels } from './backtest-governance-panels';
import { BacktestPageHeader } from './backtest-page-header';
import { BacktestRunResultsPanel } from './backtest-run-results-panel';
import { BacktestRunSetupPanel } from './backtest-run-setup-panel';

export function BacktestPageLayout() {
  return (
    <section
      className="app-workbench-route space-y-4 sm:space-y-5"
      data-workbench-route="backtest"
      data-workbench-width="wide"
    >
      <BacktestPageHeader />
      <div
        className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px] xl:gap-6"
        data-testid="backtest-primary-workbench"
      >
        <BacktestRunResultsPanel />
        <BacktestRunSetupPanel />
      </div>
      <BacktestGovernancePanels />
    </section>
  );
}
