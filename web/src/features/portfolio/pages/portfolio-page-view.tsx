import {
  formatCurrency as formatCurrencyValue,
  formatTimestamp,
} from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  EvidenceIdentityDisclosure,
  EvidenceState,
  MetricStrip,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
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
    <section className="space-y-4 sm:space-y-5">
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
                  onClick={actions.onRetrySnapshot}
                >
                  {copy.states.retry}
                </button>
              ) : undefined
            }
          />
        )}
      </div>

      {state.evidenceFilter !== 'clear' ? (
        <PortfolioEvidenceReviewPanel
          copy={copy}
          items={model.evidenceReviewItems}
          locale={locale}
        />
      ) : null}
      <PortfolioCurrentHoldingsSection actions={actions} model={model} />
      <PortfolioAnalysisSection actions={actions} model={model} />
      <PortfolioHistorySection actions={actions} model={model} />
    </section>
  );
}
