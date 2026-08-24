import { useMemo, useState } from 'react';

import { useCopy } from '../../../shared/i18n/context';
import type { ToastItem } from '../../../shared/ui/toast-stack';
import { usePreferences } from '../../../shared/preferences/context';
import {
  useAddWatchlistItemMutation,
  useCreateResearchNoteMutation,
  useDeleteResearchNoteMutation,
  useInstrumentMetadataBackfillMutation,
  useKlineQuery,
  useMarketBarsBackfillMutation,
  useQuoteFetchRunsQuery,
  useRemoveWatchlistItemMutation,
  useResearchBoardQuery,
  useResearchNotesQuery,
  useUpdateResearchNoteMutation,
} from '../api';
import { useCurrentHoldingMarketEvidenceReviewQuery } from '../market-feature-boundary';
import {
  formatMarketDataStatusNextAction,
  isCacheLikeMarketDataStatus,
  isUnconfirmedMarketDataStatus,
  normalizeMarketDataStatus,
} from '../../../shared/market-data-status';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatTimestamp } from '../../../shared/format';

export function useMarketPageController() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const board = useResearchBoardQuery();
  const primaryMarketProjectionAvailable = board.data !== undefined;
  const addWatchlistItem = useAddWatchlistItemMutation();
  const removeWatchlistItem = useRemoveWatchlistItemMutation();
  const createResearchNote = useCreateResearchNoteMutation();
  const quoteFetchRuns = useQuoteFetchRunsQuery(
    primaryMarketProjectionAvailable,
  );
  const holdingMarketEvidenceReview =
    useCurrentHoldingMarketEvidenceReviewQuery(
      primaryMarketProjectionAvailable,
    );
  const metadataBackfill = useInstrumentMetadataBackfillMutation();
  const barsBackfill = useMarketBarsBackfillMutation();
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [newSymbol, setNewSymbol] = useState('');
  const [newAssetClass, setNewAssetClass] = useState('stock');
  const [noteFilterType, setNoteFilterType] = useState('');
  const [noteFilterPriority, setNoteFilterPriority] = useState('');
  const [noteFilterDateFrom, setNoteFilterDateFrom] = useState('');
  const [noteFilterDateTo, setNoteFilterDateTo] = useState('');
  const [noteType, setNoteType] = useState('note');
  const [notePriority, setNotePriority] = useState('normal');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');
  const [noteDate, setNoteDate] = useState('');
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null);
  const items = board.data?.items ?? [];
  const health = board.data?.health;
  const healthBySymbol = useMemo(
    () => new Map((health?.quotes ?? []).map((quote) => [quote.symbol, quote])),
    [health?.quotes],
  );
  const activeSymbol = selectedSymbol || items[0]?.symbol || '';
  const updateResearchNote = useUpdateResearchNoteMutation(activeSymbol);
  const selectedItem =
    items.find((item) => item.symbol === activeSymbol) ?? null;
  const selectedHealthQuote = selectedItem
    ? (healthBySymbol.get(selectedItem.symbol) ?? null)
    : null;
  const providerReportedAction =
    health?.next_action && health.next_action in copy.market.providerActions
      ? copy.market.providerActions[
          health.next_action as keyof typeof copy.market.providerActions
        ]
      : health?.next_action
        ? formatPublicCode(health.next_action, locale)
        : null;
  const specificProviderAction =
    health?.next_action &&
    health.next_action !== 'refresh_quotes_or_check_source'
      ? providerReportedAction
      : null;
  const providerAction =
    specificProviderAction ??
    formatMarketDataStatusNextAction(health?.source_health, locale) ??
    formatMarketDataStatusNextAction(health?.refresh_policy, locale) ??
    providerReportedAction;
  const providerActionIsFundCoverage =
    health?.next_action === 'switch_to_fund_supported_provider';
  const selectedAssetClass = selectedItem?.asset_class.trim().toLowerCase();
  const selectedQuoteAssetClass = selectedHealthQuote?.asset_class
    .trim()
    .toLowerCase();
  const selectedHasFundOnlyStatus = [
    selectedHealthQuote?.stale_reason,
    selectedHealthQuote?.quote_status,
  ].some(
    (status) => normalizeMarketDataStatus(status) === 'confirmed_nav_missing',
  );
  const selectedFundIdentityIsConsistent =
    selectedAssetClass === 'fund' &&
    (!selectedQuoteAssetClass || selectedQuoteAssetClass === 'fund');
  const selectedProviderAction =
    health?.next_action === 'switch_to_fund_supported_provider' &&
    selectedAssetClass !== 'fund'
      ? null
      : providerAction;
  const selectedQuoteNextAction =
    selectedHasFundOnlyStatus && !selectedFundIdentityIsConsistent
      ? copy.market.providerActions.configure_asset_metadata
      : (formatMarketDataStatusNextAction(
          selectedHealthQuote?.stale_reason,
          locale,
        ) ??
        formatMarketDataStatusNextAction(
          selectedHealthQuote?.quote_status,
          locale,
        ) ??
        selectedProviderAction);
  const sourceHealthLabel = health?.source_health
    ? formatPublicStatus(health.source_health, locale)
    : copy.market.unknown;
  const refreshPolicyLabel = health?.refresh_policy
    ? formatPublicStatus(health.refresh_policy, locale)
    : '--';
  const cacheBound = isCacheLikeMarketDataStatus(health?.refresh_policy);
  const evidenceModeLabel = cacheBound ? refreshPolicyLabel : sourceHealthLabel;
  const providerStatusLabel = health?.provider_status
    ? formatPublicStatus(health.provider_status, locale)
    : copy.market.unknown;
  const providerConfiguredLabel = health
    ? health.provider_configured
      ? copy.market.configured
      : copy.market.notConfigured
    : copy.market.unknown;
  const providerFundsLabel =
    health?.provider_supports_funds == null
      ? copy.market.unknown
      : health.provider_supports_funds
        ? copy.market.fundSupported
        : copy.market.fundUnsupported;
  const holdingItemsCount = items.filter((item) => item.is_holding).length;
  const unconfirmedQuoteCount = (health?.quotes ?? []).filter((quote) =>
    isUnconfirmedMarketDataStatus(quote.quote_status),
  ).length;
  const staleCount = Math.max(
    health?.stale_symbols_count ?? 0,
    unconfirmedQuoteCount,
  );
  const latestQuoteLabel = formatTimestamp(health?.latest_quote_timestamp);
  const marketStateLabel = health
    ? health.market_open
      ? copy.market.marketOpen
      : copy.market.marketClosed
    : copy.market.unknown;
  const holdingReviewNeedsAttention =
    holdingMarketEvidenceReview.isError ||
    holdingMarketEvidenceReview.data?.status === 'review_required' ||
    holdingMarketEvidenceReview.data?.status === 'blocked_identity';
  const kline = useKlineQuery(activeSymbol);
  const notes = useResearchNotesQuery(activeSymbol, {
    entry_kind: noteFilterType || undefined,
    priority: noteFilterPriority || undefined,
    event_date_from: noteFilterDateFrom || undefined,
    event_date_to: noteFilterDateTo || undefined,
  });
  const deleteResearchNote = useDeleteResearchNoteMutation(activeSymbol);
  const assetClassOptions = [
    ['stock', copy.common.assetClassStock],
    ['etf', copy.common.assetClassEtf],
    ['fund', copy.common.assetClassFund],
    ['gold', copy.common.assetClassGold],
    ['bond', copy.common.assetClassBond],
  ] as const;

  const pushToast = (
    tone: ToastItem['tone'],
    title: string,
    message: string,
  ) => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((current) => [...current, { id, tone, title, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  };

  return {
    copy,
    locale,
    toasts,
    board,
    addWatchlistItem,
    removeWatchlistItem,
    createResearchNote,
    quoteFetchRuns,
    holdingMarketEvidenceReview,
    metadataBackfill,
    barsBackfill,
    selectedSymbol,
    setSelectedSymbol,
    newSymbol,
    setNewSymbol,
    newAssetClass,
    setNewAssetClass,
    noteFilterType,
    setNoteFilterType,
    noteFilterPriority,
    setNoteFilterPriority,
    noteFilterDateFrom,
    setNoteFilterDateFrom,
    noteFilterDateTo,
    setNoteFilterDateTo,
    noteType,
    setNoteType,
    notePriority,
    setNotePriority,
    noteTitle,
    setNoteTitle,
    noteContent,
    setNoteContent,
    noteDate,
    setNoteDate,
    editingNoteId,
    setEditingNoteId,
    items,
    health,
    healthBySymbol,
    activeSymbol,
    updateResearchNote,
    selectedItem,
    selectedHealthQuote,
    providerAction,
    providerActionIsFundCoverage,
    selectedQuoteNextAction,
    sourceHealthLabel,
    refreshPolicyLabel,
    cacheBound,
    evidenceModeLabel,
    providerStatusLabel,
    providerConfiguredLabel,
    providerFundsLabel,
    holdingItemsCount,
    staleCount,
    latestQuoteLabel,
    marketStateLabel,
    holdingReviewNeedsAttention,
    kline,
    notes,
    deleteResearchNote,
    assetClassOptions,
    pushToast,
  };
}

export type MarketPageController = ReturnType<typeof useMarketPageController>;
