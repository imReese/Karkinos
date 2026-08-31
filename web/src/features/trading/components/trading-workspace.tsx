import { formatTimestamp } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  StatusBadge as WorkbenchStatusBadge,
  WorkspaceHeader,
} from '../../../shared/ui/workbench';
import { ExecutionAuditPanel } from './execution-audit-panel';
import { TradingHistory } from './trading-history';
import { TradingReviewQueue } from './trading-review-queue';
import { TradingSafetyRail } from './trading-safety-rail';
import { getErrorMessage } from './trading-execution-format';
import { useTradingPageController } from './use-trading-page-controller';

export function TradingWorkspace() {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const controller = useTradingPageController();
  const {
    counts,
    latestTimestamp,
    orderFacts,
    fillFacts,
    instrumentNames,
    shadowRun,
    paperShadowRun,
    reviewShadowRun,
    handleAcceptSimulationReview,
  } = controller;

  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="trading"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
      />

      <section
        className="grid min-w-0 gap-3 border-y border-[var(--app-divider)] py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
        data-testid="trading-review-posture"
      >
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="app-product-mark">{labels.statusCheck}</span>
          <span className="app-type-primary-metric font-mono tabular-nums text-[var(--app-text)]">
            {counts.pending}
          </span>
          <span className="text-sm font-semibold text-[var(--app-text-secondary)]">
            {labels.pending}
          </span>
          <span className="app-muted min-w-0 text-xs">
            {labels.lastUpdated}: {formatTimestamp(latestTimestamp)}
          </span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2 sm:justify-end">
          <span className="app-muted text-xs font-semibold">
            {labels.operatingMode}
          </span>
          <WorkbenchStatusBadge tone="success">
            {labels.manualDefault}
          </WorkbenchStatusBadge>
          <WorkbenchStatusBadge tone="neutral">
            {labels.brokerBridgeDisabled}
          </WorkbenchStatusBadge>
        </div>
      </section>

      <div className="app-trading-command-grid grid min-w-0 gap-5 sm:gap-6">
        <TradingReviewQueue controller={controller} />
        <TradingSafetyRail controller={controller} locale={locale} />
      </div>

      <ExecutionAuditPanel
        orders={orderFacts.data ?? []}
        fills={fillFacts.data ?? []}
        loading={orderFacts.isLoading || fillFacts.isLoading}
        error={orderFacts.isError || fillFacts.isError}
        instrumentNames={instrumentNames}
        shadowRunPending={shadowRun.isPending}
        shadowRunResult={shadowRun.data ?? null}
        paperShadowRun={paperShadowRun}
        reviewPending={reviewShadowRun.isPending}
        reviewResult={reviewShadowRun.data ?? null}
        reviewError={
          reviewShadowRun.isError ? getErrorMessage(reviewShadowRun.error) : ''
        }
        onRunShadowReview={() => void shadowRun.mutate()}
        onAcceptSimulationReview={() => void handleAcceptSimulationReview()}
      />

      <TradingHistory controller={controller} />
    </section>
  );
}
