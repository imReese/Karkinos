import { createLazyRoute, getRouteApi } from '@tanstack/react-router';

import { HoldingDetailPage } from '../components/holding-detail-page';

const holdingDetailRouteApi = getRouteApi('/portfolio/$symbol');

function HoldingDetailRoutePage() {
  const { symbol } = holdingDetailRouteApi.useParams();
  return <HoldingDetailPage symbol={symbol} />;
}

export const Route = createLazyRoute('/portfolio/$symbol')({
  component: HoldingDetailRoutePage,
});
