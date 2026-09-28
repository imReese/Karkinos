import {
  formatCurrency as formatCurrencyValue,
  formatPercent,
  formatTimestamp,
} from '../../../shared/format';
import { PublicationStatus } from '../../../shared/portfolio-evidence/publication-status';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  Button,
  EvidenceIdentityDisclosure,
  EvidenceState,
  MetricStrip,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { PortfolioAllocationBar } from '../components/allocation-card';
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
      className="app-workbench-route space-y-3 sm:space-y-4"
      data-workbench-route="portfolio"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        eyebrow={copy.portfolio.kicker}
        title={copy.portfolio.title}
        description={copy.portfolio.subtitle}
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

      <PublicationStatus
        snapshotId={snapshot.data?.valuation_snapshot_id}
        asOf={snapshot.data?.valuation_as_of}
      />
      <div data-testid="portfolio-summary-strip">
        {snapshot.data ? (
          <MetricStrip
            ariaLabel={copy.portfolio.summary.ariaLabel}
            items={[
              {
                id: 'total-equity',
                label: copy.portfolio.summary.totalEquity,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(snapshot.data.total_equity)}
                  </span>
                ),
                detail: copy.portfolio.summary.totalEquityDetail,
              },
              {
                id: 'market-value',
                label: copy.portfolio.summary.marketValue,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(model.totalMarketValue)}
                  </span>
                ),
                detail: copy.portfolio.summary.marketValueDetail,
              },
              {
                id: 'cash',
                label: copy.portfolio.summary.cash,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(snapshot.data.cash)}
                  </span>
                ),
                detail: copy.portfolio.summary.cashDetail,
              },
              {
                id: 'today-pnl',
                label: copy.portfolio.summary.todayPnl,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(model.totalTodayChange)}
                    {model.totalTodayChangePct != null ? (
                      <span className="ml-1 text-xs opacity-80">
                        (
                        {formatPercent(model.totalTodayChangePct, {
                          signDisplay: 'always',
                        })}
                        )
                      </span>
                    ) : null}
                  </span>
                ),
                detail: copy.portfolio.summary.todayPnlDetail,
                tone:
                  model.totalTodayChange !== 0
                    ? model.totalTodayChange > 0
                      ? 'pnl-positive'
                      : 'pnl-negative'
                    : undefined,
              },
              {
                id: 'unrealized-pnl',
                label: copy.portfolio.summary.unrealizedPnl,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(model.totalUnrealizedPnl)}
                    {model.totalUnrealizedPnlPct != null ? (
                      <span className="ml-1 text-xs opacity-80">
                        (
                        {formatPercent(model.totalUnrealizedPnlPct, {
                          signDisplay: 'always',
                        })}
                        )
                      </span>
                    ) : null}
                  </span>
                ),
                detail: copy.portfolio.summary.unrealizedPnlDetail,
                tone:
                  model.totalUnrealizedPnl !== 0
                    ? model.totalUnrealizedPnl > 0
                      ? 'pnl-positive'
                      : 'pnl-negative'
                    : undefined,
              },
              {
                id: 'realized-pnl',
                label: copy.portfolio.summary.realizedPnl,
                value: (
                  <span className="font-mono">
                    {formatCurrencyValue(snapshot.data.realized_pnl_total)}
                  </span>
                ),
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
                <Button variant="secondary" onClick={actions.onRetrySnapshot}>
                  {copy.states.retry}
                </Button>
              ) : undefined
            }
          />
        )}
      </div>

      {snapshot.data?.allocation && snapshot.data.allocation.length > 0 ? (
        <section
          aria-label={copy.portfolio.allocation.title}
          className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3"
          data-testid="portfolio-exposed-allocation"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="app-type-label font-medium text-[var(--app-text-secondary)]">
              {copy.portfolio.allocation.title}
            </span>
          </div>
          <PortfolioAllocationBar
            items={snapshot.data.allocation}
            testId="portfolio-top-allocation-bar"
            className="space-y-2"
          />
        </section>
      ) : null}

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
