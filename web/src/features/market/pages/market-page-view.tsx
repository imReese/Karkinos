import {
  EvidenceState,
  MetricStrip,
  StatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { ToastStack } from '../../../shared/ui/toast-stack';
import { CurrentHoldingMarketEvidenceReviewPanel } from '../components/current-holding-market-evidence-review-panel';
import {
  MarketInstrumentWorkspace,
  MarketInstrumentWorkspaceLoading,
} from '../components/market-instrument-workspace';
import type { MarketPageController } from './market-page-controller';
import { MarketDataEvidenceWorkspace } from './market-data-evidence-workspace';
import { formatAge } from './market-page-format';
import { MarketResearchNotesWorkspace } from './market-research-notes-workspace';

export function MarketPageView({
  controller,
}: {
  controller: MarketPageController;
}) {
  const {
    board,
    cacheBound,
    copy,
    evidenceModeLabel,
    health,
    latestQuoteLabel,
    staleCount,
    toasts,
  } = controller;
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
          <MarketResolvedWorkspace controller={controller} />
        )}
      </section>
    </>
  );
}

function MarketResolvedWorkspace({
  controller,
}: {
  controller: MarketPageController;
}) {
  return (
    <div className="space-y-5 sm:space-y-6">
      <MarketInstrumentSelection controller={controller} />
      <MarketSummary controller={controller} />
      <MarketDataEvidenceWorkspace controller={controller} />
      <MarketResearchNotesWorkspace controller={controller} />
    </div>
  );
}

function MarketInstrumentSelection({
  controller,
}: {
  controller: MarketPageController;
}) {
  const {
    activeSymbol,
    addWatchlistItem,
    assetClassOptions,
    copy,
    healthBySymbol,
    items,
    kline,
    newAssetClass,
    newSymbol,
    removeWatchlistItem,
    selectedHealthQuote,
    selectedItem,
    selectedQuoteNextAction,
    setNewAssetClass,
    setNewSymbol,
    setSelectedSymbol,
  } = controller;
  return (
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
                onChange={(event) => setNewAssetClass(event.target.value)}
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
  );
}

function MarketSummary({ controller }: { controller: MarketPageController }) {
  const {
    copy,
    health,
    holdingItemsCount,
    holdingMarketEvidenceReview,
    holdingReviewNeedsAttention,
    items,
    latestQuoteLabel,
    marketStateLabel,
    staleCount,
  } = controller;
  return (
    <>
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
    </>
  );
}
