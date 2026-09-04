import { useQuery } from '@tanstack/react-query';

import { apiClient } from '../../shared/api/client';
import { visiblePersistedProjectionRefetchInterval } from '../../shared/api/query-policy';
import type {
  AllocationItem,
  LiveHoldingsResponse,
  PortfolioSnapshot,
} from '../../shared/portfolio-evidence/contracts';

export type {
  AllocationGroup,
  AllocationItem,
  CurrentHoldingMarketEvidenceReview,
  CurrentHoldingMarketEvidenceReviewItem,
  LiveHoldingGroup,
  LiveHoldingItem,
  LiveHoldingsResponse,
  PortfolioSnapshot,
  Position,
  PositionEvidenceReview,
} from '../../shared/portfolio-evidence/contracts';
export {
  useCurrentHoldingMarketEvidenceReviewQuery,
  usePositionsQuery,
} from '../../shared/portfolio-evidence/queries';

export type PortfolioActionTask = {
  id?: number | null;
  source_signal_id?: number | null;
  symbol: string;
  title: string;
  detail: string;
  direction: string;
  urgency: string;
  target_weight: number;
  price?: number | null;
  strategy_id: string;
  timestamp: string;
  asset_class: string;
  status: string;
  risk_decision_id?: string | null;
  risk_gate_passed?: boolean | null;
  risk_gate_status: string;
  risk_gate_severity?: string | null;
  risk_gate_reasons?: string[];
  manual_confirmation_required?: boolean;
  manual_confirmation_status?: string;
  manual_confirmation_reason?: string;
};

export type PortfolioCockpitPosition = {
  symbol: string;
  name: string;
  asset_class: string;
  market_value: number | null;
  actual_weight: number | null;
  target_weight: number | null;
  drift: number | null;
  action_task?: PortfolioActionTask | null;
};

export type PortfolioConstructionRecommendation = {
  symbol: string;
  name: string;
  asset_class: string;
  direction: string;
  status: string;
  actionable: boolean;
  actual_weight: number | null;
  target_weight: number | null;
  drift: number | null;
  account_truth_gate_status: string;
  risk_gate_status: string;
  required_actions: string[];
  rationale: string;
  source_action_task_id?: number | null;
};

export type PortfolioCockpit = {
  summary: unknown;
  positions: PortfolioCockpitPosition[];
  action_queue: PortfolioActionTask[];
  risk_alerts: unknown[];
  construction_recommendations: PortfolioConstructionRecommendation[];
};

export function useAllocationQuery() {
  return useQuery({
    queryKey: ['portfolio-allocation'],
    queryFn: () => apiClient<AllocationItem[]>('/api/portfolio/allocation'),
    staleTime: 15_000,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function usePortfolioSnapshotQuery() {
  return useQuery({
    queryKey: ['portfolio-snapshot'],
    queryFn: () => apiClient<PortfolioSnapshot>('/api/portfolio'),
    staleTime: 10_000,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function usePortfolioCockpitQuery(enabled = true) {
  return useQuery({
    queryKey: ['portfolio-cockpit'],
    queryFn: () => apiClient<PortfolioCockpit>('/api/portfolio/cockpit'),
    staleTime: 10_000,
    enabled,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}

export function useLiveHoldingsQuery(enabled = true) {
  return useQuery({
    queryKey: ['portfolio-live-holdings'],
    queryFn: () =>
      apiClient<LiveHoldingsResponse>('/api/portfolio/live-holdings'),
    staleTime: 10_000,
    enabled,
    refetchInterval: visiblePersistedProjectionRefetchInterval,
    refetchOnWindowFocus: true,
  });
}
