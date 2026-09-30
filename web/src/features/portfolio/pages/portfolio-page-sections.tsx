import { useState } from 'react';

import { formatCurrency } from '../../../shared/format';
import {
  Button,
  EvidenceState,
  SectionHeader,
} from '../../../shared/ui/workbench';
import { AllocationCard } from '../components/allocation-card';
import { LiveHoldingsBoard } from '../components/live-holdings-board';
import { PortfolioConstructionRecommendationsCard } from '../components/portfolio-construction-recommendations-card';
import { PositionsTable } from '../components/positions-table';
import {
  WorkspaceToolbar,
  type PositionSort,
} from '../components/workspace-toolbar';
import { StrategyContributionGateCard } from '../portfolio-feature-boundary';
import type {
  PortfolioPageActions,
  PortfolioPageModel,
  PortfolioMode,
} from './portfolio-page-model';

export function PortfolioCurrentHoldingsSection({
  actions,
  model,
}: {
  actions: PortfolioPageActions;
  model: PortfolioPageModel;
}) {
  const { copy, snapshot, state } = model.source;
  return (
    <section
      className="min-w-0 space-y-2"
      data-testid="portfolio-current-holdings"
    >
      <SectionHeader
        title={copy.portfolio.currentHoldings.title}
        description={copy.portfolio.currentHoldings.detail}
      />
      {model.hasQuotesNeedingReview ? (
        <EvidenceState
          kind="partial"
          title={copy.portfolio.table.cachedQuoteNotice}
          evidence={copy.portfolio.table.quoteState}
        />
      ) : null}
      <WorkspaceToolbar
        search={model.source.search}
        onSearchChange={actions.onSearchChange}
        assetClassFilter={model.source.assetClassFilter}
        onAssetClassFilterChange={actions.onAssetClassFilterChange}
        pnlFilter={model.source.pnlFilter}
        onPnlFilterChange={actions.onPnlFilterChange}
        assetClasses={model.assetClasses}
        quoteFilter={state.quoteFilter}
        onQuoteFilterChange={actions.onQuoteFilterChange}
        evidenceFilter={state.evidenceFilter}
        onEvidenceFilterChange={actions.onEvidenceFilterChange}
        sortBy={state.sortBy}
        onSortByChange={actions.onSortByChange}
        summary={`${copy.portfolio.currentHoldingsCount(
          model.portfolioPositions.length,
        )} · ${copy.portfolio.filteredHoldingsCount(
          model.filteredPositions.length,
        )}`}
      />

      <div data-testid="portfolio-current-holdings-count" className="sr-only">
        {copy.portfolio.currentHoldingsCount(model.portfolioPositions.length)} ·{' '}
        {copy.portfolio.filteredHoldingsCount(model.filteredPositions.length)}
      </div>
      {!snapshot.data && snapshot.isLoading ? (
        <EvidenceState
          kind="loading"
          title={copy.states.loading}
          description={copy.portfolio.positionsLoading}
        />
      ) : !snapshot.data && snapshot.isError ? (
        <EvidenceState
          kind="error"
          title={copy.states.error}
          description={copy.portfolio.positionsError}
          action={
            <Button variant="secondary" onClick={actions.onRetrySnapshot}>
              {copy.states.retry}
            </Button>
          }
        />
      ) : model.filteredPositions.length === 0 ? (
        <EvidenceState
          kind="empty"
          title={copy.states.empty}
          description={
            model.portfolioPositions.length === 0
              ? copy.portfolio.positionsEmpty
              : copy.portfolio.filterEmpty
          }
        />
      ) : (
        <PositionsTable
          positions={model.filteredPositions}
          assetClassBySymbol={model.assetClassBySymbol}
          weightBySymbol={model.weightBySymbol}
          sortKey={state.sortBy}
          onSort={(key) => actions.onSortByChange(key as PositionSort)}
          onOpenPosition={actions.onOpenPosition}
        />
      )}
    </section>
  );
}

export function PortfolioAnalysisSection({
  actions,
  model,
}: {
  actions: PortfolioPageActions;
  model: PortfolioPageModel;
}) {
  const [isOpen, setIsOpen] = useState(true);
  const { cockpit, copy, liveHoldings, snapshot, state, strategyContribution } =
    model.source;
  return (
    <details
      open={isOpen}
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
      className="group min-w-0 border-t border-[var(--app-divider)]"
      data-testid="portfolio-analysis"
    >
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-type-section-title block text-[var(--app-text)]">
            {copy.portfolio.analysis.title}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.analysis.detail}
          </span>
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden text-xs text-[var(--app-text-tertiary)] sm:inline">
            {isOpen
              ? model.source.locale === 'zh'
                ? '收起'
                : 'Collapse'
              : model.source.locale === 'zh'
                ? '展开'
                : 'Expand'}
          </span>
          <span
            aria-hidden="true"
            className="shrink-0 text-xs font-semibold text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
          >
            ↓
          </span>
        </div>
      </summary>

      <div className="border-t border-[var(--app-divider)] pt-3">
        <div
          role="group"
          className="app-inline-segmented mb-3"
          aria-label={copy.portfolio.toolbar.view}
        >
          {[
            { value: 'account', label: copy.mode.accountShort },
            { value: 'strategy', label: copy.mode.strategyShort },
          ].map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={state.mode === item.value}
              onClick={() => actions.onModeChange(item.value as PortfolioMode)}
              className={`app-inline-segmented-btn ${
                state.mode === item.value
                  ? 'app-inline-segmented-btn-active'
                  : ''
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div
          className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]"
          data-portfolio-analysis-layout="primary-first"
        >
          {!model.primaryPortfolioQueriesSettled ? (
            <EvidenceState
              kind="error"
              title={copy.states.error}
              description={model.portfolioPrimaryFailureDetail}
            />
          ) : state.mode === 'account' ? (
            liveHoldings.isLoading ? (
              <EvidenceState
                kind="loading"
                title={copy.states.loading}
                description={copy.portfolio.liveBoard.loading}
              />
            ) : liveHoldings.isError ? (
              <EvidenceState
                kind="error"
                title={copy.states.error}
                description={copy.portfolio.liveBoard.error}
                action={
                  <Button
                    variant="secondary"
                    onClick={actions.onRetryLiveHoldings}
                  >
                    {copy.states.retry}
                  </Button>
                }
              />
            ) : (
              <LiveHoldingsBoard groups={liveHoldings.data?.groups ?? []} />
            )
          ) : (
            <StrategyContributionGateCard
              report={strategyContribution.data}
              isLoading={strategyContribution.isLoading}
              isError={strategyContribution.isError}
              onRetry={actions.onRetryStrategyContribution}
              instruments={model.portfolioPositions}
            />
          )}

          <aside
            className="min-w-0 border-t border-[var(--app-divider)] pt-4 xl:border-t-0 xl:pt-0 xl:sticky xl:top-4 self-start"
            data-portfolio-analysis-secondary
          >
            {state.mode === 'strategy' ? (
              !model.primaryPortfolioQueriesSettled ? (
                <EvidenceState
                  kind="error"
                  title={copy.states.error}
                  description={model.portfolioPrimaryFailureDetail}
                />
              ) : (
                <PortfolioConstructionRecommendationsCard
                  recommendations={
                    cockpit.data?.construction_recommendations ?? []
                  }
                  isLoading={cockpit.isLoading}
                  isError={cockpit.isError}
                  onRetry={actions.onRetryCockpit}
                />
              )
            ) : snapshot.isLoading ? (
              <EvidenceState
                kind="loading"
                title={copy.states.loading}
                description={copy.portfolio.sidebarLoading}
              />
            ) : snapshot.isError ? (
              <EvidenceState
                kind="error"
                title={copy.states.error}
                description={copy.portfolio.sidebarError}
                action={
                  <Button variant="secondary" onClick={actions.onRetrySnapshot}>
                    {copy.states.retry}
                  </Button>
                }
              />
            ) : snapshot.data ? (
              <AllocationCard
                items={snapshot.data.allocation}
                onOpenPosition={actions.onOpenPosition}
              />
            ) : (
              <EvidenceState
                kind="empty"
                title={copy.states.empty}
                description={copy.portfolio.sidebarEmpty}
              />
            )}
          </aside>
        </div>
      </div>
    </details>
  );
}

export function PortfolioHistorySection({
  actions,
  model,
}: {
  actions: PortfolioPageActions;
  model: PortfolioPageModel;
}) {
  const [isOpen, setIsOpen] = useState(true);
  const { copy, locale, snapshot } = model.source;
  const realizedTotal = snapshot.data?.realized_pnl_total;
  return (
    <details
      open={isOpen}
      onToggle={(e) => setIsOpen(e.currentTarget.open)}
      className="group min-w-0 border-t border-[var(--app-divider)]"
      data-testid="portfolio-history"
    >
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-type-section-title block text-[var(--app-text)]">
            {copy.portfolio.detail.closedHistoryOnly}
          </span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.detail.realizedPnl}:{' '}
            <span
              className={`font-mono font-medium tabular-nums ${
                realizedTotal != null && realizedTotal > 0
                  ? 'text-[var(--app-pnl-positive)]'
                  : realizedTotal != null && realizedTotal < 0
                    ? 'text-[var(--app-pnl-negative)]'
                    : 'text-[var(--app-text)]'
              }`}
            >
              {formatCurrency(realizedTotal)}
            </span>
          </span>
        </span>
        <div className="flex shrink-0 items-center gap-2">
          {model.closedPositions.length > 0 ? (
            <span className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-1.5 py-0.5 text-xs font-mono text-[var(--app-text-secondary)]">
              {model.closedPositions.length}
            </span>
          ) : null}
          <span className="hidden text-xs text-[var(--app-text-tertiary)] sm:inline">
            {isOpen
              ? locale === 'zh'
                ? '收起'
                : 'Collapse'
              : locale === 'zh'
                ? '展开'
                : 'Expand'}
          </span>
          <span
            aria-hidden="true"
            className="shrink-0 text-xs font-semibold text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
          >
            ↓
          </span>
        </div>
      </summary>
      <div className="border-t border-[var(--app-divider)] pt-3">
        <div className="mb-3 flex justify-end">
          <a
            href="/activity"
            className="app-button app-button-secondary app-button-sm"
          >
            {copy.portfolio.detail.actionViewActivity}
          </a>
        </div>
        {model.closedPositions.length > 0 ? (
          <PositionsTable
            positions={model.closedPositions}
            variant="history"
            onOpenPosition={actions.onOpenPosition}
          />
        ) : (
          <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
            {copy.portfolio.detail.noLedger}
          </div>
        )}
      </div>
    </details>
  );
}
