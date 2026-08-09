export const PERSISTED_PROJECTION_REFETCH_MS = 30_000;

export function visiblePersistedProjectionRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return PERSISTED_PROJECTION_REFETCH_MS;
}
