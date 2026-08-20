import { useState } from 'react';

import { usePreferences } from '../../../app/preferences';
import {
  type DailyCandidateRuntimeStatus,
  type DailyCandidateTrial,
  useDailyCandidateTrialReviewMutation,
  useRunDailyCandidateMutation,
} from '../../operations/api';

type ReviewDecision =
  'go_to_bounded_manual_trial' | 'continue_paper_shadow' | 'no_go';

export function DailyCandidateTrialPanel({
  trial,
  runtime,
  reviewEnabled = true,
}: {
  trial: DailyCandidateTrial;
  runtime: DailyCandidateRuntimeStatus;
  reviewEnabled?: boolean;
}) {
  const { locale } = usePreferences();
  const review = useDailyCandidateTrialReviewMutation();
  const run = useRunDailyCandidateMutation();
  const [reviewedBy, setReviewedBy] = useState('');
  const [note, setNote] = useState('');
  const [decision, setDecision] = useState<ReviewDecision>(
    'continue_paper_shadow',
  );
  const canSubmit =
    reviewedBy.trim().length > 0 && note.trim().length > 0 && !review.isPending;
  const goDisabled = !trial.eligible_for_human_go_no_go_review;
  const dailyRunWindowOpen = trial.background_schedule.due;
  const nextWindow = trial.background_schedule.next_reviewed_window;

  return (
    <section
      data-testid="daily-candidate-trial"
      className="mt-4 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)] px-3 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {locale === 'zh' ? '生产试运行' : 'Production operating trial'}
          </div>
          <h3 className="mt-1 text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '冻结策略的每日候选运行'
              : 'Daily candidate run for frozen strategies'}
          </h3>
          <p className="app-muted mt-1 text-xs leading-5">
            {locale === 'zh'
              ? '只累计绑定同一策略晋级证据、已验证交易日和无漂移 paper/shadow 的前瞻样本；不代表未来盈利。'
              : 'Counts only forward samples bound to the same strategy advancement, verified trading days, and drift-clear paper/shadow evidence. It does not establish future profit.'}
          </p>
        </div>
        <div className="rounded-full border border-[color-mix(in_srgb,var(--app-border)_38%,transparent)] px-3 py-1 text-xs font-semibold text-[var(--app-text)]">
          {trial.eligible_for_human_go_no_go_review
            ? locale === 'zh'
              ? '可人工 GO/NO-GO 复核'
              : 'Human GO/NO-GO review eligible'
            : locale === 'zh'
              ? '继续积累证据'
              : 'Collect more evidence'}
        </div>
      </div>

      {reviewEnabled ? (
        <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="app-muted text-xs leading-5">
            <div>
              {locale === 'zh'
                ? '运行时不接受调用方提供的计划、价格、数量或账户金额。'
                : 'The run accepts no caller-supplied plan, price, quantity, or account amount.'}
            </div>
            <div data-testid="daily-candidate-background-schedule">
              {locale === 'zh' ? '后台计划：' : 'Background schedule: '}
              {trial.background_schedule.status} ·{' '}
              {trial.background_schedule.decision_window_start}–
              {trial.background_schedule.decision_window_end} Asia/Shanghai
            </div>
            <div data-testid="daily-candidate-next-reviewed-window">
              {nextWindow?.status === 'available' && nextWindow.market_date
                ? locale === 'zh'
                  ? `${nextWindow.is_current_market_date ? '当前' : '下个'}已验证窗口：${nextWindow.market_date} · 09:35–09:45 Asia/Shanghai · 仅用于准备证据，不允许重试或回填`
                  : `${nextWindow.is_current_market_date ? 'Current' : 'Next'} verified window: ${nextWindow.market_date} · 09:35–09:45 Asia/Shanghai · preparation only; no retry or backfill`
                : locale === 'zh'
                  ? `下个已验证窗口：不可用${nextWindow?.blockers.length ? ` · ${nextWindow.blockers.join(' · ')}` : ''}`
                  : `Next verified window: unavailable${nextWindow?.blockers.length ? ` · ${nextWindow.blockers.join(' · ')}` : ''}`}
            </div>
            <div
              data-testid="daily-candidate-runtime-monitor"
              className={
                runtime.background_monitor_running
                  ? 'text-[var(--app-success)]'
                  : 'text-[var(--app-warning)]'
              }
            >
              {locale === 'zh' ? '后台监控：' : 'Background monitor: '}
              {runtime.background_monitor_running
                ? locale === 'zh'
                  ? '已启用且运行中'
                  : 'enabled and running'
                : `${runtime.status} · ${runtime.operational_blockers.join(' · ')}`}
              {' · '}
              {locale === 'zh'
                ? '仅证明任务存活，不代表财务就绪'
                : 'task liveness only; financial readiness is not claimed'}
            </div>
          </div>
          <button
            type="button"
            disabled={run.isPending || !dailyRunWindowOpen}
            onClick={() => run.mutate()}
            className="app-button min-h-9 shrink-0 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {run.isPending
              ? locale === 'zh'
                ? '运行中…'
                : 'Running…'
              : locale === 'zh'
                ? dailyRunWindowOpen
                  ? '运行当前每日候选'
                  : '当前不在决策窗口'
                : dailyRunWindowOpen
                  ? 'Run current daily candidate'
                  : 'Outside decision window'}
          </button>
        </div>
      ) : null}

      {run.data ? (
        <>
          <div
            data-testid="daily-candidate-run-result"
            className="mt-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-accent)_28%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-text)]"
          >
            {locale === 'zh' ? '本次运行：' : 'Run result: '}
            {run.data.decision_outcome === 'manual_order_ticket_candidate'
              ? locale === 'zh'
                ? `人工订单票据候选（${run.data.manual_ticket_candidate_count} 笔）`
                : `manual order ticket candidate (${run.data.manual_ticket_candidate_count})`
              : `NO-ACTION · ${run.data.no_action_reasons.join(' · ')}`}
            {' · '}
            {locale === 'zh' ? '未提交券商订单' : 'no broker order submitted'}
            {' · '}
            {locale === 'zh' ? '前序成交闭环：' : 'prior execution closure: '}
            {run.data.execution_closure.status}
          </div>
          {run.data.manual_order_ticket_candidates.length > 0 ? (
            <div
              data-testid="manual-order-ticket-candidates"
              className="mt-2 grid gap-2"
            >
              {run.data.manual_order_ticket_candidates.map((ticket) => (
                <div
                  key={ticket.ticket_candidate_fingerprint}
                  className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-warning)_35%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_7%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-text)]"
                >
                  <div className="font-semibold">
                    {locale === 'zh'
                      ? '只读人工票据'
                      : 'Read-only manual ticket'}{' '}
                    · {ticket.symbol} · {ticket.side.toUpperCase()} ·{' '}
                    {ticket.quantity} @ ¥{ticket.limit_price}
                  </div>
                  <div className="app-muted">
                    {locale === 'zh' ? '预计费用' : 'Estimated fees'} ¥
                    {ticket.estimated_total_fee} ·{' '}
                    {locale === 'zh' ? '行情时间' : 'Quote time'}{' '}
                    {ticket.market_quote.timestamp} ·{' '}
                    {locale === 'zh'
                      ? '决策时行情年龄'
                      : 'Quote age at decision'}{' '}
                    {ticket.market_quote.age_seconds_at_decision}/
                    {ticket.market_quote.max_age_seconds}s ·{' '}
                    {locale === 'zh' ? '证据指纹' : 'Evidence fingerprint'}{' '}
                    {ticket.ticket_candidate_fingerprint.slice(0, 16)}…
                  </div>
                  <div className="app-muted">
                    {locale === 'zh' ? '冻结数据集' : 'Frozen dataset'}{' '}
                    {ticket.strategy_gate_binding.candidate_snapshot_id} ·{' '}
                    {locale === 'zh' ? '策略晋级证据' : 'Strategy advancement'}{' '}
                    {ticket.strategy_gate_binding.strategy_advancement_ref.slice(
                      0,
                      32,
                    )}
                    …
                  </div>
                  {ticket.strategy_operating_constraints ? (
                    <div
                      data-testid="strategy-operating-constraints"
                      className="mt-1 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] px-2 py-1"
                    >
                      <div className="font-semibold">
                        {locale === 'zh'
                          ? '冻结策略假设与失效条件'
                          : 'Frozen strategy thesis and failure conditions'}
                      </div>
                      <div className="app-muted">
                        {locale === 'zh' ? '假设：' : 'Thesis: '}
                        {
                          ticket.strategy_operating_constraints
                            .economic_hypothesis
                        }
                      </div>
                      <div className="app-muted">
                        {locale === 'zh' ? '风险影响：' : 'Risk impact: '}
                        {ticket.strategy_operating_constraints.risk_impact}
                      </div>
                      <div className="app-muted">
                        {locale === 'zh'
                          ? '失效条件：'
                          : 'Failure conditions: '}
                        {ticket.strategy_operating_constraints.failure_conditions.join(
                          ' · ',
                        )}
                      </div>
                      <div className="app-muted">
                        {locale === 'zh' ? '限制：' : 'Limitations: '}
                        {ticket.strategy_operating_constraints.limitations.join(
                          ' · ',
                        )}
                      </div>
                      <div className="app-muted">
                        {locale === 'zh'
                          ? '防未来数据假设：'
                          : 'Anti-lookahead assumptions: '}
                        {ticket.strategy_operating_constraints.anti_lookahead_assumptions.join(
                          ' · ',
                        )}
                      </div>
                      <div className="app-muted">
                        {locale === 'zh'
                          ? '仅供人工复核，不自动执行或改变资金授权。'
                          : 'Human review only; these constraints do not execute trades or change capital authority.'}
                      </div>
                    </div>
                  ) : (
                    <div
                      data-testid="strategy-operating-constraints-missing"
                      className="mt-1 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-danger)_45%,transparent)] px-2 py-1 font-semibold text-[var(--app-danger)]"
                    >
                      {locale === 'zh'
                        ? 'NO-ACTION：旧版或不完整票据缺少已复核策略失效条件，不可用于人工执行。'
                        : 'NO-ACTION: this legacy or incomplete ticket lacks reviewed strategy failure conditions and is not eligible for manual execution.'}
                    </div>
                  )}
                  <div className="app-muted">
                    Account Truth ·{' '}
                    {locale === 'zh' ? '决策时年龄' : 'Age at decision'}{' '}
                    {ticket.account_truth_binding.age_seconds_at_decision}/
                    {ticket.account_truth_binding.max_age_seconds}s ·{' '}
                    {locale === 'zh' ? '账本截止' : 'Ledger cutoff'}{' '}
                    {ticket.account_truth_binding.ledger_cutoff_id} ·{' '}
                    {locale === 'zh' ? '估值快照' : 'Valuation snapshot'}{' '}
                    {ticket.account_truth_binding.valuation_snapshot_id}
                  </div>
                  <div className="font-semibold text-[var(--app-warning)]">
                    {locale === 'zh'
                      ? '必须人工复核；未创建 OMS 订单、未授权券商提交或扩大资金。'
                      : 'Human review required; no OMS order, broker submission, or capital expansion is authorized.'}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}

      {run.isError ? (
        <div className="mt-2 text-xs text-[var(--app-danger)]">
          {locale === 'zh'
            ? '每日候选运行失败；未创建或提交真实订单。'
            : 'Daily candidate run failed; no real order was created or submitted.'}
        </div>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        <Metric
          label={locale === 'zh' ? '合格交易日' : 'Qualifying days'}
          value={`${trial.qualifying_trading_day_count}/${trial.target_qualifying_trading_days}`}
        />
        <Metric
          label={locale === 'zh' ? '模拟订单' : 'Simulated orders'}
          value={`${trial.simulated_order_count}/${trial.target_simulated_orders}`}
        />
        <Metric
          label={locale === 'zh' ? '策略冻结绑定' : 'Frozen strategy bindings'}
          value={String(trial.strategy_advancement_refs.length)}
        />
        <Metric
          label={locale === 'zh' ? '当前试运行周期' : 'Current trial epoch'}
          value={
            trial.trial_epoch_start_date
              ? `${trial.trial_epoch_start_date} · ${
                  locale === 'zh' ? '已归档' : 'superseded'
                } ${trial.superseded_qualifying_day_count}`
              : locale === 'zh'
                ? '尚未开始'
                : 'Not started'
          }
        />
      </div>

      {trial.current_execution_evidence ? (
        <div
          data-testid="daily-candidate-execution-evidence"
          className="mt-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-text)]"
        >
          <div className="font-semibold">
            {locale === 'zh'
              ? '当前真实执行闭环（计划—模拟—实际）'
              : 'Current real execution closure (plan–paper–actual)'}
          </div>
          <div className="app-muted">
            {locale === 'zh' ? '闭环覆盖' : 'Closure coverage'}{' '}
            {trial.current_execution_evidence.clear_order_count}/
            {trial.current_execution_evidence.production_order_count} ·{' '}
            {locale === 'zh' ? '实际成交已对账' : 'reconciled actual'}{' '}
            {trial.current_execution_evidence.reconciled_actual_order_count} ·{' '}
            {locale === 'zh' ? '终态无成交' : 'terminal no-fill'}{' '}
            {trial.current_execution_evidence.reconciled_no_fill_order_count} ·{' '}
            {trial.current_execution_evidence.status}
          </div>
          <div className="app-muted">
            {locale === 'zh'
              ? '这些真实成交或终态无成交只用于闭环覆盖，不计入 50 笔模拟订单，也不归因于本次试运行策略。'
              : 'Real fills and terminal no-fills are closure evidence only; they do not count toward the 50 simulated orders and are not attributed to this trial strategy.'}
          </div>
          {trial.current_execution_evidence.blockers.length > 0 ? (
            <div className="text-[var(--app-warning)]">
              {locale === 'zh' ? '闭环阻断：' : 'Closure blockers: '}
              {trial.current_execution_evidence.blockers.join(' · ')}
            </div>
          ) : null}
        </div>
      ) : (
        <div
          data-testid="daily-candidate-execution-evidence-missing"
          className="mt-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-danger)_45%,transparent)] px-3 py-2 text-xs font-semibold leading-5 text-[var(--app-danger)]"
        >
          {locale === 'zh'
            ? 'NO-ACTION：缺少当前真实执行闭环契约，GO/NO-GO 复核不可用。'
            : 'NO-ACTION: the current real-execution closure contract is missing; GO/NO-GO review is unavailable.'}
        </div>
      )}

      {trial.latest_daily_run ? (
        <div
          data-testid="daily-candidate-latest-outcome"
          className="mt-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-text)]"
        >
          <span className="font-semibold">
            {locale === 'zh' ? '最新生产结论：' : 'Latest production outcome: '}
          </span>
          {trial.latest_daily_run.decision_outcome ===
          'manual_order_ticket_candidate'
            ? locale === 'zh'
              ? `人工订单票据候选（${trial.latest_daily_run.simulated_order_count} 笔）`
              : `manual order ticket candidate (${trial.latest_daily_run.simulated_order_count})`
            : 'NO-ACTION'}
          {' · '}
          {trial.latest_daily_run.run_date}
          {trial.latest_daily_run.blockers.length > 0
            ? ` · ${trial.latest_daily_run.blockers.join(' · ')}`
            : ''}
        </div>
      ) : null}

      {trial.blockers.length > 0 ? (
        <div className="mt-3 text-xs leading-5 text-[var(--app-warning)]">
          {locale === 'zh' ? '当前阻断：' : 'Current blockers: '}
          {trial.blockers.join(' · ')}
        </div>
      ) : null}

      {trial.latest_review ? (
        <div className="mt-3 rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] bg-[color-mix(in_srgb,var(--app-success)_8%,transparent)] px-3 py-2 text-xs leading-5 text-[var(--app-text)]">
          {locale === 'zh' ? '已记录人工结论：' : 'Recorded human conclusion: '}
          {trial.latest_review.decision}
          {' · '}
          {trial.latest_review.reviewed_by}
          {' · '}
          {locale === 'zh'
            ? '不授予交易或资金额度权限'
            : 'no trading or capital authority granted'}
        </div>
      ) : reviewEnabled ? (
        <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] lg:items-end">
          <label className="min-w-0 text-xs text-[var(--app-text-secondary)]">
            <span className="mb-1 block">
              {locale === 'zh' ? '复核结论' : 'Review decision'}
            </span>
            <select
              value={decision}
              onChange={(event) =>
                setDecision(event.target.value as ReviewDecision)
              }
              className="app-input w-full"
            >
              <option value="continue_paper_shadow">
                {locale === 'zh'
                  ? '继续 paper/shadow'
                  : 'Continue paper/shadow'}
              </option>
              <option value="no_go">NO-GO</option>
              <option value="go_to_bounded_manual_trial" disabled={goDisabled}>
                {locale === 'zh'
                  ? 'GO：进入有界人工试单'
                  : 'GO: bounded manual trial'}
              </option>
            </select>
          </label>
          <label className="min-w-0 text-xs text-[var(--app-text-secondary)]">
            <span className="mb-1 block">
              {locale === 'zh' ? '复核人' : 'Reviewer'}
            </span>
            <input
              value={reviewedBy}
              onChange={(event) => setReviewedBy(event.target.value)}
              className="app-input w-full"
              placeholder={locale === 'zh' ? '人工复核人' : 'Human reviewer'}
            />
          </label>
          <label className="min-w-0 text-xs text-[var(--app-text-secondary)]">
            <span className="mb-1 block">
              {locale === 'zh' ? '复核说明' : 'Review note'}
            </span>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="app-input w-full"
              placeholder={
                locale === 'zh'
                  ? '说明继续、GO 或 NO-GO 的依据'
                  : 'State the basis for continue, GO, or NO-GO'
              }
            />
          </label>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() =>
              review.mutate({
                expected_trial_fingerprint: trial.trial_fingerprint,
                decision,
                reviewed_by: reviewedBy.trim(),
                note: note.trim(),
                confirmation:
                  'record_daily_candidate_trial_review_without_trade_or_capital_authority',
              })
            }
            className="app-button app-button-primary min-h-10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {review.isPending
              ? locale === 'zh'
                ? '记录中…'
                : 'Recording…'
              : locale === 'zh'
                ? '记录人工结论'
                : 'Record human conclusion'}
          </button>
        </div>
      ) : (
        <div className="app-muted mt-3 text-xs leading-5">
          {locale === 'zh'
            ? '交易控制状态不可验证；恢复控制证据前仅展示试运行进度，不接受新的人工结论。'
            : 'Trading controls are not verifiable. Trial progress remains read-only until control evidence is restored.'}
        </div>
      )}

      {review.isError ? (
        <div className="mt-2 text-xs text-[var(--app-danger)]">
          {locale === 'zh'
            ? '复核记录失败；请刷新证据并重试。'
            : 'Review recording failed. Refresh evidence and try again.'}
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--app-radius-control)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-2">
      <div className="app-muted text-xs">{label}</div>
      <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
        {value}
      </div>
    </div>
  );
}
