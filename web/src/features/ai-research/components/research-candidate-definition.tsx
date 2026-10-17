import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../../shared/api/client';
import { usePreferences } from '../../../shared/preferences/context';
import type { StrategyResearchSession } from '../api';
import type { ShadowResearchCandidate } from '../shadow-research-api';
import { resolveCandidateEngine } from '../candidate-display';

export function ResearchCandidateDefinition({
  candidate,
}: {
  candidate: ShadowResearchCandidate;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const query = useQuery({
    queryKey: ['strategy-research-session', candidate.session_id],
    queryFn: () =>
      apiClient<StrategyResearchSession>(
        `/api/ai/strategy-research/sessions/${encodeURIComponent(candidate.session_id)}`,
      ),
    retry: false,
  });
  const session =
    query.data?.session_id === candidate.session_id ? query.data : undefined;
  const draft = session?.drafts?.find(
    (item) => item.draft_id === candidate.draft_id,
  );
  const scope = candidate.comparison.deployment_scope;
  const validation = candidate.comparison.deployment_validation;
  const recordedModel =
    draft?.model_id ?? session?.model_id ?? resolveCandidateEngine(candidate);
  const universeCount =
    session?.selection?.universe?.length ??
    scope?.evaluated_count ??
    scope?.expected_count ??
    null;
  const developmentInterval = draft?.test_window
    ? `${draft.test_window.start_date} → ${draft.test_window.end_date}`
    : scope?.as_of
      ? zh
        ? `截至 ${scope.as_of}`
        : `As of ${scope.as_of}`
      : '—';
  return (
    <section
      className="min-w-0 text-xs"
      data-testid="research-candidate-definition"
    >
      <div className="flex items-center justify-between border-b border-[var(--app-divider)] pb-2.5">
        <h4 className="text-sm font-semibold text-[var(--app-text)]">
          {zh ? '策略来源与验证范围' : 'Strategy source and validation scope'}
        </h4>
        {query.isError ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-2 py-0.5 font-mono app-type-micro text-[var(--app-text-tertiary)]">
            {zh ? '离线快照模式' : 'Offline snapshot mode'}
          </span>
        ) : null}
      </div>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm">
          <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
            {zh ? '实际生成模型' : 'Recorded generation model'}
          </dt>
          <dd className="mt-1 font-mono text-sm font-semibold text-[var(--app-text)]">
            {recordedModel}
          </dd>
        </div>
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm">
          <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
            {zh ? '开发样本' : 'Development universe'}
          </dt>
          <dd className="mt-1 font-mono text-sm font-semibold text-[var(--app-text)]">
            {universeCount !== null
              ? `${universeCount} ${zh ? '个标的' : 'instruments'}`
              : '—'}
          </dd>
        </div>
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm">
          <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
            {zh ? '开发区间' : 'Development interval'}
          </dt>
          <dd className="mt-1 font-mono text-sm font-semibold text-[var(--app-text)]">
            {developmentInterval}
          </dd>
        </div>
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm">
          <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
            {zh ? '冻结市场覆盖' : 'Frozen market coverage'}
          </dt>
          <dd className="mt-1 font-mono text-sm font-semibold text-[var(--app-text)]">
            {scope?.status ?? (zh ? '尚无已绑定证据' : 'No bound evidence')}
          </dd>
        </div>
        <div className="rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3 shadow-sm sm:col-span-2 lg:col-span-2">
          <dt className="app-type-overline truncate text-[var(--app-text-tertiary)]">
            {zh ? '独立最终验证' : 'Independent final validation'}
          </dt>
          <dd className="mt-1 font-mono text-sm font-semibold text-[var(--app-text)]">
            {validation?.status ??
              (zh ? '尚无已绑定证据' : 'No bound evidence')}
          </dd>
        </div>
      </dl>
      {scope ? (
        <div className="mt-2.5 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-2.5 app-type-micro text-[var(--app-text-secondary)]">
          <span className="font-semibold text-[var(--app-text)]">
            {scope.scope_kind}
          </span>{' '}
          · {scope.as_of ?? '—'} ·{' '}
          {zh
            ? '预期 / 已评估 / 排除 / 未解决'
            : 'Expected / evaluated / excluded / unresolved'}
          :{' '}
          <span className="font-mono">
            {scope.expected_count ?? '—'} / {scope.evaluated_count ?? '—'} /{' '}
            {scope.excluded_count ?? '—'} / {scope.unresolved_count ?? '—'}
          </span>
        </div>
      ) : null}
      {validation ? (
        <div className="mt-2 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-2.5 app-type-micro text-[var(--app-text-secondary)] break-words">
          <span className="font-semibold text-[var(--app-text)]">
            {zh
              ? '检查点 / 起始资金 / 费用来源'
              : 'Checkpoint / initial cash / fee source'}
          </span>
          :{' '}
          <span className="font-mono">
            {validation.checkpoint ?? '—'} / {validation.initial_cash ?? '—'} /{' '}
            {validation.fee_cost_model_reference ?? '—'}
          </span>
          {validation.blockers.length
            ? ` · ${validation.blockers.join(' · ')}`
            : ''}
        </div>
      ) : null}
      {query.isError ? (
        <button
          type="button"
          className="app-button app-button-secondary mt-2 min-h-8 rounded-[var(--app-radius-control)] px-3 text-xs font-semibold"
          onClick={() => void query.refetch()}
        >
          {zh ? '重新读取策略来源' : 'Reload strategy source'}
        </button>
      ) : null}
      {draft ? (
        <details className="mt-3 rounded-[var(--app-radius-control)] border border-[var(--app-border)] bg-[var(--app-surface-raised)] p-3">
          <summary className="flex cursor-pointer list-none items-center justify-between font-semibold text-[var(--app-text)] hover:text-[var(--app-accent)] transition-colors">
            <span>
              {zh ? '查看已保存公式与参数' : 'Saved formula and parameters'}
            </span>
            <span className="app-type-micro font-mono text-[var(--app-text-tertiary)]">
              AST JSON
            </span>
          </summary>
          <div className="mt-3 space-y-2 border-t border-[var(--app-divider)] pt-2.5">
            {draft.entry_conditions ? (
              <div className="flex items-start gap-2">
                <span className="shrink-0 rounded bg-[color-mix(in_srgb,var(--app-pnl-positive)_12%,transparent)] px-1.5 py-0.5 app-type-micro font-semibold text-[var(--app-pnl-positive)]">
                  {zh ? '入场条件' : 'Entry'}
                </span>
                <span className="font-mono text-xs text-[var(--app-text)]">
                  {draft.entry_conditions}
                </span>
              </div>
            ) : null}
            {draft.exit_conditions ? (
              <div className="flex items-start gap-2">
                <span className="shrink-0 rounded bg-[color-mix(in_srgb,var(--app-pnl-negative)_12%,transparent)] px-1.5 py-0.5 app-type-micro font-semibold text-[var(--app-pnl-negative)]">
                  {zh ? '出场条件' : 'Exit'}
                </span>
                <span className="font-mono text-xs text-[var(--app-text)]">
                  {draft.exit_conditions}
                </span>
              </div>
            ) : null}
            <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-2.5 font-mono app-type-micro leading-relaxed text-[var(--app-text)]">
              {JSON.stringify(
                {
                  formula: draft.formula_ast,
                  parameters: draft.parameter_values,
                },
                null,
                2,
              )}
            </pre>
          </div>
        </details>
      ) : (
        <p className="app-muted mt-2" role="status">
          {query.isLoading
            ? zh
              ? '正在读取公式来源…'
              : 'Loading formula source…'
            : zh
              ? '公式来源尚不可用。'
              : 'Formula source is unavailable.'}
        </p>
      )}
    </section>
  );
}
