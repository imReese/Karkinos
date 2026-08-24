import { useMemo, useState } from 'react';
import { createLazyRoute } from '@tanstack/react-router';
import { ChevronDown } from 'lucide-react';

import { useCopy, type AppCopy } from '../../../app/copy';
import { ToastStack, type ToastItem } from '../../../shared/ui/toast-stack';
import {
  EvidenceState,
  FilterBar,
  MetricStrip,
  StatusBadge,
  Timeline,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
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
  type QuoteFetchRun,
} from '../api';
import { useCurrentHoldingMarketEvidenceReviewQuery } from '../../portfolio/api';
import { CurrentHoldingMarketEvidenceReviewPanel } from '../components/current-holding-market-evidence-review-panel';
import {
  MarketInstrumentWorkspace,
  MarketInstrumentWorkspaceLoading,
} from '../components/market-instrument-workspace';
import { MarketRefreshButton } from '../components/market-refresh-button';
import { getErrorMessage } from '../../../shared/error-message';
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
import { formatStaleReason } from '../../../shared/stale-reason';
import { formatTimestamp } from '../../../shared/format';

export function MarketPage() {
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

  return (
    <>
      <ToastStack toasts={toasts} />
      <section
        className="app-workbench-route space-y-5 sm:space-y-6"
        data-workbench-route="market"
      >
        <WorkspaceHeader
          eyebrow={copy.market.kicker}
          title={copy.market.title}
          description={copy.market.subtitle}
          context={`${copy.market.latestQuote}: ${latestQuoteLabel}`}
          actions={
            <StatusBadge
              tone={
                cacheBound || staleCount > 0
                  ? 'warning'
                  : health
                    ? 'success'
                    : 'neutral'
              }
            >
              {evidenceModeLabel}
            </StatusBadge>
          }
        />

        {board.isLoading ? (
          <MarketInstrumentWorkspaceLoading
            title={copy.states.loading}
            description={copy.market.loading}
          />
        ) : board.isError ? (
          <EvidenceState
            kind="error"
            title={copy.states.error}
            description={copy.market.error}
          />
        ) : (
          <div className="space-y-5 sm:space-y-6">
            <MarketInstrumentWorkspace
              items={items}
              healthBySymbol={healthBySymbol}
              activeSymbol={activeSymbol}
              selectedItem={selectedItem}
              selectedHealthQuote={selectedHealthQuote}
              selectedQuoteNextAction={selectedQuoteNextAction}
              bars={kline.data ?? []}
              barsLoading={kline.isLoading}
              barsError={kline.isError}
              onRetryBars={() => void kline.refetch()}
              onSelect={setSelectedSymbol}
              onRemove={async (symbol) => {
                await removeWatchlistItem.mutateAsync(symbol);
                if (activeSymbol === symbol) {
                  setSelectedSymbol('');
                }
              }}
              watchlistEditor={
                <details
                  className="group border-b border-[var(--app-divider)]"
                  data-testid="market-watchlist-editor"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--app-focus-ring)]">
                    <span>{copy.market.addSymbol}</span>
                    <span
                      aria-hidden="true"
                      className="transition-transform group-open:rotate-45 motion-reduce:transition-none"
                    >
                      +
                    </span>
                  </summary>
                  <form
                    className="grid gap-3 border-t border-[var(--app-divider)] px-3 py-3"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!newSymbol.trim()) {
                        return;
                      }
                      await addWatchlistItem.mutateAsync({
                        symbol: newSymbol.trim(),
                        asset_class: newAssetClass,
                      });
                      setNewSymbol('');
                      setSelectedSymbol('');
                    }}
                  >
                    <label className="grid gap-1.5">
                      <span className="text-xs font-medium">
                        {copy.market.symbolLabel}
                      </span>
                      <input
                        name="watchlist_symbol"
                        autoComplete="off"
                        value={newSymbol}
                        onChange={(event) => setNewSymbol(event.target.value)}
                        placeholder={copy.market.symbolPlaceholder}
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <label className="grid gap-1.5">
                      <span className="text-xs font-medium">
                        {copy.market.assetClass}
                      </span>
                      <select
                        name="watchlist_asset_class"
                        value={newAssetClass}
                        onChange={(event) =>
                          setNewAssetClass(event.target.value)
                        }
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      >
                        {assetClassOptions.map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="submit"
                      className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-sm sm:min-h-8"
                    >
                      {copy.market.add}
                    </button>
                  </form>
                </details>
              }
            />

            <CurrentHoldingMarketEvidenceReviewPanel
              report={holdingMarketEvidenceReview.data}
              loading={holdingMarketEvidenceReview.isLoading}
              error={holdingMarketEvidenceReview.isError}
              compact={holdingReviewNeedsAttention}
            />

            <MetricStrip
              ariaLabel={copy.market.title}
              items={[
                {
                  id: 'watchlist',
                  label: copy.market.watchlist,
                  value: items.length,
                  detail: copy.market.personalUniverse,
                },
                {
                  id: 'holdings',
                  label: copy.market.holdingsContext,
                  value: holdingItemsCount,
                  detail: `${items.length} ${copy.market.watchlist}`,
                },
                {
                  id: 'latest-quote',
                  label: copy.market.latestQuote,
                  value: latestQuoteLabel,
                  detail: `${copy.market.cacheAge} ${formatAge(health?.cache_age_seconds)}`,
                },
                {
                  id: 'market-state',
                  label: copy.market.marketOpen,
                  value: marketStateLabel,
                  detail: `${staleCount} ${copy.market.staleSymbols}`,
                  tone: staleCount > 0 ? 'warning' : 'neutral',
                },
              ]}
            />

            <div className="grid min-w-0 gap-4 lg:grid-cols-3">
              <section
                className="min-w-0 border-y border-[var(--app-divider)] py-4 lg:col-span-2"
                data-testid="market-data-health-summary"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="app-kicker app-type-overline">
                      {copy.market.health}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-semibold text-[var(--app-text)]">
                        {copy.market.sourceHealth}
                      </h2>
                      <StatusBadge
                        tone={
                          cacheBound || staleCount > 0
                            ? 'warning'
                            : health
                              ? 'success'
                              : 'neutral'
                        }
                      >
                        {sourceHealthLabel}
                      </StatusBadge>
                    </div>
                  </div>
                  <MarketRefreshButton
                    onComplete={(response) => {
                      const title =
                        response.quote_status === 'live'
                          ? copy.market.quoteRefreshComplete
                          : response.quote_status === 'partial'
                            ? copy.market.quoteRefreshPartial
                            : response.quote_status === 'stale'
                              ? copy.market.quoteRefreshStale
                              : copy.market.quoteRefreshFailed;
                      pushToast(
                        response.quote_status === 'error' ? 'error' : 'success',
                        title,
                        response.message,
                      );
                    }}
                    onError={(error) => {
                      pushToast(
                        'error',
                        copy.market.quoteRefreshFailed,
                        error.message,
                      );
                    }}
                  />
                </div>

                <MetricStrip
                  className="mt-3"
                  ariaLabel={copy.market.health}
                  items={[
                    {
                      id: 'provider',
                      label: copy.market.provider,
                      value: health?.provider_name ?? copy.market.unknown,
                      detail: providerStatusLabel,
                    },
                    {
                      id: 'refresh-policy',
                      label: copy.market.refreshPolicy,
                      value: refreshPolicyLabel,
                      detail: providerConfiguredLabel,
                      tone: cacheBound ? 'warning' : 'neutral',
                    },
                    {
                      id: 'cache-age',
                      label: copy.market.cacheAge,
                      value: formatAge(health?.cache_age_seconds),
                      detail: latestQuoteLabel,
                    },
                    {
                      id: 'review-count',
                      label: copy.market.health,
                      value: staleCount,
                      detail: copy.market.staleSymbols,
                      tone: staleCount > 0 ? 'warning' : 'neutral',
                    },
                  ]}
                />

                {providerAction ? (
                  <div
                    className="mt-3 border-l-2 border-[var(--app-warning-border)] pl-3 text-xs leading-5 text-[var(--app-text-secondary)]"
                    data-action-scope={
                      providerActionIsFundCoverage
                        ? 'fund-coverage'
                        : 'provider'
                    }
                  >
                    {providerActionIsFundCoverage ? (
                      <span className="app-type-overline mb-0.5 block text-[var(--app-warning-text)]">
                        {copy.market.providerFundCoverageScope}
                      </span>
                    ) : null}
                    <span className="font-semibold text-[var(--app-text)]">
                      {copy.market.providerNextAction}:
                    </span>{' '}
                    {providerAction}
                  </div>
                ) : null}

                <details
                  className="group mt-3 border-t border-[var(--app-divider)] pt-2"
                  data-testid="market-provider-details"
                >
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                    <span>{copy.market.providerStatus}</span>
                    <span aria-hidden="true" className="group-open:rotate-180">
                      ▾
                    </span>
                  </summary>
                  <dl className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)] text-xs">
                    {[
                      [copy.market.providerConfigured, providerConfiguredLabel],
                      [copy.market.providerSupportsFunds, providerFundsLabel],
                      [
                        copy.market.metadataConfiguredCount,
                        health == null
                          ? '--'
                          : String(health.metadata_configured_count),
                      ],
                      [
                        copy.market.providerTimeout,
                        health?.provider_timeout_seconds == null
                          ? '--'
                          : `${health.provider_timeout_seconds}s`,
                      ],
                      [
                        copy.market.lastRefreshAttempt,
                        formatTimestamp(health?.last_refresh_attempt),
                      ],
                      [
                        copy.market.lastRefreshError,
                        formatStaleReason(
                          health?.provider_last_error ??
                            health?.last_refresh_error,
                          copy.common.staleReasons,
                        ),
                      ],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className="grid grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-3 px-2 py-2"
                      >
                        <dt className="text-[var(--app-text-tertiary)]">
                          {label}
                        </dt>
                        <dd className="min-w-0 break-words text-right text-[var(--app-text-secondary)]">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </section>
              <details className="group border-y border-[var(--app-divider)] py-2">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                  <span>{copy.market.promptsTitle}</span>
                  <span aria-hidden="true" className="group-open:rotate-180">
                    ▾
                  </span>
                </summary>
                <div className="mt-2 divide-y divide-[var(--app-divider)]">
                  {copy.market.prompts.map((prompt) => (
                    <div
                      key={prompt}
                      className="py-2 text-xs leading-5 text-[var(--app-text-secondary)]"
                    >
                      {prompt}
                    </div>
                  ))}
                </div>
              </details>
              <details
                className="group border-y border-[var(--app-divider)] py-2"
                data-testid="market-data-operations-disclosure"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold text-[var(--app-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-focus-ring)]">
                  <span>{copy.market.dataOperations}</span>
                  <span className="flex items-center gap-2 font-mono text-xs font-normal tabular-nums text-[var(--app-text-tertiary)]">
                    {quoteFetchRuns.data?.length ?? 0}
                    <span aria-hidden="true" className="group-open:rotate-180">
                      ▾
                    </span>
                  </span>
                </summary>
                <div className="mt-3">
                  <MarketDataOperationsPanel
                    runs={quoteFetchRuns.data ?? []}
                    loading={quoteFetchRuns.isLoading}
                    error={quoteFetchRuns.isError}
                    metadataPending={metadataBackfill.isPending}
                    barsPending={barsBackfill.isPending}
                    onMetadataBackfill={async () => {
                      try {
                        const result = await metadataBackfill.mutateAsync();
                        pushToast(
                          'success',
                          copy.market.metadataBackfillComplete,
                          copy.market.backfillResult(
                            result.updated_count,
                            result.failed_count,
                          ),
                        );
                      } catch (error) {
                        pushToast(
                          'error',
                          copy.market.metadataBackfillFailed,
                          getErrorMessage(error),
                        );
                      }
                    }}
                    onBarsBackfill={async () => {
                      try {
                        const result = await barsBackfill.mutateAsync();
                        pushToast(
                          'success',
                          copy.market.barsBackfillComplete,
                          copy.market.backfillResult(
                            result.updated_count,
                            result.failed_count,
                          ),
                        );
                      } catch (error) {
                        pushToast(
                          'error',
                          copy.market.barsBackfillFailed,
                          getErrorMessage(error),
                        );
                      }
                    }}
                  />
                </div>
              </details>
            </div>
            <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
              <div className="app-workbench-section min-w-0 p-4 sm:p-5">
                <div className="app-kicker app-type-overline">
                  {copy.market.notesTitle}
                </div>
                {selectedItem ? (
                  <form
                    className="mt-4 grid gap-3"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (!noteTitle.trim() || !noteContent.trim()) {
                        pushToast(
                          'error',
                          copy.market.noteFailed,
                          copy.common.required,
                        );
                        return;
                      }
                      try {
                        if (editingNoteId !== null) {
                          await updateResearchNote.mutateAsync({
                            noteId: editingNoteId,
                            entry_kind: noteType,
                            title: noteTitle.trim(),
                            content: noteContent.trim(),
                            priority: notePriority,
                            event_date: noteDate || null,
                          });
                        } else {
                          await createResearchNote.mutateAsync({
                            symbol: selectedItem.symbol,
                            asset_class: selectedItem.asset_class,
                            entry_kind: noteType,
                            title: noteTitle.trim(),
                            content: noteContent.trim(),
                            priority: notePriority,
                            event_date: noteDate || null,
                          });
                        }
                        setEditingNoteId(null);
                        setNoteType('note');
                        setNotePriority('normal');
                        setNoteTitle('');
                        setNoteContent('');
                        setNoteDate('');
                        pushToast(
                          'success',
                          editingNoteId !== null
                            ? copy.market.updateNote
                            : copy.market.noteSaved,
                          selectedItem.symbol,
                        );
                      } catch (error) {
                        pushToast(
                          'error',
                          copy.market.noteFailed,
                          getErrorMessage(error),
                        );
                      }
                    }}
                  >
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="grid gap-2">
                        <span className="text-sm font-medium">
                          {copy.market.noteType}
                        </span>
                        <select
                          name="research_note_type"
                          value={noteType}
                          onChange={(event) => setNoteType(event.target.value)}
                          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        >
                          <option value="note">{copy.market.note}</option>
                          <option value="thesis">{copy.market.thesis}</option>
                          <option value="catalyst">
                            {copy.market.catalyst}
                          </option>
                        </select>
                      </label>
                      <label className="grid gap-2">
                        <span className="text-sm font-medium">
                          {copy.market.notePriority}
                        </span>
                        <select
                          name="research_note_priority"
                          value={notePriority}
                          onChange={(event) =>
                            setNotePriority(event.target.value)
                          }
                          className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        >
                          <option value="high">
                            {copy.market.highPriority}
                          </option>
                          <option value="normal">
                            {copy.market.normalPriority}
                          </option>
                          <option value="low">{copy.market.lowPriority}</option>
                        </select>
                      </label>
                    </div>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteTitle}
                      </span>
                      <input
                        name="research_note_title"
                        autoComplete="off"
                        value={noteTitle}
                        onChange={(event) => setNoteTitle(event.target.value)}
                        placeholder={copy.market.noteTitlePlaceholder}
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteContent}
                      </span>
                      <textarea
                        name="research_note_content"
                        value={noteContent}
                        onChange={(event) => setNoteContent(event.target.value)}
                        placeholder={copy.market.noteContentPlaceholder}
                        rows={5}
                        className="app-field min-h-32 rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteDate}
                      </span>
                      <input
                        name="research_note_date"
                        type="date"
                        value={noteDate}
                        onChange={(event) => setNoteDate(event.target.value)}
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={
                        createResearchNote.isPending ||
                        updateResearchNote.isPending
                      }
                      className="app-button-primary rounded-[var(--app-radius-control)] px-4 py-2 text-sm"
                    >
                      {createResearchNote.isPending ||
                      updateResearchNote.isPending
                        ? copy.market.savingNote
                        : editingNoteId !== null
                          ? copy.market.updateNote
                          : copy.market.saveNote}
                    </button>
                  </form>
                ) : (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.noSelection}
                  </div>
                )}
              </div>

              <div className="app-workbench-section min-w-0 p-4 sm:p-5">
                <div className="app-kicker app-type-overline">
                  {copy.market.notesTitle}
                </div>
                <FilterBar
                  className="mt-4"
                  label={copy.market.notesTitle}
                  summary={
                    notes.data
                      ? `${notes.data.items.length} ${copy.market.researchCount}`
                      : undefined
                  }
                >
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteType}
                    </span>
                    <select
                      value={noteFilterType}
                      onChange={(event) =>
                        setNoteFilterType(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    >
                      <option value="">{copy.market.allTypes}</option>
                      <option value="note">{copy.market.note}</option>
                      <option value="thesis">{copy.market.thesis}</option>
                      <option value="catalyst">{copy.market.catalyst}</option>
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.notePriority}
                    </span>
                    <select
                      value={noteFilterPriority}
                      onChange={(event) =>
                        setNoteFilterPriority(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                    >
                      <option value="">{copy.market.allPriorities}</option>
                      <option value="high">{copy.market.highPriority}</option>
                      <option value="normal">
                        {copy.market.normalPriority}
                      </option>
                      <option value="low">{copy.market.lowPriority}</option>
                    </select>
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteDateFrom}
                    </span>
                    <input
                      type="date"
                      value={noteFilterDateFrom}
                      onChange={(event) =>
                        setNoteFilterDateFrom(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      aria-label={copy.market.noteDateFrom}
                    />
                  </label>
                  <label className="grid gap-2">
                    <span className="text-sm font-medium">
                      {copy.market.noteDateTo}
                    </span>
                    <input
                      type="date"
                      value={noteFilterDateTo}
                      onChange={(event) =>
                        setNoteFilterDateTo(event.target.value)
                      }
                      className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                      aria-label={copy.market.noteDateTo}
                    />
                  </label>
                </FilterBar>
                {notes.isLoading ? (
                  <div className="app-muted mt-4 text-sm">
                    {copy.states.loading}
                  </div>
                ) : notes.isError ? (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.noteFailed}
                  </div>
                ) : notes.data && notes.data.items.length > 0 ? (
                  <div className="mt-4 grid gap-3">
                    {notes.data.items.map((note) => (
                      <div
                        key={note.id}
                        className="app-panel-strong rounded-[var(--app-radius-surface)] px-4 py-4"
                      >
                        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div className="min-w-0">
                            <div className="text-sm font-semibold">
                              {note.title}
                            </div>
                            <div className="app-kicker app-type-overline mt-2">
                              {getNoteTypeLabel(copy, note.entry_kind)} ·{' '}
                              {getPriorityLabel(copy, note.priority)}
                              {note.event_date ? ` · ${note.event_date}` : ''}
                            </div>
                            <div className="app-kicker app-type-overline mt-2">
                              {copy.market.noteUpdatedAt} ·{' '}
                              <time dateTime={note.updated_at}>
                                {formatTimestamp(note.updated_at)}
                              </time>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <button
                              type="button"
                              className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                              onClick={() => {
                                setEditingNoteId(note.id);
                                setNoteType(note.entry_kind);
                                setNotePriority(note.priority);
                                setNoteTitle(note.title);
                                setNoteContent(note.content);
                                setNoteDate(note.event_date ?? '');
                              }}
                            >
                              {copy.market.editNote}
                            </button>
                            <button
                              type="button"
                              className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-1 text-xs sm:min-h-8"
                              onClick={async () => {
                                try {
                                  await deleteResearchNote.mutateAsync(note.id);
                                  pushToast(
                                    'success',
                                    copy.market.noteDeleted,
                                    note.title,
                                  );
                                } catch (error) {
                                  pushToast(
                                    'error',
                                    copy.market.noteDeleteFailed,
                                    getErrorMessage(error),
                                  );
                                }
                              }}
                            >
                              {copy.market.remove}
                            </button>
                          </div>
                        </div>
                        <details
                          className="group mt-3 border-t border-[var(--app-divider)]"
                          data-testid={`market-research-note-disclosure-${note.id}`}
                        >
                          <summary className="app-focus-ring app-muted flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 rounded-[var(--app-radius-control)] py-2 text-sm font-semibold sm:min-h-8 [&::-webkit-details-marker]:hidden">
                            <span className="group-open:hidden">
                              {copy.market.showFullNote}
                            </span>
                            <span className="hidden group-open:inline">
                              {copy.market.hideFullNote}
                            </span>
                            <ChevronDown
                              aria-hidden="true"
                              className="size-4 shrink-0 transition-transform group-open:rotate-180 motion-reduce:transition-none"
                            />
                          </summary>
                          <div
                            className="app-muted whitespace-pre-wrap break-words border-t border-[var(--app-divider)] pt-3 text-sm leading-6"
                            data-testid={`market-research-note-content-${note.id}`}
                          >
                            {note.content}
                          </div>
                        </details>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="app-muted mt-4 text-sm">
                    {copy.market.notesEmpty}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </>
  );
}

function MarketDataOperationsPanel({
  runs,
  loading,
  error,
  metadataPending,
  barsPending,
  onMetadataBackfill,
  onBarsBackfill,
}: {
  runs: QuoteFetchRun[];
  loading: boolean;
  error: boolean;
  metadataPending: boolean;
  barsPending: boolean;
  onMetadataBackfill: () => Promise<void>;
  onBarsBackfill: () => Promise<void>;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  return (
    <div className="space-y-3">
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="app-kicker app-type-overline">
            {copy.market.dataOperations}
          </div>
          <p className="app-muted mt-2 break-words text-sm leading-6">
            {copy.market.dataOperationsDetail}
          </p>
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-2">
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={metadataPending}
            onClick={() => void onMetadataBackfill()}
          >
            {metadataPending
              ? copy.market.backfilling
              : copy.market.metadataBackfill}
          </button>
          <button
            type="button"
            className="app-button-secondary rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={barsPending}
            onClick={() => void onBarsBackfill()}
          >
            {barsPending ? copy.market.backfilling : copy.market.barsBackfill}
          </button>
        </div>
      </div>
      {loading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : error ? (
        <EvidenceState kind="error" title={copy.market.quoteFetchRunsFailed} />
      ) : (
        <Timeline
          ariaLabel={copy.market.dataOperations}
          emptyState={copy.market.noQuoteFetchRuns}
          items={runs.slice(0, 4).map((run) => ({
            id: run.run_id,
            timestamp: formatTimestamp(run.started_at),
            title: `${formatPublicCode(run.trigger, locale)} · ${formatPublicStatus(run.status, locale)}`,
            description: `${copy.market.provider}: ${run.provider ?? copy.market.unknown} · ${copy.market.successCount}: ${run.success_count} · ${copy.market.failedCount}: ${run.failure_count} · ${copy.market.cacheHitCount}: ${run.cache_hit_count}`,
            evidence: run.error_message,
            tone:
              run.failure_count > 0 || run.error_message
                ? ('danger' as const)
                : run.status === 'completed'
                  ? ('success' as const)
                  : ('info' as const),
          }))}
        />
      )}
    </div>
  );
}

function formatAge(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) {
    return '--';
  }
  if (seconds < 60) {
    return `${Math.max(Math.round(seconds), 0)}s`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h`;
  }
  return `${Math.round(seconds / 86400)}d`;
}

function getNoteTypeLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'note':
      return copy.market.note;
    case 'thesis':
      return copy.market.thesis;
    case 'catalyst':
      return copy.market.catalyst;
    default:
      return value;
  }
}

function getPriorityLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'high':
      return copy.market.highPriority;
    case 'normal':
      return copy.market.normalPriority;
    case 'low':
      return copy.market.lowPriority;
    default:
      return value;
  }
}

export const Route = createLazyRoute('/market')({
  component: MarketPage,
});
