import { formatCurrency, formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { useBacktestResultQuery } from '../ai-research-feature-boundary';
import type { ShadowResearchCandidate, ShadowResearchMetricView } from '../api';
import {
  SHADOW_RESEARCH_COPY,
  type ShadowResearchCopy,
} from './shadow-research-copy';

export function CandidateResearchResults({
  candidate,
  copy,
}: {
  candidate: ShadowResearchCandidate;
  copy: ShadowResearchCopy;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const comparison = candidate.comparison;
  const sourceResultId =
    typeof candidate.candidate_result_id === 'number' &&
    Number.isSafeInteger(candidate.candidate_result_id) &&
    candidate.candidate_result_id > 0
      ? candidate.candidate_result_id
      : null;
  const sourceQuery = useBacktestResultQuery(
    !comparison.candidate ? sourceResultId : null,
  );
  const sourceReport =
    !sourceQuery.isError && sourceQuery.data?.id === sourceResultId
      ? sourceQuery.data
      : null;
  return (
    <section aria-label={zh ? '研究回测结果' : 'Research backtest results'}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-[var(--app-text)]">
          {zh ? '研究回测结果' : 'Research backtest results'}
        </h4>
        {sourceResultId ? (
          <a
            className="app-link text-xs"
            href={`/backtest?id=${sourceResultId}`}
          >
            {copy.observationReport} #{sourceResultId} &rarr;
          </a>
        ) : null}
      </div>
      <p className="mt-1 text-xs leading-5 text-[var(--app-text-secondary)]">
        {zh
          ? '已保存的研究回测；前向模拟与账户收益分别记录。'
          : 'Saved research backtest evidence. Forward paper results and account returns are recorded separately.'}
      </p>
      <div
        className={`mt-4 grid min-w-0 gap-6 ${comparison.baseline ? 'md:grid-cols-2' : ''}`}
      >
        {comparison.baseline ? (
          <MetricComparison
            label={copy.baseline}
            metrics={comparison.baseline}
          />
        ) : null}
        {comparison.candidate ? (
          <MetricComparison
            label={copy.candidate}
            metrics={comparison.candidate}
          />
        ) : sourceReport ? (
          <div className="min-w-0">
            <dl
              className="grid grid-cols-2 gap-4 border-y border-[var(--app-divider)] py-4 sm:grid-cols-3"
              aria-label={zh ? '来源报告指标' : 'Source report metrics'}
            >
              <Metric
                label={copy.return}
                value={formatPercent(sourceReport.metrics.total_return)}
              />
              <Metric
                label={copy.sharpe}
                value={sourceReport.metrics.sharpe.toFixed(2)}
              />
              <Metric
                label={copy.drawdown}
                value={formatPercent(
                  Math.abs(sourceReport.metrics.max_drawdown),
                )}
              />
            </dl>
            <p className="mt-2 text-xs text-[var(--app-text-secondary)]">
              {zh
                ? '来源报告指标；登记比较与样本外分折指标未提供。'
                : 'Source report metrics; registry comparison and OOS fold metrics are not provided.'}
            </p>
          </div>
        ) : (
          <p
            role="status"
            className="border-l-2 border-[var(--app-divider)] pl-4 text-sm text-[var(--app-text-secondary)]"
          >
            {sourceQuery.isPending && sourceResultId
              ? zh
                ? '正在读取当前候选的来源报告指标…'
                : 'Reading the exact candidate source report…'
              : zh
                ? '候选登记未提供比较指标。可在策略回测中核对来源报告。'
                : 'Comparison metrics are absent from the candidate registry. Inspect the source report in Strategy Backtest.'}
          </p>
        )}
      </div>
    </section>
  );
}

export function MetricComparison({
  label,
  metrics,
}: {
  label: string;
  metrics: ShadowResearchMetricView;
}) {
  const { locale } = usePreferences();
  const copy = SHADOW_RESEARCH_COPY[locale];
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] pt-4">
      <div className="text-xs font-semibold text-[var(--app-muted)]">
        {label}
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 text-xs sm:grid-cols-3">
        <Metric
          label={copy.return}
          value={formatPercent(metrics.total_return)}
        />
        <Metric label={copy.sharpe} value={metrics.sharpe.toFixed(2)} />
        <Metric
          label={copy.drawdown}
          value={formatPercent(Math.abs(metrics.max_drawdown))}
        />
        <Metric label={copy.costs} value={formatCurrency(metrics.total_cost)} />
        <Metric
          label={copy.oos}
          value={`${formatPercent(metrics.mean_oos_return)} / ${formatPercent(metrics.worst_oos_return)}`}
        />
        <Metric label={copy.trades} value={String(metrics.total_trades)} />
      </dl>
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="app-type-label text-[var(--app-text-secondary)]">
        {label}
      </dt>
      <dd className="app-type-primary-metric mt-1 tabular-nums text-[var(--app-text)]">
        {value}
      </dd>
    </div>
  );
}
