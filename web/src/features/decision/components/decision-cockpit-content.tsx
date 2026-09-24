import { ChevronDown } from 'lucide-react';
import { StatusBadge, WorkspaceHeader } from '../../../shared/ui/workbench';
import { formatCurrency } from '../../../shared/format';
import { formatPublicStatus } from '../../../shared/public-labels';
import { DecisionQualityPanel } from './decision-quality-panel';
import { tradingPlanConclusionLabel } from './decision-trading-plan-model';
import { AutomationCockpitPanel } from './automation-cockpit-panel';
import { DailyTradingPlanPanel } from './daily-trading-plan-panel';
import {
  DecisionNextActionGuidePanel,
  DecisionSummaryCollapsedPanel,
  DecisionWorkflowPanel,
} from './decision-workflow-panels';
import { SignalQueuePanel } from './decision-signal-queue-panel';
import {
  AccountTruthGateTile,
  DecisionLanePanel,
  LaneStatusTile,
  StrategyAttributionGateTile,
  SummaryTile,
} from './decision-lane-panels';
import type { DecisionCockpitWorkspaceModel } from './use-decision-cockpit-workspace';
import { DecisionGateMatrixSection } from './decision-gate-matrix-section';

export function DecisionCockpitContent({
  model,
}: {
  model: DecisionCockpitWorkspaceModel;
}) {
  const {
    copy,
    labels,
    locale,
    today,
    intraday,
    tradingPlan,
    operationsToday,
    automationCockpit,
    brokerGatewayStatus,
    brokerConnectorHealth,
    brokerAccountFacts,
    brokerFills,
    executionReconciliationRuns,
    executionReconciliationRunDetail,
    brokerOrderQuery,
    runPaperShadow,
    signalActions,
    signalJournal,
    summaryExpanded,
    setSummaryExpanded,
    healthyGateMatrixExpanded,
    setHealthyGateMatrixExpanded,
    lanes,
    denseCandidateCount,
    collapseDecisionEvidence,
    gateItems,
    allDecisionGatesPass,
    decisionGateAttentionCount,
    idleTradingPlan,
  } = model;
  const tradingPlanPanel = (
    <DailyTradingPlanPanel
      plan={tradingPlan.data}
      candidates={today.data?.candidates ?? []}
      operationsToday={operationsToday.data}
      loading={tradingPlan.isLoading}
      error={tradingPlan.isError}
      onRunPaperShadow={() => runPaperShadow.mutate()}
      paperShadowRunPending={runPaperShadow.isPending}
      paperShadowRunError={runPaperShadow.isError}
    />
  );
  const currentSignalActions = (signalActions.data ?? []).filter(
    (action) => action.timestamp.slice(0, 10) === today.data?.decision_date,
  );
  return (
    <section
      className="app-workbench-route min-w-0 space-y-4 sm:space-y-5"
      data-workbench-route="decision"
      data-workbench-width="wide"
    >
      <WorkspaceHeader
        eyebrow={labels.kicker}
        title={labels.title}
        description={labels.subtitle}
        context={
          today.data
            ? `${today.data.decision_date} · ${formatPublicStatus(
                today.data.decision,
                locale,
              )}`
            : undefined
        }
      />

      {intraday.isLoading || intraday.isError ? (
        <div
          role="status"
          data-testid="decision-intraday-state"
          className="flex min-w-0 items-center gap-2 border-y border-[var(--app-divider)] px-3 py-2 text-xs text-[var(--app-text-secondary)]"
        >
          <StatusBadge tone={intraday.isError ? 'warning' : 'neutral'}>
            {intraday.isError ? copy.states.error : copy.states.loading}
          </StatusBadge>
          <span>
            {intraday.isError
              ? labels.intradayErrorDetail
              : labels.intradayLoadingDetail}
          </span>
        </div>
      ) : null}

      <SignalQueuePanel
        actions={currentSignalActions}
        journal={signalJournal.data ?? []}
        loading={signalActions.isLoading || signalJournal.isLoading}
        error={signalActions.isError || signalJournal.isError}
      />

      <DecisionGateMatrixSection
        gateItems={gateItems}
        allDecisionGatesPass={allDecisionGatesPass}
        decisionGateAttentionCount={decisionGateAttentionCount}
        healthyGateMatrixExpanded={healthyGateMatrixExpanded}
        onToggle={() => setHealthyGateMatrixExpanded((current) => !current)}
      />

      <DecisionNextActionGuidePanel lanes={lanes} />

      <details
        className="min-w-0 border-y border-[var(--app-divider)]"
        data-testid="decision-quality-disclosure"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-2.5 text-sm font-semibold text-[var(--app-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
          <span>
            {locale === 'zh' ? '决策证据登记' : 'Decision evidence register'}
          </span>
          <span className="text-xs font-normal text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '按需展开' : 'Expand on demand'}
          </span>
        </summary>
        <div className="py-4">
          <DecisionQualityPanel />
        </div>
      </details>

      {idleTradingPlan ? (
        <details
          className="group min-w-0 border-y border-[var(--app-divider)]"
          data-testid="decision-daily-trading-plan-disclosure"
        >
          <summary className="flex min-h-16 cursor-pointer list-none items-start justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
            <span className="min-w-0">
              <span className="app-product-mark block">
                {labels.tradingPlanKicker}
              </span>
              <span className="mt-1 block text-sm font-semibold text-[var(--app-text)]">
                {labels.tradingPlanTitle}
              </span>
              <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
                {labels.tradingPlanCounts(
                  idleTradingPlan.candidate_pool_count,
                  idleTradingPlan.order_intent_count,
                  idleTradingPlan.blocked_count,
                )}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <StatusBadge
                tone={idleTradingPlan.blocked_count > 0 ? 'warning' : 'neutral'}
              >
                {tradingPlanConclusionLabel(
                  idleTradingPlan.conclusion_status,
                  labels,
                )}
              </StatusBadge>
              <ChevronDown
                aria-hidden="true"
                className="h-4 w-4 text-[var(--app-text-secondary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
              />
            </span>
          </summary>
          <div className="border-t border-[var(--app-divider)] py-4 [&>[data-testid]]:border-y-0 [&>[data-testid]]:py-0 [&>[data-testid]>:first-child]:hidden">
            {tradingPlanPanel}
          </div>
        </details>
      ) : (
        tradingPlanPanel
      )}

      <details
        className="min-w-0 border-y border-[var(--app-divider)]"
        data-testid="decision-automation-disclosure"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-2.5 text-sm font-semibold text-[var(--app-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
          <span>
            {locale === 'zh'
              ? '自动化与受控执行证据'
              : 'Automation and controlled execution evidence'}
          </span>
          <span className="text-xs font-normal text-[var(--app-text-secondary)]">
            {locale === 'zh' ? '按需展开' : 'Expand on demand'}
          </span>
        </summary>
        <div className="py-4">
          <AutomationCockpitPanel
            cockpit={automationCockpit.data}
            brokerGatewayStatus={brokerGatewayStatus.data}
            brokerConnectorHealth={brokerConnectorHealth.data}
            brokerConnectorHealthLoading={brokerConnectorHealth.isLoading}
            brokerConnectorHealthError={brokerConnectorHealth.isError}
            brokerAccountFacts={brokerAccountFacts.data}
            brokerAccountFactsLoading={brokerAccountFacts.isLoading}
            brokerAccountFactsError={brokerAccountFacts.isError}
            brokerFills={brokerFills.data}
            brokerFillsLoading={brokerFills.isLoading}
            brokerFillsError={brokerFills.isError}
            brokerOrderQuery={brokerOrderQuery.data}
            brokerOrderQueryLoading={brokerOrderQuery.isLoading}
            brokerOrderQueryError={brokerOrderQuery.isError}
            executionReconciliationRuns={executionReconciliationRuns.data}
            executionReconciliationRunDetail={
              executionReconciliationRunDetail.data
            }
            executionReconciliationLoading={
              executionReconciliationRuns.isLoading
            }
            executionReconciliationError={
              executionReconciliationRuns.isError ||
              executionReconciliationRunDetail.isError
            }
            brokerGatewayLoading={brokerGatewayStatus.isLoading}
            brokerGatewayError={brokerGatewayStatus.isError}
            loading={automationCockpit.isLoading}
            error={automationCockpit.isError}
          />
        </div>
      </details>

      <details
        className="group min-w-0 border-y border-[var(--app-divider)]"
        data-testid="decision-supporting-details"
      >
        <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
          <span className="min-w-0">
            <span className="app-type-section-title block text-[var(--app-text)]">
              {locale === 'zh'
                ? '通道与状态明细'
                : 'Channel and status details'}
            </span>
            <span className="mt-0.5 block text-xs leading-5 text-[var(--app-text-secondary)]">
              {locale === 'zh'
                ? '仅在需要核对日级、盘中、账户事实或归因差异时展开。'
                : 'Expand only when reconciling daily, intraday, account-truth, or attribution differences.'}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-2 text-xs text-[var(--app-text-tertiary)]">
            <span>
              {locale === 'zh'
                ? ['候选池 ', denseCandidateCount].join('')
                : [denseCandidateCount, ' candidates'].join('')}
            </span>
            <ChevronDown
              aria-hidden="true"
              className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
            />
          </span>
        </summary>
        <div className="space-y-4 border-t border-[var(--app-divider)] py-4">
          <DecisionWorkflowPanel lanes={lanes} />

          {collapseDecisionEvidence && !summaryExpanded ? (
            <DecisionSummaryCollapsedPanel
              candidateCount={denseCandidateCount}
              onExpand={() => setSummaryExpanded(true)}
            />
          ) : (
            <div
              data-testid="decision-summary-grid"
              className="min-w-0 border-y border-[var(--app-divider)]"
            >
              {lanes.map((lane) => (
                <LaneStatusTile key={lane.lane} lane={lane} />
              ))}
              {lanes.map((lane) => (
                <AccountTruthGateTile
                  key={`${lane.lane}-account-truth`}
                  lane={lane}
                />
              ))}
              {lanes.map((lane) => (
                <StrategyAttributionGateTile
                  key={`${lane.lane}-strategy-attribution`}
                  lane={lane}
                />
              ))}
              <SummaryTile
                label={labels.marketHealth}
                value={`${labels.marketHealth}: ${formatPublicStatus(
                  today.data?.summary.market_data?.source_health ?? '--',
                  locale,
                )}`}
                detail={labels.quotesDetail(
                  today.data?.summary.market_data?.live_quote_count ?? 0,
                  today.data?.summary.market_data?.stale_quote_count ?? 0,
                )}
              />
              <SummaryTile
                label={labels.portfolio}
                value={`${labels.portfolioEquity}: ${formatCurrency(
                  today.data?.summary.portfolio?.total_equity,
                )}`}
                detail={labels.positionCount(
                  today.data?.summary.portfolio?.position_count ?? 0,
                )}
              />
            </div>
          )}

          <div
            data-testid="decision-lane-grid"
            className="grid min-w-0 gap-5 xl:grid-cols-2"
          >
            {lanes.map((lane) => (
              <DecisionLanePanel key={lane.lane} lane={lane} />
            ))}
          </div>
        </div>
      </details>
    </section>
  );
}
