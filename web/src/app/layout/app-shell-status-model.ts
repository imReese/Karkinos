import { isUnconfirmedMarketDataStatus } from '../../shared/market-data-status';
import {
  hasValidValuationTimestamp,
  selectValuationTimestamp,
} from '../../shared/format';
import { formatPublicStatus } from '../../shared/public-labels';
import type { Locale } from '../../shared/preferences/context';
import type { AppCopy } from '../copy';

export type ToolbarStatusTone = 'success' | 'warning' | 'danger';
export type ToolbarPopoverKey = 'valuation' | 'market' | null;
export type ToolbarStatusIndicator = 'dot' | 'syncing';

type AccountOverviewStatusSource = {
  valuation_as_of?: string | null;
  valuation_timestamp?: string | null;
  quote_status?: string | null;
  valuation_status?: string | null;
  valuation_blockers?: string[] | null;
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
  marketSourceStatus?: string;
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
  isRefreshingQuotes?: boolean;
  locale: Locale;
  marketHealth: QueryStatus<MarketHealthStatusSource>;
  now?: Date;
};

export function deriveToolbarStatusModel({
  accountOverview,
  copy,
  isRefreshingQuotes,
  locale,
  marketHealth,
  now,
}: ToolbarStatusModelInput): ToolbarStatusModel {
  const overview = accountOverview.data;
  const valuationAsOf = selectValuationTimestamp(overview);
  const valuationTimestamp = formatToolbarTimestamp(
    hasValidValuationTimestamp(valuationAsOf) ? valuationAsOf : null,
    locale,
    now,
  );
  const isQuoteStale = overview?.quote_status === 'stale';
  const isValuationDegraded =
    overview?.valuation_status === 'degraded' ||
    Boolean(
      overview?.valuation_blockers && overview.valuation_blockers.length > 0,
    );
  const isValuationMissing =
    overview?.valuation_status === 'missing' ||
    overview?.valuation_status === 'error' ||
    overview?.valuation_status === 'blocked';

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
    : accountOverview.isError || isValuationMissing
      ? status(copy.shell.valuationError, 'danger')
      : isValuationDegraded ||
          (overview?.valuation_status === undefined && isQuoteStale)
        ? status(copy.shell.valuationStale, 'warning')
        : overview && valuationTimestamp
          ? status(copy.shell.valuationMode, 'success')
          : status(copy.shell.statusUnknown, 'warning');

  const marketStatus = isRefreshingQuotes
    ? status(copy.market.refreshingQuotes, 'warning', 'syncing')
    : marketHealth.isLoading
      ? status(copy.shell.checking, 'warning', 'syncing')
      : marketHealth.isError
        ? status(copy.shell.marketError, 'danger')
        : marketQuotesUnconfirmed
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
    now,
  );

  const marketSourceStatus = marketHealth.data?.source_health
    ? formatPublicStatus(marketHealth.data.source_health, locale)
    : undefined;

  return {
    executionMode,
    marketOpenText,
    marketSourceStatus,
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

export function formatToolbarTimestamp(
  value: Date | string | null | undefined,
  _locale: Locale,
  referenceNow: Date = new Date(),
): string | null {
  if (!value) {
    return null;
  }

  const parts = parseShanghaiDate(value);
  if (!parts) {
    return null;
  }

  const today = getShanghaiDateParts(referenceNow);
  const isToday =
    parts.year === today.year &&
    parts.month === today.month &&
    parts.day === today.day;
  if (isToday) {
    return parts.time;
  }
  if (parts.year === today.year) {
    return `${parts.month}-${parts.day} ${parts.time}`;
  }
  return `${parts.year}-${parts.month}-${parts.day} ${parts.time}`;
}

function parseShanghaiDate(value: Date | string): {
  year: string;
  month: string;
  day: string;
  time: string;
} | null {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) {
      return null;
    }
    return getShanghaiDateParts(value);
  }
  if (typeof value !== 'string') {
    return null;
  }
  const hasTimezone = /[zZ]|[-+]\d{2}:?\d{2}$/.test(value);
  if (hasTimezone) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return null;
    }
    return getShanghaiDateParts(parsed);
  }
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/);
  if (match) {
    return {
      year: match[1],
      month: match[2],
      day: match[3],
      time: match[4] && match[5] ? `${match[4]}:${match[5]}` : '00:00',
    };
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return getShanghaiDateParts(parsed);
}

function getShanghaiDateParts(date: Date): {
  year: string;
  month: string;
  day: string;
  time: string;
} {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return {
    year: byType.year ?? '0000',
    month: byType.month ?? '00',
    day: byType.day ?? '00',
    time: `${byType.hour ?? '00'}:${byType.minute ?? '00'}`,
  };
}
