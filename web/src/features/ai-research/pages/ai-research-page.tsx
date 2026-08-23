import { createLazyRoute } from '@tanstack/react-router';

import { AiResearchPage } from '../components/ai-research-page';

export const Route = createLazyRoute('/ai-research')({
  component: AiResearchPage,
});
