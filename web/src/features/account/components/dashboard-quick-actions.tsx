import { useCopy } from '../../../app/copy';
import { formatDateTime, formatTimestamp } from '../../../shared/format';
import type { AccountOverview } from '../api';
import {
  useRefreshMarketQuotesMutation,
  type MarketDataHealthResponse,
} from '../../market/api';

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

export function DashboardQuickActions({
  overview,
  marketHealth,
  symbols,
}: {
  overview: AccountOverview;
  marketHealth?: MarketDataHealthResponse;
  symbols: string[];
}) {
  const copy = useCopy();
  const labels = copy.overview.dashboard;
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const quoteStatus = overview.quote_status ?? 'unknown';
  const isDemoSource =
    marketHealth?.source_health === 'demo' ||
    marketHealth?.provider_name === 'demo';
  const isStale =
    quoteStatus === 'stale' ||
    marketHealth?.source_health === 'stale' ||
    marketHealth?.source_health === 'degraded';
  const refreshMessage = refreshQuotes.isPending
    ? labels.refreshingQuotes
    : refreshQuotes.isError
      ? labels.refreshFailed
      : refreshQuotes.isSuccess
        ? labels.refreshDone
        : '';

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
      value: normalizeStatus(
        overview.refresh_policy ?? marketHealth?.refresh_policy,
      ),
    },
    {
      label: labels.quoteSource,
      value: isDemoSource
        ? copy.market.demoQuotes
        : normalizeStatus(marketHealth?.provider_name),
    },
    {
      label: copy.market.providerNextAction,
      value: normalizeStatus(
        marketHealth?.next_action &&
          marketHealth.next_action in copy.market.providerActions
          ? copy.market.providerActions[
              marketHealth.next_action as keyof typeof copy.market.providerActions
            ]
          : marketHealth?.next_action,
      ),
    },
  ];
  const staleReason = normalizeStatus(
    overview.stale_reason ??
      marketHealth?.provider_last_error ??
      marketHealth?.last_refresh_error,
  );

  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="app-panel rounded-[1.75rem] p-4 sm:p-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
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
                {isDemoSource
                  ? copy.market.demoQuotes
                  : isStale
                    ? copy.shell.cachedQuotes
                    : copy.shell.valuationMode}
              </span>
              <span className="app-muted text-xs">
                {labels.staleReason}: {staleReason}
              </span>
            </div>
          </div>
          <div className="grid gap-2 text-left sm:grid-cols-2 xl:min-w-[26rem]">
            {statusRows.map((row) => (
              <div
                key={row.label}
                className="rounded-2xl border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2"
              >
                <div className="app-kicker text-[10px] tracking-[0.14em]">
                  {row.label}
                </div>
                <div className="mt-1 font-mono text-xs font-semibold text-[var(--app-soft)] tabular-nums">
                  {row.value}
                </div>
              </div>
            ))}
          </div>
        </div>
        {marketHealth?.last_refresh_attempt ||
        marketHealth?.last_refresh_error ? (
          <div className="app-muted mt-3 text-xs">
            {labels.refreshQuotes}:{' '}
            {formatTimestamp(marketHealth.last_refresh_attempt)}
            {marketHealth.last_refresh_error
              ? ` · ${marketHealth.last_refresh_error}`
              : ''}
          </div>
        ) : null}
      </div>

      <div className="app-panel rounded-[1.75rem] p-4 sm:p-5 lg:min-w-[18rem]">
        <div className="app-product-mark">{labels.quickActions}</div>
        <div className="mt-3 grid gap-2">
          <button
            type="button"
            className="app-button-primary justify-center rounded-2xl px-4 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
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
          <div className="grid grid-cols-2 gap-2">
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
        </div>
        <div className="app-muted mt-3 min-h-4 text-xs" aria-live="polite">
          {refreshMessage}
        </div>
      </div>
    </section>
  );
}
