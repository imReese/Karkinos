import { formatCurrency } from '../../../shared/format';
import { EvidenceState } from '../../../shared/ui/workbench';
import { AllocationCard } from '../components/allocation-card';
import { LiveHoldingsBoard } from '../components/live-holdings-board';
import { PortfolioConstructionRecommendationsCard } from '../components/portfolio-construction-recommendations-card';
import { PositionsTable } from '../components/positions-table';
import { WorkspaceToolbar } from '../components/workspace-toolbar';
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
      <div>
        <h2 className="app-type-section-title text-[var(--app-text)]">
          {copy.portfolio.currentHoldings.title}
        </h2>
        <p className="mt-0.5 max-w-4xl text-xs leading-5 text-[var(--app-text-secondary)]">
          {copy.portfolio.currentHoldings.detail}
        </p>
      </div>
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
            <button
              type="button"
              className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
              onClick={actions.onRetrySnapshot}
            >
              {copy.states.retry}
            </button>
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
  const { cockpit, copy, liveHoldings, snapshot, state, strategyContribution } =
    model.source;
  return (
    <section className="min-w-0 space-y-3" data-testid="portfolio-analysis">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.portfolio.analysis.title}
          </h2>
          <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
            {copy.portfolio.analysis.detail}
          </p>
        </div>
        <div
          role="group"
          className="inline-flex overflow-hidden rounded-[var(--app-radius-control)] border border-[var(--app-border)]"
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
              className={`min-h-10 px-3 text-xs font-semibold sm:min-h-8 ${
                state.mode === item.value
                  ? 'bg-[var(--app-accent)] text-[var(--app-text-inverse)]'
                  : 'bg-transparent text-[var(--app-text-secondary)] hover:bg-[var(--app-accent-bg)]'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
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
                <button
                  type="button"
                  className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
                  onClick={actions.onRetryLiveHoldings}
                >
                  {copy.states.retry}
                </button>
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

        {state.mode === 'strategy' ? (
          !model.primaryPortfolioQueriesSettled ? (
            <EvidenceState
              kind="error"
              title={copy.states.error}
              description={model.portfolioPrimaryFailureDetail}
            />
          ) : (
            <PortfolioConstructionRecommendationsCard
              recommendations={cockpit.data?.construction_recommendations ?? []}
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
              <button
                type="button"
                className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
                onClick={actions.onRetrySnapshot}
              >
                {copy.states.retry}
              </button>
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
      </div>
    </section>
  );
}

export function PortfolioHistorySection({
  actions,
  model,
}: {
  actions: PortfolioPageActions;
  model: PortfolioPageModel;
}) {
  const { copy, snapshot } = model.source;
  return (
    <section className="min-w-0" data-testid="portfolio-history">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.portfolio.detail.closedHistoryOnly}
          </h2>
          <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {copy.portfolio.detail.realizedPnl}:{' '}
            {formatCurrency(snapshot.data?.realized_pnl_total)}
          </p>
        </div>
        <a
          href="/activity"
          className="app-button-secondary inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold"
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
    </section>
  );
}
