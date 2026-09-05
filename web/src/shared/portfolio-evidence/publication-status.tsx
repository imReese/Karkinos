import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { visiblePersistedProjectionRefetchInterval } from '../api/query-policy';
import { formatTimestamp } from '../format';
import { useCopy } from '../i18n/context';

interface Readiness {
  valuation_snapshot_id: string | null;
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
  const description = query.isError
    ? copy.publicationUnavailable
    : !state || !sameSnapshot
      ? copy.publicationChecking
      : state.latest_attempt?.status === 'failed'
        ? copy.publicationFailed
        : copy.publicationDegraded;
  return (
    <aside
      role="status"
      className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm"
    >
      <p>
        {copy.valuationAsOf}: {formatTimestamp(asOf)}
      </p>
      <p>{description}</p>
      {sameSnapshot && state?.latest_attempt?.updated_at ? (
        <p>
          {copy.publicationAttempt}:{' '}
          {formatTimestamp(state.latest_attempt.updated_at)}
        </p>
      ) : null}
    </aside>
  );
}
