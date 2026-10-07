import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

import { PreferencesProvider } from '../../../app/providers/preferences-provider';
import { FactorEvaluationPanel } from './factor-evaluation-panel';

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
              instrument_type: 'bond',
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
      mutate: vi.fn(),
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
});
