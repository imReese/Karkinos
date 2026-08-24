import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import type { InstrumentDisplayRecord } from '../../../shared/instrument-display';

type BacktestPortfolioInstrumentSnapshot = {
  positions: InstrumentDisplayRecord[];
};

export function useBacktestPortfolioInstrumentsQuery(enabled = true) {
  return useQuery({
    queryKey: ['backtest-portfolio-instruments'],
    queryFn: () =>
      apiClient<BacktestPortfolioInstrumentSnapshot>('/api/portfolio'),
    staleTime: 10_000,
    enabled,
  });
}
