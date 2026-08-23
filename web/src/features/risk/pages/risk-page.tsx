import { useMemo, useState, type ReactNode } from 'react';
import { createLazyRoute } from '@tanstack/react-router';
import { ChevronDown } from 'lucide-react';

import { useCopy, type AppCopy } from '../../../app/copy';
import {
  EvidenceIdentityDisclosure,
  EvidenceState,
  ExceptionList,
  MetricStrip,
  StatusBadge,
  Timeline,
  WorkspaceHeader,
  type ExceptionItem,
} from '../../../app/components/workbench';
import { usePreferences, type Locale } from '../../../app/preferences';
import {
  useAccountStateQuery,
  useExplainabilityQuery,
  useRiskWorkspaceQuery,
} from '../../account/api';
import {
  ReturnCalendarCard,
  type ReturnCalendarBreakdownItem,
} from '../../account/components/return-calendar-card';
import {
  useBatchPreTradeRiskMutation,
  useTodayDecisionQuery,
} from '../../decision/api';
import { KillSwitchPanel } from '../../trading/components/kill-switch-panel';
import { getErrorMessage } from '../../../shared/error-message';
import {
  formatCurrency as formatCurrencyValue,
  formatPercent as formatPercentValue,
  formatQuantity,
  formatTimestamp,
} from '../../../shared/format';
import {
  formatLedgerExplainabilityDetail,
  formatLedgerExplainabilityTitle,
} from '../../../shared/ledger-format';
import { formatInstrumentDisplayLabelFromNameMap } from '../../../shared/instrument-display';
import {
  formatPublicNote,
  formatPublicStatus,
} from '../../../shared/public-labels';

export function RiskPage() {
  const copy = useCopy();
  const { locale } = usePreferences();
  const state = useAccountStateQuery();
  const workspace = useRiskWorkspaceQuery();
  const primaryRiskQueriesReady = Boolean(state.data && workspace.data);
  const todayDecision = useTodayDecisionQuery(primaryRiskQueriesReady);
  const batchPreTradeRisk = useBatchPreTradeRiskMutation();
  const [timelineFromDate, setTimelineFromDate] = useState('');
  const [timelineToDate, setTimelineToDate] = useState('');
  const [timelineEventKind, setTimelineEventKind] = useState('');
  const [batchRiskMessage, setBatchRiskMessage] = useState<string | null>(null);
  const [batchRiskBlockedMessage, setBatchRiskBlockedMessage] = useState<
    string | null
  >(null);
  const [batchRiskError, setBatchRiskError] = useState<string | null>(null);
  const explainability = useExplainabilityQuery(
    {
      from_date: timelineFromDate || undefined,
      to_date: timelineToDate || undefined,
      event_kind: timelineEventKind || undefined,
    },
    primaryRiskQueriesReady,
  );
  const instrumentNames = useMemo(() => {
    const names = new Map<string, string>();
    const remember = (
      symbol: string | null | undefined,
      displayName: string | null | undefined,
    ) => {
      const normalizedSymbol = symbol?.trim();
      const normalizedName = displayName?.trim();
      if (!normalizedSymbol || !normalizedName) {
        return;
      }
      names.set(normalizedSymbol.toLowerCase(), normalizedName);
    };
    const snapshot = state.data?.snapshot;
    snapshot?.allocation.forEach((item) => remember(item.symbol, item.name));
    snapshot?.allocation_grouped.forEach((group) =>
      group.items.forEach((item) => remember(item.symbol, item.name)),
    );
    snapshot?.positions.forEach((position) =>
      remember(position.symbol, position.display_name ?? position.name),
    );
    return names;
  }, [state.data?.snapshot]);
  const riskReviewTask = todayDecision.data?.summary.workflow_tasks?.find(
    (task) =>
      task.id === 'risk_review' &&
      task.required_actions.includes('run_pre_trade_risk_gate') &&
      task.status !== 'pass' &&
      task.status !== 'passed',
  );
  const riskReviewEvidence = riskReviewTask?.evidence as
    | {
        total_action_count?: number;
        risk_checked_count?: number;
        risk_blocked_count?: number;
      }
    | undefined;
  const riskCandidateCount =
    riskReviewEvidence?.total_action_count ??
    todayDecision.data?.summary.candidate_count ??
    0;
  const riskCheckedCount = riskReviewEvidence?.risk_checked_count ?? 0;
  const hasAnyRiskProjection = Boolean(state.data || workspace.data);
  const isRiskWorkspacePending = !workspace.data && workspace.isLoading;
  const isInitialRiskLoad =
    (!state.data && state.isLoading) || isRiskWorkspacePending;
  const isRiskWorkspaceUnavailable = !state.data || !workspace.data;
  const hasRiskRefreshError =
    !isRiskWorkspaceUnavailable && (state.isError || workspace.isError);
  const representedRiskMetricKeys = new Set<string>();
  const activeRiskItems: ExceptionItem[] = [];
  for (const item of state.data?.risks ?? []) {
    if (item.level !== 'high' && item.level !== 'medium') {
      continue;
    }
    switch (item.kind) {
      case 'cash_buffer':
        representedRiskMetricKeys.add('cash_ratio');
        break;
      case 'concentration':
        representedRiskMetricKeys.add('largest_weight');
        representedRiskMetricKeys.add('top3_weight');
        break;
      case 'largest_weight':
      case 'gross_exposure':
      case 'current_drawdown':
      case 'max_drawdown':
        representedRiskMetricKeys.add(item.kind);
        break;
      case 'capital_deployment':
        representedRiskMetricKeys.add('gross_exposure');
        break;
    }
    activeRiskItems.push({
      id: `${item.kind}-${item.title}`,
      severity: item.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(item.level, locale),
      title: formatRiskAlertTitle(item.title, locale),
      reason: formatRiskAlertDetail(item.detail, locale),
      evidence: `${getRiskAlertKindLabel(
        copy,
        item.kind,
      )} · ${formatRiskAlertLevel(item.level, locale)}`,
    });
  }
  for (const metric of workspace.data?.metrics ?? []) {
    if (
      (metric.level !== 'high' && metric.level !== 'medium') ||
      representedRiskMetricKeys.has(metric.key)
    ) {
      continue;
    }
    activeRiskItems.push({
      id: `metric-${metric.key}`,
      severity: metric.level === 'high' ? 'danger' : 'warning',
      statusLabel: formatRiskAlertLevel(metric.level, locale),
      title: getRiskMetricLabel(copy, metric.key),
      reason: `${metric.display_value} · ${getRiskMetricDetail(
        copy,
        metric.key,
      )}`,
      evidence: `${getRiskMetricLabel(
        copy,
        metric.key,
      )} · ${formatRiskAlertLevel(metric.level, locale)}`,
    });
  }
  activeRiskItems.sort(
    (left, right) =>
      Number(left.severity !== 'danger') - Number(right.severity !== 'danger'),
  );
  const riskHistoryImpactCount =
    explainability.data?.recent_drivers.length ?? 0;
  const riskHistoryValuationDayCount =
    explainability.data?.timeline.length ?? 0;
  const runBatchRiskGate = async () => {
    setBatchRiskMessage(null);
    setBatchRiskBlockedMessage(null);
    setBatchRiskError(null);
    try {
      const result = await batchPreTradeRisk.mutateAsync();
      if (result.status === 'blocked_by_data_quality') {
        setBatchRiskBlockedMessage(
          locale === 'zh'
            ? `批量风控未运行：估值或行情证据尚未完整，已跳过 ${result.skipped_count} 个候选。未写入风险决策、订单或账本；请先处理数据状态后重试。`
            : `Batch risk did not run: valuation or market evidence is incomplete, so ${result.skipped_count} candidates were skipped. No risk decisions, orders, or ledger entries were written; resolve the data status before retrying.`,
        );
        return;
      }
      setBatchRiskMessage(
        copy.riskPage.batchRiskGateDone(
          result.passed_count,
          result.blocked_count,
        ),
      );
    } catch (error) {
      setBatchRiskError(
        `${copy.riskPage.batchRiskGateFailed} ${getErrorMessage(error)}`,
      );
    }
  };

  return (
    <section
      className="app-workbench-route space-y-5 sm:space-y-6"
      data-workbench-route="risk"
    >
      <WorkspaceHeader
        eyebrow={copy.riskPage.kicker}
        title={copy.riskPage.title}
        description={copy.riskPage.subtitle}
        context={
          state.data
            ? copy.common.valuationEvidenceAsOf(
                formatTimestamp(
                  state.data.summary.valuation_as_of ??
                    state.data.summary.valuation_timestamp,
                ),
                formatPublicStatus(
                  state.data.summary.valuation_status ??
                    state.data.summary.quote_status,
                  locale,
                ),
              )
            : undefined
        }
      />

      {isInitialRiskLoad ? (
        <div
          className="min-w-0 space-y-4"
          data-testid={
            hasAnyRiskProjection
              ? 'risk-partial-workspace'
              : 'risk-loading-workspace'
          }
        >
          {hasAnyRiskProjection ? (
            <p className="sr-only" role="status">
              {copy.riskPage.loading}
            </p>
          ) : (
            <EvidenceState
              kind="loading"
              title={copy.riskPage.loadingTitle}
              description={copy.riskPage.loading}
            />
          )}
          <div className="app-risk-command-grid grid min-w-0 gap-5 sm:gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(300px,360px)] xl:items-start">
            <section
              aria-busy={!state.data}
              className="min-w-0 space-y-2"
              data-testid="risk-loading-blocking-register"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.riskPage.blockingRegister}
                </h2>
                <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
                  {copy.riskPage.blockingRegisterDetail}
                </p>
              </div>
              {state.data ? (
                <div
                  className="min-w-0"
                  data-testid="risk-loading-live-exceptions"
                >
                  <ExceptionList
                    ariaLabel={copy.riskPage.blockingRegister}
                    emptyState={copy.riskPage.noBlockingItems}
                    density="compact"
                    labels={{
                      reason: locale === 'zh' ? '阻断原因' : 'Reason',
                      unblockCondition:
                        locale === 'zh' ? '解除条件' : 'Unblock condition',
                      nextAction:
                        locale === 'zh' ? '安全下一步' : 'Safe next step',
                      evidence: locale === 'zh' ? '证据' : 'Evidence',
                    }}
                    items={activeRiskItems}
                    className="[&>li>dl]:grid-cols-2 2xl:[&>li>dl]:grid-cols-4"
                  />
                </div>
              ) : (
                <EvidenceState
                  kind="loading"
                  statusLabel={copy.states.loading}
                  title={copy.states.loading}
                  description={copy.riskPage.blockingRegisterDetail}
                />
              )}
            </section>

            <aside className="grid min-w-0 content-start gap-3">
              <section
                aria-busy={!workspace.data}
                className="min-w-0 space-y-2"
                data-testid="risk-loading-metrics"
              >
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.riskPage.metrics}
                </h2>
                {workspace.data ? (
                  <div
                    className="min-w-0"
                    data-testid="risk-loading-live-metrics"
                  >
                    <MetricStrip
                      ariaLabel={copy.riskPage.metrics}
                      className="app-risk-metric-strip"
                      items={workspace.data.metrics.map((metric) => ({
                        id: metric.key,
                        label: getRiskMetricLabel(copy, metric.key),
                        value: metric.display_value,
                        detail: formatRiskAlertLevel(metric.level, locale),
                        tone:
                          metric.level === 'high'
                            ? ('danger' as const)
                            : metric.level === 'medium'
                              ? ('warning' as const)
                              : ('neutral' as const),
                      }))}
                    />
                  </div>
                ) : (
                  <MetricStrip
                    ariaLabel={`${copy.riskPage.metrics} · ${copy.states.loading}`}
                    className="app-risk-metric-strip"
                    items={[
                      'current_drawdown',
                      'gross_exposure',
                      'cash_ratio',
                      'largest_weight',
                    ].map((metric) => ({
                      id: metric,
                      label: getRiskMetricLabel(copy, metric),
                      value: copy.states.loading,
                    }))}
                  />
                )}
              </section>
              <section
                aria-busy={isRiskWorkspaceUnavailable}
                className="grid min-w-0 gap-2"
                data-testid="risk-loading-controlled-action"
              >
                <div>
                  <h2 className="app-type-section-title text-[var(--app-text)]">
                    {locale === 'zh' ? '受控操作' : 'Controlled action'}
                  </h2>
                  <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                    {locale === 'zh'
                      ? '熔断状态独立于风险事实；仅在需要人工干预时展开。'
                      : 'Kill-switch state stays separate from risk facts and expands only for deliberate operator intervention.'}
                  </p>
                </div>
                <EvidenceState
                  kind="loading"
                  statusLabel={copy.states.loading}
                  title={copy.states.loading}
                  description={copy.riskPage.loading}
                />
              </section>
            </aside>
          </div>
        </div>
      ) : isRiskWorkspaceUnavailable ? (
        <EvidenceState
          kind="error"
          title={copy.states.error}
          description={copy.riskPage.error}
        />
      ) : (
        <div className="space-y-5 sm:space-y-6">
          {hasRiskRefreshError ? (
            <div
              role="status"
              className="rounded-[var(--app-radius-surface)] border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-4 py-3 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
            >
              {copy.riskPage.refreshError}
            </div>
          ) : null}
          <div className="app-risk-command-grid grid min-w-0 gap-5 sm:gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(300px,360px)] xl:items-start">
            <section
              data-testid="risk-blocking-register"
              className="min-w-0 space-y-2"
            >
              <div>
                <h2 className="app-type-section-title text-[var(--app-text)]">
                  {copy.riskPage.blockingRegister}
                </h2>
                <p className="mt-0.5 max-w-3xl text-xs text-[var(--app-text-secondary)]">
                  {copy.riskPage.blockingRegisterDetail}
                </p>
              </div>
              <ExceptionList
                ariaLabel={copy.riskPage.blockingRegister}
                emptyState={copy.riskPage.noBlockingItems}
                density="compact"
                labels={{
                  reason: locale === 'zh' ? '阻断原因' : 'Reason',
                  unblockCondition:
                    locale === 'zh' ? '解除条件' : 'Unblock condition',
                  nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
                  evidence: locale === 'zh' ? '证据' : 'Evidence',
                }}
                items={activeRiskItems}
                className="[&>li>dl]:grid-cols-2 2xl:[&>li>dl]:grid-cols-4"
              />
              {activeRiskItems.length > 0 ? (
                <dl
                  data-testid="risk-resolution-guidance"
                  className="grid grid-cols-2 gap-3 border-b border-[var(--app-divider)] px-3 py-2.5 text-xs"
                >
                  <div className="min-w-0">
                    <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                      {locale === 'zh'
                        ? '统一解除条件'
                        : 'Shared unblock condition'}
                    </dt>
                    <dd className="app-type-compact mt-0.5 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
                      {copy.riskPage.clearsWithNewProjection}
                    </dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="app-type-overline text-[var(--app-text-tertiary)]">
                      {locale === 'zh' ? '安全下一步' : 'Safe next step'}
                    </dt>
                    <dd className="app-type-compact mt-0.5 text-[var(--app-text-secondary)] [overflow-wrap:anywhere]">
                      {formatRiskNextStep(state.data.next_step, locale)}
                    </dd>
                  </div>
                </dl>
              ) : null}
              <div className="flex justify-end border-b border-[var(--app-divider)] pb-2.5">
                <EvidenceIdentityDisclosure
                  triggerLabel={copy.common.viewEvidenceIdentity}
                  title={copy.common.evidenceIdentityTitle}
                  description={copy.common.evidenceIdentityDescription}
                  closeLabel={copy.common.closeEvidenceIdentity}
                  copyLabel={copy.common.copyEvidenceValue}
                  copiedLabel={copy.common.evidenceValueCopied}
                  fields={[
                    {
                      label: copy.common.valuationSnapshot,
                      value: state.data.summary.valuation_snapshot_id ?? '--',
                      mono: true,
                    },
                    {
                      label: copy.common.ledgerCutoff,
                      value: state.data.summary.ledger_cutoff_id ?? '--',
                      mono: true,
                    },
                    {
                      label: copy.common.valuationAsOf,
                      value: formatTimestamp(
                        state.data.summary.valuation_as_of ??
                          state.data.summary.valuation_timestamp,
                      ),
                      mono: true,
                    },
                    {
                      label: copy.common.valuationStatus,
                      value: formatPublicStatus(
                        state.data.summary.valuation_status ??
                          state.data.summary.quote_status,
                        locale,
                      ),
                    },
                  ]}
                />
              </div>
            </section>

            <aside
              className="grid min-w-0 content-start gap-3"
              data-testid="risk-metric-rail"
            >
              <MetricStrip
                ariaLabel={copy.riskPage.metrics}
                className="app-risk-metric-strip"
                items={workspace.data.metrics.map((metric) => ({
                  id: metric.key,
                  label: getRiskMetricLabel(copy, metric.key),
                  value: metric.display_value,
                  detail: formatRiskAlertLevel(metric.level, locale),
                  tone:
                    metric.level === 'high'
                      ? ('danger' as const)
                      : metric.level === 'medium'
                        ? ('warning' as const)
                        : ('neutral' as const),
                }))}
              />
              <section
                className="grid min-w-0 gap-2"
                data-testid="risk-trading-control-grid"
              >
                <div>
                  <h2 className="app-type-section-title text-[var(--app-text)]">
                    {locale === 'zh' ? '受控操作' : 'Controlled action'}
                  </h2>
                  <p className="mt-0.5 text-xs leading-5 text-[var(--app-text-secondary)]">
                    {locale === 'zh'
                      ? '熔断状态独立于风险事实；仅在需要人工干预时展开。'
                      : 'Kill-switch state stays separate from risk facts and expands only for deliberate operator intervention.'}
                  </p>
                </div>
                <KillSwitchPanel />
              </section>
            </aside>
          </div>

          {riskReviewTask ? (
            <section
              data-testid="risk-decision-handoff"
              className="min-w-0 space-y-2"
            >
              <h2 className="app-type-section-title text-[var(--app-text)]">
                {copy.riskPage.decisionHandoffKicker}
              </h2>
              <ExceptionList
                ariaLabel={copy.riskPage.decisionHandoffKicker}
                emptyState={copy.riskPage.noBlockingItems}
                density="compact"
                labels={{
                  reason: locale === 'zh' ? '阻断原因' : 'Reason',
                  unblockCondition:
                    locale === 'zh' ? '解除条件' : 'Unblock condition',
                  nextAction: locale === 'zh' ? '安全下一步' : 'Safe next step',
                  evidence: locale === 'zh' ? '证据' : 'Evidence',
                }}
                items={[
                  {
                    id: riskReviewTask.id,
                    severity: 'warning',
                    statusLabel: formatPublicStatus(
                      riskReviewTask.status,
                      locale,
                    ),
                    title: copy.riskPage.decisionHandoffTitle,
                    reason: copy.riskPage.decisionHandoffDetail(
                      riskCandidateCount,
                      riskCheckedCount,
                    ),
                    unblockCondition: copy.riskPage.decisionHandoffHow,
                    nextAction: copy.riskPage.decisionHandoffWhat,
                    evidence: copy.riskPage.decisionHandoffDoNot,
                  },
                ]}
                className="[&>li>dl]:grid-cols-2 lg:[&>li>dl]:grid-cols-4"
              />
              <div className="flex min-w-0 flex-col gap-2 border-b border-[var(--app-divider)] pb-3 sm:flex-row sm:justify-end">
                <button
                  type="button"
                  className="app-button-primary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-55 sm:min-h-9"
                  disabled={batchPreTradeRisk.isPending}
                  onClick={() => void runBatchRiskGate()}
                >
                  {batchPreTradeRisk.isPending
                    ? copy.riskPage.runningBatchRiskGate
                    : copy.riskPage.runBatchRiskGate}
                </button>
                <a
                  className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-1.5 text-sm font-semibold sm:min-h-9"
                  href="/decision"
                >
                  {copy.riskPage.returnToDecision}
                </a>
              </div>
              {batchRiskMessage ? (
                <div className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-success-border)] bg-[var(--app-success-bg)] px-3 py-2 text-sm font-semibold text-[var(--app-success-text)]">
                  {batchRiskMessage}
                </div>
              ) : null}
              {batchRiskBlockedMessage ? (
                <div
                  role="status"
                  className="mt-3 rounded-[var(--app-radius-surface)] border border-[var(--app-warning-border)] bg-[var(--app-warning-bg)] px-3 py-2 text-sm font-semibold leading-6 text-[var(--app-warning-text)]"
                >
                  {batchRiskBlockedMessage}
                </div>
              ) : null}
              {batchRiskError ? (
                <div className="app-error-text mt-3 text-sm">
                  {batchRiskError}
                </div>
              ) : null}
            </section>
          ) : null}

          <section className="min-w-0 space-y-2">
            <div>
              <h2 className="app-type-section-title text-[var(--app-text)]">
                {locale === 'zh'
                  ? '风险指标与阈值证据'
                  : 'Risk metric and threshold evidence'}
              </h2>
              <p className="mt-0.5 text-xs text-[var(--app-text-secondary)]">
                {locale === 'zh'
                  ? '仅展示风险服务已记录的数值、状态与说明；未提供的阈值不会在页面中推算。'
                  : 'Shows recorded risk values, states, and explanations. Missing thresholds are not inferred on this page.'}
              </p>
            </div>
            <div className="max-w-full overflow-x-auto border-y border-[var(--app-divider)]">
              <table
                className="w-full min-w-[620px] border-collapse text-left text-xs"
                data-testid="risk-threshold-table"
              >
                <caption className="sr-only">{copy.riskPage.metrics}</caption>
                <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
                  <tr>
                    {[
                      locale === 'zh' ? '指标' : 'Metric',
                      locale === 'zh' ? '当前值' : 'Current value',
                      locale === 'zh' ? '状态' : 'State',
                      locale === 'zh' ? '依据' : 'Evidence',
                    ].map((label) => (
                      <th
                        key={label}
                        scope="col"
                        className="border-b border-[var(--app-divider)] px-3 py-2 font-semibold"
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
                  {workspace.data.metrics.map((metric) => (
                    <tr key={metric.key}>
                      <th scope="row" className="px-3 py-2.5 font-semibold">
                        {getRiskMetricLabel(copy, metric.key)}
                      </th>
                      <td className="px-3 py-2.5 font-mono tabular-nums">
                        {metric.display_value}
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge
                          tone={
                            metric.level === 'high'
                              ? 'danger'
                              : metric.level === 'medium'
                                ? 'warning'
                                : 'neutral'
                          }
                        >
                          {formatRiskAlertLevel(metric.level, locale)}
                        </StatusBadge>
                      </td>
                      <td className="px-3 py-2.5 text-[var(--app-text-secondary)]">
                        {getRiskMetricDetail(copy, metric.key)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <details
            className="group min-w-0 border-y border-[var(--app-divider)]"
            data-testid="risk-analysis-disclosure"
          >
            <summary className="flex min-h-16 cursor-pointer list-none flex-col gap-3 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:flex-row sm:items-center sm:justify-between sm:gap-5 [&::-webkit-details-marker]:hidden">
              <div className="min-w-0">
                <div className="app-product-mark">
                  {locale === 'zh' ? '结构分析' : 'Structure analysis'}
                </div>
                <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
                  {locale === 'zh'
                    ? '回撤、暴露与持仓集中度'
                    : 'Drawdown, exposure, and position concentration'}
                </h2>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
                  {locale === 'zh'
                    ? '按需查看图表与逐持仓结构；当前异常、指标、阈值和熔断状态保留在上方。'
                    : 'Expand for charts and position-level structure. Current exceptions, metrics, thresholds, and kill-switch state remain above.'}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
                <StatusBadge tone="neutral">
                  {locale === 'zh'
                    ? `${workspace.data.exposure_buckets.length} 类暴露`
                    : `${workspace.data.exposure_buckets.length} exposure ${workspace.data.exposure_buckets.length === 1 ? 'bucket' : 'buckets'}`}
                </StatusBadge>
                <StatusBadge tone="neutral">
                  {locale === 'zh'
                    ? `${workspace.data.concentration.length} 个持仓`
                    : `${workspace.data.concentration.length} ${workspace.data.concentration.length === 1 ? 'position' : 'positions'}`}
                </StatusBadge>
                <span className="sr-only">
                  {locale === 'zh' ? '按需展开' : 'Expand on demand'}
                </span>
                <ChevronDown
                  aria-hidden="true"
                  className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
                />
              </div>
            </summary>
            <div className="space-y-5 border-t border-[var(--app-divider)] py-4 sm:space-y-6 sm:py-5">
              <div
                className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]"
                data-testid="risk-analysis-overview"
              >
                <section
                  className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
                  data-testid="risk-drawdown-section"
                >
                  <div className="app-type-overline text-[var(--app-text-tertiary)]">
                    {copy.riskPage.drawdown}
                  </div>
                  <div className="mt-3">
                    <DrawdownChart points={workspace.data.drawdown_series} />
                  </div>
                </section>
                <section
                  className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
                  data-testid="risk-exposure-section"
                >
                  <div className="app-type-overline text-[var(--app-text-tertiary)]">
                    {copy.riskPage.exposure}
                  </div>
                  <div className="mt-3 divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]">
                    {workspace.data.exposure_buckets.map((bucket) => (
                      <div key={bucket.bucket} className="px-2 py-2.5">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold">
                            {getRiskBucketLabel(copy, bucket.bucket)}
                          </div>
                          <div className="text-sm font-semibold tabular-nums">
                            {formatPercentValue(bucket.weight)}
                          </div>
                        </div>
                        <div className="app-muted mt-2 text-sm">
                          {formatCurrency(bucket.value)} ·{' '}
                          {copy.overview.risk.positionsHint(
                            bucket.positions_count,
                          )}
                        </div>
                        {bucket.symbols.length > 0 ? (
                          <div className="app-type-micro mt-2 font-mono text-[var(--app-text-tertiary)]">
                            {bucket.symbols.join(' · ')}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </section>
              </div>

              <section
                className="min-w-0 border-y border-[var(--app-divider)] py-3 sm:py-4"
                data-testid="risk-concentration-section"
              >
                <div className="app-type-overline text-[var(--app-text-tertiary)]">
                  {copy.riskPage.concentration}
                </div>
                <div className="mt-3 max-w-full overflow-x-auto border-y border-[var(--app-divider)]">
                  <table
                    className="w-full min-w-[620px] border-collapse text-left text-xs"
                    data-testid="risk-concentration-table"
                  >
                    <caption className="sr-only">
                      {copy.riskPage.concentration}
                    </caption>
                    <thead className="bg-[var(--app-surface-raised)] text-[var(--app-text-secondary)]">
                      <tr>
                        <th
                          scope="col"
                          className="sticky left-0 z-10 border-b border-[var(--app-divider)] bg-[var(--app-surface-raised)] px-3 py-2 font-semibold"
                        >
                          {copy.portfolio.table.symbol}
                        </th>
                        <th
                          scope="col"
                          className="border-b border-[var(--app-divider)] px-3 py-2 text-right font-semibold"
                        >
                          {copy.portfolio.table.weight}
                        </th>
                        <th
                          scope="col"
                          className="border-b border-[var(--app-divider)] px-3 py-2 text-right font-semibold"
                        >
                          {copy.portfolio.table.marketValue}
                        </th>
                        <th
                          scope="col"
                          className="border-b border-[var(--app-divider)] px-3 py-2 text-right font-semibold"
                        >
                          {copy.portfolio.table.unrealized}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--app-divider)] bg-[var(--app-surface)]">
                      {workspace.data.concentration.length > 0 ? (
                        workspace.data.concentration.map((item) => (
                          <tr key={item.symbol}>
                            <th
                              scope="row"
                              className="sticky left-0 bg-[var(--app-surface)] px-3 py-2.5 font-semibold"
                            >
                              <span
                                className="block max-w-56 truncate"
                                title={formatInstrumentDisplayLabelFromNameMap(
                                  item.symbol,
                                  instrumentNames,
                                )}
                              >
                                {formatInstrumentDisplayLabelFromNameMap(
                                  item.symbol,
                                  instrumentNames,
                                )}
                              </span>
                            </th>
                            <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                              {formatPercentValue(item.weight)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                              {formatCurrency(item.market_value)}
                            </td>
                            <td
                              className={`px-3 py-2.5 text-right font-medium tabular-nums ${
                                item.unrealized_pnl < 0
                                  ? 'text-[var(--app-pnl-negative)]'
                                  : item.unrealized_pnl > 0
                                    ? 'text-[var(--app-pnl-positive)]'
                                    : 'text-[var(--app-pnl-neutral)]'
                              }`}
                            >
                              {formatCurrency(item.unrealized_pnl)}
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td
                            colSpan={4}
                            className="px-3 py-3 text-[var(--app-text-secondary)]"
                          >
                            {copy.riskPage.noConcentration}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          </details>

          <details
            className="group min-w-0 border-y border-[var(--app-divider)]"
            data-testid="risk-history-disclosure"
          >
            <summary className="flex min-h-16 cursor-pointer list-none flex-col gap-3 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:flex-row sm:items-center sm:justify-between sm:gap-5 [&::-webkit-details-marker]:hidden">
              <div className="min-w-0">
                <div className="app-product-mark">
                  {locale === 'zh' ? '历史与归因' : 'History & attribution'}
                </div>
                <h2 className="app-type-section-title mt-1 text-[var(--app-text)]">
                  {locale === 'zh'
                    ? '净值与事件解释路径'
                    : 'Equity and event explanation path'}
                </h2>
                <p className="mt-1 max-w-3xl text-xs leading-5 text-[var(--app-text-secondary)]">
                  {locale === 'zh'
                    ? '按需查看净值桥、影响事件、持仓驱动和时间序列归因；当前风险与受控操作保持在上方。'
                    : 'Expand for the equity bridge, impact events, position drivers, and timeline attribution. Current risk and controlled actions stay above.'}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
                {explainability.isLoading ? (
                  <StatusBadge tone="neutral">
                    {copy.states.loading}
                  </StatusBadge>
                ) : (
                  <>
                    <StatusBadge tone="neutral">
                      {locale === 'zh'
                        ? `${riskHistoryImpactCount} 条影响事件`
                        : `${riskHistoryImpactCount} impact ${riskHistoryImpactCount === 1 ? 'event' : 'events'}`}
                    </StatusBadge>
                    <StatusBadge tone="neutral">
                      {locale === 'zh'
                        ? `${riskHistoryValuationDayCount} 个估值日`
                        : `${riskHistoryValuationDayCount} valuation ${riskHistoryValuationDayCount === 1 ? 'day' : 'days'}`}
                    </StatusBadge>
                  </>
                )}
                <span className="sr-only">
                  {locale === 'zh' ? '按需展开' : 'Expand on demand'}
                </span>
                <ChevronDown
                  aria-hidden="true"
                  className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
                />
              </div>
            </summary>
            <div className="border-t border-[var(--app-divider)] py-4 sm:py-5">
              <ExplainabilityWorkspace
                title={copy.riskPage.equityBridge}
                stateLabelRecent={copy.riskPage.recentDrivers}
                stateLabelPositions={copy.riskPage.positionDrivers}
                emptyLabel={copy.riskPage.emptyDrivers}
                explainability={explainability.data}
                loading={explainability.isLoading}
                instrumentNames={instrumentNames}
                filters={
                  <div className="grid gap-3 md:grid-cols-3">
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteDateFrom}
                      </span>
                      <input
                        type="date"
                        value={timelineFromDate}
                        onChange={(event) =>
                          setTimelineFromDate(event.target.value)
                        }
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        aria-label={copy.market.noteDateFrom}
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.market.noteDateTo}
                      </span>
                      <input
                        type="date"
                        value={timelineToDate}
                        onChange={(event) =>
                          setTimelineToDate(event.target.value)
                        }
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        aria-label={copy.market.noteDateTo}
                      />
                    </label>
                    <label className="grid gap-2">
                      <span className="text-sm font-medium">
                        {copy.explainability.timelineEventKind}
                      </span>
                      <select
                        value={timelineEventKind}
                        onChange={(event) =>
                          setTimelineEventKind(event.target.value)
                        }
                        className="app-field rounded-[var(--app-radius-control)] px-3 py-2 text-sm"
                        aria-label={copy.explainability.timelineEventKind}
                      >
                        <option value="">
                          {copy.explainability.allEvents}
                        </option>
                        <option value="cash_deposit">
                          {copy.explainability.deposits}
                        </option>
                        <option value="cash_withdrawal">
                          {copy.explainability.withdrawals}
                        </option>
                        <option value="dividend">
                          {copy.explainability.dividends}
                        </option>
                        <option value="trade_buy">
                          {copy.explainability.buys}
                        </option>
                        <option value="trade_sell">
                          {copy.explainability.sells}
                        </option>
                        <option value="manual_adjustment">
                          {copy.explainability.adjustments}
                        </option>
                      </select>
                    </label>
                  </div>
                }
              />
            </div>
          </details>
        </div>
      )}
    </section>
  );
}

function ExplainabilityWorkspace({
  title,
  stateLabelRecent,
  stateLabelPositions,
  emptyLabel,
  explainability,
  loading,
  instrumentNames,
  filters,
  showReturnCalendar = false,
}: {
  title: string;
  stateLabelRecent: string;
  stateLabelPositions: string;
  emptyLabel: string;
  explainability:
    | {
        equity_bridge: Array<{
          key: string;
          label: string;
          value: number;
          detail: string;
        }>;
        recent_drivers: Array<{
          kind?: string;
          title: string;
          detail: string;
          timestamp: string;
          symbol?: string | null;
          amount?: number | null;
        }>;
        positions: Array<{
          symbol: string;
          quantity: number;
          market_value: number;
          unrealized_pnl: number;
          last_activity_at: string | null;
        }>;
        timeline: Array<{
          date: string;
          equity: number;
          delta: number;
          external_flow: number;
          market_pnl: number;
          market_breakdown?: ReturnCalendarBreakdownItem[];
          external_flow_breakdown?: ReturnCalendarBreakdownItem[];
          events: Array<{
            category: string;
            impact_source: string;
            kind: string;
            title: string;
            detail?: string;
            timestamp: string;
            symbol?: string | null;
            amount?: number | null;
          }>;
        }>;
      }
    | undefined;
  loading: boolean;
  instrumentNames?: Map<string, string>;
  filters?: ReactNode;
  showReturnCalendar?: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const [activeView, setActiveView] = useState<RiskHistoryView>('bridge');
  const [recentDriverPage, setRecentDriverPage] = useState(0);
  const [timelinePage, setTimelinePage] = useState(0);

  if (loading) {
    return <EvidenceState kind="loading" title={copy.states.loading} />;
  }

  const equityBridge = explainability?.equity_bridge ?? [];
  const recentDrivers = explainability?.recent_drivers ?? [];
  const positions = explainability?.positions ?? [];
  const timeline = (explainability?.timeline ?? []).slice().reverse();
  const recentDriverPageCount = Math.max(
    1,
    Math.ceil(recentDrivers.length / RISK_HISTORY_EVENT_PAGE_SIZE),
  );
  const timelinePageCount = Math.max(
    1,
    Math.ceil(timeline.length / RISK_HISTORY_TIMELINE_PAGE_SIZE),
  );
  const visibleRecentDriverPage = Math.min(
    recentDriverPage,
    recentDriverPageCount - 1,
  );
  const visibleTimelinePage = Math.min(timelinePage, timelinePageCount - 1);
  const visibleRecentDrivers = recentDrivers.slice(
    visibleRecentDriverPage * RISK_HISTORY_EVENT_PAGE_SIZE,
    (visibleRecentDriverPage + 1) * RISK_HISTORY_EVENT_PAGE_SIZE,
  );
  const visibleTimeline = timeline.slice(
    visibleTimelinePage * RISK_HISTORY_TIMELINE_PAGE_SIZE,
    (visibleTimelinePage + 1) * RISK_HISTORY_TIMELINE_PAGE_SIZE,
  );
  const historyViews = [
    { id: 'bridge', label: title, count: equityBridge.length },
    { id: 'events', label: stateLabelRecent, count: recentDrivers.length },
    { id: 'positions', label: stateLabelPositions, count: positions.length },
    {
      id: 'timeline',
      label: copy.explainability.timeline,
      count: timeline.length,
    },
  ] as const;

  return (
    <div className="min-w-0 space-y-4">
      <div
        role="tablist"
        aria-label={
          locale === 'zh' ? '风险历史分析视图' : 'Risk history analysis views'
        }
        className="flex max-w-full overflow-x-auto border-b border-[var(--app-divider)]"
        data-testid="risk-history-tabs"
      >
        {historyViews.map((view) => (
          <button
            key={view.id}
            id={`risk-history-tab-${view.id}`}
            type="button"
            role="tab"
            aria-selected={activeView === view.id}
            aria-controls={`risk-history-panel-${view.id}`}
            tabIndex={activeView === view.id ? 0 : -1}
            onClick={() => setActiveView(view.id)}
            onKeyDown={(event) => {
              if (
                !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)
              ) {
                return;
              }
              event.preventDefault();
              const tabs = Array.from(
                event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                  '[role="tab"]',
                ) ?? [],
              );
              const currentIndex = tabs.indexOf(event.currentTarget);
              const nextIndex =
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? tabs.length - 1
                    : event.key === 'ArrowRight'
                      ? (currentIndex + 1) % tabs.length
                      : (currentIndex - 1 + tabs.length) % tabs.length;
              const nextView = historyViews[nextIndex];
              if (!nextView) return;
              setActiveView(nextView.id);
              tabs[nextIndex]?.focus();
            }}
            className={`flex h-10 shrink-0 items-center gap-2 border-b-2 px-3 text-xs font-semibold transition-colors duration-[var(--app-motion-fast)] motion-reduce:transition-none ${
              activeView === view.id
                ? 'border-[var(--app-accent)] text-[var(--app-accent)]'
                : 'border-transparent text-[var(--app-text-secondary)] hover:text-[var(--app-text)]'
            }`}
          >
            <span>{view.label}</span>
            <span className="font-mono text-xs tabular-nums text-[var(--app-text-tertiary)]">
              {view.count}
            </span>
          </button>
        ))}
      </div>

      {activeView === 'bridge' ? (
        <section
          id="risk-history-panel-bridge"
          role="tabpanel"
          aria-labelledby="risk-history-tab-bridge"
          className="space-y-3"
          data-testid="risk-equity-bridge-section"
        >
          <h2 className="app-kicker app-type-overline">{title}</h2>
          {equityBridge.length > 0 ? (
            <MetricStrip
              ariaLabel={title}
              items={equityBridge.map((item) => {
                const label =
                  copy.explainability.equityBridgeLabels[
                    item.key as keyof typeof copy.explainability.equityBridgeLabels
                  ] ?? item.label;
                const isPnlMetric =
                  item.key === 'realized' || item.key === 'unrealized';

                return {
                  id: item.key,
                  label,
                  value: formatCurrency(item.value),
                  tone:
                    isPnlMetric && item.value > 0
                      ? ('pnl-positive' as const)
                      : isPnlMetric && item.value < 0
                        ? ('pnl-negative' as const)
                        : ('neutral' as const),
                };
              })}
            />
          ) : (
            <EvidenceState kind="empty" title={emptyLabel} />
          )}
        </section>
      ) : null}

      {activeView === 'events' ? (
        <section
          id="risk-history-panel-events"
          role="tabpanel"
          aria-labelledby="risk-history-tab-events"
          className="min-w-0 space-y-3"
        >
          <h2 className="app-kicker app-type-overline">{stateLabelRecent}</h2>
          {recentDrivers.length > 0 ? (
            <ol
              className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
              data-testid="risk-recent-impact-list"
            >
              {visibleRecentDrivers.map((item) => (
                <li
                  key={`${item.title}-${item.timestamp}`}
                  className="px-3 py-3"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0 text-sm font-semibold leading-6">
                      {formatLedgerExplainabilityTitle(
                        item,
                        locale,
                        instrumentNames,
                      )}
                    </div>
                    {typeof item.amount === 'number' ? (
                      <div
                        className={`shrink-0 text-right text-sm font-semibold tabular-nums ${
                          item.amount < 0
                            ? 'text-[var(--app-pnl-negative)]'
                            : item.amount > 0
                              ? 'text-[var(--app-pnl-positive)]'
                              : 'text-[var(--app-pnl-neutral)]'
                        }`}
                      >
                        {formatCurrency(item.amount)}
                      </div>
                    ) : null}
                  </div>
                  {formatLedgerExplainabilityDetail(
                    item,
                    locale,
                    instrumentNames,
                  ) ? (
                    <div className="app-muted mt-1 break-words text-sm leading-6">
                      {formatLedgerExplainabilityDetail(
                        item,
                        locale,
                        instrumentNames,
                      )}
                    </div>
                  ) : null}
                  {item.timestamp ? (
                    <time className="app-kicker app-type-micro mt-2 block">
                      {formatAuditTimestamp(item.timestamp)}
                    </time>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <EvidenceState kind="empty" title={emptyLabel} />
          )}
          <RiskHistoryPager
            kind="events"
            page={visibleRecentDriverPage}
            pageCount={recentDriverPageCount}
            totalItems={recentDrivers.length}
            locale={locale}
            onPageChange={setRecentDriverPage}
          />
        </section>
      ) : null}

      {activeView === 'positions' ? (
        <section
          id="risk-history-panel-positions"
          role="tabpanel"
          aria-labelledby="risk-history-tab-positions"
          className="min-w-0 space-y-3"
        >
          <h2 className="app-kicker app-type-overline">
            {stateLabelPositions}
          </h2>
          {positions.length > 0 ? (
            <ul
              className="divide-y divide-[var(--app-divider)] border-y border-[var(--app-divider)]"
              data-testid="risk-position-impact-list"
            >
              {positions.map((item) => (
                <li
                  key={item.symbol}
                  className="grid gap-1 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-4"
                >
                  <div className="min-w-0 text-sm font-semibold">
                    {formatInstrumentDisplayLabelFromNameMap(
                      item.symbol,
                      instrumentNames,
                    )}
                  </div>
                  <div className="text-sm font-medium tabular-nums sm:text-right">
                    {formatCurrency(item.market_value)}
                  </div>
                  <div className="app-muted text-sm">
                    {copy.explainability.quantity}{' '}
                    {formatQuantity(item.quantity)} ·{' '}
                    {copy.portfolio.table.unrealized}{' '}
                    <span
                      className={
                        item.unrealized_pnl < 0
                          ? 'text-[var(--app-pnl-negative)]'
                          : item.unrealized_pnl > 0
                            ? 'text-[var(--app-pnl-positive)]'
                            : 'text-[var(--app-pnl-neutral)]'
                      }
                    >
                      {formatCurrency(item.unrealized_pnl)}
                    </span>
                  </div>
                  {item.last_activity_at ? (
                    <time className="app-kicker app-type-micro sm:text-right">
                      {formatAuditTimestamp(item.last_activity_at)}
                    </time>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <EvidenceState kind="empty" title={emptyLabel} />
          )}
        </section>
      ) : null}

      {activeView === 'timeline' ? (
        <section
          id="risk-history-panel-timeline"
          role="tabpanel"
          aria-labelledby="risk-history-tab-timeline"
          className="space-y-3"
          data-testid="risk-impact-timeline-section"
        >
          <h2 className="app-kicker app-type-overline">
            {copy.explainability.timeline}
          </h2>
          {filters ? <div className="mt-4">{filters}</div> : null}
          <div
            className="border-y border-[var(--app-divider)] py-3"
            data-testid="risk-impact-timeline-scroll"
          >
            <Timeline
              ariaLabel={copy.explainability.timeline}
              emptyState={copy.explainability.timelineEmpty}
              items={visibleTimeline.map((point) => ({
                id: `${point.date}-${point.equity}`,
                timestamp: point.date,
                title: `${copy.explainability.equity} ${formatCurrency(point.equity)}`,
                description: `${copy.explainability.netChange} ${formatCurrency(point.delta)} · ${copy.explainability.externalFlow} ${formatCurrency(point.external_flow)} · ${copy.explainability.marketPnl} ${formatCurrency(point.market_pnl)}`,
                evidence:
                  point.events.length > 0 ? (
                    <ul className="divide-y divide-[var(--app-divider)] border-t border-[var(--app-divider)] font-sans normal-case">
                      {point.events.map((event) => (
                        <li
                          key={`${event.timestamp}-${event.title}`}
                          className="py-2 first:pt-2 last:pb-0"
                        >
                          <div className="text-xs font-semibold text-[var(--app-text-secondary)]">
                            {formatLedgerExplainabilityTitle(
                              event,
                              locale,
                              instrumentNames,
                            )}{' '}
                            · {getEventKindLabel(copy, event.kind)} ·{' '}
                            {getEventCategoryLabel(copy, event.category)} ·{' '}
                            {getImpactSourceLabel(copy, event.impact_source)}
                          </div>
                          {formatLedgerExplainabilityDetail(
                            event,
                            locale,
                            instrumentNames,
                          ) ? (
                            <div className="mt-1 text-xs leading-5 text-[var(--app-text-tertiary)]">
                              {formatLedgerExplainabilityDetail(
                                event,
                                locale,
                                instrumentNames,
                              )}
                            </div>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : undefined,
                tone: 'neutral' as const,
              }))}
              className="pt-1"
            />
          </div>
          <RiskHistoryPager
            kind="timeline"
            page={visibleTimelinePage}
            pageCount={timelinePageCount}
            totalItems={timeline.length}
            locale={locale}
            onPageChange={setTimelinePage}
          />
        </section>
      ) : null}

      {activeView === 'timeline' && showReturnCalendar ? (
        <ReturnCalendarCard timeline={explainability?.timeline ?? []} />
      ) : null}
    </div>
  );
}

type RiskHistoryView = 'bridge' | 'events' | 'positions' | 'timeline';

const RISK_HISTORY_EVENT_PAGE_SIZE = 8;
const RISK_HISTORY_TIMELINE_PAGE_SIZE = 12;

function RiskHistoryPager({
  kind,
  page,
  pageCount,
  totalItems,
  locale,
  onPageChange,
}: {
  kind: 'events' | 'timeline';
  page: number;
  pageCount: number;
  totalItems: number;
  locale: Locale;
  onPageChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;

  return (
    <div
      role="group"
      aria-label={
        locale === 'zh'
          ? kind === 'events'
            ? '影响事件分页'
            : '估值日分页'
          : kind === 'events'
            ? 'Impact event pagination'
            : 'Valuation day pagination'
      }
      className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--app-divider)] pt-3"
      data-testid={`risk-history-${kind}-pager`}
    >
      <span className="text-xs tabular-nums text-[var(--app-text-tertiary)]">
        {locale === 'zh'
          ? `第 ${page + 1} / ${pageCount} 页 · 共 ${totalItems} 条`
          : `Page ${page + 1} of ${pageCount} · ${totalItems} items`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={page === 0}
          onClick={() => onPageChange(Math.max(0, page - 1))}
        >
          {locale === 'zh' ? '较新' : 'Newer'}
        </button>
        <button
          type="button"
          className="app-button-secondary inline-flex min-h-10 items-center justify-center rounded-[var(--app-radius-control)] px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
        >
          {locale === 'zh' ? '较早' : 'Older'}
        </button>
      </div>
    </div>
  );
}

function DrawdownChart({
  points,
}: {
  points: Array<{ timestamp: string; drawdown: number }>;
}) {
  const copy = useCopy();

  if (points.length === 0) {
    return (
      <div className="app-muted text-sm">
        {copy.explainability.timelineEmpty}
      </div>
    );
  }

  const path = points
    .map((point, index) => {
      const x = (index / Math.max(points.length - 1, 1)) * 640;
      const y =
        (point.drawdown /
          Math.max(...points.map((item) => item.drawdown), 0.01)) *
        220;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg viewBox="0 0 640 220" className="h-48 w-full sm:h-56">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        points={path}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function formatCurrency(value: number) {
  return formatCurrencyValue(value);
}

function formatAuditTimestamp(timestamp: string) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

function getEventKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'cash_deposit':
      return copy.explainability.deposits;
    case 'cash_withdrawal':
      return copy.explainability.withdrawals;
    case 'dividend':
      return copy.explainability.dividends;
    case 'trade_buy':
      return copy.explainability.buys;
    case 'trade_sell':
      return copy.explainability.sells;
    case 'manual_adjustment':
      return copy.explainability.adjustments;
    default:
      return value;
  }
}

function getEventCategoryLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'capital':
      return copy.explainability.categoryCapital;
    case 'income':
      return copy.explainability.categoryIncome;
    case 'override':
      return copy.explainability.categoryOverride;
    case 'trade':
      return copy.explainability.categoryTrade;
    default:
      return value;
  }
}

function getImpactSourceLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'external':
      return copy.explainability.sourceExternal;
    case 'cash':
      return copy.explainability.sourceCash;
    case 'manual':
      return copy.explainability.sourceManual;
    case 'positioning':
      return copy.explainability.sourcePositioning;
    default:
      return value;
  }
}

function getRiskMetricLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'gross_exposure':
      return copy.riskPage.grossExposure;
    case 'cash_ratio':
      return copy.riskPage.cashRatio;
    case 'largest_weight':
      return copy.riskPage.largestPosition;
    case 'top3_weight':
      return copy.riskPage.top3Concentration;
    default:
      return value;
  }
}

function getRiskMetricDetail(copy: AppCopy, value: string) {
  switch (value) {
    case 'current_drawdown':
      return copy.riskPage.currentDrawdownDetail;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdownDetail;
    case 'gross_exposure':
      return copy.riskPage.grossExposureDetail;
    case 'cash_ratio':
      return copy.riskPage.cashRatioDetail;
    case 'largest_weight':
      return copy.riskPage.largestPositionDetail;
    case 'top3_weight':
      return copy.riskPage.top3ConcentrationDetail;
    default:
      return value;
  }
}

function getRiskAlertKindLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'risk':
      return copy.overview.risk.registerKicker;
    case 'cash_buffer':
      return copy.overview.risk.cashBuffer;
    case 'concentration':
    case 'largest_weight':
      return copy.overview.risk.concentration;
    case 'gross_exposure':
    case 'capital_deployment':
      return copy.overview.risk.deployment;
    case 'current_drawdown':
      return copy.riskPage.currentDrawdown;
    case 'max_drawdown':
      return copy.riskPage.maxDrawdown;
    case 'market_data':
    case 'data':
      return copy.decision.marketData;
    case 'manual_confirmation':
      return copy.overview.risk.manualConfirmationRequired;
    default:
      return value;
  }
}

function formatRiskAlertDetail(value: string, locale: Locale) {
  const concentration = /^(.+)\s+占总资产\s+([\d.]+%)$/u.exec(value.trim());
  if (concentration) {
    const [, instrument, weight] = concentration;
    return locale === 'zh'
      ? value
      : `${instrument} accounts for ${weight} of total equity.`;
  }
  const cashBuffer = /^当前现金占比\s+([\d.]+%)，可用调仓空间有限$/u.exec(
    value.trim(),
  );
  if (cashBuffer) {
    const [, ratio] = cashBuffer;
    return locale === 'zh'
      ? value
      : `Cash is ${ratio} of total equity; rebalance capacity is limited.`;
  }
  const quoteTimestamp = /^(\S+)\s+最新快照时间\s+(.+)$/u.exec(value.trim());
  if (quoteTimestamp) {
    const [, symbol, timestamp] = quoteTimestamp;
    return locale === 'zh'
      ? `${symbol} 最新行情截至 ${formatTimestamp(timestamp)}`
      : `${symbol} quote evidence as of ${formatTimestamp(timestamp)}`;
  }
  return formatPublicNote(value, locale);
}

function formatRiskAlertTitle(value: string, locale: Locale) {
  if (locale === 'zh') {
    return value;
  }
  const labels: Record<string, string> = {
    仓位集中度偏高: 'Position concentration is elevated',
    现金缓冲偏低: 'Cash buffer is low',
    行情数据可能过旧: 'Market quote evidence may be stale',
    当前风险可控: 'Current risk is manageable',
  };
  return labels[value.trim()] ?? formatPublicNote(value, locale);
}

function formatRiskNextStep(value: string, locale: Locale) {
  if (locale === 'zh') {
    return value;
  }
  const labels: Record<string, string> = {
    确认待执行建议: 'Review pending recommendations before any execution.',
    继续观察市场: 'Continue monitoring the market.',
  };
  return labels[value.trim()] ?? formatPublicNote(value, locale);
}

function formatRiskAlertLevel(level: string, locale: Locale) {
  const normalized = level.trim().toLowerCase();
  if (normalized === 'medium') {
    return formatPublicStatus('warning', locale);
  }
  if (normalized === 'high') {
    return formatPublicStatus('blocked', locale);
  }
  if (normalized === 'low') {
    return formatPublicStatus('healthy', locale);
  }
  return formatPublicStatus(level, locale);
}

function getRiskBucketLabel(copy: AppCopy, value: string) {
  switch (value) {
    case 'heavy':
      return copy.riskPage.bucketHeavy;
    case 'core':
      return copy.riskPage.bucketCore;
    case 'starter':
      return copy.riskPage.bucketStarter;
    case 'small':
      return copy.riskPage.bucketSmall;
    case 'cash':
      return copy.riskPage.bucketCash;
    default:
      return value;
  }
}

export const Route = createLazyRoute('/risk')({
  component: RiskPage,
});
