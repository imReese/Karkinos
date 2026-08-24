import { isUnconfirmedMarketDataStatus } from '../../shared/market-data-status';
import { formatPublicStatus } from '../../shared/public-labels';
import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';

export type ToolbarStatusTone = 'success' | 'warning' | 'danger';
export type ToolbarPopoverKey = 'valuation' | 'market' | null;
export type ToolbarStatusIndicator = 'dot' | 'syncing';

type AccountOverviewStatusSource = {
  valuation_timestamp?: string | null;
  quote_status?: string | null;
  daily_operations?: {
    default_execution_mode?: string | null;
  } | null;
};

type MarketHealthStatusSource = {
  refresh_policy?: string | null;
  market_open?: boolean;
  source_health?: string | null;
  latest_quote_timestamp?: string | null;
  last_refresh_attempt?: string | null;
};

type QueryStatus<T> = {
  data: T | undefined;
  isError: boolean;
  isLoading: boolean;
};

export type ToolbarStatusProjection = {
  indicator: ToolbarStatusIndicator;
  tone: ToolbarStatusTone;
  value: string;
};

export type ToolbarStatusModel = {
  executionMode: string;
  marketOpenText: string;
  marketStatus: ToolbarStatusProjection;
  marketTimestamp: string | null;
  quoteStatus: string;
  refreshPolicy: string;
  valuationMeta: string | undefined;
  valuationStatus: ToolbarStatusProjection;
  valuationTimestamp: string | null;
};

type ToolbarStatusModelInput = {
  accountOverview: QueryStatus<AccountOverviewStatusSource>;
  copy: AppCopy;
  locale: Locale;
  marketHealth: QueryStatus<MarketHealthStatusSource>;
};

export function deriveToolbarStatusModel({
  accountOverview,
  copy,
  locale,
  marketHealth,
}: ToolbarStatusModelInput): ToolbarStatusModel {
  const overview = accountOverview.data;
  const valuationTimestamp = formatToolbarTimestamp(
    overview?.valuation_timestamp,
    locale,
  );
  const isQuoteStale = overview?.quote_status === 'stale';
  const quoteStatus = overview?.quote_status
    ? formatPublicStatus(overview.quote_status, locale)
    : copy.shell.statusUnknown;
  const refreshPolicy = marketHealth.data?.refresh_policy
    ? formatPublicStatus(marketHealth.data.refresh_policy, locale)
    : copy.shell.statusUnknown;
  const marketOpenText =
    marketHealth.data?.market_open === undefined
      ? copy.shell.statusUnknown
      : marketHealth.data.market_open
        ? copy.shell.marketOpen
        : copy.shell.marketClosed;
  const marketQuotesHealthy =
    marketHealth.data?.source_health === 'live' ||
    marketHealth.data?.source_health === 'healthy';
  const marketQuotesUnconfirmed = isUnconfirmedMarketDataStatus(
    marketHealth.data?.source_health,
  );

  const valuationStatus = accountOverview.isLoading
    ? status(copy.shell.checking, 'warning', 'syncing')
    : accountOverview.isError
      ? status(copy.shell.valuationError, 'danger')
      : isQuoteStale
        ? status(copy.shell.valuationStale, 'warning')
        : overview
          ? status(copy.shell.valuationMode, 'success')
          : status(copy.shell.statusUnknown, 'warning');

  const marketStatus = marketHealth.isLoading
    ? status(copy.shell.checking, 'warning', 'syncing')
    : marketHealth.isError
      ? status(copy.shell.marketError, 'danger')
      : isQuoteStale || marketQuotesUnconfirmed
        ? status(copy.shell.cachedQuotes, 'warning')
        : marketHealth.data?.refresh_policy === 'cache_only'
          ? status(
              marketHealth.data.market_open
                ? copy.shell.marketCacheOnly
                : copy.shell.marketClosed,
              !marketHealth.data.market_open && marketQuotesHealthy
                ? 'success'
                : 'warning',
            )
          : marketHealth.data
            ? status(copy.shell.marketLive, 'success')
            : status(copy.shell.statusUnknown, 'warning');

  const executionMode = accountOverview.isLoading
    ? copy.shell.checking
    : overview?.daily_operations?.default_execution_mode === 'paper_shadow'
      ? copy.shell.paperShadowMode
      : overview?.daily_operations?.default_execution_mode ===
          'manual_confirmation'
        ? copy.shell.manualConfirmationMode
        : overview?.daily_operations?.default_execution_mode
          ? formatPublicStatus(
              overview.daily_operations.default_execution_mode,
              locale,
            )
          : copy.shell.statusUnknown;

  const valuationMeta = valuationTimestamp
    ? copy.shell.valuationAt(valuationTimestamp)
    : undefined;
  const marketTimestamp = formatToolbarTimestamp(
    marketHealth.data?.latest_quote_timestamp ??
      marketHealth.data?.last_refresh_attempt,
    locale,
  );

  return {
    executionMode,
    marketOpenText,
    marketStatus,
    marketTimestamp,
    quoteStatus,
    refreshPolicy,
    valuationMeta,
    valuationStatus,
    valuationTimestamp,
  };
}

function status(
  value: string,
  tone: ToolbarStatusTone,
  indicator: ToolbarStatusIndicator = 'dot',
): ToolbarStatusProjection {
  return { value, tone, indicator };
}

function formatToolbarTimestamp(
  value: Date | string | null | undefined,
  locale: Locale,
) {
  if (!value) {
    return null;
  }
  if (typeof value === 'string') {
    const localClockTime = value.match(/T(\d{2}:\d{2})(?::\d{2})?/);
    if (localClockTime?.[1]) {
      return localClockTime[1];
    }
  }
  const timestamp = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return null;
  }
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}
