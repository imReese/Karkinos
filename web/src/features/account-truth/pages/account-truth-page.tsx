import { createLazyRoute } from '@tanstack/react-router';

import { AccountTruthReviewPage } from '../components/account-truth-review-page';

export const Route = createLazyRoute('/account-truth')({
  component: AccountTruthReviewPage,
});
