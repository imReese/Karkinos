import { StatusBadge } from '../../../shared/ui/workbench';
import {
  formatRiskAlertLevel,
  getRiskMetricDetail,
  getRiskMetricLabel,
} from '../model/risk-presentation';
import type { RiskPageController } from '../model/use-risk-page-controller';

export function RiskThresholdEvidence({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, locale, workspace } = controller;
  if (!workspace.data) return null;

  return (
    <section className="min-w-0 space-y-2">
      <div>
        <h2 className="app-type-section-title text-[var(--app-text)]">
          {locale === 'zh'
            ? '风险指标与阈值证据'
            : 'Risk metric and threshold evidence'}
        </h2>
        <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
          {locale === 'zh'
            ? '仅展示风险服务已记录的数值、状态与说明；未提供的阈值不会在页面中推算。'
            : 'Shows recorded risk values, states, and explanations. Missing thresholds are not inferred on this page.'}
        </p>
      </div>
      <div className="max-w-full overflow-x-auto border-y border-[var(--app-divider)]">
        <table
          className="w-full min-w-[620px] border-collapse text-left text-xs"
          data-testid="risk-threshold-table"
        >
          <caption className="sr-only">{copy.riskPage.metrics}</caption>
          <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
            <tr>
              {[
                locale === 'zh' ? '指标' : 'Metric',
                locale === 'zh' ? '当前值' : 'Current value',
                locale === 'zh' ? '状态' : 'State',
                locale === 'zh' ? '依据' : 'Evidence',
              ].map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="border-b border-[var(--app-divider)] px-3 py-2 font-semibold"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
            {workspace.data.metrics.map((metric) => (
              <tr key={metric.key}>
                <th scope="row" className="px-3 py-2.5 font-semibold">
                  {getRiskMetricLabel(copy, metric.key)}
                </th>
                <td className="px-3 py-2.5 font-mono tabular-nums">
                  {metric.display_value}
                </td>
                <td className="px-3 py-2.5">
                  <StatusBadge
                    tone={
                      metric.level === 'high'
                        ? 'danger'
                        : metric.level === 'medium'
                          ? 'warning'
                          : 'neutral'
                    }
                  >
                    {formatRiskAlertLevel(metric.level, locale)}
                  </StatusBadge>
                </td>
                <td className="px-3 py-2.5 text-[var(--app-text-secondary)]">
                  {getRiskMetricDetail(copy, metric.key)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
