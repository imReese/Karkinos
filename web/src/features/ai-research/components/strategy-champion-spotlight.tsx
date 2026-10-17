import { formatCurrency, formatPercent } from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import type { ShadowResearchAutomationStatus } from '../shadow-research-api';

/** A summary of saved research selection. Publication authority is shown separately. */
export function StrategyChampionSpotlight({
  status,
}: {
  status?: ShadowResearchAutomationStatus | null;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const selection = status?.daily_selections?.find(
    (item) => item.integrity_status === 'verified',
  );
  const winnerId =
    selection?.research_recommendation?.research_winner_candidate_id ??
    selection?.winner_candidate_id;
  const candidate = status?.candidates.find(
    (item) =>
      item.candidate_id === winnerId && item.run_id === selection?.run_id,
  );
  const metrics = candidate?.comparison.candidate;
  const gate =
    candidate?.comparison.research_gate ?? candidate?.comparison.promotion_gate;
  const checks = candidate?.comparison.promotion_gate.checks;
  const passed = checks?.filter((check) => check.status === 'pass').length;
  return (
    <details
      className="min-w-0 border-t border-[var(--app-divider)] py-4"
      data-testid="strategy-champion-spotlight"
    >
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between py-2 text-sm font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)] transition-colors">
        <span>{zh ? '已保存的研究选择' : 'Saved research selection'}</span>
        <span className="app-type-micro font-mono text-[var(--app-text-tertiary)]">
          {candidate ? candidate.candidate_id : '—'}
        </span>
      </summary>
      <p className="app-muted mt-1 text-xs leading-5">
        {zh
          ? '研究排名用于选择下一次实验。全范围验证、前向模拟和账户推荐授权分别显示，排名不代替资格。'
          : 'Research ranking selects the next experiment. Deployment validation, forward simulation and account publication have separate evidence and permissions.'}
      </p>
      {!candidate ? (
        <p className="mt-3 text-xs" role="status">
          {zh
            ? '尚无可核对来源的研究优选。'
            : 'No source-bound research selection is available.'}
        </p>
      ) : (
        <>
          <p className="mt-3 break-words text-sm font-semibold">
            {candidate.comparison.economic_hypothesis || candidate.candidate_id}
          </p>
          <p className="app-muted mt-1 break-all text-xs">
            {candidate.run_id} · {candidate.candidate_id}
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-3 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3.5 text-xs lg:grid-cols-4">
            {[
              [
                zh ? '研究回测收益' : 'Research backtest return',
                metrics ? formatPercent(metrics.total_return) : '—',
                metrics && metrics.total_return > 0
                  ? 'text-[var(--app-pnl-positive)]'
                  : metrics && metrics.total_return < 0
                    ? 'text-[var(--app-pnl-negative)]'
                    : 'text-[var(--app-text)]',
              ],
              [
                zh ? '研究回测回撤' : 'Research backtest drawdown',
                metrics ? formatPercent(metrics.max_drawdown) : '—',
                'text-[var(--app-text)]',
              ],
              [
                zh ? '研究成本' : 'Research trading costs',
                metrics ? formatCurrency(metrics.total_cost) : '—',
                'text-[var(--app-text)]',
              ],
              [
                zh ? '已记录门禁' : 'Recorded gate',
                checks?.length
                  ? `${passed} / ${checks.length} · ${gate?.status ?? 'unknown'}`
                  : (gate?.status ?? '—'),
                'text-[var(--app-text)]',
              ],
            ].map(([label, value, colorClass]) => (
              <div
                key={label}
                className="min-w-0 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-overlay)] p-3 shadow-sm"
              >
                <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                  {label}
                </dt>
                <dd
                  className={`mt-1 font-mono text-sm font-semibold tabular-nums ${colorClass}`}
                >
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="app-muted mt-3 break-all text-xs">
            {zh ? '数据快照' : 'Dataset snapshot'}:{' '}
            {metrics?.dataset_snapshot_id ?? '—'}
          </p>
          {gate?.blockers.length ? (
            <p className="mt-2 text-xs" role="status">
              {gate.blockers.join(' · ')}
            </p>
          ) : null}
        </>
      )}
    </details>
  );
}
