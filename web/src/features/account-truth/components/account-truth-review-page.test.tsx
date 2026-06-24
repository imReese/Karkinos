import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/preferences';
import { AccountTruthReviewPage } from './account-truth-review-page';

type RenderOptions = {
  locale?: 'en' | 'zh';
};

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
    tax_difference: '2.50',
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
      display_name: '合成样例股票A',
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
  renderOptions: RenderOptions = {},
) {
  window.localStorage.clear();
  if (renderOptions.locale) {
    window.localStorage.setItem('karkinos.locale', renderOptions.locale);
  }
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
  expect(
    await screen.findByText(
      'Cash difference CN¥120.00 · Fee difference CN¥0.00 · Tax difference CN¥2.50',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('Cash difference 120.00')).toBeNull();
  expect(screen.queryByText('Tax difference 2.50')).toBeNull();
  expect(screen.queryByText(/cash Δ/)).toBeNull();
  expect(screen.queryByText(/fee Δ/)).toBeNull();
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
  expect(within(item).getByText('合成样例股票A SYN001')).toBeTruthy();
  expect(within(item).getByText('Position')).toBeTruthy();
  expect(within(item).queryByText('position')).toBeNull();
  expect(within(item).getByText('Broker 100 shares')).toBeTruthy();
  expect(within(item).getByText('Karkinos 0 shares')).toBeTruthy();
  expect(within(item).getByText('Difference 100 shares')).toBeTruthy();
  expect(
    within(item).getByText(
      'Broker evidence · 合成样例股票A SYN001 · Position snapshot · import-run-1',
    ),
  ).toBeTruthy();
  expect(item.textContent).not.toContain(
    'broker_event:import-run-1:SYN001:position_snapshot',
  );

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
    await screen.findByText('Review saved: Known difference'),
  ).toBeTruthy();
  expect(screen.queryByText('Review saved: known_difference')).toBeNull();
});

test('localizes generated reconciliation detail copy in Chinese locale', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            detail_code: 'account_truth.position_quantity_compared',
            detail: 'Raw backend detail should not be visible.',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-position:SYN001');

  expect(
    within(item).getByText('券商持仓数量已与 Karkinos 本地持仓数量对比。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Raw backend detail');
});

test('localizes reconciliation detail codes that are review actions', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'fee:SYN001',
            category: 'fee',
            detail_code: 'review_fee_difference',
            detail: 'Raw review action detail should not be visible.',
            suggested_review_action: 'review_fee_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-fee:SYN001');

  expect(within(item).getAllByText('复核费用差异').length).toBeGreaterThan(0);
  expect(item.textContent).not.toContain('review_fee_difference');
  expect(item.textContent).not.toContain('Raw review action detail');
  expect(item.textContent).not.toContain('复核备注');
});

test('formats reconciliation report summary differences as money in Chinese locale', async () => {
  renderAccountTruthReviewPage(undefined, { locale: 'zh' });

  expect(
    await screen.findByText(
      '现金差异 ¥120.00 · 费用差异 ¥0.00 · 税费差异 ¥2.50',
    ),
  ).toBeTruthy();
  expect(screen.queryByText('现金差异 120.00')).toBeNull();
  expect(screen.queryByText('税费差异 2.50')).toBeNull();
  expect(screen.queryByText(/cash Δ/)).toBeNull();
  expect(screen.queryByText(/fee Δ/)).toBeNull();
});

test('formats reconciliation values with category-aware units in Chinese locale', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
          },
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            broker_value: '8.8',
            karkinos_value: '8.7',
            difference: '0.1',
            detail_code: 'account_truth.cost_basis_compared',
            detail: 'Broker cost basis does not match local ledger.',
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const positionItem = await screen.findByTestId(
    'account-truth-item-position:SYN001',
  );
  expect(within(positionItem).getByText('券商 100 股')).toBeTruthy();
  expect(within(positionItem).getByText('Karkinos 0 股')).toBeTruthy();
  expect(within(positionItem).getByText('差异 100 股')).toBeTruthy();

  const costBasisItem = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );
  expect(within(costBasisItem).getByText('券商 ¥8.8000')).toBeTruthy();
  expect(within(costBasisItem).getByText('Karkinos ¥8.7000')).toBeTruthy();
  expect(within(costBasisItem).getByText('差异 ¥0.1000')).toBeTruthy();
  expect(within(costBasisItem).queryByText('券商 8.8')).toBeNull();
  expect(within(costBasisItem).queryByText('差异 0.1')).toBeNull();
});

test('localizes known reconciliation detail text when detail_code is missing', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            broker_value: '8.8',
            karkinos_value: '8.7',
            difference: '0.1',
            detail_code: null,
            detail: 'Broker cost basis does not match local ledger.',
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );

  expect(
    within(item).getByText('券商成本价与 Karkinos 本地账本不一致。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain(
    'Broker cost basis does not match local ledger.',
  );
});

test('localizes latest review notes without showing backend operational text', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            latest_review: {
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
            },
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId('account-truth-item-position:SYN001');

  expect(within(item).getByText('最近复核: 已知差异')).toBeTruthy();
  expect(
    within(item).getByText('已从账户事实复核中心记录人工处理。'),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Reviewed from Account Truth center.');
});

test('renders structured reconciliation detail context without raw codes', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'cost_basis:SYN001',
            category: 'cost_basis',
            detail_code: 'account_truth.cost_basis_compared',
            detail: 'Broker cost-basis method: broker_remaining_cost.',
            detail_context: {
              cost_basis_method: 'broker_remaining_cost',
            },
            suggested_review_action: 'review_cost_basis_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const item = await screen.findByTestId(
    'account-truth-item-cost_basis:SYN001',
  );

  expect(within(item).getByText('成本口径')).toBeTruthy();
  expect(within(item).getByText('券商剩余持仓成本')).toBeTruthy();
  expect(within(item).getByText('复核成本价差异')).toBeTruthy();
  expect(item.textContent).not.toContain('broker_remaining_cost');
  expect(item.textContent).not.toContain('Broker cost-basis method');
  expect(item.textContent).not.toContain('未映射原因');
});

test('formats broker trade evidence references through shared ledger labels', async () => {
  renderAccountTruthReviewPage({
    reportDetailResponse: {
      ...reportDetail,
      items: [
        {
          ...reportDetail.items[0],
          item_key: 'trade:SYN001',
          category: 'trade_gross_amount',
          detail_code: 'account_truth.trade_gross_amount_compared',
          evidence_references: ['broker_event:import-run-1:SYN001:trade_buy'],
          suggested_review_action: 'review_trade_gross_amount_difference',
        },
      ],
    },
  });

  const item = await screen.findByTestId('account-truth-item-trade:SYN001');

  expect(
    within(item).getByText(
      'Broker evidence · 合成样例股票A SYN001 · Buy · import-run-1',
    ),
  ).toBeTruthy();
  expect(item.textContent).not.toContain('Buy trade');
  expect(item.textContent).not.toContain('trade_buy');
});

test('uses specific localized labels for cash-impact reconciliation categories', async () => {
  renderAccountTruthReviewPage(
    {
      reportDetailResponse: {
        ...reportDetail,
        items: [
          {
            ...reportDetail.items[0],
            item_key: 'net_cash_impact:SYN001',
            category: 'net_cash_impact',
            broker_value: '-1028.00',
            karkinos_value: '-1023.00',
            difference: '-5.00',
            detail_code: 'account_truth.net_cash_impact_compared',
            suggested_review_action: 'review_net_cash_impact_difference',
          },
          {
            ...reportDetail.items[0],
            item_key: 'transfer_fee:SYN001',
            category: 'transfer_fee',
            broker_value: '0.60',
            karkinos_value: '0.00',
            difference: '0.60',
            detail_code: 'account_truth.transfer_fee_compared',
            suggested_review_action: 'review_transfer_fee_difference',
          },
        ],
      },
    },
    { locale: 'zh' },
  );

  const netCashItem = await screen.findByTestId(
    'account-truth-item-net_cash_impact:SYN001',
  );
  expect(within(netCashItem).getByText('净现金影响')).toBeTruthy();
  expect(within(netCashItem).getByText('券商 -¥1,028.00')).toBeTruthy();
  expect(netCashItem.textContent).not.toContain('net_cash_impact');
  expect(netCashItem.textContent).not.toContain('待人工复核项');

  const transferFeeItem = await screen.findByTestId(
    'account-truth-item-transfer_fee:SYN001',
  );
  expect(within(transferFeeItem).getByText('过户费')).toBeTruthy();
  expect(within(transferFeeItem).getByText('差异 ¥0.60')).toBeTruthy();
  expect(transferFeeItem.textContent).not.toContain('transfer_fee');
  expect(transferFeeItem.textContent).not.toContain('待人工复核项');
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
