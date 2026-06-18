type StaleReasonLabels = {
  noRealDataAvailable: string;
  quoteTimestampMissing: string;
  marketClosedCacheOnly: string;
  refreshPolicyCacheOnly: string;
  quoteOlderThanExpectedSession: string;
  providerTimeout: string;
  providerUnavailable: string;
  sourceUnavailable: string;
  tushareFundNavPermissionDenied: string;
  confirmedFundNavMissingEstimateOnly: string;
};

const STALE_REASON_KEYS: Record<string, keyof StaleReasonLabels> = {
  no_real_data_available: 'noRealDataAvailable',
  quote_timestamp_missing: 'quoteTimestampMissing',
  market_closed_cache_only: 'marketClosedCacheOnly',
  refresh_policy_cache_only: 'refreshPolicyCacheOnly',
  quote_older_than_expected_session: 'quoteOlderThanExpectedSession',
  provider_timeout: 'providerTimeout',
  provider_unavailable: 'providerUnavailable',
  source_unavailable: 'sourceUnavailable',
  tushare_fund_nav_permission_denied: 'tushareFundNavPermissionDenied',
  confirmed_fund_nav_missing_estimate_only:
    'confirmedFundNavMissingEstimateOnly',
};

export function formatStaleReason(
  reason: string | null | undefined,
  labels: StaleReasonLabels,
) {
  const normalized = reason?.trim();
  if (!normalized) {
    return '--';
  }
  const labelKey = STALE_REASON_KEYS[normalized];
  return labelKey ? labels[labelKey] : normalized;
}
