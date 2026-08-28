import { formatCurrency, formatTimestamp } from '../../../shared/format';
import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import {
  formatMarketDataStatusNextAction,
  isCacheLikeMarketDataStatus,
  isConfirmedMarketDataStatus,
  isFundEstimateQuoteSource,
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import type {
  useAccountOverviewQuery,
  useMarketDataHealthQuery,
} from '../settings-feature-boundary';
import type {
  useAssetMetadataStatusQuery,
  useDataSourceStatusQuery,
  useLiveStatusQuery,
  useSettingsQuery,
} from '../api';

export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';
export type ManualTaskId =
  'tushare_sign_in' | 'guess_market_direction' | 'check_points';

export type SettingsModelInputs = {
  copy: ReturnType<typeof useCopy>;
  locale: Locale;
  settings: ReturnType<typeof useSettingsQuery>;
  dataSourceStatus: ReturnType<typeof useDataSourceStatusQuery>;
  assetMetadataStatus: ReturnType<typeof useAssetMetadataStatusQuery>;
  liveStatus: ReturnType<typeof useLiveStatusQuery>;
  marketHealth: ReturnType<typeof useMarketDataHealthQuery>;
  overview: ReturnType<typeof useAccountOverviewQuery>;
  pollInterval: string;
};

export function buildSettingsMarketModel(inputs: SettingsModelInputs) {
  const {
    assetMetadataStatus,
    copy,
    dataSourceStatus,
    liveStatus,
    locale,
    marketHealth,
    overview,
    settings,
  } = inputs;
  const fundNavCapabilityLabel =
    locale === 'zh' ? '基金净值接口' : 'Fund NAV capability';
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
  const latestPersistentQuoteTime = dataSourceStatus.data
    ?.latest_persistent_quote_timestamp
    ? formatTimestamp(dataSourceStatus.data.latest_persistent_quote_timestamp)
    : copy.settings.noValuationTime;
  const metadataSource = assetMetadataStatus.data?.metadata_source;
  const metadataSourceLabel =
    metadataSource === 'db+watchlist+legacy_config'
      ? copy.settings.assetMetadataSourcePersisted
      : metadataSource === 'config'
        ? copy.settings.assetMetadataSourceLocal
        : metadataSource
          ? copy.settings.assetMetadataSourceProvided
          : copy.shell.statusUnknown;
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
  const hasFundEstimate = healthQuotes.some(
    (quote) =>
      quote.asset_class === 'fund' &&
      quote.quote_status === 'live' &&
      isFundEstimateQuoteSource(quote.quote_source),
  );
  const hasTushareFundFallback =
    isTushareProvider &&
    configuredProviderSupportsFunds === false &&
    hasFundEstimate;
  const latestFallbackQuote = healthQuotes.find((quote) =>
    isFundEstimateQuoteSource(quote.quote_source),
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
      label: fundNavCapabilityLabel,
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
      source: latestFallbackQuote?.quote_source ?? 'fund_intraday_estimate',
      status: hasFundEstimate
        ? copy.settings.available
        : copy.shell.statusUnknown,
      tone: hasFundEstimate ? 'success' : 'neutral',
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
  return {
    quoteStatus,
    normalizedQuoteStatus,
    quoteStatusLabel,
    normalizedRefreshPolicy,
    refreshPolicyLabel,
    valuationTime,
    refreshPolicyNeedsReview,
    isCacheOnly,
    quoteNeedsReview,
    isStaleQuote,
    quoteNextActionLabel,
    refreshPolicyNextActionLabel,
    marketDataNoticeNextAction,
    marketDataNoticeDetail,
    notificationType,
    notificationConfigured,
    trackedAssets,
    statusLoadFailed,
    providerName,
    providerSupportsFunds,
    metadataConfiguredCount,
    missingMetadataSymbols,
    metadataSnippet,
    latestPersistentQuoteTime,
    metadataSource,
    metadataSourceLabel,
    providerNextAction,
    providerActionLabel,
    providerTimedOut,
    availableProviders,
    dataSourceOptions,
    healthQuotes,
    currentProviderName,
    isTushareProvider,
    providerError,
    configuredProviderSupportsFunds,
    fundNavBlocked,
    hasTushareStockQuote,
    hasFundEstimate,
    hasTushareFundFallback,
    latestFallbackQuote,
    isFundNavBlocked,
    permissionReason,
    capabilityRows,
  };
}

export type SettingsMarketModel = ReturnType<typeof buildSettingsMarketModel>;

export function buildSettingsOperationsModel(
  inputs: SettingsModelInputs,
  marketModel: SettingsMarketModel,
) {
  const { copy, dataSourceStatus, liveStatus, locale, pollInterval, settings } =
    inputs;
  const {
    providerSupportsFunds,
    quoteNeedsReview,
    refreshPolicyNeedsReview,
    trackedAssets,
  } = marketModel;
  const operationsRegisterRows = [
    {
      label: copy.settings.registerProvider,
      legacyLabel: copy.settings.currentProvider,
      value: dataSourceStatus.isLoading
        ? copy.shell.checking
        : (dataSourceStatus.data?.provider_name ??
          settings.data?.data_source ??
          '--'),
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
      value: settings.data?.strategy
        ? formatPublicCode(settings.data.strategy, locale)
        : copy.shell.statusUnknown,
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
    : liveStatus.isError
      ? copy.shell.statusUnknown
      : liveStatus.data?.running
        ? copy.settings.schedulerRunning
        : copy.settings.schedulerUnavailable;
  const schedulerTone = liveStatus.isLoading
    ? 'neutral'
    : liveStatus.data?.running
      ? 'success'
      : 'danger';
  const brokerState = liveStatus.isLoading
    ? copy.shell.checking
    : copy.shell.statusUnknown;
  const boundaryRows = [
    {
      label: copy.settings.scheduler,
      value: schedulerState,
      tone: schedulerTone,
    },
    {
      label: copy.settings.brokerInterface,
      value: brokerState,
      tone: 'neutral',
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

  return {
    operationsRegisterRows,
    schedulerState,
    brokerState,
    boundaryRows,
    safetyRows,
    manualTasks,
  };
}
