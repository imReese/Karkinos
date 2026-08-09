import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  PERSISTED_PROJECTION_REFETCH_MS,
  visiblePersistedProjectionRefetchInterval,
} from './query-policy';

describe('persisted projection query policy', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses a deliberate cadence while the workbench is visible', () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');

    expect(visiblePersistedProjectionRefetchInterval()).toBe(30_000);
    expect(PERSISTED_PROJECTION_REFETCH_MS).toBe(30_000);
  });

  it('stops background polling when the workbench is hidden', () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');

    expect(visiblePersistedProjectionRefetchInterval()).toBe(false);
  });
});
