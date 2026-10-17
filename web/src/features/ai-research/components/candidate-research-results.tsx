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
    <section
      aria-label={zh ? '研究回测结果' : 'Research backtest results'}
      className="space-y-3 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2.5">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-[var(--app-text)]">
          <span className="size-1.5 rounded-full bg-[var(--app-accent)]" />
          {zh ? '研究回测结果' : 'Research backtest results'}
        </h4>
        {sourceResultId ? (
          <a
            className="app-link inline-flex items-center gap-1 font-mono text-xs transition-colors hover:text-[var(--app-accent)]"
            href={`/backtest?id=${sourceResultId}`}
          >
            <span>
              {copy.observationReport} #{sourceResultId}
            </span>
            <span aria-hidden="true">&rarr;</span>
          </a>
        ) : null}
      </div>
      <div
        className={`min-w-0 gap-4 ${comparison.baseline ? 'grid md:grid-cols-2' : ''}`}
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
          <dl
            className="grid grid-cols-1 gap-3 sm:grid-cols-3"
            aria-label={zh ? '来源报告指标' : 'Source report metrics'}
          >
            <Metric
              label={copy.return}
              value={formatPercent(sourceReport.metrics.total_return)}
              tone={
                sourceReport.metrics.total_return > 0
                  ? 'positive'
                  : sourceReport.metrics.total_return < 0
                    ? 'negative'
                    : 'neutral'
              }
            />
            <Metric
              label={copy.sharpe}
              value={sourceReport.metrics.sharpe.toFixed(2)}
            />
            <Metric
              label={copy.drawdown}
              value={formatPercent(Math.abs(sourceReport.metrics.max_drawdown))}
            />
          </dl>
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
  const returnTone =
    metrics.total_return > 0
      ? 'positive'
      : metrics.total_return < 0
        ? 'negative'
        : 'neutral';
  return (
    <div className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3.5">
      <div className="flex items-center justify-between border-b border-[var(--app-divider)] pb-2 text-xs font-semibold text-[var(--app-text)]">
        <span>{label}</span>
        {metrics.dataset_snapshot_id ? (
          <span className="font-mono app-type-micro text-[var(--app-text-tertiary)]">
            #{metrics.dataset_snapshot_id}
          </span>
        ) : null}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-3">
        <Metric
          label={copy.return}
          value={formatPercent(metrics.total_return)}
          tone={returnTone}
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

export function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'negative' | 'neutral';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-[var(--app-pnl-positive)]'
      : tone === 'negative'
        ? 'text-[var(--app-pnl-negative)]'
        : 'text-[var(--app-text)]';
  return (
    <div className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3">
      <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
        {label}
      </dt>
      <dd
        className={`app-type-primary-metric mt-1.5 font-mono text-xl font-bold tabular-nums sm:text-2xl ${toneClass}`}
      >
        {value}
      </dd>
    </div>
  );
}
