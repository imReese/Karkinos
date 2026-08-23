import { createLazyRoute } from '@tanstack/react-router';

import { DecisionCockpitPage } from '../components/decision-cockpit-page';

export const Route = createLazyRoute('/decision')({
  component: DecisionCockpitPage,
});
