import { LoaderCircle } from 'lucide-react';
import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStaleReason } from '../../../shared/stale-reason';
import {
  useRefreshMarketQuotesMutation,
  type MarketQuoteRefreshResponse,
} from '../api';

type MarketRefreshButtonProps = {
  symbols?: string[];
  compact?: boolean;
  onComplete?: (response: MarketQuoteRefreshResponse) => void;
  onError?: (error: Error) => void;
};

function getRefreshSummary(
  copy: ReturnType<typeof useCopy>,
  response: MarketQuoteRefreshResponse | null,
) {
  if (!response) {
    return '';
  }
  if (response.quote_status === 'live') {
    return copy.market.quoteRefreshComplete;
  }
  if (response.quote_status === 'partial') {
    return copy.market.quoteRefreshPartial;
  }
  if (response.quote_status === 'stale') {
    return copy.market.quoteRefreshStale;
  }
  return copy.market.quoteRefreshFailed;
}

export function MarketRefreshButton({
  symbols,
  compact = false,
  onComplete,
  onError,
}: MarketRefreshButtonProps) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const [lastResponse, setLastResponse] =
    useState<MarketQuoteRefreshResponse | null>(null);

  const summary = getRefreshSummary(copy, lastResponse);
  const errorMessage =
    refreshQuotes.error instanceof Error
      ? refreshQuotes.error.message
      : copy.market.quoteRefreshFailed;

  return (
    <div
      className={
        compact
          ? 'inline-grid justify-items-start gap-1 text-left'
          : 'grid justify-items-end gap-2 text-right'
      }
    >
      <button
        type="button"
        className="app-button-secondary app-control-compact app-type-micro inline-flex h-10 items-center justify-center gap-1.5 px-2.5 font-semibold disabled:cursor-not-allowed disabled:opacity-60 sm:h-8"
        disabled={refreshQuotes.isPending}
        aria-busy={refreshQuotes.isPending}
        onClick={async () => {
          try {
            const response = await refreshQuotes.mutateAsync({
              symbols,
              force: true,
            });
            setLastResponse(response);
            onComplete?.(response);
          } catch (error) {
            const normalized =
              error instanceof Error
                ? error
                : new Error(copy.market.quoteRefreshFailed);
            onError?.(normalized);
          }
        }}
      >
        {refreshQuotes.isPending ? (
          <>
            <LoaderCircle
              className="h-3.5 w-3.5 shrink-0 animate-spin"
              aria-hidden="true"
              data-testid="market-refresh-spinner"
            />
            <span>{copy.market.refreshingQuotes}</span>
          </>
        ) : (
          copy.market.refreshQuotes
        )}
      </button>
      <div
        className={`app-muted max-w-[18rem] text-xs ${compact ? 'text-left' : ''}`}
        aria-live="polite"
        aria-atomic="true"
      >
        {refreshQuotes.isPending
          ? copy.market.refreshingQuotes
          : refreshQuotes.isError
            ? `${copy.market.quoteRefreshFailed}: ${errorMessage}`
            : summary}
      </div>
      {lastResponse && !compact ? (
        <div className="grid max-w-[22rem] gap-1 text-left text-xs">
          {[
            ...lastResponse.refreshed,
            ...lastResponse.skipped,
            ...lastResponse.failed,
          ]
            .slice(0, 5)
            .map((item) => {
              const statusLabel = formatPublicStatus(item.status, locale);
              const reasonLabel = formatStaleReason(
                item.reason,
                copy.common.staleReasons,
              );
              return (
                <div
                  key={`${item.symbol}-${item.status}`}
                  className="rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_24%,transparent)] px-3 py-2 text-[var(--app-muted)]"
                >
                  <span className="font-mono font-semibold text-[var(--app-text)]">
                    {item.symbol}
                  </span>{' '}
                  {statusLabel}
                  {item.reason ? ` · ${reasonLabel}` : ''}
                </div>
              );
            })}
        </div>
      ) : null}
    </div>
  );
}
