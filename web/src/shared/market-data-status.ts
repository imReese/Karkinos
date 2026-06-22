const STATUS_ALIASES: Record<string, string> = {
  cache_only: 'cache',
  cache_only_after_market_data_permission_fallback: 'cache',
  cached: 'cache',
  confirmed_fund_nav_missing_estimate_only: 'confirmed_nav_missing',
  confirmed_nav_missing: 'confirmed_nav_missing',
  confirmed_nav_missing_estimate_only: 'confirmed_nav_missing',
  fresh: 'confirmed',
  healthy: 'live',
  market_closed_cache_only: 'cache',
  quote_older_than_expected_session: 'stale',
  refresh_policy_cache_only: 'cache',
};

const CONFIRMED_MARKET_DATA_STATUSES = new Set([
  'confirmed',
  'fresh',
  'healthy',
  'live',
]);

const CACHE_LIKE_MARKET_DATA_STATUSES = new Set([
  'cache',
  'cache_only',
  'cache_only_after_market_data_permission_fallback',
  'cached',
  'market_closed_cache_only',
  'quote_older_than_expected_session',
  'refresh_policy_cache_only',
  'stale',
]);

type MarketDataStatusLocale = 'en' | 'zh';

const MARKET_DATA_NEXT_ACTIONS: Record<
  MarketDataStatusLocale,
  Record<string, string>
> = {
  en: {
    cache: 'Refresh quotes or check the data source',
    confirmed_nav_missing: 'Wait for confirmed fund NAV or sync NAV data',
    estimated: 'Wait for confirmed data or refresh quotes',
    missing: 'Backfill market data or run the first sync',
    stale: 'Refresh quotes or check the data source',
  },
  zh: {
    cache: '刷新行情或检查数据源',
    confirmed_nav_missing: '等待基金确认净值或同步净值',
    estimated: '等待确认数据或刷新行情',
    missing: '补齐行情数据或执行首次同步',
    stale: '刷新行情或检查数据源',
  },
};

export function normalizeMarketDataStatus(value?: string | null) {
  const raw =
    value
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '';
  return STATUS_ALIASES[raw] ?? raw;
}

export function isConfirmedMarketDataStatus(value?: string | null) {
  return CONFIRMED_MARKET_DATA_STATUSES.has(
    value
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '',
  );
}

export function isCacheLikeMarketDataStatus(value?: string | null) {
  return CACHE_LIKE_MARKET_DATA_STATUSES.has(
    value
      ?.trim()
      .toLowerCase()
      .replace(/[\s-]+/g, '_') ?? '',
  );
}

export function isUnconfirmedMarketDataStatus(value?: string | null) {
  const normalized = normalizeMarketDataStatus(value);
  return Boolean(normalized) && !isConfirmedMarketDataStatus(normalized);
}

export function formatMarketDataStatusNextAction(
  value: string | null | undefined,
  locale: MarketDataStatusLocale,
) {
  const normalized = normalizeMarketDataStatus(value);
  if (!normalized || isConfirmedMarketDataStatus(normalized)) {
    return null;
  }
  return MARKET_DATA_NEXT_ACTIONS[locale][normalized] ?? null;
}
