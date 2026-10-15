import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../../../shared/api/client';
import { usePreferences } from '../../../shared/preferences/context';
import type { StrategyResearchSession } from '../api';
import type { ShadowResearchCandidate } from '../shadow-research-api';

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
  return (
    <section
      className="mt-3 min-w-0 border-t border-[var(--app-divider)] pt-3 text-xs"
      data-testid="research-candidate-definition"
    >
      <h4 className="font-semibold">
        {zh ? '策略来源与验证范围' : 'Strategy source and validation scope'}
      </h4>
      <dl className="mt-2 grid gap-2 sm:grid-cols-2">
        <div>
          <dt className="app-muted">
            {zh ? '实际生成模型' : 'Recorded generation model'}
          </dt>
          <dd>{draft?.model_id ?? session?.model_id ?? '—'}</dd>
        </div>
        <div>
          <dt className="app-muted">
            {zh ? '开发样本' : 'Development universe'}
          </dt>
          <dd>
            {session?.selection?.universe?.length ?? '—'}{' '}
            {zh ? '个标的' : 'instruments'}
          </dd>
        </div>
        <div>
          <dt className="app-muted">
            {zh ? '开发区间' : 'Development interval'}
          </dt>
          <dd>
            {draft?.test_window
              ? `${draft.test_window.start_date} → ${draft.test_window.end_date}`
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="app-muted">
            {zh ? '冻结市场覆盖' : 'Frozen market coverage'}
          </dt>
          <dd>
            {scope?.status ?? (zh ? '尚无已绑定证据' : 'No bound evidence')}
          </dd>
        </div>
        <div>
          <dt className="app-muted">
            {zh ? '独立最终验证' : 'Independent final validation'}
          </dt>
          <dd>
            {validation?.status ??
              (zh ? '尚无已绑定证据' : 'No bound evidence')}
          </dd>
        </div>
      </dl>
      {scope ? (
        <p className="app-muted mt-2">
          {scope.scope_kind} · {scope.as_of ?? '—'} ·{' '}
          {zh
            ? '预期 / 已评估 / 排除 / 未解决'
            : 'Expected / evaluated / excluded / unresolved'}
          : {scope.expected_count ?? '—'} / {scope.evaluated_count ?? '—'} /{' '}
          {scope.excluded_count ?? '—'} / {scope.unresolved_count ?? '—'}
        </p>
      ) : null}
      {validation ? (
        <p className="app-muted mt-2 break-words">
          {zh
            ? '检查点 / 起始资金 / 费用来源'
            : 'Checkpoint / initial cash / fee source'}
          : {validation.checkpoint ?? '—'} / {validation.initial_cash ?? '—'} /{' '}
          {validation.fee_cost_model_reference ?? '—'}
          {validation.blockers.length
            ? ` · ${validation.blockers.join(' · ')}`
            : ''}
        </p>
      ) : null}
      <p className="app-muted mt-2">
        {zh
          ? '开发样本的收益不等于全市场验证；前向模拟以其冻结范围单独记录。'
          : 'A development sample is not full-market validation. Forward simulation records its own frozen scope.'}
      </p>
      {query.isError ? (
        <button
          type="button"
          className="app-button-secondary mt-2 min-h-9 px-3"
          onClick={() => void query.refetch()}
        >
          {zh ? '重新读取策略来源' : 'Reload strategy source'}
        </button>
      ) : null}
      {draft ? (
        <details className="mt-2">
          <summary className="cursor-pointer">
            {zh ? '查看已保存公式与参数' : 'Saved formula and parameters'}
          </summary>
          <p className="mt-2">{draft.entry_conditions}</p>
          <p>{draft.exit_conditions}</p>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--app-surface-raised)] p-2">
            {JSON.stringify(
              {
                formula: draft.formula_ast,
                parameters: draft.parameter_values,
              },
              null,
              2,
            )}
          </pre>
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
