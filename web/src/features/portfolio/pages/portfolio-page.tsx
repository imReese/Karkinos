import { createLazyRoute } from '@tanstack/react-router';

import { PortfolioPageController } from './portfolio-page-controller';

export function PortfolioPage() {
  return <PortfolioPageController />;
}

export const Route = createLazyRoute('/portfolio')({
  component: PortfolioPage,
});
