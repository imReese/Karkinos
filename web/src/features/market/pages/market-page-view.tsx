import { useState } from 'react';
import { ChevronDown, Plus } from 'lucide-react';

import {
  EvidenceState,
  StatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { getErrorMessage } from '../../../shared/error-message';
import { ToastStack } from '../../../shared/ui/toast-stack';
import { CurrentHoldingMarketEvidenceReviewPanel } from '../components/current-holding-market-evidence-review-panel';
import {
  MarketInstrumentWorkspace,
  MarketInstrumentWorkspaceLoading,
} from '../components/market-instrument-workspace';
import { MarketBenchmarkRibbon } from '../components/market-benchmark-ribbon';
import type { MarketPageController } from './market-page-controller';
import { MarketDataEvidenceWorkspace } from './market-data-evidence-workspace';
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
        className="app-workbench-route space-y-4 pb-8 sm:space-y-5"
        data-workbench-route="market"
        data-workbench-width="wide"
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
            action={
              <button
                type="button"
                onClick={() => void board.refetch()}
                className="app-button-secondary min-h-10 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold"
              >
                {copy.states.retry}
              </button>
            }
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
    <div className="space-y-4 sm:space-y-5">
      <MarketBenchmarkRibbon controller={controller} />
      <MarketInstrumentSelection controller={controller} />
      <MarketResearchNotesWorkspace controller={controller} />
      <MarketHoldingEvidenceReview controller={controller} />
      <MarketGlobalDataEvidence controller={controller} />
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
    pushToast,
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
        if (removeWatchlistItem.isPending) return;
        try {
          await removeWatchlistItem.mutateAsync(symbol);
          pushToast('success', copy.market.symbolRemoved, symbol);
          if (activeSymbol === symbol) {
            setSelectedSymbol('');
          }
        } catch (error) {
          pushToast('error', copy.market.removeFailed, getErrorMessage(error));
        }
      }}
      watchlistEditor={
        <details
          className="group border-b border-[var(--app-divider)]"
          data-testid="market-watchlist-editor"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs font-semibold text-[var(--app-text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--app-focus-ring)]">
            <span>{copy.market.addSymbol}</span>
            <Plus
              aria-hidden="true"
              className="size-3.5 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-45 motion-reduce:transition-none"
            />
          </summary>
          <form
            className="grid gap-3 border-t border-[var(--app-divider)] px-3 py-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const trimmed = newSymbol.trim();
              if (!trimmed) {
                return;
              }
              try {
                await addWatchlistItem.mutateAsync({
                  symbol: trimmed,
                  asset_class: newAssetClass,
                });
                pushToast('success', copy.market.symbolAdded, trimmed);
                setNewSymbol('');
                setSelectedSymbol(trimmed);
              } catch (error) {
                pushToast(
                  'error',
                  copy.market.addFailed,
                  getErrorMessage(error),
                );
              }
            }}
          >
            <label className="grid gap-1.5">
              <span className="text-xs font-medium">
                {copy.market.symbolLabel}
              </span>
              <input
                name="watchlist_symbol"
                autoComplete="off"
                disabled={addWatchlistItem.isPending}
                value={newSymbol}
                onChange={(event) => setNewSymbol(event.target.value)}
                placeholder={copy.market.symbolPlaceholder}
                className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm disabled:opacity-50"
              />
            </label>
            <label className="grid gap-1.5">
              <span className="text-xs font-medium">
                {copy.market.assetClass}
              </span>
              <select
                name="watchlist_asset_class"
                disabled={addWatchlistItem.isPending}
                value={newAssetClass}
                onChange={(event) => setNewAssetClass(event.target.value)}
                className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm disabled:opacity-50"
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
              disabled={addWatchlistItem.isPending || !newSymbol.trim()}
              className="app-button-primary min-h-10 rounded-[var(--app-radius-control)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-8"
            >
              {addWatchlistItem.isPending
                ? copy.states.loading
                : copy.market.add}
            </button>
          </form>
        </details>
      }
    />
  );
}

function MarketGlobalDataEvidence({
  controller,
}: {
  controller: MarketPageController;
}) {
  const { copy, evidenceModeLabel, staleCount } = controller;
  const [open, setOpen] = useState(false);
  return (
    <details
      className="group min-w-0 border-t border-[var(--app-divider)]"
      data-testid="market-global-data-evidence"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-type-section-title block text-[var(--app-text)]">
            {copy.market.health}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.market.dataOperationsDetail}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
          <span>{evidenceModeLabel}</span>
          <span className="font-mono tabular-nums">{staleCount}</span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="border-t border-[var(--app-divider)] pt-3">
        <MarketDataEvidenceWorkspace controller={controller} active={open} />
      </div>
    </details>
  );
}

function MarketHoldingEvidenceReview({
  controller,
}: {
  controller: MarketPageController;
}) {
  const { holdingMarketEvidenceReview, holdingReviewNeedsAttention } =
    controller;
  return (
    <CurrentHoldingMarketEvidenceReviewPanel
      report={holdingMarketEvidenceReview.data}
      loading={holdingMarketEvidenceReview.isLoading}
      error={holdingMarketEvidenceReview.isError}
      compact={holdingReviewNeedsAttention}
    />
  );
}
