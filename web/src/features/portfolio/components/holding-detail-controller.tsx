import { useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { useLiveHoldingsQuery, usePortfolioSnapshotQuery } from '../api';
import {
  useAccountOverviewQuery,
  useAccountStrategyAssignmentQuery,
  useAccountStrategyAttributionQuery,
  useAccountStrategyContributionQuery,
  useHoldingStrategyAttributionQuery,
  useKlineQuery,
  useLedgerEntriesQuery,
  useMarketDataHealthQuery,
  useRefreshMarketQuotesMutation,
} from '../portfolio-feature-boundary';
import { buildHoldingDetailModel } from './holding-detail-model';
import {
  normalizeSymbol,
  safeDecodeSymbol,
  type HoldingDetailTab,
} from './holding-detail-model-values';
import { HoldingDetailStateView } from './holding-detail-primitives';
import { HoldingDetailView } from './holding-detail-view';

export function HoldingDetailController({ symbol }: { symbol: string }) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.portfolio.detail;
  const decodedSymbol = safeDecodeSymbol(symbol);
  const normalizedSymbol = normalizeSymbol(decodedSymbol);
  const snapshot = usePortfolioSnapshotQuery();
  const currentPositions = snapshot.data?.positions ?? [];
  const currentPosition = currentPositions.find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const historicalPosition = (snapshot.data?.closed_positions ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const position = currentPosition ?? historicalPosition;
  const isHistoricalClosedPosition =
    !currentPosition && Boolean(historicalPosition);
  const allocation = (snapshot.data?.allocation ?? []).find(
    (item) => normalizeSymbol(item.symbol) === normalizedSymbol,
  );
  const kline = useKlineQuery(decodedSymbol);
  const secondaryQueriesEnabled = Boolean(
    position && (snapshot.data !== undefined || snapshot.isError),
  );
  const liveHoldings = useLiveHoldingsQuery(secondaryQueriesEnabled);
  const overview = useAccountOverviewQuery(secondaryQueriesEnabled);
  const marketHealth = useMarketDataHealthQuery(secondaryQueriesEnabled);
  const ledger = useLedgerEntriesQuery(200, secondaryQueriesEnabled);
  const accountStrategy = useAccountStrategyAssignmentQuery();
  const accountStrategyAttribution = useAccountStrategyAttributionQuery();
  const accountStrategyContribution = useAccountStrategyContributionQuery(
    secondaryQueriesEnabled,
  );
  const holdingStrategyAttribution = useHoldingStrategyAttributionQuery(
    secondaryQueriesEnabled ? decodedSymbol : '',
  );
  const refreshQuote = useRefreshMarketQuotesMutation();
  const [activeTab, setActiveTab] = useState<HoldingDetailTab>('position');
  const symbolLedgerEntries = useMemo(
    () =>
      (ledger.data ?? []).filter(
        (entry) => normalizeSymbol(entry.symbol ?? '') === normalizedSymbol,
      ),
    [ledger.data, normalizedSymbol],
  );

  const hasSnapshotProjection = snapshot.data !== undefined;
  const coreLoading = !position && !hasSnapshotProjection && snapshot.isLoading;
  if (coreLoading) {
    return <HoldingDetailStateView symbol={decodedSymbol} state="loading" />;
  }
  if (snapshot.isError) {
    return <HoldingDetailStateView symbol={decodedSymbol} state="error" />;
  }
  if (!position) {
    return <HoldingDetailStateView symbol={decodedSymbol} state="not-found" />;
  }

  const model = buildHoldingDetailModel({
    copy,
    locale,
    labels,
    normalizedSymbol,
    position,
    isHistoricalClosedPosition,
    allocation,
    kline,
    liveHoldings,
    overview,
    marketHealth,
    ledger,
    accountStrategy,
    accountStrategyAttribution,
    accountStrategyContribution,
    holdingStrategyAttribution,
    refreshQuote,
    snapshot,
    symbolLedgerEntries,
  });
  const handleRefreshQuote = () => {
    refreshQuote.mutate({
      symbols: [position.symbol],
      force: true,
    });
  };
  return (
    <HoldingDetailView
      activeTab={activeTab}
      model={model}
      onRefreshQuote={handleRefreshQuote}
      onRetryKline={() => void kline.refetch()}
      onTabChange={setActiveTab}
    />
  );
}
