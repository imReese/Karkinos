import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { type AutomationCockpitResponse } from '../decision-feature-boundary';
import { ControlledBrokerRecoveryOperatorPanel } from '../decision-feature-boundary';
import { ControlledBrokerRejectionEvidencePanel } from '../decision-feature-boundary';
import { ControlledLedgerPostingOperatorPanel } from '../decision-feature-boundary';
import { ControlledLedgerCorrectionOperatorPanel } from '../decision-feature-boundary';
import { ControlledSessionRevocationOperatorPanel } from '../decision-feature-boundary';
import { ControlledTerminalClearanceOperatorPanel } from '../decision-feature-boundary';
import { ManualBrokerCancellationTicketPanel } from '../decision-feature-boundary';
import {
  controlledExecutionCurrency,
  controlledExecutionStatusLabel,
  controlledOrderJourneyBlockerLabel,
  controlledOrderJourneyNextActionLabel,
  controlledOrderJourneyStageLabel,
} from './decision-execution-model';

type ControlledExecution = NonNullable<
  AutomationCockpitResponse['controlled_execution']
>;

export function ControlledExecutionSection({
  controlledExecution,
}: {
  controlledExecution: ControlledExecution | undefined;
}) {
  const { locale } = usePreferences();
  const controlledExecutionSession =
    controlledExecution?.sessions.find(
      (session) => session.is_current_window,
    ) ?? controlledExecution?.sessions[0];
  return (
    <>
      {controlledExecution ? (
        <div
          data-testid="controlled-execution-operator-view"
          className="mt-4 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_12%,transparent)] px-3 py-3"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                {locale === 'zh'
                  ? '受控执行操作视图'
                  : 'Controlled execution operator view'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '仅显示已持久化的资本边界、门禁与对账证据，不授予执行权限。'
                  : 'Persisted capital, gate, and reconciliation evidence only; no execution authority is granted.'}
              </div>
            </div>
            <span className="app-chip">
              {controlledExecutionStatusLabel(
                controlledExecutionSession?.status ??
                  controlledExecution.status,
                locale,
              )}
            </span>
          </div>

          {controlledExecutionSession ? (
            <>
              <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
                {[
                  {
                    label:
                      locale === 'zh' ? '账户 / 策略' : 'Account / strategy',
                    value: `${controlledExecutionSession.account_alias || '—'} / ${controlledExecutionSession.strategy_id || '—'}`,
                  },
                  {
                    label: locale === 'zh' ? '授权资本' : 'Authorized capital',
                    value: controlledExecutionCurrency(
                      controlledExecutionSession.authorized_capital,
                    ),
                  },
                  {
                    label:
                      locale === 'zh'
                        ? '当前风险资本'
                        : 'Effective capital at risk',
                    value: controlledExecutionCurrency(
                      controlledExecutionSession.effective_capital_at_risk,
                    ),
                  },
                  {
                    label: locale === 'zh' ? '资本余量' : 'Capital headroom',
                    value: controlledExecutionCurrency(
                      controlledExecutionSession.remaining_budget
                        .capital_headroom,
                    ),
                  },
                  {
                    label: locale === 'zh' ? '现金余量' : 'Cash headroom',
                    value: controlledExecutionCurrency(
                      controlledExecutionSession.remaining_budget.cash_headroom,
                    ),
                  },
                  {
                    label: locale === 'zh' ? '换手余量' : 'Turnover headroom',
                    value: controlledExecutionCurrency(
                      controlledExecutionSession.remaining_budget
                        .turnover_headroom,
                    ),
                  },
                  {
                    label:
                      locale === 'zh'
                        ? '剩余订单槽位'
                        : 'Remaining order slots',
                    value: String(
                      controlledExecutionSession.remaining_budget
                        .remaining_order_slots,
                    ),
                  },
                  {
                    label: locale === 'zh' ? '授权到期' : 'Authority expires',
                    value: controlledExecutionSession.expires_at || '—',
                  },
                ].map((item) => (
                  <div
                    className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5"
                    key={item.label}
                  >
                    <div className="app-muted text-xs">{item.label}</div>
                    <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-3 grid min-w-0 gap-2 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                <div className="min-w-0 break-words">
                  {locale === 'zh' ? '最近订单' : 'Last order'}:{' '}
                  {controlledExecutionSession.last_order.order_id || '—'} ·{' '}
                  {controlledExecutionSession.last_order.submission_status ||
                    (locale === 'zh' ? '无提交事实' : 'no submission fact')}
                </div>
                <div className="min-w-0 break-words">
                  {locale === 'zh' ? '最近对账' : 'Last reconciliation'}:{' '}
                  {controlledExecutionSession.last_reconciliation.run_id || '—'}{' '}
                  ·{' '}
                  {controlledExecutionSession.last_reconciliation
                    .suggested_action ||
                    controlledExecutionSession.last_reconciliation
                      .item_status ||
                    (locale === 'zh' ? '无对账事实' : 'no reconciliation fact')}
                </div>
                <div className="min-w-0 break-words">
                  {locale === 'zh' ? '允许标的' : 'Allowed symbols'}:{' '}
                  {controlledExecutionSession.allowed_symbols.join(', ') || '—'}
                </div>
                <div className="min-w-0 break-words">
                  {locale === 'zh' ? '门禁快照' : 'Gate snapshot'}:{' '}
                  {controlledExecutionSession.latest_gate_snapshot.status ||
                    '—'}
                </div>
              </div>

              {controlledExecutionSession.pause.reasons.length ? (
                <div className="mt-2 break-words text-xs font-semibold text-[var(--app-warning)]">
                  {locale === 'zh' ? '暂停原因' : 'Pause reason'}:{' '}
                  {controlledExecutionSession.pause.reasons.join(' · ')}
                </div>
              ) : null}
              {controlledExecutionSession.blockers.length ||
              controlledExecution.source_blockers.length ? (
                <div className="app-muted mt-2 break-words text-xs leading-5">
                  {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
                  {[
                    ...controlledExecutionSession.blockers,
                    ...controlledExecution.source_blockers,
                  ]
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ')}
                </div>
              ) : null}
              <ControlledSessionRevocationOperatorPanel
                session={controlledExecutionSession}
                locale={locale}
              />
            </>
          ) : (
            <div className="app-muted mt-3 text-sm">
              {locale === 'zh'
                ? '没有已持久化的受控执行会话；实盘提交保持关闭。'
                : 'No persisted controlled-execution session; live submission remains off.'}
            </div>
          )}

          <ControlledOrderJourneySection
            controlledExecution={controlledExecution}
          />
          <div className="mt-3 flex min-w-0 flex-wrap gap-2">
            {[
              locale === 'zh' ? '仅持久化事实' : 'Persisted facts only',
              locale === 'zh' ? '未联系外部服务' : 'No provider contact',
              locale === 'zh' ? '提交关闭' : 'Submission off',
              locale === 'zh' ? '撤单关闭' : 'Cancellation off',
              locale === 'zh'
                ? '无权限自动恢复'
                : 'No automatic authority resume',
              locale === 'zh' ? '禁止自动扩容' : 'No automatic scale-up',
            ].map((label) => (
              <span className="app-chip" key={label}>
                {label}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

function ControlledOrderJourneySection({
  controlledExecution,
}: {
  controlledExecution: ControlledExecution;
}) {
  const { locale } = usePreferences();
  const latestControlledOrderJourney = controlledExecution.latest_order_journey;
  const primaryControlledOrderJourney =
    controlledExecution.primary_attention_order_journey ??
    latestControlledOrderJourney;
  const controlledOrderAttentionQueue =
    controlledExecution.attention_order_journeys ?? [];
  return (
    <>
      {primaryControlledOrderJourney ? (
        <div
          data-testid="controlled-order-journey"
          className="mt-4 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-accent)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)] px-3 py-3"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {controlledExecution.primary_attention_order_journey
                  ? locale === 'zh'
                    ? '优先处理的受控订单证据旅程'
                    : 'Priority controlled order evidence journey'
                  : locale === 'zh'
                    ? '最近受控订单证据旅程'
                    : 'Latest controlled order evidence journey'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {primaryControlledOrderJourney.order_id || '—'} ·{' '}
                {primaryControlledOrderJourney.gateway_id || '—'}
              </div>
            </div>
            <span className="app-chip max-w-full break-words text-left">
              {locale === 'zh' ? '下一步：' : 'Next: '}
              {controlledOrderJourneyNextActionLabel(
                primaryControlledOrderJourney.next_operator_action,
                locale,
              )}
            </span>
          </div>

          <div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {primaryControlledOrderJourney.stages.map((stage) => {
              const optionalStageNotApplied =
                !stage.required && !stage.complete;
              return (
                <div
                  className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_16%,transparent)] px-3 py-2.5"
                  key={stage.key}
                >
                  <div className="app-muted app-type-micro">
                    {controlledOrderJourneyStageLabel(stage.key, locale)}
                  </div>
                  <div className="mt-1 break-words text-sm font-semibold text-[var(--app-text)]">
                    {formatPublicStatus(stage.status, locale)}
                  </div>
                  <div className="app-muted app-type-micro mt-1">
                    {stage.complete
                      ? locale === 'zh'
                        ? '证据已记录'
                        : 'Evidence recorded'
                      : optionalStageNotApplied
                        ? locale === 'zh'
                          ? '仅在发现错误时使用'
                          : 'Only used when an error is confirmed'
                        : locale === 'zh'
                          ? '等待单独人工步骤'
                          : 'Separate human step pending'}
                  </div>
                  {stage.evidence_id ? (
                    <div
                      className="app-muted mt-1 truncate font-mono text-[length:var(--app-font-size-micro)]"
                      title={stage.evidence_id}
                    >
                      {stage.evidence_id}
                    </div>
                  ) : null}
                  {stage.terminal_status ? (
                    <div className="app-muted mt-1 text-[length:var(--app-font-size-micro)]">
                      {locale === 'zh' ? '终态' : 'Terminal'}:{' '}
                      {formatPublicStatus(stage.terminal_status, locale)} ·{' '}
                      {locale === 'zh' ? '成交笔数' : 'Fills'}{' '}
                      {stage.fill_count ?? 0}
                    </div>
                  ) : null}
                  {(stage.post_ledger_cutoff_id ?? 0) > 0 ? (
                    <div className="app-muted mt-1 text-[length:var(--app-font-size-micro)]">
                      ledger cutoff #{stage.post_ledger_cutoff_id}
                    </div>
                  ) : null}
                  {stage.key === 'post_ledger_account_truth' ? (
                    <div className="app-muted mt-1 break-words text-[length:var(--app-font-size-micro)]">
                      {locale === 'zh' ? '账户事实' : 'Account Truth'}:{' '}
                      {formatPublicStatus(
                        stage.account_truth_gate_status ?? 'missing',
                        locale,
                      )}{' '}
                      · {locale === 'zh' ? '账本覆盖' : 'Ledger coverage'}:{' '}
                      {formatPublicStatus(
                        stage.ledger_coverage_status ?? 'missing',
                        locale,
                      )}
                    </div>
                  ) : null}
                  {(stage.blockers?.length ?? 0) > 0 ? (
                    <div
                      className="mt-1 break-words text-[length:var(--app-font-size-micro)] text-[var(--app-warning)]"
                      title={stage.blockers?.join(', ')}
                    >
                      {locale === 'zh' ? '复核原因' : 'Review reason'}:{' '}
                      {controlledOrderJourneyBlockerLabel(
                        stage.blockers?.[0] ?? '',
                        locale,
                      )}
                      {(stage.blockers?.length ?? 0) > 1
                        ? ` +${(stage.blockers?.length ?? 1) - 1}`
                        : ''}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          <div className="app-muted mt-3 break-words text-xs leading-5">
            {locale === 'zh'
              ? '该旅程只投影持久化证据；本次读取未联系券商、未提交或撤单、未修改账本，也未改变任何资本或执行权限。'
              : 'This journey projects persisted evidence only. This read contacted no broker, submitted or cancelled no order, mutated no ledger, and changed no capital or execution authority.'}
          </div>
          {controlledOrderAttentionQueue.length > 1 ? (
            <details
              data-testid="controlled-order-attention-queue"
              className="mt-3 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-warning)_30%,transparent)] px-3 py-2.5"
            >
              <summary className="cursor-pointer text-xs font-semibold text-[var(--app-warning)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--app-accent)]">
                {locale === 'zh'
                  ? `全部人工关注队列 · ${controlledExecution.attention_order_journey_count} 笔`
                  : `Full operator attention queue · ${controlledExecution.attention_order_journey_count}`}
              </summary>
              <div className="mt-2 grid gap-2">
                {controlledOrderAttentionQueue.map((journey, index) => (
                  <div
                    className="grid min-w-0 gap-1 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-2.5 py-2 text-xs sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]"
                    key={journey.submit_intent_id}
                  >
                    <div className="min-w-0 break-words font-semibold text-[var(--app-text)]">
                      {index === 0
                        ? locale === 'zh'
                          ? '当前优先 · '
                          : 'Current priority · '
                        : ''}
                      {journey.order_id || '—'} ·{' '}
                      {journey.attention_severity === 'critical'
                        ? locale === 'zh'
                          ? '关键'
                          : 'Critical'
                        : locale === 'zh'
                          ? '警告'
                          : 'Warning'}
                    </div>
                    <div className="app-muted min-w-0 break-words">
                      {controlledOrderJourneyNextActionLabel(
                        journey.next_operator_action,
                        locale,
                      )}
                      {journey.blocks_new_submissions
                        ? locale === 'zh'
                          ? ' · 阻断新的受控提交'
                          : ' · blocks new controlled submissions'
                        : ''}
                    </div>
                  </div>
                ))}
                {controlledExecution.attention_queue_truncated ? (
                  <div className="app-muted text-xs">
                    {locale === 'zh'
                      ? '队列显示已达到上限；请先处理当前可见项。'
                      : 'The visible queue reached its limit; review the current items first.'}
                  </div>
                ) : null}
              </div>
            </details>
          ) : null}
          <ControlledBrokerRecoveryOperatorPanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
          <ControlledBrokerRejectionEvidencePanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
          <ManualBrokerCancellationTicketPanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
          <ControlledTerminalClearanceOperatorPanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
          <ControlledLedgerPostingOperatorPanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
          <ControlledLedgerCorrectionOperatorPanel
            journey={primaryControlledOrderJourney}
            locale={locale}
          />
        </div>
      ) : null}
    </>
  );
}
