import {
  formatCurrency,
  formatDate,
  formatPercent,
  formatQuantity,
} from '../../../shared/format';
import { usePreferences } from '../../../shared/preferences/context';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import { StatusBadge } from '../../../shared/ui/workbench';
import type { ResearchSimulationPreview } from '../overview-feature-boundary';

function blockerLabel(code: string, zh: boolean) {
  if (
    code.includes('source_not_configured') ||
    code.includes('source_not_ready')
  )
    return zh
      ? '尚未绑定完整的研究来源'
      : 'A complete research source is not bound';
  if (code.includes('cross_source') || code.includes('verified_daily_window'))
    return zh
      ? '最新交易窗口的双源行情尚未核验完整'
      : 'The latest daily window lacks complete independent verification';
  if (
    code.includes('session') ||
    code.includes('critique') ||
    code.includes('draft') ||
    code.includes('backtest')
  )
    return zh
      ? '保存的策略、回测或批判记录尚未完成或绑定发生变化'
      : 'Saved strategy, backtest or critique evidence is incomplete or has changed';
  if (
    code.includes('cash') ||
    code.includes('lot') ||
    code.includes('position_limit')
  )
    return zh
      ? '现金、交易单位或持仓数量约束未满足'
      : 'Cash, lot size or position limits are not met';
  if (code.includes('sellable'))
    return zh
      ? '可卖份额尚未满足或缺少核验'
      : 'Sellable quantity is insufficient or unverified';
  if (code.includes('board_permission') || code.includes('trade_unit'))
    return zh
      ? '账户板块权限或交易单位尚不支持'
      : 'Account board access or trading units are unsupported';
  if (
    code.includes('account') ||
    code.includes('portfolio') ||
    code.includes('valuation') ||
    code.includes('position') ||
    code.includes('ledger')
  )
    return zh
      ? '账户、估值或持仓事实仍需核验'
      : 'Account, valuation or position facts need verification';
  return zh
    ? '研究模拟所需证据尚未齐全'
    : 'Required research simulation evidence is incomplete';
}

function text(value: string | string[] | null | undefined) {
  if (Array.isArray(value)) return value.join('；');
  return typeof value === 'string' && value.trim() ? value : '--';
}

export function OverviewResearchSimulationPreview({
  preview,
}: {
  preview: ResearchSimulationPreview;
}) {
  const { locale } = usePreferences();
  const zh = locale === 'zh';
  const source = preview.source;
  const available = preview.status === 'available';
  const risks = [
    ...(preview.critique?.explicit_failure_conditions ?? []),
    ...(preview.critique?.evidence_gaps ?? []),
    preview.critique?.uncertainty,
    preview.critique?.concentration_risk,
    preview.critique?.possible_overfitting,
  ].filter((item): item is string =>
    Boolean(item && !item.startsWith('none_reported')),
  );
  return (
    <section
      data-testid="overview-research-simulation-preview"
      aria-label={
        zh ? '账户研究模拟预览' : 'Account research simulation preview'
      }
      className="mt-3 min-w-0 space-y-3 rounded-xl border border-[var(--app-divider)] bg-[var(--app-surface-raised)]/60 p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="app-type-subsection-title">
          {zh ? '账户研究／模拟预览' : 'Account research / simulation preview'}
        </h3>
        <StatusBadge
          tone={preview.status === 'blocked' ? 'warning' : 'neutral'}
        >
          {available
            ? zh
              ? '研究模拟 · 待人工确认'
              : 'Research simulation · Human confirmation required'
            : preview.status === 'no_action'
              ? zh
                ? '本次无假设动作'
                : 'No hypothetical actions'
              : zh
                ? '证据待补齐'
                : 'Evidence incomplete'}
        </StatusBadge>
      </div>
      <p className="app-type-compact text-[var(--app-text-secondary)]">
        {zh
          ? '只读研究假设；人工确认尚未记录，未授权下单或账户建议发布。'
          : 'Read-only research assumptions. Human confirmation is not recorded; orders and account publication are not authorized.'}
      </p>
      <dl className="grid grid-cols-1 gap-2 app-type-compact sm:grid-cols-2">
        <div>
          <dt className="text-[var(--app-text-tertiary)]">
            {zh ? '行情截至' : 'Market data as of'}
          </dt>
          <dd>{formatDate(preview.as_of_market_date)}</dd>
        </div>
        <div>
          <dt className="text-[var(--app-text-tertiary)]">
            {zh ? '目标交易日' : 'Target trading session'}
          </dt>
          <dd>{formatDate(preview.target_market_date)}</dd>
        </div>
      </dl>
      <p className="app-type-compact text-[var(--app-text-secondary)]">
        {zh
          ? '研究价格仅使用已核验日线收盘价，不是当前报价；数量为成交模拟前的目标数量。费用沿用保存的研究假设，未核验当前账户费率。'
          : 'Research prices require verified daily closes, not current quotes. Quantities are desired targets before fill simulation. Costs use saved research assumptions; current account fees are not evaluated.'}
      </p>
      {preview.blockers.length > 0 ? (
        <ul
          className="space-y-1 app-type-compact text-[var(--app-text-secondary)]"
          data-testid="overview-research-simulation-blockers"
        >
          {[...new Set(preview.blockers)].map((code) => (
            <li key={code} title={code}>
              {blockerLabel(code, zh)}
            </li>
          ))}
        </ul>
      ) : null}
      {available && preview.actions.length > 0 ? (
        <ul
          className="divide-y divide-[var(--app-divider)]"
          data-testid="overview-research-simulation-actions"
        >
          {preview.actions.map((action, index) => (
            <li
              key={`${action.symbol}-${action.side}-${index}`}
              className="min-w-0 space-y-2 py-3 app-type-compact"
              data-testid="overview-research-simulation-action"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="min-w-0 break-words font-semibold">
                  {action.display_name || action.name || action.symbol || '--'}{' '}
                  <span className="font-normal text-[var(--app-text-tertiary)]">
                    {action.symbol}
                  </span>
                </p>
                <StatusBadge tone="neutral">
                  {action.side === 'buy'
                    ? zh
                      ? '假设买入'
                      : 'Hypothetical buy'
                    : action.side === 'sell'
                      ? zh
                        ? '假设卖出'
                        : 'Hypothetical sell'
                      : zh
                        ? '假设动作待核'
                        : 'Hypothetical action unverified'}
                </StatusBadge>
              </div>
              <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-3">
                <div>
                  <dt className="text-[var(--app-text-tertiary)]">
                    {zh ? '目标数量' : 'Desired quantity'}
                  </dt>
                  <dd>{formatQuantity(action.estimated_quantity)}</dd>
                </div>
                <div>
                  <dt className="text-[var(--app-text-tertiary)]">
                    {zh ? '目标权重' : 'Target weight'}
                  </dt>
                  <dd>{formatPercent(action.target_weight)}</dd>
                </div>
                <div>
                  <dt className="text-[var(--app-text-tertiary)]">
                    {zh ? '参考收盘价' : 'Reference close'}
                  </dt>
                  <dd>{formatCurrency(action.estimated_price)}</dd>
                </div>
              </dl>
              <p className="break-words">
                <span className="text-[var(--app-text-tertiary)]">
                  {zh ? '触发条件：' : 'Trigger: '}
                </span>
                {text(action.trigger_condition)}
              </p>
              <p className="break-words">
                <span className="text-[var(--app-text-tertiary)]">
                  {zh ? '理由：' : 'Rationale: '}
                </span>
                {text(action.reason)}
              </p>
              <p className="break-words text-[var(--app-text-secondary)]">
                <span>{zh ? '风险：' : 'Risk: '}</span>
                {text(action.risk_impact)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      {preview.status === 'no_action' ? (
        <p className="app-type-compact">
          {zh
            ? '当前核验输入下没有假设动作；不代表账户已通过正式操作资格。'
            : 'No hypothetical action under these inputs. This does not establish formal account eligibility.'}
        </p>
      ) : null}
      {preview.blocked_candidates.length > 0 ? (
        <div
          className="space-y-1 app-type-compact"
          data-testid="overview-research-simulation-excluded"
        >
          <p className="font-semibold">
            {zh ? '受限候选' : 'Constrained candidates'}
          </p>
          {preview.blocked_candidates.map((item, index) => (
            <p
              key={`${item.symbol}-${index}`}
              className="break-words"
              title={item.reason}
            >
              {item.symbol} · {blockerLabel(item.reason, zh)}
            </p>
          ))}
        </div>
      ) : null}
      <details className="min-w-0 space-y-2 border-t border-[var(--app-divider)] pt-2 app-type-compact">
        <summary className="cursor-pointer font-semibold">
          {zh
            ? '研究来源、费用假设与风险证据'
            : 'Research source, cost assumptions and risks'}
        </summary>
        <div className="space-y-2 pt-2">
          {source.canonical_backtest_result_id ? (
            <a
              href={`/backtest?id=${source.canonical_backtest_result_id}`}
              onClick={(event) =>
                handleClientNavigation(
                  event,
                  `/backtest?id=${source.canonical_backtest_result_id}`,
                )
              }
              className="inline-flex min-h-11 items-center font-semibold text-[var(--app-accent)] hover:underline"
            >
              {zh ? '保存的真实回测' : 'Saved actual backtest'} #
              {source.canonical_backtest_result_id}
            </a>
          ) : (
            <p>
              {zh
                ? '尚无已绑定的真实回测'
                : 'No actual saved backtest is bound'}
            </p>
          )}
          <p>
            {zh ? '历史验证：' : 'Historical validation: '}
            {source.historical_validation_status === 'not_assessed' ||
            !source.historical_validation_status
              ? zh
                ? '尚未评估是否通过全部历史门禁'
                : 'Passing all historical gates has not been assessed'
              : source.historical_validation_status}
          </p>
          <p>
            {zh
              ? '账户资格、前向观测与人工确认独立核验，研究可读不代表正式准入。'
              : 'Account eligibility, forward observation and human confirmation are assessed separately. Readable research is not formal admission.'}
          </p>
          {source.research_evidence_bundle?.gate_status ? (
            <p>
              {zh ? '保存报告的研究门禁：' : 'Saved report research gate: '}
              {source.research_evidence_bundle.gate_status === 'blocked'
                ? zh
                  ? '受阻'
                  : 'Blocked'
                : source.research_evidence_bundle.gate_status}
            </p>
          ) : null}
          <dl className="space-y-1 text-[var(--app-text-secondary)]">
            {[
              [zh ? '会话' : 'Session', source.session_id],
              [zh ? '草稿' : 'Draft', source.draft_id],
              [zh ? '回测运行' : 'Backtest run', source.backtest_run_id],
              [zh ? '批判记录' : 'Critique', source.critique_id],
            ].map(([label, value]) => (
              <div key={label} className="min-w-0">
                <dt>{label}</dt>
                <dd className="break-all">{value || '--'}</dd>
              </div>
            ))}
          </dl>
          {preview.cost_assumptions?.slippage_bps ? (
            <p>
              {zh ? '研究滑点假设：' : 'Research slippage assumption: '}
              {preview.cost_assumptions.slippage_bps} bps
            </p>
          ) : null}
          {preview.cost_assumptions?.limitations?.map((item, index) => (
            <p
              key={index}
              className="break-words text-[var(--app-text-secondary)]"
            >
              {item}
            </p>
          ))}
          {risks.map((item, index) => (
            <p
              key={index}
              className="break-words text-[var(--app-text-secondary)]"
            >
              {item}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}
