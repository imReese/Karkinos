import { formatTimestamp } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  EvidenceIdentityDisclosure,
  ExceptionList,
  MetricStrip,
} from '../../../shared/ui/workbench';
import {
  formatRiskAlertLevel,
  formatRiskNextStep,
  getRiskMetricLabel,
} from '../model/risk-presentation';
import type { RiskPageController } from '../model/use-risk-page-controller';
import { KillSwitchPanel } from '../risk-feature-boundary';
import {
  ControlledActionHeading,
  riskExceptionLabels,
} from './risk-loading-workspace';

export function RiskCommandWorkspace({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, locale, state, workspace } = controller;
  if (!state.data || !workspace.data) return null;

  return (
    <div className="app-risk-command-grid grid min-w-0 gap-5 sm:gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(300px,360px)] xl:items-start">
      <section
        data-testid="risk-blocking-register"
        className="min-w-0 space-y-2"
      >
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.riskPage.blockingRegister}
          </h2>
          <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
            {copy.riskPage.blockingRegisterDetail}
          </p>
        </div>
        <ExceptionList
          ariaLabel={copy.riskPage.blockingRegister}
          emptyState={copy.riskPage.noBlockingItems}
          density="compact"
          labels={riskExceptionLabels(locale)}
          items={controller.activeRiskItems}
          className="[&>li>dl]:grid-cols-2 2xl:[&>li>dl]:grid-cols-4"
        />
        {controller.activeRiskItems.length > 0 ? (
          <dl
            data-testid="risk-resolution-guidance"
            className="grid grid-cols-2 gap-3 border-b border-[var(--app-divider)] px-3 py-2.5 text-xs"
          >
            <div className="min-w-0">
              <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '统一解除条件' : 'Shared unblock condition'}
              </dt>
              <dd className="app-type-compact mt-0.5 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
                {copy.riskPage.clearsWithNewProjection}
              </dd>
            </div>
            <div className="min-w-0">
              <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '安全下一步' : 'Safe next step'}
              </dt>
              <dd className="app-type-compact mt-0.5 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
                {formatRiskNextStep(state.data.next_step, locale)}
              </dd>
            </div>
          </dl>
        ) : null}
        <div className="flex justify-end border-b border-[var(--app-divider)] pb-2.5">
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
                value: state.data.summary.valuation_snapshot_id ?? '--',
                mono: true,
              },
              {
                label: copy.common.ledgerCutoff,
                value: state.data.summary.ledger_cutoff_id ?? '--',
                mono: true,
              },
              {
                label: copy.common.valuationAsOf,
                value: formatTimestamp(
                  state.data.summary.valuation_as_of ??
                    state.data.summary.valuation_timestamp,
                ),
                mono: true,
              },
              {
                label: copy.common.valuationStatus,
                value: formatPublicStatus(
                  state.data.summary.valuation_status ??
                    state.data.summary.quote_status,
                  locale,
                ),
              },
            ]}
          />
        </div>
      </section>

      <aside
        className="grid min-w-0 content-start gap-3"
        data-testid="risk-metric-rail"
      >
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
        <section
          className="grid min-w-0 gap-2"
          data-testid="risk-trading-control-grid"
        >
          <ControlledActionHeading locale={locale} />
          <KillSwitchPanel />
        </section>
      </aside>
    </div>
  );
}
