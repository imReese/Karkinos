import { usePreferences } from '../../../shared/preferences/context';
import {
  formatPublicCode,
  formatPublicStatus,
} from '../../../shared/public-labels';
import { type AutomationCockpitResponse } from '../decision-feature-boundary';
import { objectRecord } from './decision-status-model';
import {
  automationOpenAlertReviewLabels,
  currentPerOrderReviewStatusLabel,
  strategyPromotionGateStatusLabel,
  strategyPromotionLifecycleLabels,
  strategyPromotionMissingRequirementsLabel,
  strategyPromotionStageLabel,
} from './decision-automation-model';
import {
  countLabel,
  manualExecutionEvidenceForPayload,
} from './decision-execution-evidence-model';

export function CurrentPerOrderReviewSection({
  reviews: currentPerOrderReviews,
}: {
  reviews: AutomationCockpitResponse['current_per_order_reviews'];
}) {
  const { locale } = usePreferences();
  const primaryCurrentPerOrderReview =
    currentPerOrderReviews?.primary_candidate;
  const currentPerOrderHandoffEnabled =
    currentPerOrderReviews?.status === 'review_ready' ||
    currentPerOrderReviews?.status === 'blocked_review';
  return (
    <>
      {currentPerOrderReviews ? (
        <div
          data-testid="current-per-order-review-handoff"
          className="mt-4 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-accent)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-accent)_7%,transparent)] px-3 py-3"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                {locale === 'zh'
                  ? '当前逐单证据复核'
                  : 'Current per-order evidence review'}
              </div>
              <div className="app-muted mt-1 break-words text-xs leading-5">
                {locale === 'zh'
                  ? '只展示已人工确认的订单与持久化证据；复核本身不提交或撤销券商订单。'
                  : 'Canonical manually_confirmed OMS orders and persisted evidence only; review itself cannot submit or cancel a broker order.'}
              </div>
            </div>
            <span className="app-chip">
              {currentPerOrderReviewStatusLabel(
                currentPerOrderReviews.status,
                locale,
              )}
            </span>
          </div>

          <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-3">
            {[
              {
                label: locale === 'zh' ? '当前候选' : 'Current candidates',
                value: currentPerOrderReviews.candidate_count,
              },
              {
                label: locale === 'zh' ? '可复核' : 'Review ready',
                value: currentPerOrderReviews.review_ready_count,
              },
              {
                label: locale === 'zh' ? '证据阻断' : 'Evidence blocked',
                value: currentPerOrderReviews.blocked_review_count,
              },
            ].map((item) => (
              <div
                className="min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] px-3 py-2"
                key={item.label}
              >
                <div className="app-muted text-xs">{item.label}</div>
                <div className="mt-1 font-semibold tabular-nums text-[var(--app-text)]">
                  {item.value}
                </div>
              </div>
            ))}
          </div>

          {primaryCurrentPerOrderReview ? (
            <div className="mt-3 min-w-0 rounded-xl border border-[color-mix(in_srgb,var(--app-border)_28%,transparent)] px-3 py-2.5">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 break-words text-sm font-semibold text-[var(--app-text)]">
                  {primaryCurrentPerOrderReview.symbol} ·{' '}
                  {formatPublicStatus(
                    primaryCurrentPerOrderReview.side,
                    locale,
                  )}{' '}
                  {primaryCurrentPerOrderReview.quantity}
                </div>
                <span className="app-chip">
                  {formatPublicStatus(
                    primaryCurrentPerOrderReview.review_status,
                    locale,
                  )}
                </span>
              </div>
              <div className="app-muted mt-1 break-words font-mono text-xs">
                {primaryCurrentPerOrderReview.order_id}
              </div>
              {primaryCurrentPerOrderReview.review_blockers.length ? (
                <div className="mt-2 break-words text-xs font-semibold text-[var(--app-warning)]">
                  {locale === 'zh' ? '阻断项：' : 'Blockers: '}
                  {primaryCurrentPerOrderReview.review_blockers
                    .map((item) => formatPublicCode(item, locale))
                    .join(' · ')}
                </div>
              ) : null}
            </div>
          ) : null}

          {currentPerOrderReviews.source_blockers.length ? (
            <div className="mt-2 break-words text-xs font-semibold text-[var(--app-warning)]">
              {locale === 'zh' ? '来源阻断：' : 'Source blockers: '}
              {currentPerOrderReviews.source_blockers
                .map((item) => formatPublicCode(item, locale))
                .join(' · ')}
            </div>
          ) : null}

          <div className="mt-3 flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-muted min-w-0 break-words text-xs leading-5">
              {locale === 'zh'
                ? '持久化事实 · 不联系外部服务 · 订单状态/账本/风控/资本授权不变'
                : 'Persisted facts · no provider contact · OMS/ledger/risk/capital authority unchanged'}
            </div>
            {currentPerOrderHandoffEnabled ? (
              <a
                className="inline-flex min-h-9 max-w-full items-center justify-center rounded-xl border border-[color-mix(in_srgb,var(--app-border)_34%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-1)_18%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--app-text)] transition hover:border-[color-mix(in_srgb,var(--app-accent)_45%,var(--app-border))] hover:text-[var(--app-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]"
                href="/trading"
              >
                {locale === 'zh'
                  ? '打开非提交逐单复核'
                  : 'Open non-submitting per-order review'}
              </a>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

export function AutomationOpenAlertSection({
  alert: primaryOpenAlert,
}: {
  alert: AutomationCockpitResponse['open_alerts'][number] | undefined;
}) {
  const { locale } = usePreferences();
  const primaryOpenAlertPayload = objectRecord(primaryOpenAlert?.payload);
  const openAlertManualExecutionEvidence = manualExecutionEvidenceForPayload(
    primaryOpenAlertPayload,
    locale,
  );
  const openAlertReviewLabels = automationOpenAlertReviewLabels(
    primaryOpenAlertPayload,
    locale,
  );
  return (
    <>
      {primaryOpenAlert ? (
        <div className="mt-3 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2.5">
          <div className="text-sm font-semibold text-[var(--app-text)]">
            {primaryOpenAlert.title}
          </div>
          {primaryOpenAlert.detail ? (
            <div className="app-muted mt-1 break-words text-xs leading-5">
              {primaryOpenAlert.detail}
            </div>
          ) : null}
          {openAlertReviewLabels.length ? (
            <div className="mt-3 flex min-w-0 flex-wrap gap-2">
              {openAlertReviewLabels.map((label) => (
                <span className="app-chip" key={label}>
                  {label}
                </span>
              ))}
            </div>
          ) : null}
          {openAlertManualExecutionEvidence ? (
            <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
                  {locale === 'zh'
                    ? '手工成交证据'
                    : 'Manual execution evidence'}
                </div>
                <span className="app-chip">
                  {openAlertManualExecutionEvidence.eventCountLabel}
                </span>
              </div>
              {openAlertManualExecutionEvidence.items.length ? (
                <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
                  {openAlertManualExecutionEvidence.items.map((entry) => (
                    <div
                      className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                      key={entry.label}
                    >
                      <div className="app-muted text-xs">{entry.label}</div>
                      <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                        {entry.value}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {openAlertManualExecutionEvidence.safetyLabels.length ? (
                <div className="mt-3 flex min-w-0 flex-wrap gap-2">
                  {openAlertManualExecutionEvidence.safetyLabels.map(
                    (label) => (
                      <span className="app-chip" key={label}>
                        {label}
                      </span>
                    ),
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export function StrategyPromotionStatesSection({
  cockpit,
}: {
  cockpit: AutomationCockpitResponse;
}) {
  const { locale } = usePreferences();
  return (
    <>
      {cockpit.promotion_states.length ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '策略晋级状态' : 'Strategy promotion state'}
            </div>
            <span className="app-chip">
              {cockpit.promotion_states.length === 1
                ? strategyPromotionStageLabel(
                    cockpit.promotion_states[0].stage,
                    locale,
                  )
                : countLabel(
                    cockpit.promotion_states.length,
                    locale === 'zh' ? '个策略' : 'strategy',
                    'strategies',
                    locale,
                  )}
            </span>
          </div>
          <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
            {cockpit.promotion_states.slice(0, 4).map((state) => {
              const lifecycleLabels = strategyPromotionLifecycleLabels(
                state.lifecycle,
                locale,
              );
              return (
                <div
                  className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                  key={state.strategy_id}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="break-words text-sm font-semibold text-[var(--app-text)]">
                        {state.strategy_id}
                      </div>
                      <div className="app-muted mt-1 break-words text-xs leading-5">
                        {strategyPromotionMissingRequirementsLabel(
                          state.missing_requirements,
                          locale,
                        )}
                      </div>
                    </div>
                    <span className="app-chip">
                      {strategyPromotionStageLabel(state.stage, locale)}
                    </span>
                  </div>
                  <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                    <span>
                      {strategyPromotionGateStatusLabel(
                        state.gate_status ?? state.status ?? 'unknown',
                        locale,
                      )}
                    </span>
                    <span>
                      {state.live_like_enabled
                        ? locale === 'zh'
                          ? '类实盘已启用'
                          : 'Live-like enabled'
                        : locale === 'zh'
                          ? '类实盘已关闭'
                          : 'Live-like disabled'}
                    </span>
                    {typeof state.backtest_result_id === 'number' ? (
                      <span>
                        {locale === 'zh' ? '回测证据' : 'Backtest evidence'}:{' '}
                        {state.backtest_result_id}
                      </span>
                    ) : null}
                    <span>
                      {locale === 'zh'
                        ? '默认仍需人工确认'
                        : 'Manual confirmation remains default'}
                    </span>
                  </div>
                  {lifecycleLabels.length ? (
                    <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                      {lifecycleLabels.map((label) => (
                        <span className="app-chip" key={label}>
                          {label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </>
  );
}
