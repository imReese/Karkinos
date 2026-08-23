import { createLazyRoute } from '@tanstack/react-router';

import { PublicHomePage } from '../components/public-home-page';

export const Route = createLazyRoute('/')({
  component: PublicHomePage,
});
