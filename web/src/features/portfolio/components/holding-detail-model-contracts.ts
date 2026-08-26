import type { useCopy } from '../../../shared/i18n/context';
import type { Locale } from '../../../shared/preferences/context';
import type {
  LedgerEntry,
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
import type {
  Position,
  useLiveHoldingsQuery,
  usePortfolioSnapshotQuery,
} from '../api';

export type HoldingDetailModelSource = {
  copy: ReturnType<typeof useCopy>;
  locale: Locale;
  labels: ReturnType<typeof useCopy>['portfolio']['detail'];
  normalizedSymbol: string;
  position: Position;
  isHistoricalClosedPosition: boolean;
  allocation: ReturnType<typeof usePortfolioSnapshotQuery>['data'] extends
    { allocation: Array<infer T> } | undefined
    ? T | undefined
    : never;
  kline: ReturnType<typeof useKlineQuery>;
  liveHoldings: ReturnType<typeof useLiveHoldingsQuery>;
  overview: ReturnType<typeof useAccountOverviewQuery>;
  marketHealth: ReturnType<typeof useMarketDataHealthQuery>;
  ledger: ReturnType<typeof useLedgerEntriesQuery>;
  accountStrategy: ReturnType<typeof useAccountStrategyAssignmentQuery>;
  accountStrategyAttribution: ReturnType<
    typeof useAccountStrategyAttributionQuery
  >;
  accountStrategyContribution: ReturnType<
    typeof useAccountStrategyContributionQuery
  >;
  holdingStrategyAttribution: ReturnType<
    typeof useHoldingStrategyAttributionQuery
  >;
  refreshQuote: ReturnType<typeof useRefreshMarketQuotesMutation>;
  snapshot: ReturnType<typeof usePortfolioSnapshotQuery>;
  symbolLedgerEntries: LedgerEntry[];
};
