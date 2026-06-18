import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { AccountTruthReviewPage } from './account-truth-review-page';

const score = {
  schema_version: 'karkinos.account_truth.score.v1',
  status: 'available',
  import_run_id: 'import-run-1',
  score: 42,
  gate_status: 'blocked',
  cash_status: 'mismatch',
  position_status: 'mismatch',
  fee_status: 'pass',
  cost_basis_status: 'mismatch',
  data_freshness_status: 'fresh',
  unresolved_mismatch_count: 2,
  resolved_review_count: 1,
  required_actions: ['review_position_difference'],
  blocking_reasons: ['unresolved_position_difference'],
  limitations: ['Unresolved reconciliation items require review.'],
};

const importRuns = [
  {
    import_run_id: 'import-run-1',
    schema_version: 'karkinos.broker_evidence.import_run.v1',
    source_type: 'canonical_broker_statement_csv',
    source_name: 'synthetic-safe-example.csv',
    file_fingerprint: 'sha256-safe',
    row_count: 3,
    valid_row_count: 3,
    invalid_row_count: 0,
    row_duplicate_count: 0,
    file_duplicate_count: 0,
    validation_status: 'pass',
    limitations: ['safe synthetic fixture'],
    duplicate_of_import_run_id: null,
    created_at: '2026-06-18T10:10:00+08:00',
  },
];

const reportSummaries = [
  {
    import_run_id: 'import-run-1',
    schema_version: 'karkinos.account_truth.reconciliation.v1',
    status: 'mismatch',
    row_count: 3,
    validation_status: 'pass',
    source_type: 'canonical_broker_statement_csv',
    source_name: 'synthetic-safe-example.csv',
    created_at: '2026-06-18T10:10:00+08:00',
    unresolved_count: 2,
    cash_difference: '120.00',
    fee_difference: '0.00',
    tax_difference: '0.00',
    suggested_review_actions: ['review_position_difference'],
    limitations: ['safe synthetic fixture'],
  },
];

const reportDetail = {
  ...reportSummaries[0],
  items: [
    {
      item_key: 'position:SYN001',
      category: 'position',
      status: 'mismatch',
      severity: 'mismatch',
      symbol: 'SYN001',
      broker_value: '100',
      karkinos_value: '0',
      difference: '100',
      suggested_review_action: 'review_position_difference',
      detail: 'Broker position does not match local ledger projection.',
      evidence_references: [
        'broker_event:import-run-1:SYN001:position_snapshot',
      ],
      latest_review: null,
    },
  ],
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installFetchMock({
  scoreResponse = score,
  importRunResponse = importRuns,
  reportSummaryResponse = reportSummaries,
  reportDetailResponse = reportDetail,
}: {
  scoreResponse?: unknown;
  importRunResponse?: unknown;
  reportSummaryResponse?: unknown;
  reportDetailResponse?: unknown;
} = {}) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === 'string'
          ? input
          : input instanceof Request
            ? input.url
            : input.toString();
      if (url.includes('/api/account-truth/score')) {
        return jsonResponse(scoreResponse);
      }
      if (url.includes('/api/account-truth/import-runs')) {
        return jsonResponse(importRunResponse);
      }
      if (
        url.includes(
          '/api/account-truth/reconciliation-reports/import-run-1',
        ) &&
        init?.method !== 'POST'
      ) {
        return jsonResponse(reportDetailResponse);
      }
      if (
        url.includes('/api/account-truth/reconciliation-reports') &&
        init?.method !== 'POST'
      ) {
        return jsonResponse(reportSummaryResponse);
      }
      if (url.includes('/items/position%3ASYN001/review')) {
        return jsonResponse({
          id: 7,
          import_run_id: 'import-run-1',
          item_key: 'position:SYN001',
          category: 'position',
          symbol: 'SYN001',
          review_status: 'known_difference',
          note: 'Reviewed from Account Truth center.',
          reviewer: 'local',
          schema_version: 'karkinos.account_truth.manual_review.v1',
          created_at: '2026-06-18T10:12:00+08:00',
          updated_at: '2026-06-18T10:12:00+08:00',
          does_not_mutate_production_ledger: true,
        });
      }
      return new Response('Not found', { status: 404 });
    },
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderAccountTruthReviewPage(
  fetchOptions?: Parameters<typeof installFetchMock>[0],
) {
  window.localStorage.clear();
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-color-scheme: dark'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const fetchMock = installFetchMock(fetchOptions);
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <PreferencesProvider>
      <QueryClientProvider client={queryClient}>
        <AccountTruthReviewPage />
      </QueryClientProvider>
    </PreferencesProvider>,
  );

  return { fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('renders Account Truth score, import runs, reconciliation detail, and review actions', async () => {
  const { fetchMock } = renderAccountTruthReviewPage();

  expect(await screen.findByText('Account Truth Review Center')).toBeTruthy();
  expect(await screen.findByText('42')).toBeTruthy();
  await waitFor(() =>
    expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0),
  );
  expect(await screen.findByText('Cash: Mismatch')).toBeTruthy();
  expect(await screen.findByText('Cost basis: Mismatch')).toBeTruthy();
  expect(
    (await screen.findAllByText('Review position difference')).length,
  ).toBeGreaterThan(0);
  await waitFor(() =>
    expect(
      screen.getAllByText('synthetic-safe-example.csv').length,
    ).toBeGreaterThan(0),
  );
  expect(await screen.findByText('Rows 3 · duplicates 0')).toBeTruthy();

  await userEvent.click(screen.getByRole('button', { name: 'Mismatch' }));

  await waitFor(() => {
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('status=mismatch'),
      ),
    ).toBe(true);
  });

  const item = await screen.findByTestId('account-truth-item-position:SYN001');
  expect(within(item).getByText('SYN001')).toBeTruthy();
  expect(within(item).getByText('Broker 100')).toBeTruthy();
  expect(within(item).getByText('Karkinos 0')).toBeTruthy();
  expect(within(item).getByText('Difference 100')).toBeTruthy();
  expect(
    within(item).getByText(
      'broker_event:import-run-1:SYN001:position_snapshot',
    ),
  ).toBeTruthy();

  await userEvent.click(
    within(item).getByRole('button', { name: 'Known difference' }),
  );

  await waitFor(() => {
    const postCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).includes('/items/position%3ASYN001/review') &&
        init?.method === 'POST',
    );
    expect(postCall).toBeTruthy();
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
      category: 'position',
      symbol: 'SYN001',
      review_status: 'known_difference',
      reviewer: 'local',
    });
  });
  expect(
    await screen.findByText('Review saved: known_difference'),
  ).toBeTruthy();
});

test('explains the blocked empty state without exposing internal action codes', async () => {
  renderAccountTruthReviewPage({
    scoreResponse: {
      schema_version: 'karkinos.account_truth.score.v1',
      status: 'missing',
      import_run_id: null,
      score: null,
      gate_status: 'blocked',
      cash_status: 'missing',
      position_status: 'missing',
      fee_status: 'missing',
      cost_basis_status: 'missing',
      data_freshness_status: 'missing',
      unresolved_mismatch_count: null,
      resolved_review_count: 0,
      required_actions: ['import_and_reconcile_broker_evidence'],
      blocking_reasons: ['account_truth_score_unavailable'],
      limitations: [
        'Account Truth review requires staged broker evidence before trusted use.',
      ],
    },
    importRunResponse: [],
    reportSummaryResponse: [],
  });

  expect(await screen.findByText('Account facts are not ready')).toBeTruthy();
  expect(
    await screen.findByText(
      'No broker statement, position snapshot, or cash snapshot has been staged yet.',
    ),
  ).toBeTruthy();
  expect(await screen.findByText('Import broker evidence')).toBeTruthy();
  expect(
    await screen.findByText('Then return here to review differences'),
  ).toBeTruthy();
  expect(screen.queryByText('import_and_reconcile_broker_evidence')).toBeNull();
  expect(screen.queryByText('account_truth_score_unavailable')).toBeNull();
});
