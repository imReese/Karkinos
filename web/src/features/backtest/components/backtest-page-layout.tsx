import { BacktestGovernancePanels } from './backtest-governance-panels';
import { BacktestPageHeader } from './backtest-page-header';
import { BacktestRunResultsPanel } from './backtest-run-results-panel';
import { BacktestRunSetupPanel } from './backtest-run-setup-panel';

export function BacktestPageLayout() {
  return (
    <section
      className="app-workbench-route space-y-4 sm:space-y-5"
      data-workbench-route="backtest"
    >
      <BacktestPageHeader />
      <div
        className="grid min-w-0 items-start gap-5 xl:grid-cols-[380px_minmax(0,1fr)] xl:gap-0"
        data-testid="backtest-primary-workbench"
      >
        <BacktestRunSetupPanel />
        <BacktestRunResultsPanel />
      </div>
      <BacktestGovernancePanels />
    </section>
  );
}
