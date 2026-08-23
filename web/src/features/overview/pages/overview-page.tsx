import { useMemo, useState } from 'react';
import { createLazyRoute, useNavigate } from '@tanstack/react-router';

import { useCopy, type AppCopy } from '../../../app/copy';
import {
  EvidenceState,
  MetricStrip,
  WorkspaceHeader,
} from '../../../app/components/workbench';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  useAccountOverviewQuery,
  type EquityCurveRange,
  useExplainabilityQuery,
  useEquityCurveSeriesQuery,
} from '../../account/api';
import {
  EquityCurveCard,
  EquityCurveSkeleton,
} from '../../account/components/equity-curve-card';
import { ReturnCalendarCard } from '../../account/components/return-calendar-card';
import { useAccountStrategyContributionQuery } from '../../account-strategy/api';
import { StrategyContributionGateCard } from '../../account-strategy/components/strategy-contribution-gate-card';
import {
  useTodayDecisionQuery,
  useDailyTradingPlanQuery,
} from '../../decision/api';
import { useOperationsTodayQuery } from '../../operations/api';
import {
  OverviewCards,
  OverviewSnapshotFallbackCards,
} from '../../account/components/overview-cards';
import { PortfolioExposureSummary } from '../../account/components/portfolio-exposure-summary';
import {
  usePendingManualOrdersQuery,
  type ManualOrder,
} from '../../trading/api';
import { explainMarketCalendarDate } from '../../../shared/market-calendar';
import { useLedgerEntriesQuery, type LedgerEntry } from '../../activity/api';
import {
  formatLedgerDashboardPresentation,
  formatLedgerOrderSideLabel,
} from '../../../shared/ledger-format';
import {
  type PortfolioSnapshot,
  useCurrentHoldingMarketEvidenceReviewQuery,
  usePortfolioSnapshotQuery,
} from '../../portfolio/api';
import { PositionsTable } from '../../portfolio/components/positions-table';
import {
  useMarketCalendarQuery,
  useMarketDataHealthQuery,
  type MarketCalendarSnapshot,
  type MarketDataHealthResponse,
  type MarketHealthQuote,
} from '../../market/api';
import {
  formatPercent as formatPercentValue,
  formatPrice,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import { formatAssetClassLabel } from '../../../shared/asset-class';
import { formatPublicStatus } from '../../../shared/public-labels';
import { getErrorMessage } from '../../../shared/error-message';
import { formatInstrumentDisplayLabelFromNameMap } from '../../../shared/instrument-display';
import { DashboardTodayQueue } from './overview-today-queue';

function formatShanghaiDateKey(value: Date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
  }).formatToParts(value);
  const byType = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${byType.year ?? '0000'}-${byType.month ?? '00'}-${byType.day ?? '00'}`;
}

function isTradingDayForOverviewPnl(
  calendar: Pick<MarketCalendarSnapshot, 'days'> | null | undefined,
  dateText: string,
) {
  const calendarDay = calendar?.days.find((day) => day.date === dateText);
  if (calendarDay) {
    return calendarDay.is_trading_day;
  }
  return explainMarketCalendarDate(dateText).isTradingDay;
}

export function OverviewPage() {
  const copy = useCopy();
  const [equityCurveRange, setEquityCurveRange] =
    useState<EquityCurveRange>('all');
  const [analysisView, setAnalysisView] = useState<
    'performance' | 'allocation' | 'attribution' | 'calendar'
  >('performance');
  const snapshot = usePortfolioSnapshotQuery();
  const overview = useAccountOverviewQuery();
  const secondaryQueriesEnabled = Boolean(overview.data && snapshot.data);
  const calendarAnalysisEnabled =
    secondaryQueriesEnabled && analysisView === 'calendar';
  const equityCurve = useEquityCurveSeriesQuery(
    equityCurveRange,
    secondaryQueriesEnabled,
  );
  const explainability = useExplainabilityQuery(
    undefined,
    calendarAnalysisEnabled,
  );
  const ledgerEntries = useLedgerEntriesQuery(8, secondaryQueriesEnabled);
  const pendingOrders = usePendingManualOrdersQuery(secondaryQueriesEnabled);
  const marketHealth = useMarketDataHealthQuery(secondaryQueriesEnabled);
  const holdingMarketEvidenceReview =
    useCurrentHoldingMarketEvidenceReviewQuery(secondaryQueriesEnabled);
  const strategyContribution = useAccountStrategyContributionQuery(
    secondaryQueriesEnabled,
  );
  const todayDecision = useTodayDecisionQuery(secondaryQueriesEnabled);
  const tradingPlan = useDailyTradingPlanQuery(secondaryQueriesEnabled);
  const operationsToday = useOperationsTodayQuery(secondaryQueriesEnabled);
  const assetClassBySymbol = useMemo(
    () =>
      Object.fromEntries(
        (snapshot.data?.positions ?? []).map((position) => [
          position.symbol,
          position.asset_class ??
            snapshot.data?.allocation.find(
              (item) => item.symbol === position.symbol,
            )?.asset_class ??
            '--',
        ]),
      ),
    [snapshot.data],
  );
  const positions = useMemo(
    () => snapshot.data?.positions ?? [],
    [snapshot.data],
  );
  const hasOverviewProjection = overview.data !== undefined;
  const hasPortfolioProjection = snapshot.data !== undefined;
  const hasAnyPrimaryProjection =
    hasOverviewProjection || hasPortfolioProjection;
  const isInitialOverviewLoad =
    !hasAnyPrimaryProjection && (overview.isLoading || snapshot.isLoading);
  const isInitialOverviewError =
    !hasAnyPrimaryProjection && (overview.isError || snapshot.isError);
  const marketCalendarYear = useMemo(() => {
    const years = Array.from(
      new Set(
        (explainability.data?.timeline ?? [])
          .map((row) => row.date?.slice(0, 4))
          .filter((year): year is string => /^\d{4}$/.test(year ?? '')),
      ),
    ).sort();
    return years[years.length - 1] ?? null;
  }, [explainability.data]);
  const marketCalendar = useMarketCalendarQuery(marketCalendarYear);
  const currentShanghaiDate = useMemo(
    () => formatShanghaiDateKey(new Date()),
    [],
  );
  const isCurrentMarketTradingDay = useMemo(
    () => isTradingDayForOverviewPnl(marketCalendar.data, currentShanghaiDate),
    [currentShanghaiDate, marketCalendar.data],
  );
  const todayPnlLabel = isCurrentMarketTradingDay
    ? copy.overview.cards.todayPnl
    : copy.overview.cards.latestTradingDayPnl;
  const todayPnlContext = isCurrentMarketTradingDay
    ? null
    : copy.overview.cards.marketClosedPnlContext;
  const analysisTabs = [
    {
      id: 'performance' as const,
      label: copy.overview.dashboard.equityPanel,
    },
    { id: 'allocation' as const, label: copy.portfolio.allocation.title },
    {
      id: 'attribution' as const,
      label: copy.backtest.page.accountStrategyContributionPublicTitle,
    },
    { id: 'calendar' as const, label: copy.explainability.returnCalendar },
  ];

  return (
    <section className="space-y-5">
      <WorkspaceHeader
        eyebrow={copy.overview.kicker}
        title={copy.overview.title}
        description={copy.overview.subtitle}
      />

      {isInitialOverviewLoad ? (
        <div
          className="min-w-0 space-y-4"
          data-testid="overview-loading-workspace"
        >
          <EvidenceState
            kind="loading"
            statusLabel={copy.states.loading}
            title={copy.overview.loading}
          />
          <section
            aria-hidden="true"
            className="account-overview-summary min-w-0"
            data-testid="overview-loading-summary"
          >
            <dl className="account-primary-metric min-w-0">
              <dt className="app-type-micro font-medium text-[var(--app-text-secondary)]">
                {copy.overview.cards.totalAssets}
              </dt>
              <dd className="mt-2 h-7 w-44 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
              <div className="mt-2 h-2 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
            </dl>
            <div
              className="account-metric-strip account-support-metric-strip app-metric-strip grid min-w-0 sm:grid-flow-row sm:grid-cols-2 lg:grid-flow-row lg:grid-cols-5"
              data-testid="overview-loading-supporting-metrics"
            >
              {[
                todayPnlLabel,
                copy.overview.cards.unrealizedPnl,
                copy.portfolio.table.realized,
                copy.overview.cards.availableCash,
                copy.overview.cards.currentDrawdown,
              ].map((label) => (
                <div
                  key={label}
                  className="app-metric-strip-item min-w-0 px-3 py-2.5"
                >
                  <span className="app-type-label block font-medium text-[var(--app-text-secondary)]">
                    {label}
                  </span>
                  <span className="mt-2 block h-4 w-24 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                </div>
              ))}
            </div>
          </section>
          <div
            className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,0.85fr)]"
            data-testid="overview-loading-daily-workbench"
          >
            <section
              className="min-w-0 space-y-2 xl:order-2"
              data-testid="overview-loading-queue"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.overview.dashboard.todayToReview}
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {copy.overview.dashboard.opsPanel}
                </p>
              </div>
              <div
                aria-hidden="true"
                className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
                data-testid="overview-loading-queue-rows"
              >
                {Array.from({ length: 2 }, (_, index) => (
                  <div key={index} className="min-w-0 px-3 py-3">
                    <span className="block h-3 w-28 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                    <span className="mt-2 block h-3 w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                  </div>
                ))}
              </div>
            </section>
            <section
              className="min-w-0 space-y-2 xl:order-1"
              data-testid="overview-loading-holdings"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.overview.dashboard.positionsPanel}
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                  {copy.overview.dashboard.positionsDetail}
                </p>
              </div>
              <div
                aria-hidden="true"
                className="min-w-0 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
                data-testid="overview-loading-holding-rows"
              >
                {Array.from({ length: 3 }, (_, index) => (
                  <div
                    key={index}
                    className="grid min-h-14 min-w-0 grid-cols-[minmax(0,1fr)_6rem] items-center gap-4 px-3 py-3 sm:grid-cols-[minmax(9rem,1fr)_repeat(3,minmax(5rem,0.55fr))]"
                  >
                    <span className="block h-3 w-36 max-w-full rounded-[var(--app-radius-control)] bg-[var(--app-divider)]" />
                    {Array.from({ length: 3 }, (_, metricIndex) => (
                      <span
                        key={metricIndex}
                        className={`h-3 rounded-[var(--app-radius-control)] bg-[var(--app-divider)] ${
                          metricIndex > 0 ? 'hidden sm:block' : 'block'
                        }`}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      ) : isInitialOverviewError ? (
        <StatusCard
          tone="danger"
          title={copy.states.error}
          detail={copy.overview.error}
          actionLabel={copy.states.retry}
          onAction={() => {
            void overview.refetch();
            void snapshot.refetch();
          }}
        />
      ) : hasAnyPrimaryProjection ? (
        <div className="space-y-5">
          {overview.data ? (
            <OverviewCards
              overview={overview.data}
              variant="workbench"
              todayPnlLabel={todayPnlLabel}
              todayPnlContext={todayPnlContext}
            />
          ) : snapshot.data ? (
            <OverviewSnapshotFallbackCards
              snapshot={snapshot.data}
              todayPnlLabel={todayPnlLabel}
            />
          ) : (
            <EvidenceState
              kind={overview.isError ? 'error' : 'loading'}
              title={
                overview.isError
                  ? copy.portfolio.summary.error
                  : copy.portfolio.summary.loading
              }
              description={
                overview.isError
                  ? copy.portfolio.summary.errorDetail
                  : copy.portfolio.summary.loadingDetail
              }
              action={
                overview.isError ? (
                  <button
                    type="button"
                    className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                    onClick={() => void overview.refetch()}
                  >
                    {copy.states.retry}
                  </button>
                ) : undefined
              }
            />
          )}

          {snapshot.data ? (
            overview.data ? (
              <div
                className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(340px,0.85fr)]"
                data-testid="overview-daily-workbench"
              >
                <div className="min-w-0 xl:order-2">
                  <DashboardTodayQueue
                    overview={overview.data}
                    marketHealth={marketHealth.data}
                    portfolioSnapshot={snapshot.data}
                    marketEvidenceReview={holdingMarketEvidenceReview.data}
                    marketEvidenceReviewLoading={
                      holdingMarketEvidenceReview.isLoading
                    }
                    marketEvidenceReviewError={
                      holdingMarketEvidenceReview.isError
                    }
                    quoteDiagnostics={positions}
                    pendingOrders={pendingOrders.data ?? []}
                    pendingOrdersLoading={pendingOrders.isLoading}
                    pendingOrdersError={pendingOrders.isError}
                    strategyContribution={strategyContribution.data}
                    strategyContributionLoading={strategyContribution.isLoading}
                    strategyContributionError={strategyContribution.isError}
                    todayDecision={todayDecision.data}
                    todayDecisionLoading={todayDecision.isLoading}
                    todayDecisionError={todayDecision.isError}
                    tradingPlan={tradingPlan.data}
                    tradingPlanLoading={tradingPlan.isLoading}
                    tradingPlanError={tradingPlan.isError}
                    operationsToday={operationsToday.data}
                    operationsTodayLoading={operationsToday.isLoading}
                    operationsTodayError={operationsToday.isError}
                  />
                </div>
                <OverviewHoldingsSection
                  positions={positions}
                  assetClassBySymbol={assetClassBySymbol}
                  className="xl:order-1"
                />
              </div>
            ) : (
              <OverviewHoldingsSection
                positions={positions}
                assetClassBySymbol={assetClassBySymbol}
              />
            )
          ) : (
            <section
              className="min-w-0 space-y-2"
              data-testid="overview-holdings-section"
            >
              <h2 className="app-type-section-title text-[var(--app-text)]">
                {copy.overview.dashboard.positionsPanel}
              </h2>
              <EvidenceState
                kind={snapshot.isError ? 'error' : 'loading'}
                title={
                  snapshot.isError
                    ? copy.portfolio.positionsError
                    : copy.portfolio.positionsLoading
                }
                description={copy.overview.dashboard.positionsDetail}
                action={
                  snapshot.isError ? (
                    <button
                      type="button"
                      className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
                      onClick={() => void snapshot.refetch()}
                    >
                      {copy.states.retry}
                    </button>
                  ) : undefined
                }
              />
            </section>
          )}

          {overview.data && snapshot.data ? (
            <>
              <section
                data-testid="overview-performance-card"
                className="min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent"
              >
                <div
                  role="tablist"
                  aria-label={copy.overview.dashboard.equityPanel}
                  className="flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
                >
                  {analysisTabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={analysisView === tab.id}
                      onClick={() => setAnalysisView(tab.id)}
                      className={`h-9 shrink-0 border-b-2 px-3 text-xs font-semibold ${
                        analysisView === tab.id
                          ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                          : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className="min-w-0 py-3 sm:py-4">
                  {analysisView === 'performance' ? (
                    equityCurve.isLoading && !equityCurve.data ? (
                      <EquityCurveSkeleton />
                    ) : equityCurve.isError && !equityCurve.data ? (
                      <StatusCard
                        tone="danger"
                        title={copy.states.error}
                        detail={getEquityCurveErrorDetail(
                          equityCurve.error,
                          copy,
                        )}
                        actionLabel={copy.states.retry}
                        onAction={() => void equityCurve.refetch()}
                      />
                    ) : (
                      <div className="space-y-3">
                        {equityCurve.isError ? (
                          <div
                            role="status"
                            data-testid="equity-curve-refresh-warning"
                            className="app-panel-danger rounded-[var(--app-radius-surface)] px-3 py-2 text-xs leading-5"
                          >
                            {copy.overview.curveRefreshError}
                          </div>
                        ) : null}
                        <EquityCurveCard
                          points={equityCurve.data ?? []}
                          range={equityCurveRange}
                          onRangeChange={setEquityCurveRange}
                        />
                      </div>
                    )
                  ) : analysisView === 'allocation' ? (
                    <PortfolioExposureSummary snapshot={snapshot.data} />
                  ) : analysisView === 'attribution' ? (
                    <StrategyContributionGateCard
                      report={strategyContribution.data}
                      isLoading={strategyContribution.isLoading}
                      isError={strategyContribution.isError}
                      onRetry={() => void strategyContribution.refetch()}
                      instruments={positions}
                      variant="compact"
                    />
                  ) : (
                    <ReturnCalendarCard
                      timeline={explainability.data?.timeline ?? []}
                      positions={positions}
                      marketCalendar={marketCalendar.data}
                      compact
                    />
                  )}
                </div>
              </section>

              <div
                className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]"
                data-testid="overview-review-strip"
              >
                <DashboardMarketPulse
                  marketHealth={marketHealth.data}
                  isLoading={marketHealth.isLoading}
                  isError={marketHealth.isError}
                />
                <section className="min-w-0 border-y border-[var(--app-divider)] bg-transparent py-3 sm:py-4">
                  <div className="mb-3 flex items-end justify-between gap-3">
                    <h2 className="app-type-section-title text-[var(--app-text)]">
                      {copy.overview.dashboard.pendingApprovals}
                    </h2>
                    <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
                      {copy.overview.dashboard.pendingCount(
                        pendingOrders.data?.length ?? 0,
                      )}
                    </span>
                  </div>
                  <DashboardPendingOrders
                    orders={pendingOrders.data ?? []}
                    isLoading={pendingOrders.isLoading}
                    isError={pendingOrders.isError}
                    copy={copy}
                  />
                  <DashboardLedger
                    entries={ledgerEntries.data ?? []}
                    isLoading={ledgerEntries.isLoading}
                    isError={ledgerEntries.isError}
                    copy={copy}
                  />
                </section>
              </div>
            </>
          ) : null}
        </div>
      ) : (
        <StatusCard title={copy.states.empty} detail={copy.overview.empty} />
      )}
    </section>
  );
}

function OverviewHoldingsSection({
  positions,
  assetClassBySymbol,
  className,
}: {
  positions: PortfolioSnapshot['positions'];
  assetClassBySymbol: Record<string, string>;
  className?: string;
}) {
  const copy = useCopy();
  const navigate = useNavigate();

  return (
    <section
      className={`min-w-0 ${className ?? ''}`.trim()}
      data-testid="overview-holdings-section"
    >
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.overview.dashboard.positionsPanel}
          </h2>
          <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {copy.overview.dashboard.positionsDetail}
          </p>
        </div>
        <span className="text-xs tabular-nums text-[var(--app-text-tertiary)]">
          {positions.length} {copy.overview.risk.positions}
        </span>
      </div>
      {positions.length === 0 ? (
        <StatusCard
          title={copy.states.empty}
          detail={copy.portfolio.positionsEmpty}
        />
      ) : (
        <PositionsTable
          positions={positions}
          assetClassBySymbol={assetClassBySymbol}
          variant="dashboard"
          onOpenPosition={(symbol) => {
            void navigate({
              to: '/portfolio/$symbol',
              params: { symbol },
            });
          }}
        />
      )}
    </section>
  );
}

const MARKET_INDEX_DISPLAY_NAMES: Record<string, { en: string; zh: string }> = {
  '000001': { en: 'Shanghai Composite', zh: '上证指数' },
  '399001': { en: 'Shenzhen Component', zh: '深证成指' },
  '399006': { en: 'ChiNext Index', zh: '创业板指' },
  '000300': { en: 'CSI 300', zh: '沪深300' },
  '000905': { en: 'CSI 500', zh: '中证500' },
  '000016': { en: 'SSE 50', zh: '上证50' },
};

function marketPulseToneClass(value: number | null) {
  if (value == null || value === 0) {
    return 'text-[var(--app-pnl-neutral)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

function normalizeMarketPulsePercent(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return Math.abs(value) > 1.5 ? value / 100 : value;
}

function marketPulseChangePct(quote: MarketHealthQuote) {
  return normalizeMarketPulsePercent(
    quote.daily_change_pct ?? quote.change_pct ?? quote.pct_chg,
  );
}

function finiteMarketPulseNumber(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function marketPulseChangeAmount(quote: MarketHealthQuote) {
  return finiteMarketPulseNumber(quote.daily_change ?? quote.change);
}

function marketPulseSignalValue(quote: MarketHealthQuote) {
  return marketPulseChangePct(quote) ?? marketPulseChangeAmount(quote);
}

function formatMarketPulseSignedValue(value: number, locale: Locale) {
  const absolute = new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (value > 0) {
    return `+${absolute}`;
  }
  if (value < 0) {
    return `-${absolute}`;
  }
  return absolute;
}

function marketPulseMoveLabel(
  quote: MarketHealthQuote,
  labels: AppCopy['overview']['dashboard'],
  locale: Locale,
) {
  const changePct = marketPulseChangePct(quote);
  if (changePct !== null) {
    return formatPercentValue(changePct, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  const changeAmount = marketPulseChangeAmount(quote);
  if (changeAmount !== null) {
    return formatMarketPulseSignedValue(changeAmount, locale);
  }
  return labels.marketPulseMoveMissing;
}

function isMarketIndexQuote(quote: MarketHealthQuote) {
  const symbol = quote.symbol.trim();
  const assetClass = quote.asset_class.toLowerCase();
  const text = `${quote.display_name ?? ''} ${quote.name ?? ''}`.toLowerCase();
  return (
    assetClass === 'index' ||
    symbol in MARKET_INDEX_DISPLAY_NAMES ||
    text.includes('index') ||
    text.includes('指数') ||
    text.includes('上证') ||
    text.includes('深证') ||
    text.includes('创业板') ||
    text.includes('沪深') ||
    text.includes('中证')
  );
}

function marketIndexDisplayName(quote: MarketHealthQuote, locale: Locale) {
  const fallback = MARKET_INDEX_DISPLAY_NAMES[quote.symbol];
  return (
    quote.display_name?.trim() ||
    quote.name?.trim() ||
    (fallback ? fallback[locale] : null) ||
    quote.symbol
  );
}

function marketPulseSignalLabel(
  quotes: MarketHealthQuote[],
  labels: AppCopy['overview']['dashboard'],
) {
  const changes = quotes
    .map((quote) => marketPulseSignalValue(quote))
    .filter((value): value is number => value !== null);
  if (quotes.length === 0) {
    return labels.marketPulsePending;
  }
  if (changes.length === 0) {
    return labels.marketPulseNoSignal;
  }
  const positiveCount = changes.filter((value) => value > 0).length;
  const negativeCount = changes.filter((value) => value < 0).length;
  if (positiveCount > negativeCount) {
    return labels.marketPulsePositive;
  }
  if (negativeCount > positiveCount) {
    return labels.marketPulseNegative;
  }
  return labels.marketPulseMixed;
}

function DashboardMarketPulse({
  marketHealth,
  isLoading,
  isError,
}: {
  marketHealth?: MarketDataHealthResponse;
  isLoading: boolean;
  isError: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const labels = copy.overview.dashboard;
  const indexQuotes = useMemo(
    () =>
      (marketHealth?.quotes ?? [])
        .filter(isMarketIndexQuote)
        .sort((left, right) => {
          const leftKnown = left.symbol in MARKET_INDEX_DISPLAY_NAMES ? 0 : 1;
          const rightKnown = right.symbol in MARKET_INDEX_DISPLAY_NAMES ? 0 : 1;
          return (
            leftKnown - rightKnown || left.symbol.localeCompare(right.symbol)
          );
        })
        .slice(0, 4),
    [marketHealth?.quotes],
  );
  const signalLabel = marketPulseSignalLabel(indexQuotes, labels);
  const changeValues = indexQuotes
    .map((quote) => marketPulseSignalValue(quote))
    .filter((value): value is number => value !== null);
  const missingChangeCount = indexQuotes.length - changeValues.length;
  const marketPulseCoverageLabel =
    missingChangeCount > 0
      ? labels.marketPulseMissingChanges(missingChangeCount)
      : labels.marketPulseChangeCoverage(
          changeValues.length,
          indexQuotes.length,
        );
  const sourceStatus = formatPublicStatus(
    marketHealth?.source_health ?? marketHealth?.provider_status,
    locale,
  );

  return (
    <section
      className="min-w-0 overflow-hidden border-y border-[var(--app-divider)] bg-transparent"
      data-testid="overview-market-pulse"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--app-divider)] py-2.5">
        <div className="min-w-0">
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {labels.marketPulse}
          </h2>
          <div className="mt-1 max-w-3xl text-xs text-[var(--app-text-secondary)]">
            {labels.marketPulseDetail}
          </div>
        </div>
        <a
          href="/market"
          className="app-button-secondary rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-xs font-semibold"
        >
          {labels.viewMarket}
        </a>
      </div>

      <div className="min-w-0 py-3">
        {isLoading ? (
          <EvidenceState kind="loading" title={copy.states.loading} />
        ) : isError ? (
          <EvidenceState kind="error" title={copy.states.error} />
        ) : indexQuotes.length === 0 ? (
          <EvidenceState
            kind="missing"
            title={labels.marketPulsePending}
            description={labels.marketPulseMissing}
          />
        ) : (
          <div className="grid min-w-0 gap-3">
            <MetricStrip
              ariaLabel={labels.marketPulse}
              items={[
                {
                  id: 'signal',
                  label: labels.marketPulseDisclosure,
                  value: (
                    <span
                      className="block whitespace-normal break-words"
                      title={signalLabel}
                    >
                      {signalLabel}
                    </span>
                  ),
                },
                {
                  id: 'source',
                  label: labels.dataStatus,
                  value: sourceStatus,
                  detail: marketPulseCoverageLabel,
                  tone: missingChangeCount > 0 ? 'warning' : 'neutral',
                },
              ]}
            />
            <div className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {indexQuotes.map((quote) => {
                const changeValue = marketPulseSignalValue(quote);
                const changeMissing = changeValue === null;
                const changeAmount = marketPulseChangeAmount(quote);
                const changePct = marketPulseChangePct(quote);
                const displayName = marketIndexDisplayName(quote, locale);
                const quoteStatus = formatPublicStatus(
                  quote.quote_status,
                  locale,
                );
                return (
                  <a
                    href={`/market?symbol=${encodeURIComponent(quote.symbol)}`}
                    key={quote.symbol}
                    className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-2 py-2 hover:bg-[var(--app-accent-bg)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-[var(--app-text)]">
                        {displayName}
                      </div>
                      <div className="app-type-micro mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[var(--app-text-tertiary)]">
                        <span className="font-mono">{quote.symbol}</span>
                        <span>{quoteStatus}</span>
                        <span>{formatTimestamp(quote.timestamp)}</span>
                      </div>
                    </div>

                    <div className="grid shrink-0 justify-items-end gap-1">
                      <span className="font-mono text-sm font-semibold text-[var(--app-soft)] tabular-nums">
                        {formatPrice(quote.price)}
                      </span>
                      <span
                        data-testid={`market-pulse-change-amount-${quote.symbol}`}
                        className={`font-mono text-xs font-semibold tabular-nums ${marketPulseToneClass(
                          changeValue,
                        )} ${changeMissing ? 'text-[var(--app-warning-text)]' : ''}`}
                      >
                        {changeAmount === null
                          ? marketPulseMoveLabel(quote, labels, locale)
                          : formatMarketPulseSignedValue(changeAmount, locale)}
                      </span>
                      {changePct !== null && changeAmount !== null ? (
                        <span
                          data-testid={`market-pulse-change-pct-${quote.symbol}`}
                          className={`font-mono text-[length:var(--app-font-size-micro)] font-semibold tabular-nums ${marketPulseToneClass(
                            changePct,
                          )}`}
                        >
                          {formatPercentValue(changePct, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })}
                        </span>
                      ) : null}
                    </div>
                  </a>
                );
              })}
            </div>
            <div
              className="border-l-2 border-[var(--app-warning-indicator)] bg-[var(--app-warning-bg)] px-3 py-2"
              data-testid="market-breadth-heatmap-unavailable"
            >
              <div className="text-xs font-semibold text-[var(--app-warning-text)]">
                {labels.marketHeatmapUnavailable}
              </div>
              <div className="app-type-compact mt-1 text-[var(--app-text-secondary)]">
                {labels.marketHeatmapUnavailableDetail}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function DashboardPendingOrders({
  orders,
  isLoading,
  isError,
  copy,
}: {
  orders: ManualOrder[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  if (isLoading) {
    return <EvidenceState kind="loading" title={copy.trading.orders.loading} />;
  }

  if (isError) {
    return (
      <EvidenceState kind="error" title={copy.trading.orders.loadFailed} />
    );
  }

  if (orders.length === 0) {
    return (
      <EvidenceState
        kind="empty"
        title={copy.overview.dashboard.pendingEmpty}
        description={copy.overview.dashboard.pendingEmptyDetail}
      />
    );
  }

  return (
    <div className="max-h-[270px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
      {orders.map((order) => {
        const normalizedSide = order.side.toLowerCase();
        const isBuy = normalizedSide === 'buy';
        const isSell = normalizedSide === 'sell';
        const sideToneClass = isBuy
          ? 'border-[color-mix(in_srgb,var(--app-chart-buy)_56%,transparent)] text-[var(--app-chart-buy)]'
          : isSell
            ? 'border-[color-mix(in_srgb,var(--app-chart-sell)_56%,transparent)] text-[var(--app-chart-sell)]'
            : 'border-[var(--app-warning-border)] text-[var(--app-warning-text)]';
        const sideLabel = formatLedgerOrderSideLabel(order.side, locale);
        const displayName = order.display_name ?? order.name ?? null;
        const instrumentNames = displayName
          ? new Map([[order.symbol.toLowerCase(), displayName]])
          : undefined;
        const instrumentLabel = formatInstrumentDisplayLabelFromNameMap(
          order.symbol,
          instrumentNames,
        );
        return (
          <div
            key={order.order_id}
            className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="app-type-subsection-title truncate">
                  {instrumentLabel}
                </div>
                <div className="app-muted mt-1 text-xs">
                  {formatTimestamp(order.timestamp)}
                </div>
              </div>
              <div
                className={`rounded-[var(--app-radius-control)] border bg-transparent px-2 py-1 text-xs font-semibold ${sideToneClass}`}
              >
                {sideLabel}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3 text-xs tabular-nums">
              <MetricLine
                label={copy.trading.orders.quantity}
                value={formatQuantity(order.quantity)}
              />
              <MetricLine
                label={copy.trading.orders.price}
                value={formatPrice(order.price)}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DashboardLedger({
  entries,
  isLoading,
  isError,
  copy,
}: {
  entries: LedgerEntry[];
  isLoading: boolean;
  isError: boolean;
  copy: AppCopy;
}) {
  const { locale } = usePreferences();
  return (
    <div className="mt-4 border-t border-[var(--app-divider)] pt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-[var(--app-text)]">
          {copy.overview.dashboard.ledgerPanel}
        </div>
        <div className="shrink-0 text-xs font-medium text-[var(--app-text-tertiary)] tabular-nums">
          {copy.overview.dashboard.ledgerCount(entries.length)}
        </div>
      </div>
      {isLoading ? (
        <EvidenceState kind="loading" title={copy.states.loading} />
      ) : isError ? (
        <EvidenceState kind="error" title={copy.states.error} />
      ) : entries.length === 0 ? (
        <EvidenceState
          kind="empty"
          title={copy.overview.dashboard.ledgerEmpty}
        />
      ) : (
        <div className="max-h-[340px] divide-y divide-[var(--app-divider)] overflow-y-auto border-y border-[var(--app-divider)]">
          {entries.map((entry) => {
            const presentation = formatLedgerDashboardPresentation(
              entry,
              copy.activity.feed.detailFields,
              locale,
              formatAssetClassLabel(entry.asset_class, copy.common),
            );
            return (
              <div
                key={entry.id}
                className="px-2 py-2.5 transition-colors hover:bg-[var(--app-accent-bg)]"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">
                      {presentation.title}
                    </div>
                    <div className="app-muted mt-1 text-xs">
                      {formatTimestamp(entry.timestamp)}
                    </div>
                    <div className="app-muted mt-2 flex flex-wrap gap-x-2 gap-y-1 text-xs">
                      {presentation.details.map((detail) => (
                        <span key={detail}>{detail}</span>
                      ))}
                    </div>
                    {presentation.publicNote ? (
                      <div className="app-muted mt-2 break-words text-xs leading-5">
                        {presentation.publicNote}
                      </div>
                    ) : null}
                  </div>
                  <div
                    className="shrink-0 whitespace-nowrap text-right font-mono text-sm font-semibold tabular-nums text-[var(--app-text-secondary)]"
                    data-testid={`dashboard-ledger-amount-${entry.id}`}
                  >
                    {presentation.amount}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <dl className="min-w-0">
      <dt className="text-[length:var(--app-font-size-micro)] font-medium text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd className="mt-0.5 truncate font-mono font-semibold text-[var(--app-text)]">
        {value}
      </dd>
    </dl>
  );
}

function StatusCard({
  title,
  detail,
  tone = 'default',
  actionLabel,
  onAction,
}: {
  title: string;
  detail: string;
  tone?: 'default' | 'danger';
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div
      className={
        tone === 'danger'
          ? 'app-panel-danger rounded-3xl p-4 sm:p-5'
          : 'app-terminal-panel rounded-3xl p-4 sm:p-5'
      }
    >
      <div className="app-type-subsection-title">{title}</div>
      <div className="mt-2 text-sm opacity-80">{detail}</div>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="app-button-secondary mt-4 rounded-2xl px-4 py-2 text-sm"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

function getEquityCurveErrorDetail(error: unknown, copy: AppCopy) {
  const detail = getErrorMessage(error);
  if (
    detail.includes(
      'Current valuation facts have not been published as an immutable snapshot',
    )
  ) {
    return copy.overview.curveSnapshotPending;
  }
  return `${copy.overview.curveError} ${detail}`;
}

export const Route = createLazyRoute('/overview')({
  component: OverviewPage,
});
