import { formatCurrency, formatPercent } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import { strategySourceDisplayName } from './backtest-page-model';
import { useBacktestPage } from './backtest-page-context';

export function BacktestPageHeader() {
  const {
    copy,
    labels,
    locale,
    mobileWorkspaceView,
    parameterSchema,
    readiness,
    selectedAssetClassLabel,
    selectedReadiness,
    selectedStrategy,
    setMobileWorkspaceTouched,
    setMobileWorkspaceView,
    summary,
    symbol,
  } = useBacktestPage();
  return (
    <>
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={labels.decisionHandoffResearchOnly}
      />

      <MetricStrip
        ariaLabel={labels.title}
        className="app-backtest-context-strip app-backtest-evidence-strip app-horizontal-scroll-cue"
        items={[
          {
            id: 'strategy',
            label: labels.strategy,
            value: strategyDisplayName(selectedStrategy, labels.strategyNames),
            detail: strategySourceDisplayName(selectedStrategy, labels),
          },
          {
            id: 'instrument',
            label: labels.symbol,
            value: symbol || labels.notDeclared,
            detail: selectedAssetClassLabel,
          },
          {
            id: 'parameters',
            label: labels.formKicker,
            value: parameterSchema.length,
            detail: labels.runReadinessDatasetPending,
          },
          {
            id: 'latest-result',
            label: labels.currentKicker,
            value: summary
              ? formatPercent(summary.returnValue)
              : labels.notDeclared,
            detail: summary
              ? `${labels.totalCost}: ${formatCurrency(summary.cost)}`
              : labels.emptyCurrent,
          },
          {
            id: 'promotion-readiness',
            label: labels.promotionReadiness,
            value: readiness.isLoading
              ? copy.shell.checking
              : selectedReadiness
                ? formatPublicStatus(selectedReadiness.promotion_status, locale)
                : labels.notDeclared,
            detail: selectedReadiness
              ? labels.promotionRequirementsCount(
                  selectedReadiness.missing_requirements.length,
                )
              : labels.promotionEvidenceUnavailable,
            tone: selectedReadiness
              ? selectedReadiness.is_promotable
                ? 'neutral'
                : 'warning'
              : 'neutral',
          },
        ]}
      />

      <div
        aria-label={labels.title}
        className="flex border-y border-[var(--app-divider)] xl:hidden"
        data-workspace-view={mobileWorkspaceView}
        data-testid="backtest-mobile-workspace-tabs"
        role="tablist"
      >
        {[
          { id: 'setup' as const, label: labels.formKicker },
          { id: 'results' as const, label: labels.resultsWorkspaceTab },
        ].map((item) => (
          <button
            aria-controls={`backtest-mobile-${item.id}`}
            aria-selected={mobileWorkspaceView === item.id}
            className={`min-h-10 flex-1 border-b-2 px-3 text-xs font-semibold transition-colors ${
              mobileWorkspaceView === item.id
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)]'
            }`}
            key={item.id}
            onClick={() => {
              setMobileWorkspaceTouched(true);
              setMobileWorkspaceView(item.id);
            }}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
    </>
  );
}
