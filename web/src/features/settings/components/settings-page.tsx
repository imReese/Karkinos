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
  ControlledActionZone,
  MetricStrip,
  WorkspaceHeader,
} from '../../../app/components/workbench';
import {
  usePreferences,
  type Locale,
  type ThemePreference,
} from '../../../app/preferences';
import { formatCurrency, formatTimestamp } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import {
  formatMarketDataStatusNextAction,
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import {
  useDataSourceStatusQuery,
  useAssetMetadataStatusQuery,
  useLiveStatusQuery,
  useSettingsQuery,
  useStartLiveMutation,
  useStopLiveMutation,
  useTestNotificationMutation,
  useUpdateDataSourceSettingsMutation,
  useUpdateSettingsMutation,
} from '../api';

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';
type ManualTaskId =
  'tushare_sign_in' | 'guess_market_direction' | 'check_points';

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

function dailyTaskKey() {
  return `karkinos.tushareDailyTasks.${new Date().toISOString().slice(0, 10)}`;
}

export function SettingsPage() {
  const copy = useCopy();
  const settings = useSettingsQuery();
  const dataSourceStatus = useDataSourceStatusQuery();
  const assetMetadataStatus = useAssetMetadataStatusQuery();
  const liveStatus = useLiveStatusQuery();
  const marketHealth = useMarketDataHealthQuery();
  const overview = useAccountOverviewQuery();
  const updateDataSource = useUpdateDataSourceSettingsMutation();
  const updateSettings = useUpdateSettingsMutation();
  const startLive = useStartLiveMutation();
  const stopLive = useStopLiveMutation();
  const testNotification = useTestNotificationMutation();
  const { locale, setLocale, theme, setTheme } = usePreferences();
  const [dataSource, setDataSource] = useState('');
  const [pollInterval, setPollInterval] = useState('60');
  const [accountCommissionRate, setAccountCommissionRate] = useState('0.0001');
  const [accountMinCommission, setAccountMinCommission] = useState('5');
  const taskStorageKey = useMemo(() => dailyTaskKey(), []);
  const [manualTasksDone, setManualTasksDone] = useState<
    Partial<Record<ManualTaskId, boolean>>
  >(() => {
    try {
      return JSON.parse(window.localStorage.getItem(taskStorageKey) ?? '{}');
    } catch {
      return {};
    }
  });

  useEffect(() => {
    if (!settings.data) {
      return;
    }
    setDataSource(settings.data.data_source);
    setPollInterval(String(settings.data.live_poll_interval));
    setAccountCommissionRate(String(settings.data.account_commission_rate));
    setAccountMinCommission(String(settings.data.account_min_commission));
  }, [settings.data]);

  useEffect(() => {
    window.localStorage.setItem(
      taskStorageKey,
      JSON.stringify(manualTasksDone),
    );
  }, [manualTasksDone, taskStorageKey]);

  const quoteStatus = overview.data?.quote_status ?? null;
  const normalizedQuoteStatus = normalizeMarketDataStatus(quoteStatus);
  const quoteStatusLabel = normalizedQuoteStatus
    ? formatPublicStatus(normalizedQuoteStatus, locale)
    : copy.shell.statusUnknown;
  const normalizedRefreshPolicy = normalizeMarketDataStatus(
    marketHealth.data?.refresh_policy,
  );
  const refreshPolicyLabel = marketHealth.data?.refresh_policy
    ? formatPublicStatus(normalizedRefreshPolicy, locale)
    : copy.shell.statusUnknown;
  const valuationTime = overview.data?.valuation_timestamp
    ? formatTimestamp(overview.data.valuation_timestamp)
    : copy.settings.noValuationTime;
  const refreshPolicyNeedsReview = isUnconfirmedMarketDataStatus(
    normalizedRefreshPolicy,
  );
  const isCacheOnly = isCacheLikeMarketDataStatus(normalizedRefreshPolicy);
  const quoteNeedsReview =
    Boolean(normalizedQuoteStatus) &&
    !isConfirmedMarketDataStatus(normalizedQuoteStatus);
  const isStaleQuote = isCacheLikeMarketDataStatus(normalizedQuoteStatus);
  const quoteNextActionLabel = formatMarketDataStatusNextAction(
    normalizedQuoteStatus,
    locale,
  );
  const refreshPolicyNextActionLabel = formatMarketDataStatusNextAction(
    normalizedRefreshPolicy,
    locale,
  );
  const marketDataNoticeNextAction = isStaleQuote
    ? quoteNextActionLabel
    : isCacheOnly
      ? refreshPolicyNextActionLabel
      : (quoteNextActionLabel ?? refreshPolicyNextActionLabel);
  const marketDataNoticeDetail = (detail: string) =>
    marketDataNoticeNextAction
      ? `${detail} ${copy.settings.providerNextAction}: ${marketDataNoticeNextAction}`
      : detail;
  const notificationType = String(
    settings.data?.notification?.type ?? copy.settings.notificationUnavailable,
  );
  const notificationConfigured = Boolean(
    settings.data?.notification?.configured,
  );
  const trackedAssets = settings.data?.assets.length ?? 0;
  const statusLoadFailed =
    settings.isError ||
    dataSourceStatus.isError ||
    assetMetadataStatus.isError ||
    liveStatus.isError ||
    marketHealth.isError ||
    overview.isError;
  const providerName =
    dataSourceStatus.data?.provider_name ?? settings.data?.data_source ?? '--';
  const providerSupportsFunds =
    dataSourceStatus.data?.provider_supports_funds ??
    marketHealth.data?.provider_supports_funds;
  const metadataConfiguredCount =
    assetMetadataStatus.data?.configured_count ??
    dataSourceStatus.data?.metadata_configured_count ??
    marketHealth.data?.metadata_configured_count ??
    0;
  const missingMetadataSymbols =
    assetMetadataStatus.data?.missing_symbols ?? [];
  const metadataSnippet = assetMetadataStatus.data?.suggested_config
    ? JSON.stringify(assetMetadataStatus.data.suggested_config, null, 2)
    : '';
  const providerNextAction =
    dataSourceStatus.data?.next_action ?? marketHealth.data?.next_action;
  const providerActionLabel =
    providerNextAction && providerNextAction in copy.market.providerActions
      ? copy.market.providerActions[
          providerNextAction as keyof typeof copy.market.providerActions
        ]
      : providerNextAction
        ? formatPublicCode(providerNextAction, locale)
        : null;
  const providerTimedOut =
    marketHealth.data?.provider_last_error === 'provider_timeout' ||
    marketHealth.data?.last_refresh_error === 'provider_timeout';
  const availableProviders = dataSourceStatus.data?.available_providers ?? [];
  const dataSourceOptions =
    availableProviders.length > 0 ? availableProviders : ['akshare', 'tushare'];
  const healthQuotes = marketHealth.data?.quotes ?? [];
  const currentProviderName = String(providerName).toLowerCase();
  const isTushareProvider = currentProviderName === 'tushare';
  const providerError =
    marketHealth.data?.provider_last_error ??
    marketHealth.data?.last_refresh_error ??
    null;
  const configuredProviderSupportsFunds =
    dataSourceStatus.data?.provider_supports_funds;
  const fundNavBlocked =
    providerError === 'tushare_fund_nav_permission_denied' ||
    healthQuotes.some(
      (quote) => quote.stale_reason === 'tushare_fund_nav_permission_denied',
    );
  const hasTushareStockQuote = healthQuotes.some(
    (quote) =>
      quote.asset_class === 'stock' &&
      quote.quote_status === 'live' &&
      (quote.quote_source?.includes('tushare') ?? false),
  );
  const hasEastmoneyFundEstimate = healthQuotes.some(
    (quote) =>
      quote.asset_class === 'fund' &&
      quote.quote_status === 'live' &&
      quote.quote_source === 'eastmoney_fund_estimate',
  );
  const hasTushareFundFallback =
    isTushareProvider &&
    configuredProviderSupportsFunds === false &&
    hasEastmoneyFundEstimate;
  const latestFallbackQuote = healthQuotes.find(
    (quote) => quote.quote_source === 'eastmoney_fund_estimate',
  );
  const isFundNavBlocked = fundNavBlocked || hasTushareFundFallback;
  const permissionReason = formatStaleReason(
    isFundNavBlocked ? 'tushare_fund_nav_permission_denied' : providerError,
    copy.common.staleReasons,
  );
  const capabilityRows = [
    {
      label: copy.settings.capabilityStockRealtime,
      source: isTushareProvider
        ? 'tushare_realtime_quote'
        : marketHealth.data?.provider_name || '--',
      status:
        hasTushareStockQuote || isTushareProvider
          ? copy.settings.available
          : copy.shell.statusUnknown,
      tone: hasTushareStockQuote || isTushareProvider ? 'success' : 'neutral',
    },
    {
      label: copy.settings.capabilityStockDaily,
      source: isTushareProvider
        ? 'tushare_daily'
        : marketHealth.data?.provider_name || '--',
      status: isTushareProvider
        ? copy.settings.available
        : copy.shell.statusUnknown,
      tone: isTushareProvider ? 'success' : 'neutral',
    },
    {
      label: 'fund_nav',
      source: 'tushare_fund_nav',
      status: isFundNavBlocked
        ? copy.settings.permissionBlocked
        : providerSupportsFunds
          ? copy.settings.available
          : copy.settings.permissionUnknown,
      tone: isFundNavBlocked
        ? 'danger'
        : providerSupportsFunds
          ? 'success'
          : 'warning',
    },
    {
      label: copy.settings.capabilityFundEstimate,
      source: 'eastmoney_fund_estimate',
      status: hasEastmoneyFundEstimate
        ? copy.settings.available
        : copy.shell.statusUnknown,
      tone: hasEastmoneyFundEstimate ? 'success' : 'neutral',
    },
    {
      label: copy.settings.capabilityPersistentCache,
      source: 'SQLite',
      status: marketHealth.data?.has_persistent_cache
        ? copy.settings.available
        : copy.market.notConfigured,
      tone: marketHealth.data?.has_persistent_cache ? 'success' : 'warning',
    },
  ] satisfies Array<{
    label: string;
    source: string;
    status: string;
    tone: StatusTone;
  }>;
  const operationsRegisterRows = [
    {
      label: copy.settings.registerProvider,
      legacyLabel: copy.settings.currentProvider,
      value: dataSourceStatus.isLoading ? copy.shell.checking : providerName,
      tone: dataSourceStatus.data?.provider_configured ? 'success' : 'warning',
    },
    {
      label: copy.settings.registerPollInterval,
      value: settings.isLoading ? copy.shell.checking : `${pollInterval}s`,
      tone: 'neutral',
    },
    {
      label: copy.settings.registerTrackedAssets,
      value: settings.isLoading
        ? copy.shell.checking
        : copy.settings.assetsTracked(trackedAssets),
      tone: trackedAssets > 0 ? 'success' : 'warning',
    },
    {
      label: copy.settings.registerStrategy,
      value: settings.data?.strategy ?? copy.shell.statusUnknown,
      tone: 'neutral',
    },
    {
      label: copy.settings.initialCash,
      value: settings.data
        ? formatCurrency(settings.data.initial_cash)
        : copy.shell.statusUnknown,
      tone: 'neutral',
    },
    {
      label: copy.settings.providerSupportsFunds,
      value:
        providerSupportsFunds == null
          ? copy.market.unknown
          : providerSupportsFunds
            ? copy.market.fundSupported
            : copy.market.fundUnsupported,
      tone:
        providerSupportsFunds == null
          ? 'neutral'
          : providerSupportsFunds
            ? 'success'
            : 'warning',
    },
    {
      label: copy.settings.persistentCache,
      value: dataSourceStatus.data?.has_persistent_cache
        ? copy.market.configured
        : copy.market.notConfigured,
      tone: dataSourceStatus.data?.has_persistent_cache ? 'success' : 'warning',
    },
  ] satisfies Array<{
    label: string;
    legacyLabel?: string;
    value: string | number;
    tone: StatusTone;
  }>;
  const schedulerState = liveStatus.isLoading
    ? copy.shell.checking
    : liveStatus.data?.running
      ? copy.settings.schedulerRunning
      : copy.settings.schedulerStopped;
  const brokerState = liveStatus.isLoading
    ? copy.shell.checking
    : liveStatus.data?.running
      ? copy.settings.brokerReady
      : copy.settings.brokerDegraded;
  const boundaryRows = [
    {
      label: copy.settings.scheduler,
      value: schedulerState,
      tone: liveStatus.data?.running ? 'success' : 'neutral',
    },
    {
      label: copy.settings.brokerInterface,
      value: brokerState,
      tone: liveStatus.data?.running ? 'success' : 'neutral',
    },
    {
      label: copy.settings.executionDefault,
      value: copy.settings.manualConfirmation,
      tone: 'success',
    },
  ] satisfies Array<{
    label: string;
    value: string | number;
    tone: StatusTone;
  }>;
  const safetyRows = [
    {
      label: copy.settings.executionDefault,
      value: copy.settings.manualConfirmationRequired,
      detail: copy.settings.safetyManualConfirmation,
      tone: 'success',
    },
    {
      label: copy.settings.marketDataBoundary,
      value: copy.settings.timestampRequired,
      detail: copy.settings.safetyCachedQuotes,
      tone:
        refreshPolicyNeedsReview || quoteNeedsReview ? 'warning' : 'success',
    },
    {
      label: copy.settings.adviceBoundary,
      value: copy.settings.analysisOnly,
      detail: copy.settings.safetyNoAdvice,
      tone: 'neutral',
    },
    {
      label: copy.settings.privateDataBoundary,
      value: copy.settings.keepPrivate,
      detail: copy.settings.safetyPrivateData,
      tone: 'neutral',
    },
  ] satisfies Array<{
    label: string;
    value: string | number;
    detail: string;
    tone: StatusTone;
  }>;
  const manualTasks: Array<{ id: ManualTaskId; label: string; href: string }> =
    [
      {
        id: 'tushare_sign_in',
        label: copy.settings.taskTushareSignIn,
        href: 'https://tushare.pro/',
      },
      {
        id: 'guess_market_direction',
        label: copy.settings.taskGuessMarketDirection,
        href: 'https://tushare.pro/',
      },
      {
        id: 'check_points',
        label: copy.settings.taskCheckPoints,
        href: 'https://tushare.pro/user/token',
      },
    ];

  const dataSourceChanged = useMemo(() => {
    if (!settings.data) {
      return false;
    }
    return (
      dataSource !== settings.data.data_source ||
      Number(pollInterval) !== settings.data.live_poll_interval
    );
  }, [dataSource, pollInterval, settings.data]);

  const accountCommissionChanged = useMemo(() => {
    if (!settings.data) {
      return false;
    }
    return (
      Number(accountCommissionRate) !== settings.data.account_commission_rate ||
      Number(accountMinCommission) !== settings.data.account_min_commission
    );
  }, [accountCommissionRate, accountMinCommission, settings.data]);

  const submitDataSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedInterval = Math.max(Number(pollInterval) || 60, 15);
    await updateDataSource.mutateAsync({
      data_source: dataSource.trim() || settings.data?.data_source || 'akshare',
      live_poll_interval: normalizedInterval,
    });
    setPollInterval(String(normalizedInterval));
  };

  const submitAccountCommission = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings.data) {
      return;
    }
    const normalizedRate = Math.max(Number(accountCommissionRate) || 0, 0);
    const normalizedMinimum = Math.max(Number(accountMinCommission) || 0, 0);
    await updateSettings.mutateAsync({
      ...settings.data,
      account_commission_rate: normalizedRate,
      account_min_commission: normalizedMinimum,
    });
    setAccountCommissionRate(String(normalizedRate));
    setAccountMinCommission(String(normalizedMinimum));
  };

  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="settings"
    >
      <WorkspaceHeader
        eyebrow={copy.settings.kicker}
        title={copy.settings.title}
        description={copy.settings.subtitle}
      />

      {statusLoadFailed ? (
        <InlineNotice
          tone="danger"
          title={copy.settings.error}
          detail={[
            settings.error,
            dataSourceStatus.error,
            assetMetadataStatus.error,
            liveStatus.error,
            marketHealth.error,
            overview.error,
          ]
            .filter(Boolean)
            .map((error) => getErrorMessage(error, copy.settings.error))
            .join(' · ')}
        />
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <div className="min-w-0 space-y-5">
          <SettingsSection
            title={copy.settings.dataStatus}
            detail={copy.settings.dataStatusDetail}
          >
            <MetricStrip
              ariaLabel={copy.settings.dataStatus}
              items={[
                {
                  id: 'market-state',
                  label: copy.settings.marketState,
                  value: marketHealth.isLoading ? (
                    copy.shell.checking
                  ) : marketHealth.data?.market_open ? (
                    <span
                      aria-label={`${copy.settings.marketState}: ${copy.shell.marketOpen}`}
                    >
                      {copy.shell.marketOpen}
                    </span>
                  ) : (
                    <span
                      aria-label={`${copy.settings.marketState}: ${copy.shell.marketClosed}`}
                    >
                      {copy.shell.marketClosed}
                    </span>
                  ),
                  tone: 'neutral',
                },
                {
                  id: 'refresh-policy',
                  label: copy.settings.refreshPolicy,
                  value: marketHealth.isLoading ? (
                    copy.shell.checking
                  ) : (
                    <span
                      aria-label={`${copy.settings.refreshPolicy}: ${refreshPolicyLabel}`}
                    >
                      {refreshPolicyLabel}
                    </span>
                  ),
                  tone: refreshPolicyNeedsReview ? 'warning' : 'neutral',
                },
                {
                  id: 'quote-state',
                  label: copy.settings.quoteState,
                  value: overview.isLoading ? (
                    copy.shell.checking
                  ) : isStaleQuote ? (
                    <span
                      aria-label={`${copy.settings.quoteState}: ${copy.settings.cachedQuotes}`}
                    >
                      {copy.settings.cachedQuotes}
                    </span>
                  ) : (
                    <span
                      aria-label={`${copy.settings.quoteState}: ${quoteStatusLabel}`}
                    >
                      {quoteStatusLabel}
                    </span>
                  ),
                  tone: quoteNeedsReview ? 'warning' : 'neutral',
                },
                {
                  id: 'valuation-time',
                  label: copy.settings.valuationTime,
                  value: overview.isLoading
                    ? copy.shell.checking
                    : valuationTime,
                  tone: quoteNeedsReview ? 'warning' : 'neutral',
                },
              ]}
            />

            {refreshPolicyNeedsReview || quoteNeedsReview ? (
              <InlineNotice
                tone="warning"
                title={
                  isStaleQuote
                    ? copy.settings.cachedQuotes
                    : isCacheOnly
                      ? copy.settings.cacheOnly
                      : copy.settings.valuationRequiresReview
                }
                detail={
                  isStaleQuote
                    ? marketDataNoticeDetail(copy.settings.cachedQuotesDetail)
                    : isCacheOnly
                      ? marketDataNoticeDetail(copy.settings.cacheOnlyDetail)
                      : marketDataNoticeDetail(
                          copy.settings.valuationRequiresReviewDetail(
                            quoteStatusLabel,
                          ),
                        )
                }
              />
            ) : null}

            <ControlledActionZone
              title={copy.market.refreshQuotes}
              description={copy.settings.refreshActionDetail}
              evidence={copy.settings.refreshActionEvidence}
            >
              <MarketRefreshButton />
            </ControlledActionZone>
          </SettingsSection>

          <SettingsDisclosure
            testId="settings-data-source-disclosure"
            title={copy.settings.dataSourceOperations}
            detail={copy.settings.dataSourceOperationsDetail}
          >
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-sm font-semibold">
                    {copy.settings.providerCapabilityMatrix}
                  </div>
                  <div className="app-muted text-xs">
                    {copy.settings.currentProvider}: {providerName}
                  </div>
                </div>
                <div className="mt-4 overflow-x-auto">
                  <div className="min-w-[34rem] divide-y divide-[color-mix(in_srgb,var(--app-border)_18%,transparent)]">
                    {capabilityRows.map((row) => (
                      <CapabilityRow
                        key={row.label}
                        label={row.label}
                        source={row.source}
                        status={row.status}
                        tone={row.tone}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <div className="grid min-w-0 gap-4">
                <div className="rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
                  <div className="text-sm font-semibold">
                    {copy.settings.tusharePermissions}
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <StatusMetric
                      label="fund_nav"
                      value={
                        isFundNavBlocked
                          ? copy.settings.permissionBlocked
                          : copy.settings.permissionUnknown
                      }
                      tone={isFundNavBlocked ? 'danger' : 'warning'}
                    />
                    <StatusMetric
                      label={copy.settings.fundFallback}
                      value={
                        hasEastmoneyFundEstimate
                          ? copy.settings.eastmoneyFundEstimate
                          : copy.shell.statusUnknown
                      }
                      tone={hasEastmoneyFundEstimate ? 'success' : 'neutral'}
                    />
                  </div>
                  <div className="app-muted mt-3 text-xs leading-5">
                    {permissionReason}
                    {latestFallbackQuote?.timestamp
                      ? ` · ${copy.settings.latestFallbackQuote}: ${formatTimestamp(
                          latestFallbackQuote.timestamp,
                        )}`
                      : ''}
                  </div>
                </div>

                <div className="rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
                  <div className="text-sm font-semibold">
                    {copy.settings.manualDailyTaskChecklist}
                  </div>
                  <div className="mt-3 grid gap-2">
                    {manualTasks.map((task) => (
                      <ManualTaskRow
                        key={task.id}
                        label={task.label}
                        href={task.href}
                        actionLabel={copy.settings.openExternal}
                        checked={Boolean(manualTasksDone[task.id])}
                        onChange={(checked) =>
                          setManualTasksDone((current) => ({
                            ...current,
                            [task.id]: checked,
                          }))
                        }
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </SettingsDisclosure>

          <SettingsSection
            title={copy.settings.liveServices}
            detail={copy.settings.liveServicesDetail}
          >
            <div className="grid gap-x-4 border-y border-[var(--app-divider)] md:grid-cols-2">
              {boundaryRows.map((row) => (
                <RegisterRow
                  key={row.label}
                  label={row.label}
                  value={row.value}
                  tone={row.tone}
                  ariaLabelPrefix="Boundary item"
                />
              ))}
            </div>

            <ControlledActionZone
              title={copy.settings.scheduler}
              description={copy.settings.schedulerBoundaryDetail}
              evidence={copy.settings.noAutoTrading}
            >
              <button
                type="button"
                className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
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
                className="app-button-secondary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={stopLive.isPending || !liveStatus.data?.running}
                aria-busy={stopLive.isPending}
                onClick={() => void stopLive.mutateAsync()}
              >
                {stopLive.isPending
                  ? copy.settings.updatingScheduler
                  : copy.settings.stopScheduler}
              </button>
            </ControlledActionZone>

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
          <SettingsDisclosure
            testId="settings-backend-disclosure"
            title={copy.settings.backendSettings}
            detail={copy.settings.persistedSettingsDetail}
          >
            <div className="grid gap-3 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold">
                  {copy.settings.operationsRegister}
                </div>
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2.5 py-1 text-[11px] font-semibold text-[var(--app-soft)]">
                  {dataSourceStatus.data?.latest_persistent_quote_timestamp ??
                    copy.settings.noValuationTime}
                </span>
              </div>
              <div className="grid gap-2">
                {operationsRegisterRows.map((row) => (
                  <RegisterRow
                    key={row.label}
                    label={row.label}
                    legacyLabel={row.legacyLabel}
                    value={row.value}
                    tone={row.tone}
                  />
                ))}
              </div>
            </div>

            {providerTimedOut ? (
              <InlineNotice
                tone="warning"
                title={copy.settings.providerNextAction}
                detail={copy.settings.providerTimeoutNotice}
              />
            ) : null}
            {metadataConfiguredCount === 0 ? (
              <InlineNotice
                tone="warning"
                title={copy.settings.assetMetadataMissing}
                detail={copy.settings.assetMetadataMissingDetail}
              />
            ) : null}
            {providerActionLabel ? (
              <InlineNotice
                tone="neutral"
                title={copy.settings.providerNextAction}
                detail={providerActionLabel}
              />
            ) : null}

            <form
              className="grid gap-4 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4"
              onSubmit={submitAccountCommission}
            >
              <div>
                <div className="text-sm font-semibold">
                  {copy.settings.accountCostProfile}
                </div>
                <div className="app-muted mt-1 text-xs leading-5">
                  {copy.settings.accountCostProfileDetail}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.settings.stockCommissionRate}
                  </span>
                  <input
                    aria-label={copy.settings.stockCommissionRate}
                    className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
                    type="number"
                    min={0}
                    step="0.00001"
                    value={accountCommissionRate}
                    onChange={(event) =>
                      setAccountCommissionRate(event.target.value)
                    }
                    disabled={settings.isLoading}
                  />
                </label>
                <label className="grid gap-2">
                  <span className="text-sm font-medium">
                    {copy.settings.minimumCommission}
                  </span>
                  <input
                    aria-label={copy.settings.minimumCommission}
                    className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
                    type="number"
                    min={0}
                    step="0.01"
                    value={accountMinCommission}
                    onChange={(event) =>
                      setAccountMinCommission(event.target.value)
                    }
                    disabled={settings.isLoading}
                  />
                </label>
              </div>
              <div className="app-muted text-xs leading-5">
                {copy.settings.accountCostPreview(
                  Number(accountCommissionRate) || 0,
                  Number(accountMinCommission) || 0,
                )}
              </div>
              <button
                type="submit"
                className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={
                  settings.isLoading ||
                  updateSettings.isPending ||
                  !accountCommissionChanged
                }
                aria-busy={updateSettings.isPending}
              >
                {updateSettings.isPending
                  ? copy.settings.savingAccountCosts
                  : copy.settings.saveAccountCosts}
              </button>
            </form>

            {updateSettings.isSuccess ? (
              <InlineNotice
                tone="success"
                title={copy.settings.accountCostsSaved}
                detail={copy.settings.accountCostsSavedDetail}
              />
            ) : null}
            {updateSettings.isError ? (
              <InlineNotice
                tone="danger"
                title={copy.settings.accountCostsFailed}
                detail={getErrorMessage(
                  updateSettings.error,
                  copy.settings.accountCostsFailed,
                )}
              />
            ) : null}

            <form
              className="grid gap-4 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4"
              onSubmit={submitDataSource}
            >
              <div>
                <div className="text-sm font-semibold">
                  {copy.settings.providerConfiguration}
                </div>
                <div className="app-muted mt-1 text-xs leading-5">
                  {copy.settings.providerConfigurationDetail}
                </div>
              </div>
              <div className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.selectDataSource}
                </span>
                <div className="grid gap-2 sm:grid-cols-3">
                  {dataSourceOptions.map((option) => {
                    const selected = dataSource === option;
                    const label =
                      option === 'akshare'
                        ? copy.settings.providerAkshare
                        : option === 'tushare'
                          ? copy.settings.providerTushare
                          : option;
                    return (
                      <button
                        key={option}
                        type="button"
                        className={`rounded-[var(--app-radius-control)] border px-3 py-2 text-sm font-semibold transition-[transform,border-color,background-color] duration-200 active:scale-[0.98] ${
                          selected
                            ? 'border-[var(--app-accent-border)] bg-[var(--app-accent-ghost)] text-[var(--app-accent)]'
                            : 'border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] text-[var(--app-soft)] hover:border-[color-mix(in_srgb,var(--app-border)_48%,transparent)]'
                        }`}
                        aria-pressed={selected}
                        aria-label={`${copy.settings.dataSource}: ${label}`}
                        onClick={() => setDataSource(option)}
                        disabled={settings.isLoading}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </div>
              <label className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.pollInterval}
                </span>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                  <input
                    aria-label={copy.settings.pollInterval}
                    className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm tabular-nums"
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
              <div className="grid gap-2">
                <span className="text-sm font-medium">
                  {copy.settings.token}
                </span>
                <div
                  className="border-y border-[var(--app-divider)] px-1 py-2 text-sm"
                  role="status"
                  aria-label={copy.settings.token}
                >
                  {dataSource !== 'tushare'
                    ? copy.settings.credentialNotRequired
                    : settings.data?.tushare_token_configured
                      ? copy.settings.credentialConfigured
                      : copy.settings.credentialMissing}
                </div>
                <span className="app-muted text-xs leading-5">
                  {copy.settings.credentialEnvironmentDetail}
                </span>
              </div>
              <button
                type="submit"
                className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                disabled={
                  settings.isLoading ||
                  updateDataSource.isPending ||
                  !dataSourceChanged ||
                  (dataSource === 'tushare' &&
                    !settings.data?.tushare_token_configured)
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
                detail={
                  dataSourceStatus.data?.requires_restart
                    ? copy.settings.requiresRestart
                    : copy.settings.hotSwitchAvailable
                }
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

            <div className="grid gap-3 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
              <div>
                <div className="text-sm font-semibold">
                  {copy.settings.metadataReadiness}
                </div>
                <div className="app-muted mt-1 text-xs leading-5">
                  {copy.settings.metadataReadinessDetail}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <StatusMetric
                  label={copy.settings.metadataConfigured}
                  value={
                    assetMetadataStatus.isLoading
                      ? copy.shell.checking
                      : metadataConfiguredCount
                  }
                  tone={metadataConfiguredCount > 0 ? 'success' : 'warning'}
                />
                <StatusMetric
                  label={copy.settings.assetMetadataMissingCount}
                  value={
                    assetMetadataStatus.isLoading
                      ? copy.shell.checking
                      : missingMetadataSymbols.length
                  }
                  tone={
                    missingMetadataSymbols.length > 0 ? 'warning' : 'success'
                  }
                />
                <StatusMetric
                  label={copy.settings.assetMetadataSource}
                  value={
                    assetMetadataStatus.data?.metadata_source ??
                    copy.shell.statusUnknown
                  }
                  tone="neutral"
                />
              </div>
              {assetMetadataStatus.isLoading ? (
                <InlineNotice
                  tone="neutral"
                  title={copy.shell.checking}
                  detail={copy.settings.assetMetadataDetail}
                />
              ) : assetMetadataStatus.data?.has_missing_metadata ? (
                <div className="grid gap-3">
                  <InlineNotice
                    tone="warning"
                    title={copy.settings.assetMetadataMissingSymbols}
                    detail={missingMetadataSymbols.join(', ')}
                  />
                  <label className="grid gap-2">
                    <span className="text-sm font-semibold">
                      {copy.settings.assetMetadataSnippet}
                    </span>
                    <textarea
                      className="app-field min-h-44 resize-y rounded-[var(--app-radius-control)] px-3 py-3 font-mono text-xs leading-5"
                      readOnly
                      aria-label={copy.settings.assetMetadataSnippet}
                      value={metadataSnippet}
                    />
                    <span className="app-muted text-xs leading-5">
                      {copy.settings.assetMetadataSnippetDetail}
                    </span>
                  </label>
                </div>
              ) : (
                <InlineNotice
                  tone="success"
                  title={copy.settings.assetMetadataComplete}
                  detail={copy.settings.assetMetadataCompleteDetail}
                />
              )}
            </div>
          </SettingsDisclosure>

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

          <SettingsSection
            title={copy.settings.dataSafety}
            detail={copy.settings.dataSafetyDetail}
          >
            <div className="grid gap-3 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold">
                  {copy.settings.safetyRegister}
                </div>
                <span className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-2.5 py-1 text-[11px] font-semibold text-[var(--app-soft)]">
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
          </SettingsSection>

          <SettingsSection
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
    <section className="border-y border-[var(--app-divider)]">
      <div className="space-y-4 py-4 sm:py-5">
        <div>
          <div className="app-card-title text-lg">{title}</div>
          <p className="app-muted mt-2 text-sm leading-6">{detail}</p>
        </div>
        {children}
      </div>
    </section>
  );
}

function SettingsDisclosure({
  testId,
  title,
  detail,
  children,
}: {
  testId: string;
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <details
      className="min-w-0 border-y border-[var(--app-divider)]"
      data-testid={testId}
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-start justify-between gap-4 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
        <span className="min-w-0">
          <span className="block text-sm font-semibold text-[var(--app-text)]">
            {title}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {detail}
          </span>
        </span>
        <span
          aria-hidden="true"
          className="shrink-0 text-sm text-[var(--app-text-secondary)]"
        >
          +
        </span>
      </summary>
      <div className="space-y-4 py-4">{children}</div>
    </details>
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
      className={`rounded-[var(--app-radius-control)] border px-4 py-3 ${getStatusToneClasses(tone)}`}
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

function RegisterRow({
  label,
  legacyLabel,
  value,
  tone,
  ariaLabelPrefix = 'Register item',
}: {
  label: string;
  legacyLabel?: string;
  value: string | number;
  tone: StatusTone;
  ariaLabelPrefix?: string;
}) {
  return (
    <div
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-[var(--app-divider)] px-1 py-2.5 last:border-b-0"
      aria-label={`${ariaLabelPrefix}: ${label} ${value}`}
    >
      {legacyLabel ? (
        <span className="sr-only" aria-label={`${legacyLabel}: ${value}`} />
      ) : null}
      <div className="min-w-0 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--app-muted)]">
        {label}
      </div>
      <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-2 justify-self-end text-right">
        <span
          className={`h-2 w-2 rounded-full border ${getStatusToneClasses(tone)}`}
          aria-hidden="true"
        />
        <span className="min-w-0 font-mono text-sm font-semibold tabular-nums text-[var(--app-text)]">
          {value}
        </span>
      </div>
    </div>
  );
}

function CapabilityRow({
  label,
  source,
  status,
  tone,
}: {
  label: string;
  source: string;
  status: string;
  tone: StatusTone;
}) {
  return (
    <div className="grid grid-cols-[minmax(10rem,1fr)_minmax(10rem,1fr)_8rem] items-center gap-3 py-3 text-sm">
      <div className="min-w-0 font-semibold text-[var(--app-text)]">
        {label}
      </div>
      <div className="min-w-0 truncate font-mono text-xs text-[var(--app-soft)]">
        {source}
      </div>
      <span
        className={`justify-self-start rounded-full border px-2.5 py-1 text-xs font-semibold ${getStatusToneClasses(
          tone,
        )}`}
      >
        {status}
      </span>
    </div>
  );
}

function ManualTaskRow({
  label,
  href,
  actionLabel,
  checked,
  onChange,
}: {
  label: string;
  href: string;
  actionLabel: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center border-t border-[var(--app-divider)] first:border-t-0">
      <label className="flex min-h-[var(--app-touch-target)] min-w-0 cursor-pointer items-center gap-3 px-3 py-2">
        <input
          type="checkbox"
          className="h-5 w-5 shrink-0 accent-[var(--app-accent)]"
          checked={checked}
          aria-label={`Manual task: ${label}`}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="min-w-0 text-sm font-medium text-[var(--app-soft)]">
          {label}
        </span>
      </label>
      <a
        className="app-link inline-flex min-h-[var(--app-touch-target)] items-center px-3 py-2 text-xs font-semibold"
        href={href}
        target="_blank"
        rel="noreferrer"
      >
        {actionLabel}
      </a>
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
            className={`rounded-[var(--app-radius-control)] border px-3 py-2 text-sm font-semibold transition-colors ${
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
      className={`rounded-[var(--app-radius-control)] border px-4 py-3 ${getStatusToneClasses(tone)}`}
    >
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-xs leading-5 opacity-85">{detail}</div>
    </div>
  );
}
