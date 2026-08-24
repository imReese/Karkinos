const OPERATIONS_REFETCH_MS = 15_000;

export function liveOperationsRefetchInterval() {
  if (
    typeof document !== 'undefined' &&
    document.visibilityState !== 'visible'
  ) {
    return false;
  }
  return OPERATIONS_REFETCH_MS;
}
