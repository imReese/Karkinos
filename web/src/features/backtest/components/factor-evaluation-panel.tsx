import { useState } from 'react';
import { Layers, BarChart3 } from 'lucide-react';

import { usePreferences } from '../../../shared/preferences/context';
import {
  useUniversesQuery,
  useFactorEvaluationMutation,
  type FactorEvaluationResponse,
} from '../factor-api';

const FACTOR_TYPE_OPTIONS = [
  {
    id: 'momentum',
    nameZh: '区间动量 (Momentum)',
    nameEn: 'Momentum (Price Return)',
  },
  {
    id: 'risk_adjusted_momentum',
    nameZh: '夏普动量 (Risk-Adjusted Momentum)',
    nameEn: 'Risk-Adjusted Momentum',
  },
  {
    id: 'reversal',
    nameZh: '短期反转 (Reversal)',
    nameEn: 'Short-Term Reversal',
  },
  {
    id: 'volatility',
    nameZh: '年化波动率 (Volatility)',
    nameEn: 'Annualized Volatility',
  },
  {
    id: 'rsi',
    nameZh: '相对强弱指数 (RSI)',
    nameEn: 'Relative Strength Index (RSI)',
  },
];

export function FactorEvaluationPanel() {
  const { locale } = usePreferences();
  const universesQuery = useUniversesQuery();
  const factorMutation = useFactorEvaluationMutation();

  const [selectedUniverseId, setSelectedUniverseId] =
    useState('core_etf_universe');
  const [factorType, setFactorType] = useState('momentum');
  const [lookbackPeriod, setLookbackPeriod] = useState(20);
  const [forwardPeriod, setForwardPeriod] = useState(5);
  const [evaluationResult, setEvaluationResult] =
    useState<FactorEvaluationResponse | null>(null);

  const universes = universesQuery.data ?? [];
  const currentUniverse =
    universes.find((u) => u.universe_id === selectedUniverseId) ??
    universes[0] ??
    null;

  const handleRunEvaluation = () => {
    factorMutation.mutate(
      {
        universe_id: selectedUniverseId,
        factor_type: factorType,
        lookback_period: lookbackPeriod,
        forward_period: forwardPeriod,
        n_quantiles: 5,
      },
      {
        onSuccess: (data) => {
          setEvaluationResult(data);
        },
      },
    );
  };

  return (
    <div
      className="space-y-4 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-4 sm:p-5"
      data-testid="factor-evaluation-panel"
    >
      {/* 头部与简介 */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="app-kicker">
            {locale === 'zh' ? '多标的截面投研' : 'Cross-Sectional Analytics'}
          </div>
          <h3 className="app-card-title mt-1">
            {locale === 'zh'
              ? '因子体检仪与宏观 ETF 资产池'
              : 'Factor Tear Sheet & Curated Universes'}
          </h3>
          <p className="app-muted mt-1 text-xs">
            {locale === 'zh'
              ? '使用完整的本地行情探索 Rank IC、ICIR 与税费前分层利差。数据缺失时阻断；不使用随机示例或补造价格。'
              : 'Explore Rank IC, ICIR and gross quantile spreads from complete local bars. Missing data blocks evaluation; prices are never replaced with synthetic samples.'}
          </p>
        </div>
      </div>

      {/* 资产池选择与成分概览 */}
      <div className="space-y-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-[var(--app-text)]">
          <Layers className="h-4 w-4 text-[var(--app-accent)]" />
          <span>
            {locale === 'zh' ? '选择投研资产池' : 'Select Curated Universe'}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {universes.map((univ) => {
            const isSelected = univ.universe_id === selectedUniverseId;
            return (
              <button
                key={univ.universe_id}
                type="button"
                onClick={() => {
                  setSelectedUniverseId(univ.universe_id);
                  setEvaluationResult(null);
                }}
                className={`rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-medium transition ${
                  isSelected
                    ? 'border border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-text)]'
                    : 'border border-[var(--app-border)] bg-[var(--app-surface)] text-[var(--app-text-secondary)] hover:border-[var(--app-accent)]'
                }`}
              >
                {univ.display_name}
              </button>
            );
          })}
        </div>

        {currentUniverse ? (
          <div className="mt-2 space-y-1.5 border-t border-[var(--app-divider)] pt-2 text-xs">
            <p className="app-muted">{currentUniverse.description}</p>
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <span className="app-type-micro font-medium text-[var(--app-text-tertiary)]">
                {locale === 'zh' ? '成分标的:' : 'Members:'}
              </span>
              {currentUniverse.members.map((m) => (
                <span
                  key={m.symbol}
                  className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[length:var(--app-font-size-micro)] font-mono ${
                    m.benchmark
                      ? 'border border-[var(--app-accent-border)] bg-[var(--app-accent-bg)] text-[var(--app-accent-text)]'
                      : m.cash_proxy
                        ? 'border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] text-[var(--app-warning-text)]'
                        : 'border border-[var(--app-divider)] bg-[var(--app-surface)] text-[var(--app-text)]'
                  }`}
                  title={m.description || m.name}
                >
                  <span className="font-semibold">{m.name}</span>
                  <span className="opacity-70">{m.symbol}</span>
                  {m.benchmark && (
                    <span className="text-[length:var(--app-font-size-micro)] font-bold">
                      ★基准
                    </span>
                  )}
                  {m.cash_proxy && (
                    <span className="text-[length:var(--app-font-size-micro)] font-bold">
                      🛡避险
                    </span>
                  )}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {/* 因子参数控制与执行 */}
      <div className="grid gap-3 sm:grid-cols-4">
        <label className="grid gap-1.5 text-xs font-medium text-[var(--app-text)]">
          <span>{locale === 'zh' ? '因子类型' : 'Factor Metric'}</span>
          <select
            value={factorType}
            onChange={(e) => setFactorType(e.target.value)}
            className="app-field min-h-9 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs"
          >
            {FACTOR_TYPE_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {locale === 'zh' ? opt.nameZh : opt.nameEn}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1.5 text-xs font-medium text-[var(--app-text)]">
          <span>
            {locale === 'zh' ? '因子回看周期 (日)' : 'Lookback Window (Days)'}
          </span>
          <input
            type="number"
            min={2}
            max={250}
            value={lookbackPeriod}
            onChange={(e) =>
              setLookbackPeriod(Math.max(2, Number(e.target.value) || 2))
            }
            className="app-field min-h-9 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-mono tabular-nums"
          />
        </label>

        <label className="grid gap-1.5 text-xs font-medium text-[var(--app-text)]">
          <span>
            {locale === 'zh' ? '前瞻预测期 (日)' : 'Forward Horizon (Days)'}
          </span>
          <input
            type="number"
            min={1}
            max={60}
            value={forwardPeriod}
            onChange={(e) =>
              setForwardPeriod(Math.max(1, Number(e.target.value) || 1))
            }
            className="app-field min-h-9 rounded-[var(--app-radius-control)] px-2.5 py-1 text-xs font-mono tabular-nums"
          />
        </label>

        <div className="flex items-end">
          <button
            type="button"
            disabled={factorMutation.isPending}
            aria-busy={factorMutation.isPending ? 'true' : undefined}
            onClick={handleRunEvaluation}
            className="app-button-primary min-h-9 w-full rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {factorMutation.isPending
              ? locale === 'zh'
                ? '评估计算中...'
                : 'Evaluating...'
              : locale === 'zh'
                ? '运行因子体检'
                : 'Run Evaluation'}
          </button>
        </div>
      </div>

      {factorMutation.isError ? (
        <div role="alert" className="text-xs text-[var(--app-danger-text)]">
          {locale === 'zh'
            ? '因子体检未完成。请确认所选 ETF 标的均有完整且足够的本地日线历史，再重试。'
            : 'Factor evaluation did not complete. Confirm that every selected ETF has sufficient, complete local daily-bar history before retrying.'}
        </div>
      ) : null}

      {/* 因子体检结果看板 */}
      {evaluationResult ? (
        <FactorEvaluationResults
          evaluationResult={evaluationResult}
          locale={locale}
        />
      ) : null}
    </div>
  );
}

function FactorEvaluationResults({
  evaluationResult,
  locale,
}: {
  evaluationResult: FactorEvaluationResponse;
  locale: 'en' | 'zh';
}) {
  return (
    <div
      className="space-y-4 border-t border-[var(--app-divider)] pt-4"
      data-testid="factor-results"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-[var(--app-accent)]" />
          <h4 className="text-xs font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '因子体检报告 (Tear Sheet)'
              : 'Factor Evaluation Tear Sheet'}
          </h4>
        </div>
        <span className="app-type-micro font-mono tabular-nums text-[var(--app-text-tertiary)]">
          {locale === 'zh'
            ? `非重叠有效样本: ${evaluationResult.sample_count} 期`
            : `Non-overlapping valid samples: ${evaluationResult.sample_count} periods`}
        </span>
      </div>
      <p className="app-muted text-xs leading-5">
        {evaluationResult.universe_name} · {evaluationResult.data_start} →{' '}
        {evaluationResult.data_end} ·{' '}
        {locale === 'zh'
          ? `每 ${evaluationResult.forward_period} 根日线抽样；按每年 ${evaluationResult.summary.annual_periods} 期年化。税费前、不复权因子诊断，不包含成交或完整分配收益，也不构成策略准入依据。`
          : `Sampled every ${evaluationResult.forward_period} daily bars; annualized at ${evaluationResult.summary.annual_periods} periods per year. Gross unadjusted factor diagnostics exclude fills and complete distributions and provide no strategy admission evidence.`}
      </p>
      <p className="app-muted text-xs leading-5">
        {locale === 'zh'
          ? '本地缓存未证明历史时点可得性或完整公司行动覆盖；正态近似 p 值不证明样本独立或 alpha。'
          : 'Local cached bars do not establish historical PIT or complete corporate-action coverage. Normal-approximation p-values do not prove sample independence or alpha.'}
      </p>

      {/* 核心指标卡片矩阵 */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
        <MetricCard
          label="Rank IC 均值"
          value={`${(evaluationResult.summary.mean_ic * 100).toFixed(2)}%`}
          tone={
            evaluationResult.summary.mean_ic > 0.03
              ? 'positive'
              : evaluationResult.summary.mean_ic < -0.03
                ? 'negative'
                : 'neutral'
          }
          subtext={`Std: ${(evaluationResult.summary.std_ic * 100).toFixed(2)}%`}
        />
        <MetricCard
          label="年化 ICIR"
          value={evaluationResult.summary.annualized_icir.toFixed(2)}
          tone={
            evaluationResult.summary.annualized_icir > 0.8
              ? 'positive'
              : 'neutral'
          }
          subtext={`ICIR: ${evaluationResult.summary.icir.toFixed(2)}`}
        />
        <MetricCard
          label="t 检验统计量"
          value={evaluationResult.summary.t_stat.toFixed(2)}
          tone={
            Math.abs(evaluationResult.summary.t_stat) > 2.0
              ? 'positive'
              : 'neutral'
          }
          subtext={`p-val: ${evaluationResult.summary.p_value.toFixed(4)}`}
        />
        <MetricCard
          label="IC 胜率"
          value={`${(evaluationResult.summary.positive_ratio * 100).toFixed(1)}%`}
          tone={
            evaluationResult.summary.positive_ratio > 0.55
              ? 'positive'
              : 'neutral'
          }
          subtext="IC > 0 占比"
        />
        <MetricCard
          label="分层单调性"
          value={evaluationResult.spread_summary.monotonicity_score.toFixed(2)}
          tone={
            evaluationResult.spread_summary.monotonicity_score > 0.7
              ? 'positive'
              : evaluationResult.spread_summary.monotonicity_score < -0.7
                ? 'negative'
                : 'neutral'
          }
          subtext={`Q1..Q${evaluationResult.n_quantiles}`}
        />
        <MetricCard
          label={
            locale === 'zh' ? '税费前年化分层利差' : 'Annualized gross spread'
          }
          value={`${(evaluationResult.spread_summary.annualized_spread_return * 100).toFixed(2)}%`}
          tone={
            evaluationResult.spread_summary.annualized_spread_return > 0
              ? 'positive'
              : 'negative'
          }
          subtext={`Q${evaluationResult.n_quantiles} - Q1`}
        />
        <MetricCard
          label={locale === 'zh' ? '税费前分层夏普' : 'Gross spread Sharpe'}
          value={evaluationResult.spread_summary.spread_sharpe.toFixed(2)}
          tone={
            evaluationResult.spread_summary.spread_sharpe > 1.0
              ? 'positive'
              : 'neutral'
          }
          subtext={`回撤: ${(evaluationResult.spread_summary.spread_max_drawdown * 100).toFixed(1)}%`}
        />
      </div>

      {/* 最新截面标的评分与排序 */}
      {evaluationResult.latest_cross_section.length > 0 ? (
        <div className="space-y-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-[var(--app-text)]">
              {locale === 'zh'
                ? '最新截面因子评分与排序 (Latest Cross-Section Ranking)'
                : 'Latest Cross-Section Ranking'}
            </span>
            <span className="app-type-micro text-[var(--app-text-tertiary)]">
              {locale === 'zh'
                ? '探索性排名，不生成组合目标'
                : 'Exploratory ranking; no portfolio target'}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--app-divider)] text-[var(--app-text-secondary)]">
                  <th className="py-1.5 pr-3 text-left font-semibold">排名</th>
                  <th className="py-1.5 px-3 text-left font-semibold">
                    标的名称
                  </th>
                  <th className="py-1.5 px-3 text-left font-semibold">代码</th>
                  <th className="py-1.5 px-3 text-right font-semibold">
                    因子原始值
                  </th>
                  <th className="py-1.5 pl-3 text-right font-semibold">
                    截面百分位
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--app-divider)] font-mono tabular-nums">
                {evaluationResult.latest_cross_section.map((item) => (
                  <tr
                    key={item.symbol}
                    className="hover:bg-[var(--app-accent-bg)]"
                  >
                    <td className="py-1.5 pr-3 text-left">
                      <span
                        className={`inline-block w-5 text-center font-bold ${
                          item.rank <= 3
                            ? 'text-[var(--app-accent-text)]'
                            : 'text-[var(--app-text-tertiary)]'
                        }`}
                      >
                        #{item.rank}
                      </span>
                    </td>
                    <td className="py-1.5 px-3 font-sans text-left font-medium text-[var(--app-text)]">
                      {item.name}
                    </td>
                    <td className="py-1.5 px-3 text-left text-[var(--app-text-secondary)]">
                      {item.symbol}
                    </td>
                    <td className="py-1.5 px-3 text-right text-[var(--app-text)]">
                      {item.factor_value.toFixed(4)}
                    </td>
                    <td className="py-1.5 pl-3 text-right font-semibold text-[var(--app-text)]">
                      {item.percentile.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MetricCard({
  label,
  value,
  subtext,
  tone,
}: {
  label: string;
  value: string;
  subtext?: string;
  tone: 'positive' | 'negative' | 'neutral';
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-[var(--app-pnl-positive)]'
      : tone === 'negative'
        ? 'text-[var(--app-pnl-negative)]'
        : 'text-[var(--app-text)]';

  return (
    <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface-raised)] p-2.5">
      <div className="app-type-micro truncate text-[var(--app-text-secondary)]">
        {label}
      </div>
      <div
        className={`mt-1 font-mono text-sm font-bold tabular-nums ${toneClass}`}
      >
        {value}
      </div>
      {subtext ? (
        <div className="app-type-micro mt-0.5 truncate text-[var(--app-text-tertiary)] font-mono">
          {subtext}
        </div>
      ) : null}
    </div>
  );
}
