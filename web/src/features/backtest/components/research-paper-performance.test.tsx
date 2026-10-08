import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import type { ResearchPaperBook } from '../paper-book-contracts';
import { PreferencesContext } from '../../../shared/preferences/context';
import { ResearchPaperPerformance } from './research-paper-performance';

test('shows recorded net returns, aligned benchmark, model limits and the health action without calculating returns again', () => {
  const book = {
    performance: {
      status: 'measured',
      evaluation_start: '2026-09-21',
      through_session: '2026-09-23',
      sessions_since_first_accepted_target: 2,
      net_return: '-0.012',
      max_drawdown: '0.025',
      benchmark_net_return: '-0.005',
      modeled_net_excess_return: '-0.007',
      fees_paid: '12',
      slippage_cost: '25',
      cash_weight: '0.25',
      return_basis: 'price_only',
      pnl_reconciliation_residual: '0',
      position_contributions: [
        {
          symbol: '518880',
          net_pnl: '-1200',
          return_contribution: '-0.012',
          distribution_income: '0',
        },
      ],
      equity_series: [
        { session: null, net_return: '0', benchmark_net_return: '0' },
        {
          session: '2026-09-23',
          net_return: '-0.012',
          benchmark_net_return: '-0.005',
        },
      ],
    },
    health: {
      status: 'threshold_breached',
      action: 'pause_paper_target_acceptance',
      breaches: ['minimum_net_excess_return'],
    },
  } as ResearchPaperBook;
  render(
    <PreferencesContext.Provider
      value={{
        locale: 'en',
        setLocale: () => {},
        theme: 'light',
        setTheme: () => {},
        resolvedTheme: 'light',
      }}
    >
      <ResearchPaperPerformance book={book} />
    </PreferencesContext.Provider>,
  );
  expect(screen.getAllByText('-1.2%')[0]).toBeVisible();
  expect(screen.getByText('-0.7%')).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent(
    'New target intake stopped',
  );
  expect(screen.getByText(/ETF distributions are unverified/)).toBeVisible();
  expect(screen.getByText(/costs below are not deducted again/)).toBeVisible();
  fireEvent.click(screen.getByText('Daily comparison data'));
  expect(screen.getByText('Initial cash')).toBeVisible();
  fireEvent.click(screen.getByText('Position P&L contributions'));
  expect(screen.getByText('518880')).toBeVisible();
  expect(
    screen.getByText(/not causal factor or alpha attribution/),
  ).toBeVisible();
});
