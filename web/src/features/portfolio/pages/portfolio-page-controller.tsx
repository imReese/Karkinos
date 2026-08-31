import { useState } from 'react';
import { getRouteApi, useNavigate } from '@tanstack/react-router';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useLiveHoldingsQuery,
  usePortfolioCockpitQuery,
  usePortfolioSnapshotQuery,
} from '../api';
import type {
  EvidenceFilter,
  PositionSort,
  QuoteFilter,
} from '../components/workspace-toolbar';
import { useAccountStrategyContributionQuery } from '../portfolio-feature-boundary';
import {
  buildPortfolioPageModel,
  type PortfolioMode,
  type PortfolioPageActions,
} from './portfolio-page-model';
import { PortfolioPageView } from './portfolio-page-view';

const portfolioRouteApi = getRouteApi('/portfolio');

export function PortfolioPageController() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const navigate = useNavigate();
  const searchState = portfolioRouteApi.useSearch();
  const [mode, setMode] = useState<PortfolioMode>('account');
  const [quoteFilter, setQuoteFilter] = useState<QuoteFilter>('all');
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>('all');
  const [sortBy, setSortBy] = useState<PositionSort>('market_value');
  const snapshot = usePortfolioSnapshotQuery();
  const primaryPortfolioQueriesSettled = snapshot.data !== undefined;
  const accountAnalysisEnabled =
    primaryPortfolioQueriesSettled && mode === 'account';
  const strategyAnalysisEnabled =
    primaryPortfolioQueriesSettled && mode === 'strategy';
  const cockpit = usePortfolioCockpitQuery(strategyAnalysisEnabled);
  const liveHoldings = useLiveHoldingsQuery(accountAnalysisEnabled);
  const strategyContribution = useAccountStrategyContributionQuery(
    strategyAnalysisEnabled,
  );
  const model = buildPortfolioPageModel({
    copy,
    locale,
    search: searchState.q,
    assetClassFilter: searchState.assetClass,
    pnlFilter: searchState.pnl as 'all' | 'winners' | 'losers',
    state: { mode, quoteFilter, evidenceFilter, sortBy },
    snapshot,
    cockpit,
    liveHoldings,
    strategyContribution,
  });
  const actions: PortfolioPageActions = {
    onOpenPosition: (symbol) => {
      void navigate({
        to: '/portfolio/$symbol',
        params: { symbol },
      });
    },
    onSearchChange: (value) => {
      void navigate({
        to: '/portfolio',
        search: (current) => ({
          assetClass: current.assetClass ?? 'all',
          pnl: current.pnl ?? 'all',
          q: value,
        }),
        replace: true,
      });
    },
    onAssetClassFilterChange: (value) => {
      void navigate({
        to: '/portfolio',
        search: (current) => ({
          assetClass: value,
          pnl: current.pnl ?? 'all',
          q: current.q ?? '',
        }),
      });
    },
    onPnlFilterChange: (value) => {
      void navigate({
        to: '/portfolio',
        search: (current) => ({
          assetClass: current.assetClass ?? 'all',
          pnl: value,
          q: current.q ?? '',
        }),
      });
    },
    onModeChange: setMode,
    onQuoteFilterChange: setQuoteFilter,
    onEvidenceFilterChange: setEvidenceFilter,
    onSortByChange: setSortBy,
    onRetryCockpit: () => void cockpit.refetch(),
    onRetryLiveHoldings: () => void liveHoldings.refetch(),
    onRetrySnapshot: () => void snapshot.refetch(),
    onRetryStrategyContribution: () => void strategyContribution.refetch(),
  };
  return <PortfolioPageView actions={actions} model={model} />;
}
