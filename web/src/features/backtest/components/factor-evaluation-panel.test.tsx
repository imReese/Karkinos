import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { FactorEvaluationPanel } from './factor-evaluation-panel';

const evaluation = vi.hoisted(() => ({ mutate: vi.fn() }));

vi.mock('../factor-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../factor-api')>();
  return {
    ...actual,
    useUniversesQuery: () => ({
      data: [
        {
          universe_id: 'core_etf_universe',
          display_name: 'China Core Macro & Broad Index ETFs',
          description:
            'Broad equity indexes, style factors, gold, and treasury bond ETFs for macro rotation.',
          benchmark_symbol: '510300',
          cash_proxy_symbol: '511010',
          symbols: ['510300', '510500', '511010'],
          member_count: 3,
          members: [
            {
              symbol: '510300',
              name: '沪深300ETF',
              asset_class: 'fund',
              instrument_type: 'etf',
              benchmark: true,
              cash_proxy: false,
              description: 'Large-cap benchmark',
            },
            {
              symbol: '510500',
              name: '中证500ETF',
              asset_class: 'fund',
              instrument_type: 'etf',
              benchmark: false,
              cash_proxy: false,
              description: 'Mid-cap equity',
            },
            {
              symbol: '511010',
              name: '国债ETF',
              asset_class: 'bond',
              instrument_type: 'etf',
              benchmark: false,
              cash_proxy: true,
              description: 'Treasury cash proxy',
            },
          ],
        },
      ],
      isLoading: false,
      isError: false,
    }),
    useFactorEvaluationMutation: () => ({
      mutate: evaluation.mutate,
      isPending: false,
      isError: false,
    }),
  };
});

describe('FactorEvaluationPanel', () => {
  it('renders curated universes, members, factor options, and evaluation action', () => {
    window.localStorage.clear();
    window.localStorage.setItem('karkinos.locale', 'zh');
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <PreferencesProvider>
          <FactorEvaluationPanel />
        </PreferencesProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByTestId('factor-evaluation-panel')).toBeTruthy();
    expect(
      screen.getByText('China Core Macro & Broad Index ETFs'),
    ).toBeTruthy();
    expect(screen.getByText('沪深300ETF')).toBeTruthy();
    expect(screen.getByText('国债ETF')).toBeTruthy();
    expect(screen.getByText('510300')).toBeTruthy();
    expect(screen.getByText('运行因子体检')).toBeTruthy();
  });

  it('labels real non-overlapping samples and gross diagnostics with their actual data interval', () => {
    window.localStorage.clear();
    window.localStorage.setItem('karkinos.locale', 'en');
    evaluation.mutate.mockImplementationOnce((_request, options) =>
      options.onSuccess({
        universe_id: 'core_etf_universe',
        universe_name: 'Saved ETF universe',
        factor_type: 'momentum',
        lookback_period: 20,
        forward_period: 5,
        n_quantiles: 3,
        sample_count: 11,
        data_source: 'local_typed_daily_bars',
        data_start: '2026-01-05',
        data_end: '2026-04-24',
        evaluated_symbols: ['510300', '510500'],
        sampling: 'fixed_nonoverlapping_daily_bar_rows',
        return_basis: 'gross_unadjusted_quantile_diagnostic',
        research_only: true,
        limitations: [],
        summary: {
          sample_count: 11,
          sample_stride: 5,
          annual_periods: 50.4,
          mean_ic: 0.1,
          std_ic: 0.2,
          icir: 0.5,
          annualized_icir: 3.55,
          t_stat: 1.6,
          p_value: 0.1,
          positive_ratio: 0.6,
        },
        spread_summary: {
          annualized_spread_return: 0.01,
          annualized_spread_volatility: 0.1,
          spread_sharpe: 0.1,
          spread_max_drawdown: 0.1,
          monotonicity_score: 0.5,
        },
        ic_series: [],
        quantile_cumulative: [],
        latest_cross_section: [
          {
            symbol: '510300',
            name: '沪深300ETF',
            factor_value: 0.1,
            rank: 1,
            percentile: 100,
          },
        ],
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PreferencesProvider>
          <FactorEvaluationPanel />
        </PreferencesProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByText('Run Evaluation'));
    expect(
      screen.getByText('Non-overlapping valid samples: 11 periods'),
    ).toBeTruthy();
    expect(screen.getByText(/2026-01-05.*2026-04-24/)).toBeTruthy();
    expect(
      screen.getByText(/annualized at 50.4 periods per year/),
    ).toBeTruthy();
    expect(screen.getByText('Annualized gross spread')).toBeTruthy();
    expect(screen.getByText('Q3 - Q1')).toBeTruthy();
    expect(
      screen.getByText('Exploratory ranking; no portfolio target'),
    ).toBeTruthy();
    expect(
      screen.getByText(/do not prove sample independence or alpha/),
    ).toBeTruthy();
  });
});
