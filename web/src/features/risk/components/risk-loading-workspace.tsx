import {
  EvidenceState,
  ExceptionList,
  MetricStrip,
} from '../../../shared/ui/workbench';
import type { RiskPageController } from '../model/use-risk-page-controller';
import {
  formatRiskAlertLevel,
  getRiskMetricLabel,
} from '../model/risk-presentation';

export function RiskLoadingWorkspace({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, locale, state, workspace } = controller;
  return (
    <div
      className="min-w-0 space-y-4"
      data-testid={
        controller.hasAnyRiskProjection
          ? 'risk-partial-workspace'
          : 'risk-loading-workspace'
      }
    >
      {controller.hasAnyRiskProjection ? (
        <p className="sr-only" role="status">
          {copy.riskPage.loading}
        </p>
      ) : (
        <EvidenceState
          kind="loading"
          title={copy.riskPage.loadingTitle}
          description={copy.riskPage.loading}
        />
      )}
      <div className="app-risk-command-grid grid min-w-0 gap-5 sm:gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(300px,360px)] xl:items-start">
        <section
          aria-busy={!state.data}
          className="min-w-0 space-y-2"
          data-testid="risk-loading-blocking-register"
        >
          <div>
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.riskPage.blockingRegister}
            </h2>
            <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
              {copy.riskPage.blockingRegisterDetail}
            </p>
          </div>
          {state.data ? (
            <div className="min-w-0" data-testid="risk-loading-live-exceptions">
              <ExceptionList
                ariaLabel={copy.riskPage.blockingRegister}
                emptyState={copy.riskPage.noBlockingItems}
                density="compact"
                labels={riskExceptionLabels(locale)}
                items={controller.activeRiskItems}
                className="[&>li>dl]:grid-cols-2 2xl:[&>li>dl]:grid-cols-4"
              />
            </div>
          ) : (
            <EvidenceState
              kind="loading"
              statusLabel={copy.states.loading}
              title={copy.states.loading}
              description={copy.riskPage.blockingRegisterDetail}
            />
          )}
        </section>

        <aside className="grid min-w-0 content-start gap-3">
          <section
            aria-busy={!workspace.data}
            className="min-w-0 space-y-2"
            data-testid="risk-loading-metrics"
          >
            <h2 className="app-type-section-title text-[var(--app-text)]">
              {copy.riskPage.metrics}
            </h2>
            {workspace.data ? (
              <div className="min-w-0" data-testid="risk-loading-live-metrics">
                <MetricStrip
                  ariaLabel={copy.riskPage.metrics}
                  className="app-risk-metric-strip"
                  items={workspace.data.metrics.map((metric) => ({
                    id: metric.key,
                    label: getRiskMetricLabel(copy, metric.key),
                    value: metric.display_value,
                    detail: formatRiskAlertLevel(metric.level, locale),
                    tone:
                      metric.level === 'high'
                        ? ('danger' as const)
                        : metric.level === 'medium'
                          ? ('warning' as const)
                          : ('neutral' as const),
                  }))}
                />
              </div>
            ) : (
              <MetricStrip
                ariaLabel={`${copy.riskPage.metrics} · ${copy.states.loading}`}
                className="app-risk-metric-strip"
                items={[
                  'current_drawdown',
                  'gross_exposure',
                  'cash_ratio',
                  'largest_weight',
                ].map((metric) => ({
                  id: metric,
                  label: getRiskMetricLabel(copy, metric),
                  value: copy.states.loading,
                }))}
              />
            )}
          </section>
          <section
            aria-busy={controller.isRiskWorkspaceUnavailable}
            className="grid min-w-0 gap-2"
            data-testid="risk-loading-controlled-action"
          >
            <ControlledActionHeading locale={locale} />
            <EvidenceState
              kind="loading"
              statusLabel={copy.states.loading}
              title={copy.states.loading}
              description={copy.riskPage.loading}
            />
          </section>
        </aside>
      </div>
    </div>
  );
}

export function ControlledActionHeading({ locale }: { locale: 'zh' | 'en' }) {
  return (
    <div>
      <h2 className="app-type-section-title text-[var(--app-text)]">
        {locale === 'zh' ? '受控操作' : 'Controlled action'}
      </h2>
      <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
        {locale === 'zh'
          ? '熔断状态独立于风险事实；仅在需要人工干预时展开。'
          : 'Kill-switch state stays separate from risk facts and expands only for deliberate operator intervention.'}
      </p>
    </div>
  );
}

export function riskExceptionLabels(locale: 'zh' | 'en') {
  return {
    reason: locale === 'zh' ? '阻断原因' : 'Reason',
    unblockCondition: locale === 'zh' ? '解除条件' : 'Unblock condition',
    nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
    evidence: locale === 'zh' ? '证据' : 'Evidence',
  };
}
