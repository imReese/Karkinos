/** Explicit cross-feature ports consumed by the AI research feature. */
export { useAccountStateQuery } from '../account/api';
export {
  useAccountStrategyAssignmentQuery,
  useBacktestResultQuery,
  useBacktestResultsQuery,
  type BacktestReport,
} from '../backtest/api';
export { useResearchObservations } from '../backtest/observation-api';
export { useResearchPaperBook } from '../backtest/paper-book-api';
export { ResearchPaperPerformance } from '../backtest/components/research-paper-performance';
export { ResearchObservationsPanel } from '../backtest/components/research-observations-panel';
export { ResearchTaskPanel } from '../research-workflow/components/research-task-panel';
export { StrategyHypothesisPanel } from '../research-workflow/components/strategy-hypothesis-panel';
