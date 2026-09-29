import type {
  Locale,
  ThemePreference,
} from '../../../shared/preferences/context';
import type { SettingsPageController } from './settings-page-controller';
import {
  BeaconDot,
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
    <aside className="min-w-0 space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <SettingsDisclosure
          testId="settings-preferences-disclosure"
          title={copy.settings.preferences}
          detail={copy.settings.preferencesDetail}
          badge={
            <span className="app-type-micro rounded-full border border-[var(--app-border)] px-2 py-0.5 text-[var(--app-muted)]">
              {locale === 'zh' ? '右上角可快捷切换' : 'Quick toggle in top nav'}
            </span>
          }
        >
          <div className="divide-y divide-[var(--app-divider)]">
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
          </div>
        </SettingsDisclosure>

        <SettingsDisclosure
          testId="settings-notifications-disclosure"
          title={copy.settings.notifications}
          detail={copy.settings.notificationsDetail}
        >
          <div className="space-y-2.5">
            <div className="divide-y divide-[var(--app-divider)]">
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
            </div>
            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="button"
                className="app-button-secondary inline-flex items-center gap-1.5 rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                disabled={testNotification.isPending || !notificationConfigured}
                aria-busy={testNotification.isPending}
                onClick={() => void testNotification.mutateAsync()}
              >
                {notificationConfigured ? (
                  <BeaconDot
                    tone="success"
                    pulse={testNotification.isPending}
                  />
                ) : null}
                {testNotification.isPending
                  ? copy.settings.testingNotification
                  : copy.settings.testNotification}
              </button>
              {testNotification.isSuccess || testNotification.isError ? (
                <div className="text-xs" aria-live="polite">
                  {testNotification.isSuccess ? (
                    testNotification.data.status === 'ok' ? (
                      <span className="font-medium text-[var(--app-success-text)]">
                        ✓ {copy.settings.notificationOk}
                      </span>
                    ) : (
                      <span className="font-medium text-[var(--app-danger-text)]">
                        ✕{' '}
                        {`${copy.settings.notificationFailed}: ${testNotification.data.message}`}
                      </span>
                    )
                  ) : testNotification.isError ? (
                    <span className="font-medium text-[var(--app-danger-text)]">
                      ✕{' '}
                      {`${copy.settings.notificationFailed}: ${getErrorMessage(
                        testNotification.error,
                        copy.settings.notificationFailed,
                      )}`}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <details className="group rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-2.5 text-xs">
              <summary className="flex cursor-pointer select-none items-center justify-between font-medium text-[var(--app-text)] outline-hidden">
                <span>
                  {locale === 'zh'
                    ? '💡 如何配置消息推送密钥？'
                    : '💡 How to configure notification credentials?'}
                </span>
                <span className="app-muted app-type-micro transition-transform group-open:rotate-180">
                  ▾
                </span>
              </summary>
              <p className="app-muted mt-2 border-t border-[var(--app-divider)] pt-2 leading-relaxed">
                {locale === 'zh'
                  ? '在本地 .env 文件中添加对应密钥（如 Telegram: KARKINOS_TELEGRAM_BOT_TOKEN，微信: KARKINOS_WECHAT_SENDKEY），重启服务后自动生效。'
                  : 'Add credentials to your local .env file (e.g. Telegram: KARKINOS_TELEGRAM_BOT_TOKEN, WeChat: KARKINOS_WECHAT_SENDKEY), then restart.'}
              </p>
            </details>
          </div>
        </SettingsDisclosure>
      </div>

      <SettingsDisclosure
        testId="settings-data-safety-disclosure"
        title={copy.settings.dataSafety}
        detail={copy.settings.dataSafetyDetail}
      >
        <div
          className="grid gap-2 border-y border-[var(--app-divider)] py-2.5"
          data-settings-surface="flat"
        >
          <div className="flex items-center justify-between gap-3 pb-1">
            <div className="text-xs font-semibold text-[var(--app-text)]">
              {copy.settings.safetyRegister}
            </div>
            <span className="app-type-micro rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2 py-0.5 font-medium text-[var(--app-soft)]">
              {copy.settings.noAutoTrading}
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {safetyRows.map((row) => (
              <div
                key={row.label}
                className="flex flex-col justify-between gap-1.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-0)_8%,transparent)] p-2.5"
              >
                <RegisterRow
                  label={row.label}
                  value={row.value}
                  tone={row.tone}
                  ariaLabelPrefix="Safety item"
                />
                <div className="app-muted app-type-micro leading-snug">
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
    </aside>
  );
}
