import { BacktestPageProvider } from './backtest-page-context';
import { BacktestPageLayout } from './backtest-page-layout';

export function BacktestPage() {
  return (
    <BacktestPageProvider>
      <BacktestPageLayout />
    </BacktestPageProvider>
  );
}
