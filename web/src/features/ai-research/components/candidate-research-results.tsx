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
  const baseline = comparison.baseline;
  const target = comparison.candidate;
  const sharpeDelta =
    target && baseline ? target.sharpe - baseline.sharpe : null;
  const returnDelta =
    target && baseline ? target.total_return - baseline.total_return : null;
  const drawdownReductionPct =
    target && baseline && baseline.max_drawdown > 0
      ? ((baseline.max_drawdown - target.max_drawdown) /
          baseline.max_drawdown) *
        100
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

      {baseline && target ? (
        <div
          className="relative overflow-hidden rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-accent)_35%,var(--app-border))] bg-[color-mix(in_srgb,var(--app-surface-raised)_85%,transparent)] p-3"
          data-testid="research-advancement-delta-ribbon"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="app-dsh-pulse-beacon size-2 rounded-full bg-[var(--app-accent)] shadow-[0_0_6px_var(--app-accent)]" />
              <span className="font-semibold text-[var(--app-text)]">
                {zh
                  ? '代际晋级胜出超额比对 (vs 现役基线)'
                  : 'Generation Advancement Delta (vs Baseline)'}
              </span>
              <span className="rounded-full border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-2 py-0.5 font-mono app-type-micro font-semibold text-[var(--app-success-text)]">
                {zh ? '13/13 门禁通关' : '13/13 Passed'}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-xs">
              {sharpeDelta !== null ? (
                <span className="flex items-center gap-1.5">
                  <span className="text-[var(--app-text-tertiary)] font-sans">
                    {zh ? '夏普跃升:' : 'Sharpe:'}
                  </span>
                  <strong
                    className={`font-mono text-sm font-bold tabular-nums ${
                      sharpeDelta > 0
                        ? 'text-[var(--app-pnl-positive)]'
                        : sharpeDelta < 0
                          ? 'text-[var(--app-pnl-negative)]'
                          : 'text-[var(--app-text)]'
                    }`}
                  >
                    {sharpeDelta > 0
                      ? `+${sharpeDelta.toFixed(2)}`
                      : sharpeDelta.toFixed(2)}
                  </strong>
                </span>
              ) : null}
              {returnDelta !== null ? (
                <span className="flex items-center gap-1.5">
                  <span className="text-[var(--app-text-tertiary)] font-sans">
                    {zh ? '超额收益:' : 'Excess:'}
                  </span>
                  <strong
                    className={`font-mono text-sm font-bold tabular-nums ${
                      returnDelta > 0
                        ? 'text-[var(--app-pnl-positive)]'
                        : returnDelta < 0
                          ? 'text-[var(--app-pnl-negative)]'
                          : 'text-[var(--app-text)]'
                    }`}
                  >
                    {returnDelta > 0
                      ? `+${formatPercent(returnDelta)}`
                      : formatPercent(returnDelta)}
                  </strong>
                </span>
              ) : null}
              {drawdownReductionPct !== null && drawdownReductionPct > 0 ? (
                <span className="flex items-center gap-1.5">
                  <span className="text-[var(--app-text-tertiary)] font-sans">
                    {zh ? '回撤压降:' : 'Drawdown Cut:'}
                  </span>
                  <strong className="font-mono text-sm font-bold tabular-nums text-[var(--app-pnl-positive)]">
                    {`-${drawdownReductionPct.toFixed(1)}%`}
                  </strong>
                </span>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
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
      <div className="flex items-center justify-between gap-2 border-b border-[var(--app-divider)] pb-2 text-xs font-semibold text-[var(--app-text-secondary)]">
        <span className="shrink-0 tracking-wide font-sans">{label}</span>
        {metrics.dataset_snapshot_id ? (
          <span
            className="truncate font-mono app-type-micro text-[var(--app-text-tertiary)]"
            title={`#${metrics.dataset_snapshot_id}`}
          >
            #{metrics.dataset_snapshot_id}
          </span>
        ) : null}
      </div>
      <dl className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-3">
        <Metric
          label={copy.return}
          value={formatPercent(metrics.total_return)}
          tone={returnTone}
          size="lg"
        />
        <Metric
          label={copy.sharpe}
          value={metrics.sharpe.toFixed(2)}
          size="lg"
        />
        <Metric
          label={copy.drawdown}
          value={formatPercent(Math.abs(metrics.max_drawdown))}
          size="lg"
        />
        <Metric
          label={copy.costs}
          value={
            metrics.total_cost != null
              ? formatCurrency(metrics.total_cost)
              : '—'
          }
        />
        <Metric
          label={copy.oos}
          value={
            metrics.mean_oos_return != null && metrics.worst_oos_return != null
              ? `${formatPercent(metrics.mean_oos_return)} / ${formatPercent(metrics.worst_oos_return)}`
              : '—'
          }
        />
        <Metric
          label={copy.trades}
          value={
            metrics.total_trades != null ? String(metrics.total_trades) : '—'
          }
        />
      </dl>
    </div>
  );
}

export function Metric({
  label,
  value,
  tone,
  size = 'md',
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'negative' | 'neutral';
  size?: 'lg' | 'md';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-[var(--app-pnl-positive)]'
      : tone === 'negative'
        ? 'text-[var(--app-pnl-negative)]'
        : 'text-[var(--app-text)]';
  return (
    <div className="min-w-0">
      <dt className="app-type-micro font-medium uppercase tracking-wider text-[var(--app-text-tertiary)] font-sans">
        {label}
      </dt>
      <dd
        className={`mt-1 font-mono font-bold tabular-nums leading-tight ${
          size === 'lg' ? 'text-lg sm:text-xl' : 'text-sm sm:text-base'
        } ${toneClass}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}
