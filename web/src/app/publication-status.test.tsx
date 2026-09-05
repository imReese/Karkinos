import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { copy } from './copy';

import { apiClient } from '../shared/api/client';
import { sharedCopy } from '../shared/i18n/catalog';
import { CopyContext } from '../shared/i18n/context';
import { PublicationStatus } from '../shared/portfolio-evidence/publication-status';

vi.mock('../shared/api/client', () => ({ apiClient: vi.fn() }));
afterEach(() => vi.resetAllMocks());

function show(data: unknown, language: 'en' | 'zh' = 'en') {
  if (data instanceof Error) vi.mocked(apiClient).mockRejectedValue(data);
  else vi.mocked(apiClient).mockResolvedValue(data);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CopyContext.Provider value={copy[language]}>
        <PublicationStatus
          snapshotId="last-good"
          asOf="2026-09-04T15:00:00+08:00"
        />
      </CopyContext.Provider>
    </QueryClientProvider>,
  );
  return client;
}

function evidence(snapshot = 'last-good', status = 'degraded') {
  return {
    valuation_snapshot_id: snapshot,
    subsystems: {
      valuation_read: {
        status,
        latest_attempt: {
          status: 'failed',
          updated_at: '2026-09-04T15:02:00+08:00',
        },
        blockers: ['refresh_failed'],
      },
    },
  };
}

test.each(['en', 'zh'] as const)(
  'explains a failed publication in %s while preserving its as_of',
  async (language) => {
    show(evidence(), language);
    expect(
      await screen.findByText(sharedCopy[language].common.publicationFailed),
    ).not.toBeNull();
    expect(screen.getByRole('status').textContent).toContain('09/04, 15:00');
    expect(screen.getByRole('status').textContent).toContain(
      sharedCopy[language].common.publicationAttempt,
    );
  },
);

test('does not attach readiness for a different snapshot to the displayed valuation', async () => {
  const client = show(evidence('new-snapshot', 'ready'));
  await waitFor(() =>
    expect(client.getQueryState(['system-readiness'])?.status).toBe('success'),
  );
  expect(screen.getByRole('status').textContent).toContain(
    sharedCopy.en.common.publicationChecking,
  );
});

test('removes degradation only when the displayed snapshot is verified ready', async () => {
  show(evidence('last-good', 'ready'));
  await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
});

test('shows unavailable status when the readiness request fails', async () => {
  show(new Error('offline'));
  expect(
    await screen.findByText(sharedCopy.en.common.publicationUnavailable),
  ).not.toBeNull();
});
