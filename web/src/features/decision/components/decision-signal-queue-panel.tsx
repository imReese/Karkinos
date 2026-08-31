import { useState } from 'react';
import {
  ControlledActionZone,
  EvidenceState,
} from '../../../shared/ui/workbench';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatTimestamp } from '../../../shared/format';
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
  type SignalJournalEntry,
} from '../api';
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

export function SignalQueuePanel({
  actions,
  journal,
  loading,
  error,
}: {
  actions: ActionCard[];
  journal: SignalJournalEntry[];
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
    <section className="app-workbench-section min-w-0 py-4">
      <div className="min-w-0 px-1 sm:px-3">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">{labels.signalQueue}</div>
            <h2 className="app-card-title mt-1.5">{labels.signalQueueTitle}</h2>
          </div>
          <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
            {labels.signalQueueDetail}
          </p>
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
              <p className="app-muted mt-1 break-words text-xs leading-5">
                {labels.signalQueueCollapsedDetail}
              </p>
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
          <div className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
            <div className="grid min-w-0 gap-2">
              {actions.length === 0 ? (
                <EvidenceState
                  kind="empty"
                  statusLabel={labels.signalQueue}
                  title={labels.noSignalActions}
                  description={labels.signalQueueDetail}
                />
              ) : (
                actions.slice(0, 4).map((action) => {
                  const instrumentLabel = formatInstrumentDisplayLabel(action);
                  const actionId = action.id;
                  return (
                    <article
                      key={action.id ?? action.symbol}
                      data-testid={`signal-action-card-${action.id ?? action.symbol}`}
                      className="min-w-0 border-b border-[var(--app-divider)] px-1 py-3 last:border-b-0"
                    >
                      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="font-semibold text-[var(--app-text)]">
                            {instrumentLabel}
                          </div>
                          <div className="app-muted mt-1 break-words text-xs">
                            {formatPublicStatus(action.direction, locale)} ·{' '}
                            {formatPublicStatus(
                              action.risk_gate_status,
                              locale,
                            )}{' '}
                            ·{' '}
                            {formatPublicStatus(
                              action.manual_confirmation_status,
                              locale,
                            )}
                          </div>
                          <div className="app-muted mt-2 break-words text-xs leading-5">
                            {formatPublicNote(action.detail, locale)}
                          </div>
                        </div>
                        <div className="grid shrink-0 gap-2 sm:grid-cols-2 lg:min-w-[280px]">
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionBacktestHref(action)}
                            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
                          >
                            {labels.openBacktestEvidence}
                          </a>
                          <a
                            className="app-button-secondary inline-flex min-h-9 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-center text-xs font-semibold whitespace-normal"
                            href={signalActionHoldingAttributionHref(action)}
                            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
                          >
                            {labels.openAttributionReview}
                          </a>
                          {actionId !== null &&
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
              className="min-w-0 border-t border-[var(--app-divider)] pt-3 xl:border-t-0 xl:border-l xl:pl-4"
            >
              <div className="app-product-mark">{labels.signalJournal}</div>
              <div className="mt-2 grid divide-y divide-[var(--app-divider)]">
                {latestJournal.length === 0 ? (
                  <div className="app-muted text-sm">
                    {labels.noSignalJournal}
                  </div>
                ) : (
                  latestJournal.map((entry) => {
                    const strategyNames = copy.backtest.page.strategyNames;
                    const instrumentLabel = formatInstrumentDisplayLabel(
                      entry.signal,
                    );
                    const strategyLabel = strategyDisplayNameFromId(
                      entry.signal.strategy_id,
                      strategyNames,
                    );
                    const strategyAuditId = strategyAuditIdFromDisplay(
                      entry.signal.strategy_id,
                      strategyNames,
                    );
                    const latestSourceRef = entry.latest_event?.source_ref;
                    const publicSourceRef =
                      latestSourceRef && latestSourceRef.includes(':')
                        ? formatPublicEvidenceReference(latestSourceRef, locale)
                        : null;
                    return (
                      <div
                        key={`${entry.signal.id}-${entry.signal.timestamp}`}
                        className="px-1 py-3 text-xs"
                      >
                        <div className="font-semibold text-[var(--app-soft)]">
                          {instrumentLabel} · {strategyLabel}
                        </div>
                        {strategyAuditId ? (
                          <div className="app-muted mt-1 break-words">
                            {labels.strategyAuditId}: {strategyAuditId}
                          </div>
                        ) : null}
                        <div className="app-muted mt-1 break-words">
                          {formatPublicCode(
                            entry.latest_event?.event_type ??
                              entry.review?.outcome ??
                              entry.action_task?.status ??
                              '--',
                            locale,
                          )}
                        </div>
                        {publicSourceRef ? (
                          <div className="mt-1 break-words text-[var(--app-soft)]">
                            {publicSourceRef}
                          </div>
                        ) : null}
                        <div className="app-muted mt-1 font-mono tabular-nums">
                          {formatTimestamp(
                            entry.latest_event?.timestamp ??
                              entry.review?.reviewed_at ??
                              entry.signal.timestamp,
                          )}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <a
                            className="app-button-secondary app-type-micro inline-flex min-h-8 items-center justify-center rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-center font-semibold whitespace-normal"
                            href={signalBacktestHref(entry.signal)}
                            aria-label={`${labels.openBacktestEvidence}: ${instrumentLabel}`}
                          >
                            {labels.openBacktestEvidence}
                          </a>
                          <a
                            className="app-button-secondary app-type-micro inline-flex min-h-8 items-center justify-center rounded-[var(--app-radius-control)] px-2.5 py-1.5 text-center font-semibold whitespace-normal"
                            href={signalHoldingAttributionHref(entry.signal)}
                            aria-label={`${labels.openAttributionReview}: ${instrumentLabel}`}
                          >
                            {labels.openAttributionReview}
                          </a>
                        </div>
                        <DecisionOutcomeReviewPanel entry={entry} />
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
