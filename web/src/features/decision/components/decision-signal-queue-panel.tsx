import { useState } from 'react';
import {
  ControlledActionZone,
  EvidenceState,
  StatusBadge,
} from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';
import {
  formatPublicCode,
  formatPublicEvidenceReference,
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import {
  useCreateManualOrderFromActionMutation,
  type ActionCard,
  type DecisionResponse,
  type SignalJournalEntry,
} from '../api';
import { isShadowStrategy } from '../../../shared/strategy-display';
import { DecisionOutcomeReviewPanel } from './decision-outcome-review-panel';
import {
  strategyAuditIdFromDisplay,
  strategyDisplayNameFromId,
} from './decision-status-model';
import {
  signalActionBacktestHref,
  signalActionHoldingAttributionHref,
  signalBacktestHref,
  signalHoldingAttributionHref,
} from './decision-workflow-model';

import type { Locale } from '../../../shared/locale';

export function PageHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle: string;
}) {
  const labels = useCopy().decision;
  return (
    <header className="app-page-header min-w-0 pb-1">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.kicker}</div>
          <h1 className="app-page-title mt-2">{title}</h1>
        </div>
        <p className="app-page-subtitle min-w-0 break-words sm:max-w-xl sm:text-right">
          {subtitle}
        </p>
      </div>
    </header>
  );
}

function OperatingPostureCard({
  locale,
  signalCount,
}: {
  locale: Locale;
  signalCount: number;
}) {
  return (
    <div className="rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3.5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="app-type-micro font-semibold text-[var(--app-text-tertiary)] uppercase tracking-wider">
          {locale === 'zh'
            ? '今日决策姿态与约束检查'
            : 'Operating Posture & Controls'}
        </span>
        <StatusBadge tone="success">
          {locale === 'zh' ? '风控通过 · 无待办' : 'Risk Passed · Clear'}
        </StatusBadge>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '策略信号流水' : 'Recorded Signals'}
          </dt>
          <dd className="mt-0.5 font-medium text-[var(--app-text)] font-mono tabular-nums">
            {locale === 'zh'
              ? `${signalCount} 条已入库`
              : `${signalCount} recorded`}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '前置风控拦截' : 'Risk Interceptions'}
          </dt>
          <dd className="mt-0.5 font-medium text-[var(--app-text)] font-mono tabular-nums">
            {locale === 'zh' ? '0 项阻断' : '0 blocked'}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '执行授权模式' : 'Execution Authority'}
          </dt>
          <dd className="mt-0.5 font-medium text-[var(--app-text)]">
            {locale === 'zh' ? '人工确认 · 券商离线' : 'Manual only · Offline'}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '动作准备状态' : 'Action Readiness'}
          </dt>
          <dd className="mt-0.5 font-medium text-[var(--app-text)]">
            {locale === 'zh' ? '暂无待确认订单' : 'No pending orders'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function SignalJournalCard({
  entry,
  locale,
  labels,
  strategyNames,
}: {
  entry: SignalJournalEntry;
  locale: Locale;
  labels: ReturnType<typeof useCopy>['decision'];
  strategyNames: Record<string, string>;
}) {
  const instrumentLabel = formatInstrumentDisplayLabel(entry.signal);
  const strategyLabel = strategyDisplayNameFromId(
    entry.signal.strategy_id,
    strategyNames,
  );
  const strategyAuditId = strategyAuditIdFromDisplay(
    entry.signal.strategy_id,
    strategyNames,
  );
  const isShadow = isShadowStrategy(entry.signal.strategy_id);
  const latestSourceRef = entry.latest_event?.source_ref;
  const publicSourceRef =
    latestSourceRef && latestSourceRef.includes(':')
      ? formatPublicEvidenceReference(latestSourceRef, locale)
      : null;
  const direction = entry.signal.direction?.toLowerCase();
  const isBuy = direction === 'buy';
  const isSell = direction === 'sell';
  const directionTone = isBuy ? 'success' : isSell ? 'danger' : 'neutral';
  const directionLabel = formatPublicStatus(entry.signal.direction, locale);
  const formattedWeight =
    entry.signal.target_weight != null
      ? `${(entry.signal.target_weight * 100).toFixed(1)}%`
      : null;
  const formattedPrice =
    entry.signal.price != null ? `¥${entry.signal.price.toFixed(2)}` : null;

  return (
    <article className="rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 min-w-0">
          <span className="font-semibold text-[var(--app-text)]">
            {instrumentLabel}
          </span>
          <StatusBadge tone={directionTone}>{directionLabel}</StatusBadge>
        </div>
        <time className="shrink-0 font-mono tabular-nums app-type-micro text-[var(--app-text-tertiary)]">
          {formatTimestamp(
            entry.latest_event?.timestamp ??
              entry.review?.reviewed_at ??
              entry.signal.timestamp,
          )}
        </time>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {labels.strategy}
          </dt>
          <dd
            className="flex items-center gap-1.5 font-medium text-[var(--app-text)] truncate"
            title={
              strategyAuditId
                ? `${strategyLabel} (${strategyAuditId})`
                : strategyLabel
            }
          >
            <span className="truncate">{strategyLabel}</span>
            {isShadow ? (
              <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-normal border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] text-[var(--app-text-secondary)]">
                {locale === 'zh' ? '影子试运行' : 'Shadow trial'}
              </span>
            ) : null}
          </dd>
        </div>
        {formattedWeight ? (
          <div className="min-w-0">
            <dt className="text-[var(--app-text-secondary)]">
              {labels.targetWeight}
            </dt>
            <dd className="font-mono tabular-nums text-[var(--app-text)]">
              {formattedWeight}
            </dd>
          </div>
        ) : null}
        {formattedPrice ? (
          <div className="min-w-0">
            <dt className="text-[var(--app-text-secondary)]">{labels.price}</dt>
            <dd className="font-mono tabular-nums text-[var(--app-text)]">
              {formattedPrice}
            </dd>
          </div>
        ) : null}
        <div className="min-w-0">
          <dt className="text-[var(--app-text-secondary)]">
            {labels.riskDecision}
          </dt>
          <dd className="text-[var(--app-text-secondary)] truncate">
            {formatPublicCode(
              entry.latest_event?.event_type ??
                entry.review?.outcome ??
                entry.action_task?.status ??
                '--',
              locale,
            )}
          </dd>
        </div>
      </dl>
      {publicSourceRef ? (
        <div
          className="mt-1 truncate font-mono app-type-micro text-[var(--app-text-tertiary)]"
          title={publicSourceRef}
        >
          {publicSourceRef}
        </div>
      ) : null}

      <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-[var(--app-divider)] pt-2">
        <a
          className="app-button-secondary app-type-micro inline-flex min-h-8 items-center justify-center rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-center font-semibold whitespace-normal"
          href={signalBacktestHref(entry.signal)}
          onClick={(e) =>
            handleClientNavigation(e, signalBacktestHref(entry.signal))
          }
          aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
        >
          {labels.openBacktestEvidence}
        </a>
        <a
          className="app-button-secondary app-type-micro inline-flex min-h-8 items-center justify-center rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-center font-semibold whitespace-normal"
          href={signalHoldingAttributionHref(entry.signal)}
          onClick={(e) =>
            handleClientNavigation(
              e,
              signalHoldingAttributionHref(entry.signal),
            )
          }
          aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
        >
          {labels.openAttributionReview}
        </a>
        <DecisionOutcomeReviewPanel entry={entry} />
      </div>
    </article>
  );
}

export function SignalQueuePanel({
  actions,
  journal,
  dailyGeneration,
  decisionDate,
  loading,
  error,
}: {
  actions: ActionCard[];
  journal: SignalJournalEntry[];
  dailyGeneration?: DecisionResponse['generation'];
  decisionDate?: string;
  loading: boolean;
  error: boolean;
}) {
  const copy = useCopy();
  const labels = copy.decision;
  const { locale } = usePreferences();
  const createManualOrder = useCreateManualOrderFromActionMutation();
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [signalQueueExpanded, setSignalQueueExpanded] = useState(false);
  const latestJournal = journal.slice(0, 4);
  const collapseSignalQueue = actions.length > 3 && !signalQueueExpanded;

  const prepareManualOrder = async (action: ActionCard) => {
    if (action.id === null) {
      return;
    }
    const quantity = Number(quantities[action.id] ?? '100');
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return;
    }
    await createManualOrder.mutateAsync({
      actionId: action.id,
      quantity,
      price: action.price,
    });
  };

  return (
    <section
      className="min-w-0 border-y border-[var(--app-divider)] py-4"
      data-testid="decision-signal-queue-register"
    >
      <div className="min-w-0 px-1 sm:px-3">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.signalQueue}</div>
            <h2 className="app-type-section-title mt-1.5 text-[var(--app-text)]">
              {labels.signalQueueTitle}
            </h2>
          </div>
        </div>

        {loading ? (
          <div className="app-muted mt-4 text-sm">{labels.loading}</div>
        ) : error ? (
          <div className="app-error-text mt-4 text-sm">{labels.error}</div>
        ) : collapseSignalQueue ? (
          <div
            data-testid="signal-queue-collapsed"
            className="mt-4 flex min-w-0 flex-col gap-3 border-y border-[var(--app-divider)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <div className="text-sm font-semibold text-[var(--app-text)]">
                {labels.signalQueueCollapsedTitle(actions.length)}
              </div>
            </div>
            <button
              className="app-button-secondary inline-flex min-h-9 max-w-full items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-xs font-semibold"
              type="button"
              onClick={() => setSignalQueueExpanded(true)}
            >
              {labels.expandSignalQueue}
            </button>
          </div>
        ) : (
          <div
            className={`mt-4 grid min-w-0 gap-5 ${
              actions.length === 0
                ? 'xl:grid-cols-[minmax(320px,360px)_minmax(0,1fr)]'
                : 'xl:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.95fr)]'
            }`}
          >
            <div className="grid min-w-0 max-h-[36rem] gap-3 overflow-y-auto pr-1">
              {actions.length === 0 ? (
                <div className="space-y-3">
                  <EvidenceState
                    kind="empty"
                    statusLabel={labels.signalQueue}
                    title={labels.noSignalActions}
                    description={labels.signalQueueDetail}
                  />
                  <OperatingPostureCard
                    locale={locale}
                    signalCount={latestJournal.length}
                  />
                </div>
              ) : (
                actions.slice(0, 4).map((action) => {
                  const instrumentLabel = formatInstrumentDisplayLabel(action);
                  const actionId = action.id;
                  const unverifiedDailyScanAction =
                    action.strategy_id.startsWith('ai_formula_shadow:') &&
                    action.timestamp.slice(0, 10) === decisionDate &&
                    (dailyGeneration?.recommendation_authoritative !== true ||
                      actionId === null ||
                      !(
                        dailyGeneration.formal_candidate_action_ids ?? []
                      ).includes(actionId));
                  return (
                    <article
                      key={action.id ?? action.symbol}
                      data-testid={`signal-action-card-${action.id ?? action.symbol}`}
                      className="min-w-0 rounded-[var(--app-radius-surface)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3"
                    >
                      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-[var(--app-text)]">
                              {instrumentLabel}
                            </span>
                            <StatusBadge
                              tone={
                                action.direction?.toLowerCase() === 'buy'
                                  ? 'success'
                                  : action.direction?.toLowerCase() === 'sell'
                                    ? 'danger'
                                    : 'neutral'
                              }
                            >
                              {formatPublicStatus(action.direction, locale)}
                            </StatusBadge>
                            <StatusBadge tone="neutral">
                              {formatPublicStatus(
                                action.risk_gate_status,
                                locale,
                              )}
                            </StatusBadge>
                          </div>
                          <div className="app-muted mt-1 break-words text-xs">
                            {formatPublicStatus(
                              action.manual_confirmation_status,
                              locale,
                            )}
                          </div>
                          <div className="app-muted mt-2 break-words text-xs leading-5">
                            {formatPublicNote(action.detail, locale)}
                          </div>
                          {unverifiedDailyScanAction ? (
                            <div className="mt-2 text-xs text-[var(--app-warning-text)]">
                              {locale === 'zh'
                                ? '此信号未绑定今日最终报告，不能据此准备手工订单。'
                                : 'This signal is not bound to today’s final report and cannot prepare a manual order.'}
                            </div>
                          ) : null}
                        </div>
                        <div className="grid shrink-0 gap-2 sm:grid-cols-2 lg:min-w-[280px]">
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionBacktestHref(action)}
                            onClick={(e) =>
                              handleClientNavigation(
                                e,
                                signalActionBacktestHref(action),
                              )
                            }
                            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
                          >
                            {labels.openBacktestEvidence}
                          </a>
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionHoldingAttributionHref(action)}
                            onClick={(e) =>
                              handleClientNavigation(
                                e,
                                signalActionHoldingAttributionHref(action),
                              )
                            }
                            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
                          >
                            {labels.openAttributionReview}
                          </a>
                          {actionId !== null &&
                          !unverifiedDailyScanAction &&
                          action.manual_confirmation_status ===
                            'ready_for_manual_confirmation' ? (
                            <ControlledActionZone
                              className="sm:col-span-2"
                              tone="info"
                              layout="stack"
                              title={labels.manual}
                              description={formatPublicStatus(
                                action.manual_confirmation_status,
                                locale,
                              )}
                              evidence={`${formatPublicStatus(action.direction, locale)} · ${formatPublicStatus(action.risk_gate_status, locale)}`}
                            >
                              <input
                                className="app-field min-h-9 rounded-[var(--app-radius-control)] px-3 py-2 text-xs tabular-nums"
                                type="number"
                                min="1"
                                value={quantities[actionId] ?? '100'}
                                aria-label={`${labels.orderQuantity}: ${instrumentLabel}`}
                                onChange={(event) =>
                                  setQuantities((current) => ({
                                    ...current,
                                    [actionId]: event.target.value,
                                  }))
                                }
                              />
                              <button
                                type="button"
                                className="app-button-primary min-h-9 rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={createManualOrder.isPending}
                                onClick={() => void prepareManualOrder(action)}
                              >
                                {labels.prepareManualOrder}
                              </button>
                            </ControlledActionZone>
                          ) : null}
                        </div>
                      </div>
                    </article>
                  );
                })
              )}
            </div>

            <div
              data-testid="signal-journal-panel"
              className="min-w-0 border-t border-[var(--app-divider)] pt-3 xl:border-t-0 xl:border-l xl:pl-5"
            >
              <div className="flex items-center justify-between pb-1">
                <div className="app-product-mark">{labels.signalJournal}</div>
                {latestJournal.length > 0 ? (
                  <span className="app-type-micro font-mono tabular-nums text-[var(--app-text-tertiary)]">
                    {latestJournal.length}{' '}
                    {locale === 'zh' ? '条记录' : 'records'}
                  </span>
                ) : null}
              </div>
              <div
                className={`mt-2 grid max-h-[36rem] gap-2.5 overflow-y-auto pr-1 ${
                  actions.length === 0 ? 'sm:grid-cols-2' : ''
                }`}
              >
                {latestJournal.length === 0 ? (
                  <div className="app-muted text-sm">
                    {labels.noSignalJournal}
                  </div>
                ) : (
                  latestJournal.map((entry) => (
                    <SignalJournalCard
                      key={`${entry.signal.id}-${entry.signal.timestamp}`}
                      entry={entry}
                      locale={locale}
                      labels={labels}
                      strategyNames={copy.backtest.page.strategyNames}
                    />
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
