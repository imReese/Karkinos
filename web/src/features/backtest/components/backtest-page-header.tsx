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
    symbol,
    runAssets,
  } = useBacktestPage();
  return (
    <>
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
      />

      <section aria-label={labels.nextRunConfiguration} className="min-w-0">
        <h2 className="app-kicker mb-2">{labels.nextRunConfiguration}</h2>
        <MetricStrip
          ariaLabel={labels.nextRunConfiguration}
          className="app-backtest-context-strip app-backtest-evidence-strip app-horizontal-scroll-cue"
          items={[
            {
              id: 'strategy',
              label: labels.strategy,
              value: strategyDisplayName(
                selectedStrategy,
                labels.strategyNames,
              ),
              detail: strategySourceDisplayName(selectedStrategy, labels),
            },
            {
              id: 'instrument',
              label: labels.symbol,
              value:
                runAssets?.map((asset) => asset.symbol).join(', ') ||
                symbol ||
                labels.notDeclared,
              detail: selectedAssetClassLabel,
            },
            {
              id: 'parameters',
              label: labels.formKicker,
              value: parameterSchema.length,
              detail: labels.runReadinessDatasetPending,
            },
            {
              id: 'promotion-readiness',
              label: labels.promotionReadiness,
              value: readiness.isLoading
                ? copy.shell.checking
                : selectedReadiness
                  ? formatPublicStatus(
                      selectedReadiness.promotion_status,
                      locale,
                    )
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
      </section>

      <div
        aria-label={labels.title}
        className="flex items-center gap-1 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-1 xl:hidden"
        data-workspace-view={mobileWorkspaceView}
        data-testid="backtest-mobile-workspace-tabs"
        role="tablist"
      >
        {[
          { id: 'setup' as const, label: labels.formKicker },
          { id: 'results' as const, label: labels.resultsWorkspaceTab },
        ].map((item, index, tabs) => (
          <button
            aria-controls={`backtest-mobile-${item.id}`}
            aria-selected={mobileWorkspaceView === item.id}
            className={`min-h-9 flex-1 rounded-[calc(var(--app-radius-control)-2px)] px-4 text-xs font-semibold transition-all ${
              mobileWorkspaceView === item.id
                ? 'bg-[var(--app-surface)] text-[var(--app-accent)] shadow-sm'
                : 'text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
            }`}
            key={item.id}
            id={`backtest-tab-${item.id}`}
            onClick={() => {
              setMobileWorkspaceTouched(true);
              setMobileWorkspaceView(item.id);
            }}
            onKeyDown={(event) => {
              const nextIndex =
                event.key === 'ArrowRight'
                  ? (index + 1) % tabs.length
                  : event.key === 'ArrowLeft'
                    ? (index - 1 + tabs.length) % tabs.length
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? tabs.length - 1
                        : null;
              if (nextIndex === null) return;
              event.preventDefault();
              setMobileWorkspaceTouched(true);
              setMobileWorkspaceView(tabs[nextIndex].id);
              event.currentTarget.parentElement
                ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
                [nextIndex]?.focus();
            }}
            role="tab"
            tabIndex={mobileWorkspaceView === item.id ? 0 : -1}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
    </>
  );
}
