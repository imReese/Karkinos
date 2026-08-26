import { useSettingsPageController } from './settings-page-controller';
import { SettingsPageView } from './settings-page-view';

export function SettingsPage() {
  return <SettingsPageView controller={useSettingsPageController()} />;
}
