import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  formatCurrency,
  formatPercent,
  formatPrice,
} from '../../../shared/format';
import {
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { formatInstrumentDisplayLabel } from '../../../shared/instrument-display';
import { type OperationsTodayResponse } from '../../operations/api';
import { type DecisionCandidate, type DailyTradingPlanResponse } from '../api';
import {
  manualStatus,
  paperShadowCostSummaryItems,
} from './decision-status-model';
import { paperShadowDivergenceEvidenceBlocks } from './decision-candidate-evidence-model';
import {
  paperShadowInputSnapshotEvidenceItems,
  paperShadowManualHandoffEvidenceItems,
  paperShadowNextStepLabel,
  paperShadowReviewQueueDetailItems,
  paperShadowReviewQueueItemTitle,
  paperShadowReviewQueueSafetyText,
  paperShadowStatusLabel,
  tradingPlanBlockerLabel,
  tradingPlanConclusionLabel,
  tradingPlanConstraintLabel,
} from './decision-trading-plan-model';
import { StatusPill } from './decision-lane-panels';

type DailyTradingPlanPanelProps = {
  plan: DailyTradingPlanResponse | undefined;
  candidates: DecisionCandidate[];
  operationsToday: OperationsTodayResponse | undefined;
  loading: boolean;
  error: boolean;
  onRunPaperShadow: () => void;
  paperShadowRunPending: boolean;
  paperShadowRunError: boolean;
};

export function DailyTradingPlanPanel(props: DailyTradingPlanPanelProps) {
  const labels = useCopy().decision;
  const { plan, loading, error } = props;
  return (
    <section
      data-testid="decision-daily-trading-plan"
      className="min-w-0 border-y border-[var(--app-divider)] py-4 sm:py-5"
    >
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="app-product-mark">{labels.tradingPlanKicker}</div>
          <h2 className="app-card-title mt-1.5">{labels.tradingPlanTitle}</h2>
        </div>
        <p className="app-muted max-w-2xl break-words text-sm leading-6 sm:text-right">
          {labels.tradingPlanDetail}
        </p>
      </div>
      {loading ? (
        <div className="app-muted mt-4 text-sm">
          {labels.tradingPlanLoading}
        </div>
      ) : error || !plan ? (
        <div className="app-error-text mt-4 text-sm">
          {labels.tradingPlanError}
        </div>
      ) : (
        <DailyTradingPlanContent {...props} plan={plan} />
      )}
    </section>
  );
}

function DailyTradingPlanContent(
  props: DailyTradingPlanPanelProps & { plan: DailyTradingPlanResponse },
) {
  return (
    <div className="mt-4 grid min-w-0 gap-x-6 gap-y-4 xl:grid-cols-[0.9fr_1.1fr]">
      <TradingPlanSummary plan={props.plan} />
      <TradingPlanOrderIntentPreview plan={props.plan} />
      <TradingPlanCandidateSignals
        plan={props.plan}
        candidates={props.candidates}
      />
      <PaperShadowReview
        plan={props.plan}
        operationsToday={props.operationsToday}
        onRunPaperShadow={props.onRunPaperShadow}
        paperShadowRunPending={props.paperShadowRunPending}
        paperShadowRunError={props.paperShadowRunError}
      />
    </div>
  );
}

function TradingPlanSummary({ plan }: { plan: DailyTradingPlanResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  return (
    <div className="min-w-0 border-l-2 border-[var(--app-accent)] py-1 pl-3">
      <div className="text-sm font-semibold text-[var(--app-text)]">
        {plan.order_intent_count === 0 && plan.candidate_pool_count > 0
          ? locale === 'zh'
            ? '有候选信号，暂无可执行订单'
            : 'Candidate signals exist; no executable orders'
          : tradingPlanConclusionLabel(plan.conclusion_status, labels)}
      </div>
      <div className="app-muted mt-2 text-sm">
        {labels.tradingPlanCounts(
          plan.candidate_pool_count,
          plan.order_intent_count,
          plan.blocked_count,
        )}
      </div>
      <div className="mt-3 flex min-w-0 flex-wrap gap-2">
        <span className="app-chip">{labels.tradingPlanDefaultManual}</span>
        <span className="app-chip">{labels.tradingPlanBrokerDisabled}</span>
      </div>
    </div>
  );
}

function TradingPlanOrderIntentPreview({
  plan,
}: {
  plan: DailyTradingPlanResponse;
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const firstIntent = plan.order_intents?.[0];
  const constraintChecks = firstIntent?.constraint_checks ?? [];
  return (
    <div className="min-w-0 border-l-2 border-[var(--app-divider)] py-1 pl-3">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
          {labels.tradingPlanOrderIntentPreviews}
        </div>
        <span className="app-chip">{plan.order_intent_count}</span>
      </div>
      {firstIntent ? (
        <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-2">
          <div className="min-w-0 break-words">
            {firstIntent.symbol} ·{' '}
            {formatPublicStatus(firstIntent.side, locale)}
          </div>
          <div className="font-mono tabular-nums">
            {labels.tradingPlanQuantity}: {firstIntent.estimated_quantity}
          </div>
          <div className="font-mono tabular-nums">
            {labels.targetWeight}: {formatPercent(firstIntent.target_weight)}
          </div>
          <div className="font-mono tabular-nums">
            {labels.price}: {formatPrice(firstIntent.estimated_price)}
          </div>
          <div className="font-mono tabular-nums">
            {labels.tradingPlanFee}:{' '}
            {formatCurrency(firstIntent.estimated_total_fee)}
          </div>
          <div className="font-mono tabular-nums">
            {labels.tradingPlanNetCash}:{' '}
            {formatCurrency(firstIntent.estimated_net_cash_impact)}
          </div>
          {firstIntent.cash_shortfall > 0 ? (
            <div className="font-mono tabular-nums text-[var(--app-warning-text)]">
              {labels.tradingPlanCashShortfallAmount}:{' '}
              {formatCurrency(firstIntent.cash_shortfall)}
            </div>
          ) : null}
          {constraintChecks.length > 0 ? (
            <div className="sm:col-span-2">
              <div className="app-muted app-type-overline mb-2">
                {labels.tradingPlanConstraintChecks}
              </div>
              <div className="flex min-w-0 flex-wrap gap-2">
                {constraintChecks.map((check) => (
                  <span
                    className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                      check.status === 'blocked'
                        ? 'border-[color-mix(in_srgb,var(--app-danger)_40%,transparent)] text-[var(--app-danger-text)]'
                        : 'border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] text-[var(--app-success-text)]'
                    }`}
                    key={check.id}
                  >
                    {tradingPlanConstraintLabel(check.id, locale)} ·{' '}
                    {formatPublicStatus(check.status, locale)}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
          {firstIntent.position_effect ? (
            <>
              <div className="font-mono tabular-nums">
                {labels.tradingPlanPositionAfter}:{' '}
                {firstIntent.position_effect.estimated_quantity_after}
              </div>
              <div className="font-mono tabular-nums">
                {labels.tradingPlanCostBasis}:{' '}
                {firstIntent.position_effect.estimated_avg_cost_after === null
                  ? firstIntent.position_effect.cost_basis_method
                  : `${formatPrice(
                      firstIntent.position_effect.estimated_avg_cost_after,
                    )} · ${firstIntent.position_effect.cost_basis_method}`}
              </div>
            </>
          ) : null}
          <div className="app-muted sm:col-span-2">
            {labels.tradingPlanDoesNotSubmit}
          </div>
        </div>
      ) : (
        <div className="app-muted mt-3 text-sm">
          {labels.tradingPlanNoOrderIntents}
        </div>
      )}
    </div>
  );
}

function TradingPlanCandidateSignals({
  plan,
  candidates,
}: {
  plan: DailyTradingPlanResponse;
  candidates: DecisionCandidate[];
}) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const visibleCandidateSignals = candidates.slice(0, 3);
  return (
    <>
      {plan.order_intent_count === 0 && visibleCandidateSignals.length > 0 ? (
        <div
          className="min-w-0 border-t border-[var(--app-divider)] pt-4 xl:col-span-2"
          data-testid="decision-daily-candidate-signals"
        >
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {locale === 'zh'
              ? '今日候选信号（仅研究，不是订单）'
              : "Today's candidate signals (research only, not orders)"}
          </div>
          <p className="app-muted mt-1 text-sm leading-6">
            {locale === 'zh'
              ? '仅当持仓与行情证据完整、风控通过并生成订单意图后，候选才会进入人工确认。'
              : 'A candidate reaches manual confirmation only after position and market evidence are complete, risk passes, and an order intent is generated.'}
          </p>
          <div className="mt-3 grid min-w-0 gap-2">
            {visibleCandidateSignals.map((candidate) => {
              const blocker = plan.blockers.find(
                (item) => item.symbol === candidate.symbol,
              );
              const blockerSummary = plan.blocker_summary?.find((item) =>
                item.sample_symbols.includes(candidate.symbol),
              );
              const blockerReason =
                blocker?.reason ?? blockerSummary?.reasons[0];
              return (
                <div
                  className="min-w-0 border-l-2 border-[var(--app-warning)] py-2 pl-3"
                  data-testid={`decision-daily-candidate-signal-${candidate.symbol}`}
                  key={`${candidate.action_id ?? 'candidate'}-${candidate.symbol}`}
                >
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="break-words font-semibold text-[var(--app-text)]">
                      {formatInstrumentDisplayLabel(candidate)}
                    </span>
                    <StatusPill value={candidate.action} />
                    <StatusPill
                      value={candidate.risk_gate_status}
                      prefix={labels.riskGate}
                    />
                  </div>
                  <p className="app-muted mt-1 break-words text-sm">
                    {formatPublicNote(
                      candidate.detail || candidate.title || labels.noDetail,
                      locale,
                    )}
                  </p>
                  <div className="mt-1 break-words text-xs font-semibold text-[var(--app-warning-text)]">
                    {locale === 'zh' ? '当前阻断' : 'Current blocker'}:{' '}
                    {blockerReason
                      ? tradingPlanBlockerLabel(blockerReason, locale)
                      : manualStatus(candidate, locale)}
                  </div>
                </div>
              );
            })}
          </div>
          {candidates.length > visibleCandidateSignals.length ? (
            <div className="app-muted mt-2 text-xs">
              {locale === 'zh'
                ? `另有 ${candidates.length - visibleCandidateSignals.length} 个候选，请在下方决策通道展开证据明细。`
                : `${candidates.length - visibleCandidateSignals.length} more candidate(s); expand the decision-lane evidence below.`}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function PaperShadowReview({
  plan,
  operationsToday,
  onRunPaperShadow,
  paperShadowRunPending,
  paperShadowRunError,
}: Pick<
  DailyTradingPlanPanelProps,
  | 'plan'
  | 'operationsToday'
  | 'onRunPaperShadow'
  | 'paperShadowRunPending'
  | 'paperShadowRunError'
> & { plan: DailyTradingPlanResponse }) {
  const labels = useCopy().decision;
  const { locale } = usePreferences();
  const fallbackShadowStatus =
    plan.order_intent_count > 0 ? 'not_run' : 'not_required';
  const currentShadowStatus =
    operationsToday?.paper_shadow.effective_status ??
    operationsToday?.paper_shadow.status ??
    fallbackShadowStatus;
  const canRunPaperShadow = plan.order_intent_count > 0;
  const runPaperShadowLabel =
    currentShadowStatus === 'within_expectations' ||
    currentShadowStatus === 'accepted_for_manual_confirmation'
      ? locale === 'zh'
        ? '重新运行模拟复核'
        : 'Rerun paper/shadow simulation'
      : locale === 'zh'
        ? '运行模拟复核'
        : 'Run paper/shadow simulation';
  const paperShadowCostItems = paperShadowCostSummaryItems(
    operationsToday?.paper_shadow.divergence_summary?.cost_summary,
    locale,
  );
  const paperShadowDivergenceBlocks = paperShadowDivergenceEvidenceBlocks(
    operationsToday?.paper_shadow.divergence_summary,
    locale,
  );
  const paperShadowReviewQueue =
    operationsToday?.paper_shadow.review_queue ?? [];
  const paperShadowManualHandoffItems = operationsToday?.paper_shadow
    .manual_handoff
    ? paperShadowManualHandoffEvidenceItems(
        operationsToday.paper_shadow.manual_handoff,
        locale,
      )
    : [];
  const paperShadowInputSnapshotItems = paperShadowInputSnapshotEvidenceItems(
    operationsToday?.paper_shadow.input_snapshot,
    operationsToday?.paper_shadow.input_fingerprint,
    locale,
  );
  return (
    <div className="min-w-0 border-t border-[var(--app-divider)] pt-4 xl:col-span-2">
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
          {locale === 'zh'
            ? '模拟与影子复核'
            : 'Paper/shadow simulation review'}
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="app-chip">
            {paperShadowStatusLabel(currentShadowStatus, locale)}
          </span>
          <button
            type="button"
            className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-center text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canRunPaperShadow || paperShadowRunPending}
            onClick={onRunPaperShadow}
          >
            {paperShadowRunPending
              ? locale === 'zh'
                ? '运行中'
                : 'Running'
              : runPaperShadowLabel}
          </button>
        </div>
      </div>
      <div className="app-muted mt-2 text-sm">
        {paperShadowNextStepLabel(
          operationsToday?.paper_shadow.next_manual_review_step ??
            'run_paper_shadow_daily',
          locale,
        )}
      </div>
      {paperShadowInputSnapshotItems.length > 0 ? (
        <div className="mt-3 grid min-w-0 gap-1 border-l-2 border-[var(--app-divider)] py-1 pl-3 text-xs text-[var(--app-text)]">
          {paperShadowInputSnapshotItems.map((item) => (
            <div className="min-w-0 break-words" key={item}>
              {item}
            </div>
          ))}
        </div>
      ) : null}
      {paperShadowManualHandoffItems.length > 0 ? (
        <div className="mt-3 grid min-w-0 gap-1 border-l-2 border-[var(--app-divider)] py-1 pl-3 text-xs text-[var(--app-text)]">
          {paperShadowManualHandoffItems.map((item) => (
            <div className="min-w-0 break-words" key={item}>
              {item}
            </div>
          ))}
        </div>
      ) : null}
      {paperShadowRunError ? (
        <div className="mt-2 text-sm font-semibold text-[var(--app-danger-text)]">
          {labels.simulationReviewRunFailed}
        </div>
      ) : null}
      <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
        <div>
          <div className="app-muted text-xs">
            {locale === 'zh' ? '订单意图' : 'Order intents'}
          </div>
          <div className="font-mono tabular-nums">
            {operationsToday?.paper_shadow.order_intent_count ??
              plan.order_intent_count}
          </div>
        </div>
        <div>
          <div className="app-muted text-xs">
            {locale === 'zh' ? '模拟订单' : 'Sim orders'}
          </div>
          <div className="font-mono tabular-nums">
            {operationsToday?.paper_shadow.simulated_order_count ?? 0}
          </div>
        </div>
        <div>
          <div className="app-muted text-xs">
            {locale === 'zh' ? '模拟成交' : 'Sim fills'}
          </div>
          <div className="font-mono tabular-nums">
            {operationsToday?.paper_shadow.simulated_fill_count ?? 0}
          </div>
        </div>
        <div>
          <div className="app-muted text-xs">
            {locale === 'zh' ? '偏差复核' : 'Divergence reviews'}
          </div>
          <div className="font-mono tabular-nums">
            {operationsToday?.paper_shadow.divergence_reviewed_count ?? 0}
          </div>
        </div>
      </div>
      {paperShadowReviewQueue.length > 0 ? (
        <div className="mt-3 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-warning)_32%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2 text-sm">
          <div className="text-xs font-semibold uppercase text-[var(--app-muted)]">
            {locale === 'zh' ? '复核队列' : 'Review queue'}
          </div>
          <div className="mt-2 grid min-w-0 gap-2">
            {paperShadowReviewQueue.slice(0, 3).map((item) => {
              const safetyText = paperShadowReviewQueueSafetyText(item, locale);
              const detailItems = paperShadowReviewQueueDetailItems(
                item,
                locale,
              );
              return (
                <div
                  className="min-w-0"
                  key={item.review_id || item.order_id || item.symbol}
                >
                  <div className="min-w-0 break-words font-semibold text-[var(--app-text)]">
                    {paperShadowReviewQueueItemTitle(item, locale)}
                  </div>
                  {safetyText ? (
                    <div className="app-muted mt-1 min-w-0 break-words text-xs">
                      {safetyText}
                    </div>
                  ) : null}
                  {detailItems.length > 0 ? (
                    <div className="mt-1 grid min-w-0 gap-1 text-xs text-[var(--app-text)]">
                      {detailItems.map((detail) => (
                        <div className="min-w-0 break-words" key={detail}>
                          {detail}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      {paperShadowCostItems.length > 0 ? (
        <div className="mt-3 grid min-w-0 border-y border-[var(--app-divider)] text-sm sm:grid-cols-2 xl:grid-cols-5">
          {paperShadowCostItems.map((item) => (
            <div
              className="min-w-0 border-l border-[var(--app-divider)] px-3 py-2 first:border-l-0"
              key={item.label}
            >
              <div className="app-muted text-xs">{item.label}</div>
              <div className="min-w-0 break-words font-mono tabular-nums text-[var(--app-text)]">
                {item.value}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {paperShadowDivergenceBlocks.length > 0 ? (
        <div className="mt-3 grid min-w-0 gap-2 text-sm lg:grid-cols-2">
          {paperShadowDivergenceBlocks.map((block) => (
            <div
              className="min-w-0 border-l-2 border-[var(--app-divider)] py-1 pl-3"
              key={block.title}
            >
              <div className="text-xs font-semibold uppercase text-[var(--app-muted)]">
                {block.title}
              </div>
              <div className="mt-2 grid min-w-0 gap-1">
                {block.items.map((item) => (
                  <div
                    className="min-w-0 break-words text-[var(--app-text)]"
                    key={item}
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
