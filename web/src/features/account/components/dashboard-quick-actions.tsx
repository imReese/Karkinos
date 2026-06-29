import { useCopy } from '../../../app/copy';
import { usePreferences } from '../../../app/preferences';
import { formatDateTime, formatTimestamp } from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import {
  formatMarketDataStatusNextAction,
  isUnconfirmedMarketDataStatus,
} from '../../../shared/market-data-status';
import { formatStaleReason } from '../../../shared/stale-reason';
import type { AccountOverview } from '../api';
import {
  useRefreshMarketQuotesMutation,
  type MarketDataHealthResponse,
} from '../../market/api';

export type QuoteDiagnosticItem = {
  symbol: string;
  name?: string | null;
  display_name?: string | null;
  asset_class?: string | null;
  quote_status?: string | null;
  quote_source?: string | null;
  quote_timestamp?: string | null;
  stale_reason?: string | null;
};

function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(0, Math.round(seconds))}s`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}

function normalizeStatus(value: string | null | undefined) {
  return value && value.trim().length > 0 ? value : '--';
}

function isActionableQuoteDiagnostic(item: QuoteDiagnosticItem) {
  const quoteStatus = item.quote_status?.toLowerCase();
  const quoteSource = item.quote_source?.toLowerCase();
  return (
    Boolean(item.stale_reason) ||
    isUnconfirmedMarketDataStatus(quoteStatus) ||
    quoteStatus === 'error' ||
    quoteSource === 'eastmoney_fund_estimate'
  );
}

function assetClassLabel(
  value: string | null | undefined,
  labels: ReturnType<typeof useCopy>,
) {
  if (value === 'stock') {
    return labels.common.assetClassStock;
  }
  if (value === 'fund') {
    return labels.common.assetClassFund;
  }
  if (value === 'etf') {
    return labels.common.assetClassEtf;
  }
  if (value === 'gold') {
    return labels.common.assetClassGold;
  }
  if (value === 'bond') {
    return labels.common.assetClassBond;
  }
  return normalizeStatus(value);
}

function diagnosticActionLabel(
  item: QuoteDiagnosticItem,
  locale: 'en' | 'zh',
  staleReasons: ReturnType<typeof useCopy>['common']['staleReasons'],
) {
  return (
    formatMarketDataStatusNextAction(item.stale_reason, locale) ??
    formatMarketDataStatusNextAction(item.quote_status, locale) ??
    (item.quote_source === 'eastmoney_fund_estimate'
      ? formatMarketDataStatusNextAction('confirmed_nav_missing', locale)
      : null) ??
    formatStaleReason(item.stale_reason, staleReasons)
  );
}

export function DashboardQuickActions({
  overview,
  marketHealth,
  symbols,
  quoteDiagnostics = [],
  compact = false,
}: {
  overview: AccountOverview;
  marketHealth?: MarketDataHealthResponse;
  symbols: string[];
  quoteDiagnostics?: QuoteDiagnosticItem[];
  compact?: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const quoteStatus = overview.quote_status ?? 'unknown';
  const isStale =
    isUnconfirmedMarketDataStatus(quoteStatus) ||
    isUnconfirmedMarketDataStatus(marketHealth?.source_health) ||
    marketHealth?.persistent_cache_status === 'missing';
  const refreshMessage = refreshQuotes.isPending
    ? labels.refreshingQuotes
    : refreshQuotes.isError
      ? labels.refreshFailed
      : refreshQuotes.isSuccess
        ? labels.refreshDone
        : '';
  const marketDataNextAction =
    formatMarketDataStatusNextAction(overview.stale_reason, locale) ??
    formatMarketDataStatusNextAction(quoteStatus, locale) ??
    formatMarketDataStatusNextAction(marketHealth?.source_health, locale) ??
    formatMarketDataStatusNextAction(
      marketHealth?.persistent_cache_status,
      locale,
    ) ??
    formatMarketDataStatusNextAction(
      overview.refresh_policy ?? marketHealth?.refresh_policy,
      locale,
    );
  const providerNextAction =
    marketHealth?.next_action &&
    marketHealth.next_action in copy.market.providerActions
      ? copy.market.providerActions[
          marketHealth.next_action as keyof typeof copy.market.providerActions
        ]
      : marketHealth?.next_action
        ? formatPublicCode(marketHealth.next_action, locale)
        : null;
  const specificProviderNextAction =
    marketHealth?.next_action &&
    marketHealth.next_action !== 'refresh_quotes_or_check_source'
      ? providerNextAction
      : null;

  const statusRows = [
    {
      label: labels.valuationTime,
      value: formatDateTime(overview.valuation_timestamp),
    },
    {
      label: labels.quoteAge,
      value: formatAge(
        overview.quote_age_seconds ?? marketHealth?.cache_age_seconds,
      ),
    },
    {
      label: labels.refreshPolicy,
      value: formatPublicStatus(
        overview.refresh_policy ?? marketHealth?.refresh_policy,
        locale,
      ),
    },
    {
      label: labels.quoteSource,
      value: normalizeStatus(marketHealth?.provider_name),
    },
    {
      label: copy.market.providerNextAction,
      value: normalizeStatus(
        specificProviderNextAction ??
          marketDataNextAction ??
          providerNextAction,
      ),
    },
  ];
  const staleReason = formatStaleReason(
    overview.stale_reason ??
      marketHealth?.provider_last_error ??
      marketHealth?.last_refresh_error,
    copy.common.staleReasons,
  );
  const actionableDiagnostics = quoteDiagnostics
    .filter(isActionableQuoteDiagnostic)
    .slice(0, 4);

  return (
    <section
      className={
        compact
          ? 'app-terminal-panel min-w-0 overflow-hidden rounded-[2rem] p-1.5'
          : 'app-panel min-w-0 rounded-[1.75rem] p-4 sm:p-5'
      }
      data-testid="overview-operations-panel"
      data-compact={compact ? 'true' : 'false'}
    >
      <div
        className={
          compact
            ? 'app-terminal-inner grid min-w-0 gap-4 p-4 sm:p-5'
            : 'grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start'
        }
      >
        <div className="min-w-0">
          <div className="app-product-mark">{labels.dataStatus}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold ${
                isStale
                  ? 'border-[color-mix(in_srgb,var(--app-warning)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] text-[var(--app-warning)]'
                  : 'border-[color-mix(in_srgb,var(--app-success)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_10%,transparent)] text-[var(--app-success)]'
              }`}
              title={`${labels.staleReason}: ${staleReason}`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {quoteStatus === 'missing' ||
              marketHealth?.persistent_cache_status === 'missing'
                ? copy.market.providerActions.run_first_sync
                : isStale
                  ? copy.shell.cachedQuotes
                  : copy.shell.valuationMode}
            </span>
            <span className="app-muted min-w-0 text-xs">
              {labels.staleReason}: {staleReason}
            </span>
          </div>
        </div>

        <div
          className={
            compact
              ? 'flex min-w-0 flex-col gap-2'
              : 'flex min-w-0 flex-col gap-2 xl:items-end'
          }
          data-testid="overview-quick-actions"
        >
          <div className="app-product-mark">{labels.quickActions}</div>
          <div
            className={
              compact
                ? 'grid min-w-0 grid-cols-2 gap-2'
                : 'flex min-w-0 flex-wrap gap-2 xl:justify-end'
            }
          >
            <button
              type="button"
              className={`app-button-primary justify-center rounded-2xl px-4 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60 ${
                compact ? 'col-span-2' : ''
              }`}
              disabled={refreshQuotes.isPending}
              aria-busy={refreshQuotes.isPending}
              onClick={() => {
                void refreshQuotes.mutateAsync({
                  symbols: symbols.length > 0 ? symbols : undefined,
                  force: true,
                });
              }}
            >
              {refreshQuotes.isPending
                ? labels.refreshingQuotes
                : labels.refreshQuotes}
            </button>
            <a
              href="/activity"
              className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
            >
              {labels.addLedger}
            </a>
            <a
              href="/trading"
              className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
            >
              {labels.tradingDesk}
            </a>
            <a
              href="/market"
              className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
            >
              {labels.checkDataSource}
            </a>
            <a
              href="/settings"
              className="app-button-secondary justify-center rounded-2xl px-3 py-2 text-xs font-semibold"
            >
              {labels.dataSettings}
            </a>
          </div>
          <div className="app-muted min-h-4 text-xs" aria-live="polite">
            {refreshMessage}
          </div>
        </div>

        <div
          className={`grid min-w-0 gap-2 text-left ${
            compact ? 'sm:grid-cols-2' : 'sm:grid-cols-2 xl:grid-cols-5'
          }`}
        >
          {statusRows.slice(0, compact ? 4 : statusRows.length).map((row) => (
            <div
              key={row.label}
              className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2"
            >
              <div className="app-kicker text-[10px] tracking-[0.14em]">
                {row.label}
              </div>
              <div className="mt-1 break-words font-mono text-xs font-semibold text-[var(--app-soft)] tabular-nums">
                {row.value}
              </div>
            </div>
          ))}
        </div>

        {!compact && actionableDiagnostics.length > 0 ? (
          <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="app-product-mark">{labels.affectedHoldings}</div>
              <div className="app-muted text-xs">
                {labels.affectedCount(actionableDiagnostics.length)}
              </div>
            </div>
            <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2 2xl:grid-cols-3">
              {actionableDiagnostics.map((item) => {
                const displayName =
                  item.display_name ?? item.name ?? item.symbol;
                const quoteSource =
                  item.quote_source === 'eastmoney_fund_estimate'
                    ? labels.usingEstimate
                    : normalizeStatus(item.quote_source);
                return (
                  <div
                    key={`${item.symbol}-${item.quote_source ?? 'quote'}`}
                    className="min-w-0 rounded-2xl border border-[color-mix(in_srgb,var(--app-warning)_26%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2"
                  >
                    <div className="flex min-w-0 items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-[var(--app-soft)]">
                          {displayName}
                        </div>
                        <div className="mt-1 text-xs text-[var(--app-subtext-0)]">
                          {item.symbol} ·{' '}
                          {assetClassLabel(item.asset_class, copy)}
                        </div>
                      </div>
                      <span className="shrink-0 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_26%,transparent)] px-2 py-1 text-[10px] font-semibold text-[var(--app-warning)]">
                        {quoteSource}
                      </span>
                    </div>
                    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--app-subtext-0)]">
                      <span>
                        {diagnosticActionLabel(
                          item,
                          locale,
                          copy.common.staleReasons,
                        )}
                      </span>
                      {item.quote_timestamp ? (
                        <span className="font-mono tabular-nums">
                          {formatTimestamp(item.quote_timestamp)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
        {marketHealth?.last_refresh_attempt ||
        marketHealth?.last_refresh_error ? (
          <div className="app-muted mt-3 text-xs">
            {labels.refreshQuotes}:{' '}
            {formatTimestamp(marketHealth.last_refresh_attempt)}
            {marketHealth.last_refresh_error
              ? ` · ${formatStaleReason(
                  marketHealth.last_refresh_error,
                  copy.common.staleReasons,
                )}`
              : ''}
          </div>
        ) : null}
      </div>
    </section>
  );
}
