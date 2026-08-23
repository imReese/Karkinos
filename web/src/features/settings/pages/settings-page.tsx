import { createLazyRoute } from '@tanstack/react-router';

import { SettingsPage } from '../components/settings-page';

export const Route = createLazyRoute('/settings')({
  component: SettingsPage,
});
