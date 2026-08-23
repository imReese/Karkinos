import { useCallback, useState } from 'react';
import {
  createLazyRoute,
  getRouteApi,
  useNavigate,
} from '@tanstack/react-router';

import { useCopy } from '../../../app/copy';
import {
  EvidenceIdentityDisclosure,
  EvidenceState,
  ExceptionList,
  MetricStrip,
  WorkspaceHeader,
} from '../../../app/components/workbench';
import { usePreferences } from '../../../app/preferences';
import { useAccountStrategyContributionQuery } from '../../account-strategy/api';
import { StrategyContributionGateCard } from '../../account-strategy/components/strategy-contribution-gate-card';
import {
  useLiveHoldingsQuery,
  usePortfolioCockpitQuery,
  usePortfolioSnapshotQuery,
  type PositionEvidenceReview,
} from '../api';
import { AllocationCard } from '../components/allocation-card';
import { LiveHoldingsBoard } from '../components/live-holdings-board';
import { PortfolioConstructionRecommendationsCard } from '../components/portfolio-construction-recommendations-card';
import { PositionsTable } from '../components/positions-table';
import {
  WorkspaceToolbar,
  type EvidenceFilter,
  type PositionSort,
  type QuoteFilter,
} from '../components/workspace-toolbar';
import {
  filterAndSortPortfolioPositions,
  quoteNeedsReview,
} from '../position-observation';
import {
  formatCurrency as formatCurrencyValue,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';

type PortfolioSearchState = {
  assetClass: string;
  pnl: 'all' | 'winners' | 'losers';
  q: string;
};

const portfolioRouteApi = getRouteApi('/portfolio');

function PortfolioEvidenceReviewPanel({
  items,
}: {
  items: PositionEvidenceReview[];
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  if (items.length === 0) {
    return null;
  }
  return (
    <section
      data-testid="portfolio-position-evidence-review"
      className="min-w-0"
    >
      <div className="mb-2 flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.portfolio.evidenceReview.title}
          </h2>
          <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
            {copy.portfolio.evidenceReview.detail}
          </p>
        </div>
        <span className="text-xs font-semibold tabular-nums text-[var(--app-warning-text)]">
          {copy.portfolio.evidenceReview.count(items.length)}
        </span>
      </div>
      <ExceptionList
        ariaLabel={copy.portfolio.evidenceReview.title}
        emptyState={copy.portfolio.evidenceReview.detail}
        items={items.map((item) => ({
          id: item.position.symbol,
          severity: 'warning',
          statusLabel: locale === 'zh' ? '待复核' : 'Review',
          title:
            item.position.display_name ??
            item.position.name ??
            item.position.symbol,
          reason: item.reason_codes
            .map((reason) => formatPublicCode(reason, locale))
            .join(' · '),
          nextAction: (
            <a
              href="/account-truth"
              className="font-semibold text-[var(--app-accent)] hover:underline"
            >
              {locale === 'zh' ? '复核账户事实' : 'Review account truth'}
            </a>
          ),
          evidence: item.position.symbol,
        }))}
        labels={
          locale === 'zh'
            ? {
                reason: '原因',
                unblockCondition: '解除条件',
                nextAction: '安全下一步',
                evidence: '标的',
              }
            : {
                reason: 'Reason',
                unblockCondition: 'Unblock condition',
                nextAction: 'Safe next step',
                evidence: 'Instrument',
              }
        }
      />
    </section>
  );
}

export function PortfolioPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const navigate = useNavigate();
  const searchState = portfolioRouteApi.useSearch();
  const [mode, setMode] = useState<'account' | 'strategy'>('account');
  const [quoteFilter, setQuoteFilter] = useState<QuoteFilter>('all');
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>('all');
  const [sortBy, setSortBy] = useState<PositionSort>('market_value');
  const snapshot = usePortfolioSnapshotQuery();
  const portfolioPositions = snapshot.data?.positions ?? [];
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
  const search = searchState.q;
  const assetClassFilter = searchState.assetClass;
  const pnlFilter = searchState.pnl as 'all' | 'winners' | 'losers';

  const allocationBySymbol = new Map(
    (snapshot.data?.allocation ?? []).map((item) => [item.symbol, item]),
  );
  const evidenceReviewItems = snapshot.data?.position_review_items ?? [];
  const evidenceReviewSymbols = new Set(
    evidenceReviewItems.map((item) => item.position.symbol),
  );
  const assetClasses = Array.from(
    new Set((snapshot.data?.allocation ?? []).map((item) => item.asset_class)),
  );
  const filteredPositions = filterAndSortPortfolioPositions({
    positions: portfolioPositions,
    allocation: snapshot.data?.allocation ?? [],
    search,
    assetClassFilter,
    pnlFilter,
    quoteFilter,
    evidenceFilter,
    evidenceReviewSymbols,
    sortBy,
  });
  const hasQuotesNeedingReview = portfolioPositions.some((position) =>
    quoteNeedsReview(position.quote_status),
  );
  const openPosition = useCallback(
    (symbol: string) => {
      void navigate({
        to: '/portfolio/$symbol',
        params: { symbol },
      });
    },
    [navigate],
  );

  const closedPositions = snapshot.data?.closed_positions ?? [];
  const portfolioIdentity = snapshot.data
    ? `${copy.common.valuationAsOf} ${formatTimestamp(
        snapshot.data.valuation_as_of,
      )}`
    : undefined;
  const isInitialPortfolioLoad = !snapshot.data && snapshot.isLoading;
  const portfolioPrimaryFailureDetail = copy.portfolio.summary.errorDetail;

  if (isInitialPortfolioLoad) {
    return (
      <section className="space-y-4 sm:space-y-5">
        <WorkspaceHeader
          eyebrow={copy.portfolio.kicker}
          title={copy.portfolio.title}
          description={copy.portfolio.subtitle}
        />
        <EvidenceState
          kind="loading"
          statusLabel={copy.states.loading}
          title={copy.portfolio.summary.loading}
          description={copy.portfolio.summary.loadingDetail}
        />
        <div
          aria-hidden="true"
          className="app-metric-strip grid min-w-0 grid-cols-2 border-y border-[var(--app-divider)] bg-transparent sm:grid-flow-col sm:auto-cols-fr sm:grid-cols-none"
          data-testid="portfolio-loading-summary"
        >
          {[
            copy.portfolio.summary.totalEquity,
            copy.portfolio.summary.cash,
            copy.portfolio.summary.openHoldings,
            copy.portfolio.summary.realizedPnl,
          ].map((label) => (
            <div
              key={label}
              className="app-metric-strip-item min-w-0 px-3 py-2.5"
            >
              <span className="app-type-label block truncate font-medium text-[var(--app-text-secondary)]">
                {label}
              </span>
              <span className="mt-2 block h-4 w-24 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
              <span className="mt-2 block h-2 w-32 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            </div>
          ))}
        </div>
        <section
          className="min-w-0 space-y-2"
          data-testid="portfolio-loading-current-holdings"
        >
          <div>
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.portfolio.currentHoldings.title}
            </h2>
            <p className="mt-0.5 max-w-4xl text-xs leading-5 text-[var(--app-text-secondary)]">
              {copy.portfolio.currentHoldings.detail}
            </p>
          </div>
          <div
            aria-hidden="true"
            className="flex min-w-0 flex-wrap gap-2 border-y border-[var(--app-divider)] py-2"
            data-testid="portfolio-loading-filters"
          >
            <span className="block h-9 w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)] sm:w-64" />
            <span className="block h-9 w-40 rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            <span className="block h-9 w-40 rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
          </div>
          <div
            aria-hidden="true"
            className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
            data-testid="portfolio-loading-rows"
          >
            {Array.from({ length: 4 }, (_, index) => (
              <div
                key={index}
                className="grid min-h-16 min-w-0 grid-cols-[minmax(0,1fr)_7rem] items-center gap-4 px-3 py-3 md:min-h-14 md:grid-cols-[minmax(9rem,1fr)_repeat(4,minmax(5rem,0.55fr))_minmax(8rem,0.75fr)]"
              >
                <span className="block h-3 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                {Array.from({ length: 5 }, (_, metricIndex) => (
                  <span
                    key={metricIndex}
                    className={`h-3 rounded-[var(--app-radius-control)] bg-[var(--app-divider)] ${
                      metricIndex > 0 ? 'hidden md:block' : 'block'
                    }`}
                  />
                ))}
              </div>
            ))}
          </div>
        </section>
      </section>
    );
  }

  return (
    <section className="space-y-4 sm:space-y-5">
      <WorkspaceHeader
        eyebrow={copy.portfolio.kicker}
        title={copy.portfolio.title}
        description={copy.portfolio.subtitle}
        context={portfolioIdentity}
        actions={
          snapshot.data ? (
            <EvidenceIdentityDisclosure
              triggerLabel={copy.common.viewEvidenceIdentity}
              title={copy.common.evidenceIdentityTitle}
              description={copy.common.evidenceIdentityDescription}
              closeLabel={copy.common.closeEvidenceIdentity}
              copyLabel={copy.common.copyEvidenceValue}
              copiedLabel={copy.common.evidenceValueCopied}
              fields={[
                {
                  label: copy.common.valuationSnapshot,
                  value: snapshot.data.valuation_snapshot_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.ledgerCutoff,
                  value: snapshot.data.ledger_cutoff_id ?? '--',
                  mono: true,
                },
                {
                  label: copy.common.valuationAsOf,
                  value: formatTimestamp(snapshot.data.valuation_as_of),
                  mono: true,
                },
                {
                  label: copy.common.valuationStatus,
                  value: formatPublicStatus(
                    snapshot.data.valuation_status,
                    locale,
                  ),
                },
              ]}
            />
          ) : undefined
        }
      />

      <div data-testid="portfolio-summary-strip">
        {snapshot.data ? (
          <MetricStrip
            ariaLabel={copy.portfolio.summary.ariaLabel}
            items={[
              {
                id: 'total-equity',
                label: copy.portfolio.summary.totalEquity,
                value: formatCurrencyValue(snapshot.data.total_equity),
                detail: copy.portfolio.summary.totalEquityDetail,
              },
              {
                id: 'cash',
                label: copy.portfolio.summary.cash,
                value: formatCurrencyValue(snapshot.data.cash),
                detail: copy.portfolio.summary.cashDetail,
              },
              {
                id: 'open-holdings',
                label: copy.portfolio.summary.openHoldings,
                value: snapshot.data.positions.length,
                detail: copy.portfolio.summary.openHoldingsDetail,
              },
              {
                id: 'realized-pnl',
                label: copy.portfolio.summary.realizedPnl,
                value: formatCurrencyValue(snapshot.data.realized_pnl_total),
                detail: copy.portfolio.summary.realizedPnlDetail,
                tone:
                  typeof snapshot.data.realized_pnl_total === 'number' &&
                  snapshot.data.realized_pnl_total !== 0
                    ? snapshot.data.realized_pnl_total > 0
                      ? 'pnl-positive'
                      : 'pnl-negative'
                    : undefined,
              },
            ]}
          />
        ) : (
          <EvidenceState
            kind={
              snapshot.isError
                ? 'error'
                : snapshot.isLoading
                  ? 'loading'
                  : 'missing'
            }
            statusLabel={
              snapshot.isError
                ? copy.states.error
                : snapshot.isLoading
                  ? copy.states.loading
                  : copy.states.empty
            }
            title={
              snapshot.isError
                ? copy.portfolio.summary.error
                : snapshot.isLoading
                  ? copy.portfolio.summary.loading
                  : copy.portfolio.summary.missing
            }
            description={
              snapshot.isError
                ? copy.portfolio.summary.errorDetail
                : snapshot.isLoading
                  ? copy.portfolio.summary.loadingDetail
                  : copy.portfolio.summary.missingDetail
            }
            action={
              snapshot.isError ? (
                <button
                  type="button"
                  className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
                  onClick={() => void snapshot.refetch()}
                >
                  {copy.states.retry}
                </button>
              ) : undefined
            }
          />
        )}
      </div>

      {evidenceFilter !== 'clear' ? (
        <PortfolioEvidenceReviewPanel items={evidenceReviewItems} />
      ) : null}

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
        {hasQuotesNeedingReview ? (
          <EvidenceState
            kind="partial"
            title={copy.portfolio.table.cachedQuoteNotice}
            evidence={copy.portfolio.table.quoteState}
          />
        ) : null}
        <WorkspaceToolbar
          search={search}
          onSearchChange={(value) => {
            void navigate({
              to: '/portfolio',
              search: (current: PortfolioSearchState) => ({
                ...current,
                q: value,
              }),
              replace: true,
            });
          }}
          assetClassFilter={assetClassFilter}
          onAssetClassFilterChange={(value) => {
            void navigate({
              to: '/portfolio',
              search: (current: PortfolioSearchState) => ({
                ...current,
                assetClass: value,
              }),
            });
          }}
          pnlFilter={pnlFilter}
          onPnlFilterChange={(value) => {
            void navigate({
              to: '/portfolio',
              search: (current: PortfolioSearchState) => ({
                ...current,
                pnl: value,
              }),
            });
          }}
          assetClasses={assetClasses}
          quoteFilter={quoteFilter}
          onQuoteFilterChange={setQuoteFilter}
          evidenceFilter={evidenceFilter}
          onEvidenceFilterChange={setEvidenceFilter}
          sortBy={sortBy}
          onSortByChange={setSortBy}
          summary={`${copy.portfolio.currentHoldingsCount(
            portfolioPositions.length,
          )} · ${copy.portfolio.filteredHoldingsCount(
            filteredPositions.length,
          )}`}
        />

        <div data-testid="portfolio-current-holdings-count" className="sr-only">
          {copy.portfolio.currentHoldingsCount(portfolioPositions.length)} ·{' '}
          {copy.portfolio.filteredHoldingsCount(filteredPositions.length)}
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
                onClick={() => void snapshot.refetch()}
              >
                {copy.states.retry}
              </button>
            }
          />
        ) : filteredPositions.length === 0 ? (
          <EvidenceState
            kind="empty"
            title={copy.states.empty}
            description={
              portfolioPositions.length === 0
                ? copy.portfolio.positionsEmpty
                : copy.portfolio.filterEmpty
            }
          />
        ) : (
          <PositionsTable
            positions={filteredPositions}
            assetClassBySymbol={Object.fromEntries(
              Array.from(allocationBySymbol.entries()).map(([symbol, item]) => [
                symbol,
                item.asset_class,
              ]),
            )}
            weightBySymbol={Object.fromEntries(
              Array.from(allocationBySymbol.entries()).map(([symbol, item]) => [
                symbol,
                item.weight,
              ]),
            )}
            onOpenPosition={openPosition}
          />
        )}
      </section>

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
                aria-pressed={mode === item.value}
                onClick={() => setMode(item.value as 'account' | 'strategy')}
                className={`min-h-10 px-3 text-xs font-semibold sm:min-h-8 ${
                  mode === item.value
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
          {!primaryPortfolioQueriesSettled ? (
            <EvidenceState
              kind="error"
              title={copy.states.error}
              description={portfolioPrimaryFailureDetail}
            />
          ) : mode === 'account' ? (
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
                    onClick={() => void liveHoldings.refetch()}
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
              onRetry={() => void strategyContribution.refetch()}
              instruments={portfolioPositions}
            />
          )}

          {mode === 'strategy' ? (
            !primaryPortfolioQueriesSettled ? (
              <EvidenceState
                kind="error"
                title={copy.states.error}
                description={portfolioPrimaryFailureDetail}
              />
            ) : (
              <PortfolioConstructionRecommendationsCard
                recommendations={
                  cockpit.data?.construction_recommendations ?? []
                }
                isLoading={cockpit.isLoading}
                isError={cockpit.isError}
                onRetry={() => void cockpit.refetch()}
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
                  onClick={() => void snapshot.refetch()}
                >
                  {copy.states.retry}
                </button>
              }
            />
          ) : snapshot.data ? (
            <AllocationCard
              items={snapshot.data.allocation}
              onOpenPosition={openPosition}
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

      <section className="min-w-0" data-testid="portfolio-history">
        <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.portfolio.detail.closedHistoryOnly}
            </h2>
            <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
              {copy.portfolio.detail.realizedPnl}:{' '}
              {formatCurrencyValue(snapshot.data?.realized_pnl_total)}
            </p>
          </div>
          <a
            href="/activity"
            className="app-button-secondary inline-flex min-h-8 items-center rounded-[var(--app-radius-control)] px-2.5 text-xs font-semibold"
          >
            {copy.portfolio.detail.actionViewActivity}
          </a>
        </div>
        {closedPositions.length > 0 ? (
          <PositionsTable
            positions={closedPositions}
            variant="history"
            onOpenPosition={openPosition}
          />
        ) : (
          <div className="border-y border-[var(--app-divider)] px-3 py-3 text-sm text-[var(--app-text-secondary)]">
            {copy.portfolio.detail.noLedger}
          </div>
        )}
      </section>
    </section>
  );
}

export const Route = createLazyRoute('/portfolio')({
  component: PortfolioPage,
});
