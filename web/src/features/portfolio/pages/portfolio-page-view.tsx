import {
  formatCurrency as formatCurrencyValue,
  formatPercent,
  formatValuationTimestamp,
} from '../../../shared/format';
import { PublicationStatus } from '../../../shared/portfolio-evidence/publication-status';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  Button,
  EvidenceIdentityDisclosure,
  EvidenceState,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { RebalanceAlertBanner } from '../components/rebalance-alert-banner';
import { PortfolioEvidenceReviewPanel } from './portfolio-evidence-review-panel';
import { PortfolioPageLoadingView } from './portfolio-page-loading-view';
import type {
  PortfolioPageActions,
  PortfolioPageModel,
} from './portfolio-page-model';
import {
  PortfolioAnalysisSection,
  PortfolioCurrentHoldingsSection,
  PortfolioHistorySection,
} from './portfolio-page-sections';

export function PortfolioPageView({
  actions,
  model,
}: {
  actions: PortfolioPageActions;
  model: PortfolioPageModel;
}) {
  const { copy, locale, snapshot, state } = model.source;
  if (model.isInitialPortfolioLoad) {
    return <PortfolioPageLoadingView copy={copy} />;
  }
  return (
    <section
      className="app-workbench-route space-y-3 pb-8 sm:space-y-4"
      data-workbench-route="portfolio"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        eyebrow={copy.portfolio.kicker}
        title={copy.portfolio.title}
        context={model.portfolioIdentity}
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
                  value: formatValuationTimestamp(
                    snapshot.data.valuation_as_of,
                  ),
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

      <PublicationStatus
        snapshotId={snapshot.data?.valuation_snapshot_id}
        asOf={snapshot.data?.valuation_as_of}
        showAsOf={false}
      />
      <div data-testid="portfolio-summary-strip">
        {snapshot.data ? (
          <div
            className="min-w-0 border-b border-[var(--app-divider)] pb-4"
            aria-label={copy.portfolio.summary.ariaLabel}
          >
            <dl className="grid min-w-0 grid-cols-2 gap-4 py-2 md:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))] md:items-end md:gap-6">
              <div className="min-w-0">
                <dt className="text-xs text-[var(--app-text-secondary)]">
                  {copy.portfolio.summary.totalEquity}
                </dt>
                <dd className="mt-1 break-words app-type-primary-metric tabular-nums text-[var(--app-text)]">
                  {formatCurrencyValue(snapshot.data.total_equity)}
                </dd>
                <p className="sr-only">
                  {copy.portfolio.summary.totalEquityDetail}
                </p>
              </div>
              {[
                {
                  id: 'cash',
                  label: copy.portfolio.summary.cash,
                  value: snapshot.data.cash,
                  detail: copy.portfolio.summary.cashDetail,
                },
                {
                  id: 'today-pnl',
                  label: copy.portfolio.summary.todayPnl,
                  value: model.totalTodayChange,
                  detail: copy.portfolio.summary.todayPnlDetail,
                },
                {
                  id: 'unrealized-pnl',
                  label: copy.portfolio.summary.unrealizedPnl,
                  value: model.totalUnrealizedPnl,
                  detail: copy.portfolio.summary.unrealizedPnlDetail,
                },
              ].map((metric) => (
                <div
                  key={metric.id}
                  className="min-w-0 md:border-l md:border-[var(--app-divider)] md:pl-6"
                >
                  <dt className="text-xs text-[var(--app-text-secondary)]">
                    {metric.label}
                  </dt>
                  <dd
                    className={`mt-1 break-words text-xl font-semibold tabular-nums ${metric.id !== 'cash' && metric.value != null && metric.value !== 0 ? (metric.value > 0 ? 'text-[var(--app-pnl-positive)]' : 'text-[var(--app-pnl-negative)]') : 'text-[var(--app-text)]'}`}
                  >
                    {formatCurrencyValue(metric.value)}
                    {metric.id === 'unrealized-pnl' &&
                    model.totalUnrealizedPnlPct != null ? (
                      <span className="ml-2 whitespace-nowrap text-xs">
                        {formatPercent(model.totalUnrealizedPnlPct, {
                          signDisplay: 'always',
                        })}
                      </span>
                    ) : null}
                  </dd>
                  {metric.id === 'today-pnl' &&
                  snapshot.data.performance_session_date ? (
                    <p className="mt-1 text-xs tabular-nums text-[var(--app-text-tertiary)]">
                      {snapshot.data.performance_session_date}
                    </p>
                  ) : null}
                  <p className="sr-only">{metric.detail}</p>
                </div>
              ))}
            </dl>
            <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-[var(--app-divider)] pt-3 text-xs">
              <div className="flex flex-wrap items-baseline gap-2">
                <dt className="text-[var(--app-text-secondary)]">
                  {copy.portfolio.summary.marketValue}
                </dt>
                <dd className="font-mono tabular-nums text-[var(--app-text)]">
                  {formatCurrencyValue(model.totalMarketValue)}
                </dd>
                <p className="sr-only">
                  {copy.portfolio.summary.marketValueDetail}
                </p>
              </div>
              <div className="flex flex-wrap items-baseline gap-2">
                <dt className="text-[var(--app-text-secondary)]">
                  {copy.portfolio.summary.realizedPnl}
                </dt>
                <dd
                  className={`font-mono tabular-nums ${snapshot.data.realized_pnl_total != null && snapshot.data.realized_pnl_total !== 0 ? (snapshot.data.realized_pnl_total > 0 ? 'text-[var(--app-pnl-positive)]' : 'text-[var(--app-pnl-negative)]') : 'text-[var(--app-text)]'}`}
                >
                  {formatCurrencyValue(snapshot.data.realized_pnl_total)}
                </dd>
                <p className="sr-only">
                  {copy.portfolio.summary.realizedPnlDetail}
                </p>
              </div>
            </dl>
          </div>
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
                <Button variant="secondary" onClick={actions.onRetrySnapshot}>
                  {copy.states.retry}
                </Button>
              ) : undefined
            }
          />
        )}
      </div>

      <RebalanceAlertBanner
        copy={copy.portfolio}
        tradingPlan={model.tradingPlan}
      />

      <PortfolioCurrentHoldingsSection actions={actions} model={model} />
      {state.evidenceFilter !== 'clear' ? (
        <PortfolioEvidenceReviewPanel
          copy={copy}
          items={model.evidenceReviewItems}
          locale={locale}
        />
      ) : null}
      <PortfolioAnalysisSection actions={actions} model={model} />
      <PortfolioHistorySection actions={actions} model={model} />
    </section>
  );
}
