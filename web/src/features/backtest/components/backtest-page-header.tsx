import { formatPublicStatus } from '../../../shared/public-labels';
import { formatStrategyDisplayName as strategyDisplayName } from '../../../shared/strategy-display';
import { MetricStrip, WorkspaceHeader } from '../../../shared/ui/workbench';
import { strategySourceDisplayName } from './backtest-page-model';
import { useBacktestPage } from './backtest-page-context';

export function BacktestDraftContext() {
  const {
    copy,
    labels,
    locale,
    parameterSchema,
    readiness,
    selectedAssetClassLabel,
    selectedReadiness,
    selectedStrategy,
    symbol,
    runAssets,
  } = useBacktestPage();
  return (
    <section aria-label={labels.nextRunConfiguration} className="min-w-0">
      <h2 className="app-kicker mb-2">{labels.nextRunConfiguration}</h2>
      <MetricStrip
        ariaLabel={labels.nextRunConfiguration}
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
    </section>
  );
}

export function BacktestPageHeader() {
  const {
    labels,
    mobileWorkspaceView,
    setMobileWorkspaceTouched,
    setMobileWorkspaceView,
  } = useBacktestPage();
  const tabs = [
    { id: 'results' as const, label: labels.resultsWorkspaceTab },
    { id: 'setup' as const, label: labels.setupWorkspaceTab },
    { id: 'observations' as const, label: labels.observationsWorkspaceTab },
  ];
  return (
    <>
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
      />
      <div
        aria-label={labels.title}
        className="flex min-w-0 gap-4 border-b border-[var(--app-divider)] sm:gap-8"
        data-workspace-view={mobileWorkspaceView}
        data-testid="backtest-mobile-workspace-tabs"
        role="tablist"
      >
        {tabs.map((item, index) => (
          <button
            aria-controls={`backtest-mobile-${item.id === 'observations' ? 'results' : item.id}`}
            aria-label={item.label}
            aria-selected={mobileWorkspaceView === item.id}
            className={`relative min-h-12 min-w-0 border-b-2 px-1 py-3 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] ${
              mobileWorkspaceView === item.id
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
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
            {item.id === 'results' ? (
              <>
                <span className="sm:hidden">{labels.resultsShortTab}</span>
                <span className="hidden sm:inline">{item.label}</span>
              </>
            ) : (
              item.label
            )}
          </button>
        ))}
      </div>
    </>
  );
}
