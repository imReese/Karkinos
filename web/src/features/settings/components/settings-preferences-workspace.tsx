import type {
  Locale,
  ThemePreference,
} from '../../../shared/preferences/context';
import type { SettingsPageController } from './settings-page-controller';
import {
  getErrorMessage,
  InlineNotice,
  PreferenceGroup,
  RegisterRow,
  SettingsDisclosure,
} from './settings-view-primitives';

export function SettingsPreferencesWorkspace({
  controller,
}: {
  controller: SettingsPageController;
}) {
  const {
    copy,
    locale,
    notificationConfigured,
    notificationType,
    safetyRows,
    setLocale,
    setTheme,
    testNotification,
    theme,
  } = controller;
  return (
    <aside className="order-2 min-w-0 space-y-5 xl:col-start-2 xl:row-start-1">
      <SettingsDisclosure
        testId="settings-notifications-disclosure"
        title={copy.settings.notifications}
        detail={copy.settings.notificationsDetail}
      >
        <RegisterRow
          label={copy.settings.notificationType}
          value={notificationType}
          tone={
            notificationType === copy.settings.notificationUnavailable
              ? 'neutral'
              : 'success'
          }
        />
        <RegisterRow
          label={copy.settings.notificationStatus}
          value={
            notificationConfigured
              ? copy.settings.notificationConfigured
              : copy.settings.notificationMissingCredential
          }
          tone={notificationConfigured ? 'success' : 'neutral'}
        />
        <button
          type="button"
          className="app-button-secondary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          disabled={testNotification.isPending || !notificationConfigured}
          aria-busy={testNotification.isPending}
          onClick={() => void testNotification.mutateAsync()}
        >
          {testNotification.isPending
            ? copy.settings.testingNotification
            : copy.settings.testNotification}
        </button>
        <div className="app-muted text-xs" aria-live="polite">
          {testNotification.isSuccess
            ? testNotification.data.status === 'ok'
              ? copy.settings.notificationOk
              : `${copy.settings.notificationFailed}: ${testNotification.data.message}`
            : testNotification.isError
              ? `${copy.settings.notificationFailed}: ${getErrorMessage(
                  testNotification.error,
                  copy.settings.notificationFailed,
                )}`
              : copy.settings.notificationsDetail}
        </div>
      </SettingsDisclosure>

      <SettingsDisclosure
        testId="settings-data-safety-disclosure"
        title={copy.settings.dataSafety}
        detail={copy.settings.dataSafetyDetail}
      >
        <div
          className="grid gap-3 border-y border-[var(--app-divider)] py-3"
          data-settings-surface="flat"
        >
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-semibold">
              {copy.settings.safetyRegister}
            </div>
            <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2.5 py-1 font-semibold text-[var(--app-soft)]">
              {copy.settings.noAutoTrading}
            </span>
          </div>
          <div className="grid gap-2">
            {safetyRows.map((row) => (
              <div key={row.label} className="grid gap-1.5">
                <RegisterRow
                  label={row.label}
                  value={row.value}
                  tone={row.tone}
                  ariaLabelPrefix="Safety item"
                />
                <div className="app-muted px-3 text-xs leading-5">
                  {row.detail}
                </div>
              </div>
            ))}
          </div>
        </div>
        <InlineNotice
          tone="neutral"
          title={copy.settings.deferred}
          detail={copy.settings.deferredDetail}
        />
      </SettingsDisclosure>

      <SettingsDisclosure
        testId="settings-preferences-disclosure"
        title={copy.settings.preferences}
        detail={copy.settings.preferencesDetail}
      >
        <PreferenceGroup
          label={copy.shell.theme}
          helper={copy.settings.localOnly}
          options={[
            ['dark', copy.settings.themeMocha],
            ['light', copy.settings.themeLatte],
            ['system', copy.settings.themeSystem],
          ]}
          value={theme}
          onChange={(value) => setTheme(value as ThemePreference)}
        />
        <PreferenceGroup
          label={copy.shell.language}
          helper={copy.settings.localOnly}
          options={[
            ['zh', copy.settings.languageZh],
            ['en', copy.settings.languageEn],
          ]}
          value={locale}
          onChange={(value) => setLocale(value as Locale)}
        />
      </SettingsDisclosure>
    </aside>
  );
}
