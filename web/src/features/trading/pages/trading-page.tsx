import { createLazyRoute } from '@tanstack/react-router';

import { TradingPage } from '../components/trading-page';

export const Route = createLazyRoute('/trading')({
  component: TradingPage,
});
