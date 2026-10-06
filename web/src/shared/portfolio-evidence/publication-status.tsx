import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { visiblePersistedProjectionRefetchInterval } from '../api/query-policy';
import { formatTimestamp } from '../format';
import { useCopy } from '../i18n/context';

interface Readiness {
  valuation_snapshot_id: string | null;
  market_session?: {
    status?: string;
    is_open?: boolean;
    latest_completed_trade_date?: string;
  };
  subsystems: {
    valuation_read: {
      status: string;
      as_of: string | null;
      latest_attempt: { status: string; updated_at?: string } | null;
      blockers: string[];
    };
  };
}

export function PublicationStatus({
  snapshotId,
  asOf,
}: {
  snapshotId?: string | null;
  asOf?: string | null;
}) {
  const { common: copy } = useCopy();
  const query = useQuery({
    queryKey: ['system-readiness'],
    queryFn: () => apiClient<Readiness>('/api/health/readiness'),
    enabled: Boolean(snapshotId),
    staleTime: 10_000,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
  });
  if (!snapshotId) return null;
  const state = query.data?.subsystems?.valuation_read;
  const sameSnapshot = query.data?.valuation_snapshot_id === snapshotId;
  if (sameSnapshot && state?.status === 'ready' && !query.isError) return null;

  const isClosedSession =
    query.data?.market_session?.is_open === false ||
    query.data?.market_session?.status === 'non_trading_day' ||
    query.data?.market_session?.status === 'closed' ||
    query.data?.market_session?.status === 'holiday';

  const description = query.isError
    ? copy.publicationUnavailable
    : !state || !sameSnapshot
      ? copy.publicationChecking
      : isClosedSession
        ? copy.publicationMarketClosed
        : state.latest_attempt?.status === 'failed'
          ? copy.publicationFailed
          : copy.publicationDegraded;

  const containerClasses = isClosedSession
    ? 'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[color-mix(in_srgb,var(--app-surface-raised)_75%,transparent)] px-3 py-2 text-xs text-[var(--app-text)]'
    : 'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-warning-indicator)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-warning-indicator)_8%,transparent)] px-3 py-2 text-xs text-[var(--app-text)]';

  return (
    <aside role="status" className={containerClasses}>
      <p className="font-medium">
        {copy.valuationAsOf}:{' '}
        <span className="font-mono">{formatTimestamp(asOf)}</span>
      </p>
      {isClosedSession ? (
        <span
          data-testid="market-closed-valuation-badge"
          className="inline-flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] px-1.5 py-0.5 text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-text-tertiary)]"
        >
          <span className="inline-block size-1.5 rounded-full bg-[var(--app-text-tertiary)] opacity-60" />
          {copy.staleReasons?.marketClosedCacheOnly ? '休市' : 'Closed'}
        </span>
      ) : null}
      <p className="text-[var(--app-text-secondary)]">{description}</p>
      {sameSnapshot && state?.latest_attempt?.updated_at && !isClosedSession ? (
        <p className="text-[var(--app-text-tertiary)]">
          {copy.publicationAttempt}:{' '}
          <span className="font-mono">
            {formatTimestamp(state.latest_attempt.updated_at)}
          </span>
        </p>
      ) : null}
    </aside>
  );
}
