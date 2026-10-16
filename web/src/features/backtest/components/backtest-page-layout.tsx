import { BacktestGovernancePanels } from './backtest-governance-panels';
import { BacktestPageHeader } from './backtest-page-header';
import { BacktestRunResultsPanel } from './backtest-run-results-panel';
import { BacktestRunSetupPanel } from './backtest-run-setup-panel';
import { useBacktestPage } from './backtest-page-context';

export function BacktestPageLayout() {
  const { latestReport, savedResults } = useBacktestPage();
  const hasReport = Boolean(latestReport || savedResults.data?.length);
  return (
    <section
      className="app-workbench-route space-y-4 pb-8 sm:space-y-5"
      data-workbench-route="backtest"
      data-workbench-width="wide"
    >
      <BacktestPageHeader />
      <div
        className={`grid min-w-0 items-start gap-5 xl:gap-6 ${hasReport ? 'xl:grid-cols-[minmax(320px,0.8fr)_minmax(0,1.2fr)]' : ''}`}
        data-testid="backtest-primary-workbench"
      >
        <BacktestRunSetupPanel />
        <BacktestRunResultsPanel />
      </div>
      <BacktestGovernancePanels />
    </section>
  );
}
