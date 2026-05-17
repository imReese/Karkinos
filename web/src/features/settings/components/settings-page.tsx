import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';

import { useAccountOverviewQuery } from '../../account/api';
import { MarketRefreshButton } from '../../market/components/market-refresh-button';
import { useMarketDataHealthQuery } from '../../market/api';
import { useCopy } from '../../../app/copy';
import {
  usePreferences,
  type Locale,
  type ThemePreference,
} from '../../../app/preferences';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import {
  useLiveStatusQuery,
  useSettingsQuery,
  useStartLiveMutation,
  useStopLiveMutation,
  useTestNotificationMutation,
  useUpdateDataSourceSettingsMutation,
} from '../api';

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';

function getStatusToneClasses(tone: StatusTone) {
  if (tone === 'success') {
    return 'border-[var(--app-success-border)] bg-[var(--app-success-bg)] text-[var(--app-success)]';
  }
  if (tone === 'warning') {
    return 'border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning)]';
  }
  if (tone === 'danger') {
    return 'border-[var(--app-danger-border)] bg-[var(--app-danger-bg)] text-[var(--app-danger)]';
  }
  return 'border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_14%,transparent)] text-[var(--app-soft)]';
}

function getErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function isMaskedToken(value: string) {
  return value.startsWith('****');
}

export function SettingsPage() {
  const copy = useCopy();
  const settings = useSettingsQuery();
  const liveStatus = useLiveStatusQuery();
  const marketHealth = useMarketDataHealthQuery();
  const overview = useAccountOverviewQuery();
  const updateDataSource = useUpdateDataSourceSettingsMutation();
  const startLive = useStartLiveMutation();
  const stopLive = useStopLiveMutation();
  const testNotification = useTestNotificationMutation();
  const { locale, setLocale, theme, setTheme, resolvedTheme } =
    usePreferences();
  const [dataSource, setDataSource] = useState('');
  const [providerToken, setProviderToken] = useState('');
  const [pollInterval, setPollInterval] = useState('60');

  useEffect(() => {
    if (!settings.data) {
      return;
    }
    setDataSource(settings.data.data_source);
    setProviderToken(settings.data.tushare_token);
    setPollInterval(String(settings.data.live_poll_interval));
  }, [settings.data]);

  const quoteStatus = overview.data?.quote_status ?? copy.shell.statusUnknown;
  const valuationTime = overview.data?.valuation_timestamp
    ? formatTimestamp(overview.data.valuation_timestamp)
    : copy.settings.noValuationTime;
  const isCacheOnly = marketHealth.data?.refresh_policy === 'cache_only';
  const isStaleQuote = overview.data?.quote_status === 'stale';
  const notificationType = String(
    settings.data?.notification?.type ?? copy.settings.notificationUnavailable,
  );
  const trackedAssets = settings.data?.assets.length ?? 0;
  const statusLoadFailed =
    settings.isError ||
    liveStatus.isError ||
    marketHealth.isError ||
    overview.isError;

  const dataSourceChanged = useMemo(() => {
    if (!settings.data) {
      return false;
    }
    return (
      dataSource !== settings.data.data_source ||
      providerToken !== settings.data.tushare_token ||
      Number(pollInterval) !== settings.data.live_poll_interval
    );
  }, [dataSource, pollInterval, providerToken, settings.data]);

  const submitDataSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedInterval = Math.max(Number(pollInterval) || 60, 15);
    await updateDataSource.mutateAsync({
      data_source: dataSource.trim() || settings.data?.data_source || 'akshare',
      tushare_token: providerToken,
      live_poll_interval: normalizedInterval,
    });
    setPollInterval(String(normalizedInterval));
  };

  return (
    <section className="space-y-5 sm:space-y-6">
      <header className="app-page-header pb-1">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{copy.settings.kicker}</div>
            <h1 className="app-page-title mt-2">{copy.settings.title}</h1>
          </div>
          <p className="app-page-subtitle sm:max-w-xl sm:text-right">
            {copy.settings.subtitle}
          </p>
        </div>
      </header>

      {statusLoadFailed ? (
        <InlineNotice
          tone="danger"
          title={copy.settings.error}
          detail={[
            settings.error,
            liveStatus.error,
            marketHealth.error,
            overview.error,
          ]
            .filter(Boolean)
            .map((error) => getErrorMessage(error, copy.settings.error))
            .join(' · ')}
        />
      ) : null}

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div className="min-w-0 space-y-5">
          <SettingsSection
            title={copy.settings.dataStatus}
            detail={copy.settings.dataStatusDetail}
          >
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <StatusMetric
                label={copy.settings.marketState}
                value={
                  marketHealth.isLoading
                    ? copy.shell.checking
                    : marketHealth.data?.market_open
                      ? copy.shell.marketOpen
                      : copy.shell.marketClosed
                }
                tone={
                  marketHealth.isLoading
                    ? 'neutral'
                    : marketHealth.data?.market_open
                      ? 'success'
                      : 'warning'
                }
              />
              <StatusMetric
                label={copy.settings.refreshPolicy}
                value={
                  marketHealth.isLoading
                    ? copy.shell.checking
                    : (marketHealth.data?.refresh_policy ??
                      copy.shell.statusUnknown)
                }
                tone={isCacheOnly ? 'warning' : 'success'}
              />
              <StatusMetric
                label={copy.settings.quoteState}
                value={
                  overview.isLoading
                    ? copy.shell.checking
                    : isStaleQuote
                      ? copy.settings.cachedQuotes
                      : quoteStatus
                }
                tone={isStaleQuote ? 'warning' : 'success'}
              />
              <StatusMetric
                label={copy.settings.valuationTime}
                value={overview.isLoading ? copy.shell.checking : valuationTime}
                tone={isStaleQuote ? 'warning' : 'neutral'}
              />
            </div>

            {isCacheOnly || isStaleQuote ? (
              <InlineNotice
                tone="warning"
                title={
                  isStaleQuote
                    ? copy.settings.cachedQuotes
                    : copy.settings.cacheOnly
                }
                detail={
                  isStaleQuote
                    ? copy.settings.cachedQuotesDetail
                    : copy.settings.cacheOnlyDetail
                }
              />
            ) : null}

            <div className="flex flex-col gap-3 rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-sm font-semibold">
                  {copy.market.refreshQuotes}
                </div>
                <div className="app-muted mt-1 text-xs leading-5">
                  {copy.settings.dataStatusDetail}
                </div>
              </div>
              <MarketRefreshButton />
            </div>
          </SettingsSection>

          <SettingsSection
            title={copy.settings.liveServices}
            detail={copy.settings.liveServicesDetail}
          >
            <div className="grid gap-3 md:grid-cols-3">
              <StatusMetric
                label={copy.settings.scheduler}
                value={
                  liveStatus.isLoading
                    ? copy.shell.checking
                    : liveStatus.data?.running
                      ? copy.settings.schedulerRunning
                      : copy.settings.schedulerStopped
                }
                tone={
                  liveStatus.isLoading
                    ? 'neutral'
                    : liveStatus.data?.running
                      ? 'success'
                      : 'warning'
                }
              />
              <StatusMetric
                label={copy.settings.brokerInterface}
                value={
                  liveStatus.isLoading
                    ? copy.shell.checking
                    : liveStatus.data?.running
                      ? copy.settings.brokerReady
                      : copy.settings.brokerDegraded
                }
                tone={
                  liveStatus.isLoading
                    ? 'neutral'
                    : liveStatus.data?.running
                      ? 'success'
                      : 'warning'
                }
              />
              <StatusMetric
                label={copy.shell.marketSession}
                value={
                  liveStatus.isLoading
                    ? copy.shell.checking
                    : liveStatus.data?.market_open
                      ? copy.shell.marketOpen
                      : copy.shell.marketClosed
                }
                tone={liveStatus.data?.market_open ? 'success' : 'warning'}
              />
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="app-button-primary rounded-2xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={startLive.isPending || liveStatus.data?.running}
                aria-busy={startLive.isPending}
                onClick={() => void startLive.mutateAsync()}
              >
                {startLive.isPending
                  ? copy.settings.updatingScheduler
                  : copy.settings.startScheduler}
              </button>
              <button
                type="button"
                className="app-button-secondary rounded-2xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={stopLive.isPending || !liveStatus.data?.running}
                aria-busy={stopLive.isPending}
                onClick={() => void stopLive.mutateAsync()}
              >
                {stopLive.isPending
                  ? copy.settings.updatingScheduler
                  : copy.settings.stopScheduler}
              </button>
            </div>

            {startLive.isError || stopLive.isError ? (
              <InlineNotice
                tone="danger"
                title={copy.settings.schedulerUpdateFailed}
                detail={getErrorMessage(
                  startLive.error ?? stopLive.error,
                  copy.settings.schedulerUpdateFailed,
                )}
              />
            ) : null}
          </SettingsSection>
        </div>

        <aside className="min-w-0 space-y-5">
          <SettingsSection
            title={copy.settings.preferences}
            detail={copy.settings.preferencesDetail}
          >
            <PreferenceGroup
              label={copy.shell.theme}
              helper={`${copy.settings.localOnly} · ${resolvedTheme}`}
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
          </SettingsSection>

          <SettingsSection
            title={copy.settings.backendSettings}
            detail={copy.settings.liveServicesDetail}
          >
            <form className="grid gap-4" onSubmit={submitDataSource}>
              <label className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.dataSource}
                </span>
                <input
                  aria-label={copy.settings.dataSource}
                  className="app-field rounded-2xl px-3 py-2 text-sm"
                  value={dataSource}
                  onChange={(event) => setDataSource(event.target.value)}
                  disabled={settings.isLoading}
                />
              </label>
              <label className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.pollInterval}
                </span>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                  <input
                    aria-label={copy.settings.pollInterval}
                    className="app-field rounded-2xl px-3 py-2 text-sm tabular-nums"
                    type="number"
                    min={15}
                    value={pollInterval}
                    onChange={(event) => setPollInterval(event.target.value)}
                    disabled={settings.isLoading}
                  />
                  <span className="app-muted text-xs">
                    {copy.settings.pollIntervalUnit}
                  </span>
                </div>
              </label>
              <label className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.token}
                </span>
                <input
                  aria-label={copy.settings.token}
                  className="app-field rounded-2xl px-3 py-2 text-sm"
                  value={providerToken}
                  onChange={(event) => setProviderToken(event.target.value)}
                  disabled={settings.isLoading}
                />
                {isMaskedToken(providerToken) ? (
                  <span className="app-muted text-xs">
                    {copy.settings.maskedToken}
                  </span>
                ) : null}
              </label>
              <button
                type="submit"
                className="app-button-primary rounded-2xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={
                  settings.isLoading ||
                  updateDataSource.isPending ||
                  !dataSourceChanged
                }
                aria-busy={updateDataSource.isPending}
              >
                {updateDataSource.isPending
                  ? copy.settings.savingDataSource
                  : copy.settings.saveDataSource}
              </button>
            </form>

            {updateDataSource.isSuccess ? (
              <InlineNotice
                tone="success"
                title={copy.settings.dataSourceSaved}
                detail={copy.settings.dataStatusDetail}
              />
            ) : null}
            {updateDataSource.isError ? (
              <InlineNotice
                tone="danger"
                title={copy.settings.dataSourceFailed}
                detail={getErrorMessage(
                  updateDataSource.error,
                  copy.settings.dataSourceFailed,
                )}
              />
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              <StatusMetric
                label={copy.settings.assetsTracked(trackedAssets)}
                value={settings.isLoading ? copy.shell.checking : trackedAssets}
                tone="neutral"
              />
              <StatusMetric
                label={copy.settings.initialCash}
                value={
                  settings.data
                    ? formatCurrency(settings.data.initial_cash)
                    : copy.shell.statusUnknown
                }
                tone="neutral"
              />
              <StatusMetric
                label={copy.settings.strategy}
                value={settings.data?.strategy ?? copy.shell.statusUnknown}
                tone="neutral"
              />
              <StatusMetric
                label={copy.settings.notificationType}
                value={notificationType}
                tone={
                  notificationType === copy.settings.notificationUnavailable
                    ? 'warning'
                    : 'success'
                }
              />
            </div>
          </SettingsSection>

          <SettingsSection
            title={copy.settings.notifications}
            detail={copy.settings.notificationsDetail}
          >
            <button
              type="button"
              className="app-button-secondary rounded-2xl px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              disabled={testNotification.isPending}
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
          </SettingsSection>

          <SettingsSection
            title={copy.settings.dataSafety}
            detail={copy.settings.dataSafetyDetail}
          >
            <div className="grid gap-3">
              <SafetyLine text={copy.settings.safetyCachedQuotes} />
              <SafetyLine text={copy.settings.safetyNoAdvice} />
              <SafetyLine text={copy.settings.safetyPrivateData} />
            </div>
            <InlineNotice
              tone="neutral"
              title={copy.settings.deferred}
              detail={copy.settings.deferredDetail}
            />
          </SettingsSection>
        </aside>
      </div>
    </section>
  );
}

function SettingsSection({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <section className="app-terminal-panel rounded-[2rem] p-1.5">
      <div className="app-terminal-inner space-y-4 p-4 sm:p-5">
        <div>
          <div className="app-card-title text-lg">{title}</div>
          <p className="app-muted mt-2 text-sm leading-6">{detail}</p>
        </div>
        {children}
      </div>
    </section>
  );
}

function StatusMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: StatusTone;
}) {
  return (
    <div
      className={`rounded-2xl border px-4 py-3 ${getStatusToneClasses(tone)}`}
      title={`${label}: ${value}`}
      aria-label={`${label}: ${value}`}
    >
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] opacity-75">
        {label}
      </div>
      <div className="mt-2 break-words font-mono text-sm font-semibold tabular-nums">
        {value}
      </div>
    </div>
  );
}

function PreferenceGroup({
  label,
  helper,
  options,
  value,
  onChange,
}: {
  label: string;
  helper: string;
  options: Array<[string, string]>;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold">{label}</div>
        <div className="app-muted text-xs">{helper}</div>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map(([optionValue, optionLabel]) => (
          <button
            key={optionValue}
            type="button"
            className={`rounded-2xl border px-3 py-2 text-sm font-semibold transition-[transform,border-color,background-color] duration-200 active:scale-[0.98] ${
              value === optionValue
                ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent)]'
                : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] text-[var(--app-soft)] hover:border-[color-mix(in_srgb,var(--app-border)_48%,transparent)]'
            }`}
            aria-pressed={value === optionValue}
            onClick={() => onChange(optionValue)}
          >
            {optionLabel}
          </button>
        ))}
      </div>
    </div>
  );
}

function InlineNotice({
  tone,
  title,
  detail,
}: {
  tone: StatusTone;
  title: string;
  detail: string;
}) {
  return (
    <div
      className={`rounded-2xl border px-4 py-3 ${getStatusToneClasses(tone)}`}
    >
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-xs leading-5 opacity-85">{detail}</div>
    </div>
  );
}

function SafetyLine({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-4 py-3 text-sm leading-6 text-[var(--app-soft)]">
      {text}
    </div>
  );
}
