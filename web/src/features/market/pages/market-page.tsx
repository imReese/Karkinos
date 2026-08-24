import { createLazyRoute } from '@tanstack/react-router';

import { useMarketPageController } from './market-page-controller';
import { MarketPageView } from './market-page-view';

export function MarketPage() {
  return <MarketPageView controller={useMarketPageController()} />;
}

export const Route = createLazyRoute('/market')({
  component: MarketPage,
});
