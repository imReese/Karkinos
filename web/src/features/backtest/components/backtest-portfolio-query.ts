import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../../shared/api/client';
import type { PortfolioSnapshot } from '../../../shared/portfolio-evidence/contracts';

export function useBacktestPortfolioInstrumentsQuery(enabled = true) {
  return useQuery({
    queryKey: ['portfolio-snapshot'],
    queryFn: () => apiClient<PortfolioSnapshot>('/api/portfolio'),
    staleTime: 10_000,
    enabled,
  });
}
