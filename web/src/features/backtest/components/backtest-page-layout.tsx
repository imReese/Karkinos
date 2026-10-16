import { BacktestGovernancePanels } from './backtest-governance-panels';
import { BacktestPageHeader } from './backtest-page-header';
import { BacktestRunResultsPanel } from './backtest-run-results-panel';
import { BacktestRunSetupPanel } from './backtest-run-setup-panel';
import { useBacktestPage } from './backtest-page-context';

export function BacktestPageLayout() {
  const { mobileWorkspaceView } = useBacktestPage();
  return (
    <section
      className="app-workbench-route space-y-4 pb-8 sm:space-y-5"
      data-workbench-route="backtest"
      data-workbench-width="wide"
    >
      <BacktestPageHeader />
      <div className="min-w-0" data-testid="backtest-primary-workbench">
        <BacktestRunSetupPanel />
        <BacktestRunResultsPanel />
      </div>
      <div hidden={mobileWorkspaceView === 'observations'}>
        <BacktestGovernancePanels />
      </div>
    </section>
  );
}
