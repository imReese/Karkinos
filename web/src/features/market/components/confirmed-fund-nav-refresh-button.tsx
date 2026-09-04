import { useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import {
  useRefreshConfirmedFundNavMutation,
  type ConfirmedFundNavRefreshResponse,
} from '../api';

type ConfirmedFundNavRefreshButtonProps = {
  symbols: string[];
  compact?: boolean;
};

function shortRunId(runId: string) {
  return runId.length > 26 ? `${runId.slice(0, 16)}…${runId.slice(-8)}` : runId;
}

export function ConfirmedFundNavRefreshButton({
  symbols,
  compact = false,
}: ConfirmedFundNavRefreshButtonProps) {
  const copy = useCopy();
  const refreshNav = useRefreshConfirmedFundNavMutation();
  const [lastResponse, setLastResponse] =
    useState<ConfirmedFundNavRefreshResponse | null>(null);

  const failedCount = lastResponse
    ? Object.keys(lastResponse.failed_symbols).length
    : 0;
  const summary = !lastResponse
    ? ''
    : lastResponse.status === 'success'
      ? copy.market.confirmedFundNavRefreshComplete(
          lastResponse.refreshed_symbols.length,
        )
      : lastResponse.status === 'partial' ||
          lastResponse.status === 'partial_success'
        ? copy.market.confirmedFundNavRefreshPartial(
            lastResponse.refreshed_symbols.length,
            failedCount,
          )
        : lastResponse.status === 'running'
          ? copy.market.confirmedFundNavRefreshInProgress
          : copy.market.confirmedFundNavRefreshUnavailable;
  const errorMessage =
    refreshNav.error instanceof Error
      ? refreshNav.error.message
      : copy.market.confirmedFundNavRefreshFailed;

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
        className="app-button-secondary app-control-compact app-type-micro h-10 px-2.5 font-semibold disabled:cursor-not-allowed disabled:opacity-60 sm:h-8"
        disabled={refreshNav.isPending || symbols.length === 0}
        aria-busy={refreshNav.isPending}
        onClick={async () => {
          try {
            const response = await refreshNav.mutateAsync({
              symbols,
              request_id: globalThis.crypto.randomUUID(),
            });
            setLastResponse(response);
          } catch {
            setLastResponse(null);
          }
        }}
      >
        {refreshNav.isPending
          ? copy.market.refreshingConfirmedFundNav
          : copy.market.refreshConfirmedFundNav}
      </button>
      <div
        className={`app-muted max-w-[20rem] text-xs ${compact ? 'text-left' : ''}`}
        aria-live="polite"
        aria-atomic="true"
      >
        {refreshNav.isPending
          ? copy.market.refreshingConfirmedFundNav
          : refreshNav.isError
            ? `${copy.market.confirmedFundNavRefreshFailed}: ${errorMessage}`
            : summary}
      </div>
      {lastResponse ? (
        <div
          className={`grid max-w-[20rem] gap-1 text-[length:var(--app-font-size-micro)] text-[var(--app-muted)] ${compact ? 'text-left' : 'text-right'}`}
        >
          {lastResponse.idempotent_replay ? (
            <span>{copy.market.confirmedFundNavIdempotentReplay}</span>
          ) : null}
          <span
            className="truncate font-mono tabular-nums"
            title={lastResponse.run.run_id}
          >
            {copy.market.confirmedFundNavAuditRun}:{' '}
            {shortRunId(lastResponse.run.run_id)}
          </span>
        </div>
      ) : null}
    </div>
  );
}
