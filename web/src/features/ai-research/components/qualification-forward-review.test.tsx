import '@testing-library/jest-dom/vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { PreferencesContext } from '../../../shared/preferences/context';
import { QualificationForwardReview } from './qualification-forward-review';

afterEach(() => vi.unstubAllGlobals());

test('human review can bind only the exact settled source book and a refresh clears its previous version', async () => {
  let version = 2;
  const select = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (input: RequestInfo | URL) =>
        new Response(
          JSON.stringify(
            String(input).includes('paper-book')
              ? {
                  id: 'book-1',
                  observation_id: 'observation-1',
                  version,
                  performance: {
                    input_version: version,
                    outcome_fingerprint: 'a'.repeat(64),
                    status: 'measured',
                    through_session: '2026-09-23',
                    evaluation_start: '2026-09-21',
                    sessions_since_first_accepted_target: 2,
                    net_return: '0.01',
                    benchmark_net_return: '0.005',
                    modeled_net_excess_return: '0.005',
                    max_drawdown: '0.01',
                    cash_weight: '0.2',
                    fees_paid: '10',
                    slippage_cost: '20',
                    pnl_reconciliation_residual: '0',
                    return_basis: 'price_only',
                    equity_series: [],
                    position_contributions: [],
                  },
                }
              : [
                  {
                    id: 'observation-1',
                    source_backtest_result_id: 7,
                    started_at: '2026-09-18',
                  },
                  {
                    id: 'wrong-source',
                    source_backtest_result_id: 8,
                    started_at: '2026-09-18',
                  },
                ],
          ),
        ),
    ),
  );
  render(
    <QueryClientProvider client={client}>
      <PreferencesContext.Provider
        value={{
          locale: 'en',
          setLocale: () => {},
          theme: 'light',
          setTheme: () => {},
          resolvedTheme: 'light',
        }}
      >
        <QualificationForwardReview
          sourceResultId={7}
          binding={null}
          onSelect={select}
          disabled={false}
        />
      </PreferencesContext.Provider>
    </QueryClientProvider>,
  );
  fireEvent.click(
    screen.getByText('Attach a reviewed forward paper interval (optional)'),
  );
  const choices = screen.getByLabelText('Forward observation for this source');
  await waitFor(() =>
    expect(
      choices.querySelector('option[value="observation-1"]'),
    ).not.toBeNull(),
  );
  expect(choices.querySelector('option[value="wrong-source"]')).toBeNull();
  fireEvent.change(choices, { target: { value: 'observation-1' } });
  fireEvent.click(await screen.findByRole('checkbox'));
  expect(select).toHaveBeenLastCalledWith({
    observation_id: 'observation-1',
    book_id: 'book-1',
    input_version: 2,
    outcome_fingerprint: 'a'.repeat(64),
    evaluation_start: '2026-09-21',
    through_session: '2026-09-23',
  });
  version = 3;
  await client.invalidateQueries({
    queryKey: ['research-paper-book', 'observation-1'],
  });
  await waitFor(() => expect(select).toHaveBeenLastCalledWith(null));
});
