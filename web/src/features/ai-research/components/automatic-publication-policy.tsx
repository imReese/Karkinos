import { useEffect, useState } from 'react';
import { usePreferences } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
import {
  usePublicationPolicy,
  usePreviewPublicationPolicy,
  useWritePublicationPolicy,
  type PublicationPolicyBounds,
} from '../publication-policy-api';

const fieldClass = 'app-field min-h-10 w-full min-w-0 px-3 py-2';
const buttonClass =
  'app-button-secondary min-h-10 px-3 py-2 text-xs disabled:opacity-50';
const defaults: PublicationPolicyBounds = {
  allocation_scope: 'stock_research',
  strategy_family: 'formula',
  max_initial_cash: '100000',
  risk_limits: {
    max_drawdown: '0.1',
    max_gross_weight: '1',
    max_symbol_weight: '0.30',
    max_positions: 4,
  },
  max_publications: 1,
  max_final_tests: 1,
  total_error_budget: '0.05',
  statistical_policy: {
    method: 'paired_moving_block_bootstrap.v1',
    minimum_observations: 60,
    block_length: 5,
    minimum_effective_blocks: 12,
    bootstrap_samples: 100000,
    significance_level: '0.05',
    minimum_net_excess: '0.01',
    decision_checkpoint: '',
    checkpoint_interval_days: 120,
  },
  min_net_improvement: '0.01',
  cooldown_days: 20,
  incumbent_strategy_id: null,
  expires_at: '',
};

export function AutomaticPublicationPolicy({
  updatedBy,
}: {
  updatedBy: string;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const boardLabels: Record<string, string> = zh
    ? { main: '主板', chinext: '创业板', star: '科创板', beijing: '北交所' }
    : { main: 'Main boards', chinext: 'ChiNext', star: 'STAR', beijing: 'BSE' };
  const entryBoards = (boards: string[] | undefined) =>
    boards?.length
      ? boards
          .map((board) => boardLabels[board] ?? board)
          .join(zh ? '、' : ', ')
      : zh
        ? '尚未核验'
        : 'Not verified';
  const query = usePublicationPolicy();
  const preview = usePreviewPublicationPolicy();
  const write = useWritePublicationPolicy();
  const [draft, setDraft] = useState<PublicationPolicyBounds>(defaults);
  const [initialized, setInitialized] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [previewGeneration, setPreviewGeneration] = useState<string | null>(
    null,
  );
  const state = query.isError ? undefined : query.data;
  useEffect(() => {
    if (!initialized && state?.proposed_binding) {
      setDraft(state.proposed_binding);
      setInitialized(true);
    }
  }, [initialized, state]);
  const busy = query.isFetching || preview.isPending || write.isPending;
  const proposed = preview.data?.proposed_binding;
  const reviewed = Boolean(
    proposed &&
    !preview.data?.preview_blockers.length &&
    !preview.isError &&
    !preview.isPending,
  );
  function change(update: Partial<PublicationPolicyBounds>) {
    setDraft((current) => ({ ...current, ...update }));
    preview.reset();
    write.reset();
    setConfirmed(false);
    setPreviewGeneration(null);
  }
  const blockers = [
    ...new Set([
      ...(state?.blockers ?? []),
      ...(preview.data?.preview_blockers ?? state?.preview_blockers ?? []),
    ]),
  ];
  const valid =
    draft.allocation_scope.trim() &&
    Number(draft.max_initial_cash) > 0 &&
    /^\d{4}-\d{2}-\d{2}$/.test(draft.statistical_policy.decision_checkpoint) &&
    Number.isFinite(Date.parse(draft.expires_at));
  return (
    <section
      className="mt-3 min-w-0 space-y-3 rounded-[var(--app-radius-control)] border border-[var(--app-divider)] p-3 text-xs"
      data-testid="automatic-publication-policy"
    >
      <h3 className="text-sm font-semibold">
        {zh
          ? '自动上岗：账户建议发布授权'
          : 'Automatic account recommendation publication'}
      </h3>
      <p className="app-muted leading-5">
        {zh
          ? '授权后，满足冻结全范围验证和当前账户资格的候选可自动成为指定账户范围的建议来源，无需逐候选确认。此授权不创建订单或授予交易权限。'
          : 'After authorization, candidates that pass frozen deployment-scope validation and current account qualification may automatically become the recommendation source for the specified allocation. No per-candidate confirmation is required. This grant creates no order or trading permission.'}
      </p>
      <p role="status">
        {zh ? '当前授权' : 'Current grant'}:{' '}
        {query.isLoading
          ? zh
            ? '读取中'
            : 'Loading'
          : query.isError || !state?.status
            ? zh
              ? '未知'
              : 'Unknown'
            : state.status}
      </p>
      {state?.policy?.enabled && 'entry_board_policy' in state.policy ? (
        <p>
          {zh ? '账户可买板块' : 'Allowed entry boards'}:{' '}
          {entryBoards(state.policy.entry_board_policy?.allowed_boards)}
        </p>
      ) : null}
      <div className="space-y-1" data-testid="usable-publication-sources">
        <p className="font-semibold">
          {zh ? '当前可用账户来源' : 'Usable account sources'}
        </p>
        {state?.usable_current_sources?.length ? (
          state.usable_current_sources.map((source) => (
            <p className="break-all" key={source.strategy_id}>
              {source.strategy_id} · {zh ? '授权来源' : 'Decision source'}:{' '}
              {source.decision_source ?? (zh ? '尚未提供' : 'Not provided')}
            </p>
          ))
        ) : (
          <p className="app-muted">
            {query.isLoading || query.isError
              ? zh
                ? '尚无法核对'
                : 'Not verified yet'
              : zh
                ? '无适用来源'
                : 'No applicable source'}
          </p>
        )}
      </div>
      {state?.latest_decision ? (
        <p className="app-muted break-all">
          {zh ? '最近自动决策' : 'Latest automatic decision'}:{' '}
          {state.latest_decision.status ?? '—'} ·{' '}
          {state.latest_decision.strategy_id ?? '—'} ·{' '}
          {state.latest_decision.decision_source ?? '—'}
        </p>
      ) : null}
      {blockers.length ? (
        <ul
          className="list-disc space-y-1 pl-4"
          aria-label={zh ? '授权阻断' : 'Publication blockers'}
        >
          {blockers.map((blocker) => (
            <li key={blocker}>{blocker}</li>
          ))}
        </ul>
      ) : null}
      {query.isError ? (
        <button
          type="button"
          className={buttonClass}
          onClick={() => void query.refetch()}
          disabled={busy}
        >
          {zh ? '重新读取发布授权' : 'Reload publication grant'}
        </button>
      ) : null}
      <details>
        <summary className="cursor-pointer font-semibold">
          {zh
            ? '配置并核验自动发布边界'
            : 'Configure and verify publication bounds'}
        </summary>
        <PublicationPolicyFields
          draft={draft}
          change={change}
          busy={busy}
          zh={zh}
          sourceIds={
            state?.usable_current_sources?.map(
              (source) => source.strategy_id,
            ) ?? []
          }
        />
        <button
          type="button"
          className={`${buttonClass} mt-3`}
          disabled={busy || !valid || query.isError}
          onClick={() => {
            setConfirmed(false);
            setPreviewGeneration(state?.policy.generation ?? null);
            preview.mutate(draft, {
              onSuccess: (result) => {
                if (result.proposed_binding) setDraft(result.proposed_binding);
              },
            });
          }}
        >
          {zh ? '核验授权边界' : 'Verify authorization bounds'}
        </button>
        {reviewed && proposed ? (
          <div
            className="mt-3 space-y-3 border-t border-[var(--app-divider)] pt-3"
            data-testid="publication-grant-preview"
          >
            <p>
              {zh
                ? '后端已绑定账户与部署范围；以下授权仅覆盖本次预览的精确边界。'
                : 'The backend bound the account and deployment scope. Authorization covers these exact previewed bounds.'}
            </p>
            <p>
              {proposed.allocation_scope} · CNY {proposed.max_initial_cash} ·{' '}
              {zh ? '到期' : 'Expires'} {formatTimestamp(proposed.expires_at)}
            </p>
            <p data-testid="publication-entry-boards">
              {zh ? '账户可买板块' : 'Allowed entry boards'}:{' '}
              {entryBoards(proposed.entry_board_policy?.allowed_boards)}
            </p>
            {proposed.entry_board_policy ? (
              <p className="app-muted">
                {zh ? '未纳入新增买入' : 'Excluded from new entries'}:{' '}
                {entryBoards(
                  Object.keys(proposed.entry_board_policy.excluded_boards),
                )}
                .{' '}
                {zh
                  ? '研究行情仍覆盖完整申明市场，前向验证和推荐使用相同的可买板块条件。'
                  : 'Research data still cover the declared market. Forward validation and recommendations use the same entry board constraints.'}
              </p>
            ) : null}
            <p>
              {zh
                ? '最终决策日 / 最少观测 / 单次错误预算 / 最低净超额'
                : 'Final date / minimum observations / per-test error budget / minimum net excess'}
              : {proposed.statistical_policy.decision_checkpoint} /{' '}
              {proposed.statistical_policy.minimum_observations} /{' '}
              {proposed.statistical_policy.significance_level} /{' '}
              {proposed.statistical_policy.minimum_net_excess}
            </p>
            <p>
              {zh
                ? '最多持仓 / 总仓位 / 最大回撤 / 发布次数'
                : 'Maximum positions / gross weight / drawdown / publications'}
              : {proposed.risk_limits.max_positions} /{' '}
              {proposed.risk_limits.max_gross_weight} /{' '}
              {proposed.risk_limits.max_drawdown} / {proposed.max_publications}
            </p>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                disabled={busy}
              />
              {zh
                ? '我授权这些边界内的候选通过验证后自动发布账户建议，无需逐策略确认。'
                : 'I authorize automatic account recommendation publication within these bounds after validation, without per-strategy confirmation.'}
            </label>
            <button
              type="button"
              className={buttonClass}
              disabled={busy || !confirmed || query.isError}
              onClick={() =>
                write.mutate(
                  {
                    ...proposed,
                    enabled: true,
                    expected_generation: previewGeneration,
                    updated_by: updatedBy,
                    confirmation:
                      'authorize_bounded_automatic_account_recommendation_publication_without_trade_or_capital_authority',
                  },
                  {
                    onSuccess: () => {
                      setConfirmed(false);
                      preview.reset();
                    },
                  },
                )
              }
            >
              {zh ? '启用自动发布授权' : 'Enable automatic publication'}
            </button>
          </div>
        ) : null}
      </details>
      {state?.policy?.enabled ? (
        <button
          type="button"
          className={buttonClass}
          disabled={write.isPending}
          onClick={() =>
            write.mutate(
              {
                enabled: false,
                expected_generation: state.policy.generation,
                updated_by: updatedBy,
                confirmation:
                  'revoke_automatic_account_recommendation_publication',
              },
              {
                onSuccess: () => {
                  setConfirmed(false);
                  setPreviewGeneration(null);
                  preview.reset();
                },
              },
            )
          }
        >
          {zh
            ? '撤销授权并停用相关推荐来源'
            : 'Revoke grant and suspend its recommendation sources'}
        </button>
      ) : null}
      {preview.isError || write.isError ? (
        <p role="alert">
          {zh
            ? '核验或保存失败。请重新读取并核验；当前授权未被确认改变。'
            : 'Verification or saving failed. Reload and verify again; a changed grant has not been confirmed.'}
        </p>
      ) : null}
      {write.isSuccess ? (
        <p role="status">
          {zh
            ? '已读取保存后的真实授权状态。'
            : 'The saved grant state has been read back.'}
        </p>
      ) : null}
    </section>
  );
}

function PublicationPolicyFields({
  draft,
  change,
  busy,
  zh,
  sourceIds,
}: {
  draft: PublicationPolicyBounds;
  change: (update: Partial<PublicationPolicyBounds>) => void;
  busy: boolean;
  zh: boolean;
  sourceIds: string[];
}) {
  return (
    <fieldset
      className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2"
      disabled={busy}
    >
      {(
        [
          [zh ? '策略资金范围' : 'Allocation scope', 'allocation_scope'],
          [
            zh
              ? '最大模拟/适用本金（人民币）'
              : 'Maximum applicable capital (CNY)',
            'max_initial_cash',
          ],
          [
            zh
              ? '总错误预算（比例）'
              : 'Total statistical error budget (ratio)',
            'total_error_budget',
          ],
          [
            zh
              ? '最小替换净改善（比例）'
              : 'Minimum net replacement improvement (ratio)',
            'min_net_improvement',
          ],
        ] as const
      ).map(([label, name]) => (
        <label className="grid gap-2" key={name}>
          {label}
          <input
            className={fieldClass}
            value={draft[name]}
            onChange={(event) => change({ [name]: event.target.value })}
          />
        </label>
      ))}
      {(
        [
          [
            zh ? '最多自动发布次数' : 'Maximum publications',
            'max_publications',
          ],
          [zh ? '最多最终检验次数' : 'Maximum final tests', 'max_final_tests'],
          [zh ? '替换冷却天数' : 'Replacement cooldown days', 'cooldown_days'],
        ] as const
      ).map(([label, name]) => (
        <label className="grid gap-2" key={name}>
          {label}
          <input
            type="number"
            min={name === 'cooldown_days' ? 0 : 1}
            step="1"
            className={fieldClass}
            value={draft[name]}
            onChange={(event) => change({ [name]: Number(event.target.value) })}
          />
        </label>
      ))}
      {(
        [
          [
            zh ? '最大回撤（比例）' : 'Maximum drawdown (ratio)',
            'max_drawdown',
          ],
          [
            zh
              ? '观测总仓位上限（比例）'
              : 'Observed gross weight limit (ratio)',
            'max_gross_weight',
          ],
          [
            zh
              ? '观测单标的上限（比例）'
              : 'Observed symbol weight limit (ratio)',
            'max_symbol_weight',
          ],
          [zh ? '总持仓数上限' : 'Maximum total positions', 'max_positions'],
        ] as const
      ).map(([label, name]) => (
        <label className="grid gap-2" key={name}>
          {label}
          <input
            type="number"
            min="0"
            step="any"
            className={fieldClass}
            value={draft.risk_limits[name]}
            onChange={(event) =>
              change({
                risk_limits: {
                  ...draft.risk_limits,
                  [name]:
                    name === 'max_positions'
                      ? Number(event.target.value)
                      : event.target.value,
                },
              })
            }
          />
        </label>
      ))}
      <p className="app-muted sm:col-span-2">
        {zh
          ? '组合目标固定为最多 4 个持仓、单标的 25%、总仓位 97%。上述为实际成交后观测的风险上限；默认单标的 30%，用于容纳价格变动与费用造成的权重漂移。'
          : 'Portfolio targets use at most 4 positions, 25% per symbol and 97% gross. The limits above apply to observed holdings after fills; the default 30% symbol limit allows weight drift from prices and fees.'}
      </p>
      <label className="grid gap-2">
        {zh ? '替换指定来源' : 'Replace designated source'}
        <select
          className={fieldClass}
          value={draft.incumbent_strategy_id ?? ''}
          onChange={(event) =>
            change({ incumbent_strategy_id: event.target.value || null })
          }
        >
          <option value="">
            {zh
              ? '首次发布，不替换其他来源'
              : 'First publication; preserve other sources'}
          </option>
          {sourceIds.map((strategyId) => (
            <option key={strategyId} value={strategyId}>
              {strategyId}
            </option>
          ))}
        </select>
      </label>
      <label className="grid gap-2">
        {zh ? '授权到期时间（含时区）' : 'Grant expiry (with timezone)'}
        <input
          className={fieldClass}
          placeholder="2027-01-15T16:00:00+08:00"
          value={draft.expires_at}
          onChange={(event) => change({ expires_at: event.target.value })}
        />
      </label>
      <div className="sm:col-span-2 space-y-3 border-t border-[var(--app-divider)] pt-3">
        <p className="font-semibold">
          {zh
            ? '冻结最终检验方法：配对移动区块自助法'
            : 'Freeze final method: paired moving block bootstrap'}
        </p>
        <p className="app-muted">
          {zh
            ? '这些是可修改的实验设计参数，不代表已满足证据要求。开发数据与最终区间必须隔离；预览重新核验范围并计算绑定。'
            : 'These editable experiment settings do not establish sufficient evidence. Development data remain separate from the final interval; preview verifies scope and calculates bindings.'}
        </p>
      </div>
      {(
        [
          [
            zh ? '最少收益观测日' : 'Minimum return observations',
            'minimum_observations',
          ],
          [
            zh ? '区块长度（交易日）' : 'Block length (sessions)',
            'block_length',
          ],
          [
            zh ? '最少有效区块' : 'Minimum effective blocks',
            'minimum_effective_blocks',
          ],
          [zh ? '重采样次数' : 'Bootstrap samples', 'bootstrap_samples'],
          [
            zh ? '后续检查间隔（天）' : 'Later checkpoint interval (days)',
            'checkpoint_interval_days',
          ],
        ] as const
      ).map(([label, name]) => (
        <label className="grid gap-2" key={name}>
          {label}
          <input
            type="number"
            min="1"
            step="1"
            className={fieldClass}
            value={draft.statistical_policy[name]}
            onChange={(event) =>
              change({
                statistical_policy: {
                  ...draft.statistical_policy,
                  [name]: Number(event.target.value),
                },
              })
            }
          />
        </label>
      ))}
      {(
        [
          [
            zh
              ? '单次显著性错误预算（比例）'
              : 'Per-test significance budget (ratio)',
            'significance_level',
          ],
          [
            zh ? '最低经济净超额（比例）' : 'Minimum useful net excess (ratio)',
            'minimum_net_excess',
          ],
          [
            zh ? '固定最终决策日' : 'Fixed final decision date',
            'decision_checkpoint',
          ],
        ] as const
      ).map(([label, name]) => (
        <label className="grid gap-2" key={name}>
          {label}
          <input
            type={name === 'decision_checkpoint' ? 'date' : 'text'}
            className={fieldClass}
            value={draft.statistical_policy[name]}
            onChange={(event) =>
              change({
                statistical_policy: {
                  ...draft.statistical_policy,
                  [name]: event.target.value,
                },
              })
            }
          />
        </label>
      ))}
    </fieldset>
  );
}
