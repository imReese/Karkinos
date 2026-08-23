import { createLazyRoute } from '@tanstack/react-router';

import { OperationsPage } from '../components/operations-page';

export const Route = createLazyRoute('/operations')({
  component: OperationsPage,
});
