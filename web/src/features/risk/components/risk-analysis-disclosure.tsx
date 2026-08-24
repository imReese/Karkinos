import { ChevronDown } from 'lucide-react';

import { formatPercent as formatPercentValue } from '../../../shared/format';
import { useCopy } from '../../../shared/i18n/context';
import { formatInstrumentDisplayLabelFromNameMap } from '../../../shared/instrument-display';
import { StatusBadge } from '../../../shared/ui/workbench';
import {
  formatRiskCurrency,
  getRiskBucketLabel,
} from '../model/risk-presentation';
import type { RiskPageController } from '../model/use-risk-page-controller';

export function RiskAnalysisDisclosure({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { copy, instrumentNames, locale, workspace } = controller;
  if (!workspace.data) return null;

  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="risk-analysis-disclosure"
    >
      <summary className="flex min-h-16 cursor-pointer list-none flex-col gap-3 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:flex-row sm:items-center sm:justify-between sm:gap-5 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="app-product-mark">
            {locale === 'zh' ? '结构分析' : 'Structure analysis'}
          </div>
          <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
            {locale === 'zh'
              ? '回撤、暴露与持仓集中度'
              : 'Drawdown, exposure, and position concentration'}
          </h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
            {locale === 'zh'
              ? '按需查看图表与逐持仓结构；当前异常、指标、阈值和熔断状态保留在上方。'
              : 'Expand for charts and position-level structure. Current exceptions, metrics, thresholds, and kill-switch state remain above.'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
          <StatusBadge tone="neutral">
            {locale === 'zh'
              ? `${workspace.data.exposure_buckets.length} 类暴露`
              : `${workspace.data.exposure_buckets.length} exposure ${workspace.data.exposure_buckets.length === 1 ? 'bucket' : 'buckets'}`}
          </StatusBadge>
          <StatusBadge tone="neutral">
            {locale === 'zh'
              ? `${workspace.data.concentration.length} 个持仓`
              : `${workspace.data.concentration.length} ${workspace.data.concentration.length === 1 ? 'position' : 'positions'}`}
          </StatusBadge>
          <span className="sr-only">
            {locale === 'zh' ? '按需展开' : 'Expand on demand'}
          </span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </div>
      </summary>
      <div className="space-y-5 border-t border-[var(--app-divider)] py-4 sm:space-y-6 sm:py-5">
        <div
          className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]"
          data-testid="risk-analysis-overview"
        >
          <section
            className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
            data-testid="risk-drawdown-section"
          >
            <div className="app-type-overline text-[var(--app-text-tertiary)]">
              {copy.riskPage.drawdown}
            </div>
            <div className="mt-3">
              <DrawdownChart points={workspace.data.drawdown_series} />
            </div>
          </section>
          <section
            className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
            data-testid="risk-exposure-section"
          >
            <div className="app-type-overline text-[var(--app-text-tertiary)]">
              {copy.riskPage.exposure}
            </div>
            <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
              {workspace.data.exposure_buckets.map((bucket) => (
                <div key={bucket.bucket} className="px-2 py-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold">
                      {getRiskBucketLabel(copy, bucket.bucket)}
                    </div>
                    <div className="text-sm font-semibold tabular-nums">
                      {formatPercentValue(bucket.weight)}
                    </div>
                  </div>
                  <div className="app-muted mt-2 text-sm">
                    {formatRiskCurrency(bucket.value)} ·{' '}
                    {copy.overview.risk.positionsHint(bucket.positions_count)}
                  </div>
                  {bucket.symbols.length > 0 ? (
                    <div className="app-type-micro mt-2 font-mono text-[var(--app-text-tertiary)]">
                      {bucket.symbols.join(' · ')}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </section>
        </div>

        <section
          className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
          data-testid="risk-concentration-section"
        >
          <div className="app-type-overline text-[var(--app-text-tertiary)]">
            {copy.riskPage.concentration}
          </div>
          <div className="mt-3 max-w-full overflow-x-auto border-y border-[var(--app-divider)]">
            <table
              className="w-full min-w-[620px] border-collapse text-left text-xs"
              data-testid="risk-concentration-table"
            >
              <caption className="sr-only">
                {copy.riskPage.concentration}
              </caption>
              <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
                <tr>
                  <th
                    scope="col"
                    className="sticky left-0 z-10 border-b border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-3 py-2 font-semibold"
                  >
                    {copy.portfolio.table.symbol}
                  </th>
                  {[
                    copy.portfolio.table.weight,
                    copy.portfolio.table.marketValue,
                    copy.portfolio.table.unrealized,
                  ].map((label) => (
                    <th
                      key={label}
                      scope="col"
                      className="border-b border-[var(--app-divider)] px-3 py-2 text-right font-semibold"
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
                {workspace.data.concentration.length > 0 ? (
                  workspace.data.concentration.map((item) => (
                    <tr key={item.symbol}>
                      <th
                        scope="row"
                        className="sticky left-0 bg-[var(--app-surface)] px-3 py-2.5 font-semibold"
                      >
                        <span
                          className="block max-w-56 truncate"
                          title={formatInstrumentDisplayLabelFromNameMap(
                            item.symbol,
                            instrumentNames,
                          )}
                        >
                          {formatInstrumentDisplayLabelFromNameMap(
                            item.symbol,
                            instrumentNames,
                          )}
                        </span>
                      </th>
                      <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                        {formatPercentValue(item.weight)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                        {formatRiskCurrency(item.market_value)}
                      </td>
                      <td
                        className={`px-3 py-2.5 text-right font-medium tabular-nums ${
                          item.unrealized_pnl < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : item.unrealized_pnl > 0
                              ? 'text-[var(--app-pnl-positive)]'
                              : 'text-[var(--app-pnl-neutral)]'
                        }`}
                      >
                        {formatRiskCurrency(item.unrealized_pnl)}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-3 text-[var(--app-text-secondary)]"
                    >
                      {copy.riskPage.noConcentration}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </details>
  );
}

function DrawdownChart({
  points,
}: {
  points: Array<{ timestamp: string; drawdown: number }>;
}) {
  const copy = useCopy();
  if (points.length === 0) {
    return (
      <div className="app-muted text-sm">
        {copy.explainability.timelineEmpty}
      </div>
    );
  }
  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 640;
      const y =
        (point.drawdown /
          Math.max(...points.map((item) => item.drawdown), 0.01)) *
        220;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg viewBox="0 0 640 220" className="h-48 w-full sm:h-56">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        points={path}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
