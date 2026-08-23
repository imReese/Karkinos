import { createLazyRoute } from '@tanstack/react-router';

import { BacktestPage } from '../components/backtest-page';

export const Route = createLazyRoute('/backtest')({
  component: BacktestPage,
});
