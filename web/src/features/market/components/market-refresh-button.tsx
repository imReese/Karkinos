import { useState } from 'react';

import { useCopy } from '../../../app/copy';
import {
  useRefreshMarketQuotesMutation,
  type MarketQuoteRefreshResponse,
} from '../api';

type MarketRefreshButtonProps = {
  symbols?: string[];
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
  onComplete,
  onError,
}: MarketRefreshButtonProps) {
  const copy = useCopy();
  const refreshQuotes = useRefreshMarketQuotesMutation();
  const [lastResponse, setLastResponse] =
    useState<MarketQuoteRefreshResponse | null>(null);

  const summary = getRefreshSummary(copy, lastResponse);
  const errorMessage =
    refreshQuotes.error instanceof Error
      ? refreshQuotes.error.message
      : copy.market.quoteRefreshFailed;

  return (
    <div className="grid justify-items-end gap-2 text-right">
      <button
        type="button"
        className="app-button-secondary rounded-2xl px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-60"
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
        {refreshQuotes.isPending
          ? copy.market.refreshingQuotes
          : copy.market.refreshQuotes}
      </button>
      <div
        className="app-muted max-w-[18rem] text-xs"
        aria-live="polite"
        aria-atomic="true"
      >
        {refreshQuotes.isPending
          ? copy.market.refreshingQuotes
          : refreshQuotes.isError
            ? `${copy.market.quoteRefreshFailed}: ${errorMessage}`
            : summary}
      </div>
    </div>
  );
}
