import { usePreferences } from '../../../shared/preferences/context';
import {
  type AutomationCockpitResponse,
  type BrokerConnectorHealthResponse,
  type ExecutionReconciliationRun,
  type BrokerGatewayAccountFactsResponse,
  type BrokerGatewayFillsQueryResponse,
  type BrokerGatewayOrderQueryResponse,
  type BrokerGatewayStatusResponse,
} from '../../operations/api';
import { DailyCandidateTrialPanel } from './daily-candidate-trial-panel';
import {
  automationExecutionMode,
  automationModeLabel,
  automationNextAction,
} from './decision-automation-model';
import { DailyCandidateFinancialPreflightPanel } from './daily-candidate-financial-preflight-panel';
import {
  AutomationOpenAlertSection,
  CurrentPerOrderReviewSection,
  StrategyPromotionStatesSection,
} from './automation-review-sections';
import { ControlledExecutionSection } from './automation-controlled-execution-section';
import {
  BrokerConnectorHealthSection,
  BrokerGatewayStatusSection,
} from './automation-broker-status-sections';
import {
  BrokerAccountFactsSection,
  BrokerFillsSection,
} from './automation-broker-evidence-sections';
import { ExecutionReconciliationSection } from './automation-reconciliation-section';

export function AutomationCockpitPanel({
  cockpit,
  brokerGatewayStatus,
  brokerConnectorHealth,
  brokerConnectorHealthLoading,
  brokerConnectorHealthError,
  brokerAccountFacts,
  brokerAccountFactsLoading,
  brokerAccountFactsError,
  brokerFills,
  brokerFillsLoading,
  brokerFillsError,
  brokerOrderQuery,
  brokerOrderQueryLoading,
  brokerOrderQueryError,
  executionReconciliationRuns,
  executionReconciliationRunDetail,
  executionReconciliationLoading,
  executionReconciliationError,
  brokerGatewayLoading,
  brokerGatewayError,
  loading,
  error,
}: {
  cockpit: AutomationCockpitResponse | undefined;
  brokerGatewayStatus: BrokerGatewayStatusResponse | undefined;
  brokerConnectorHealth: BrokerConnectorHealthResponse | undefined;
  brokerConnectorHealthLoading: boolean;
  brokerConnectorHealthError: boolean;
  brokerAccountFacts: BrokerGatewayAccountFactsResponse | undefined;
  brokerAccountFactsLoading: boolean;
  brokerAccountFactsError: boolean;
  brokerFills: BrokerGatewayFillsQueryResponse | undefined;
  brokerFillsLoading: boolean;
  brokerFillsError: boolean;
  brokerOrderQuery: BrokerGatewayOrderQueryResponse | undefined;
  brokerOrderQueryLoading: boolean;
  brokerOrderQueryError: boolean;
  executionReconciliationRuns: ExecutionReconciliationRun[] | undefined;
  executionReconciliationRunDetail: ExecutionReconciliationRun | undefined;
  executionReconciliationLoading: boolean;
  executionReconciliationError: boolean;
  brokerGatewayLoading: boolean;
  brokerGatewayError: boolean;
  loading: boolean;
  error: boolean;
}) {
  const { locale } = usePreferences();

  if (loading) return null;
  if (error || !cockpit) return null;

  const openAlerts = cockpit.open_alert_count;
  const reconciliationReviews =
    cockpit.execution_reconciliation_open_items.length;
  const currentPerOrderReviewCount =
    cockpit.current_per_order_reviews?.candidate_count ?? 0;
  const nextAction = automationNextAction(cockpit, locale);
  const manualDefault = cockpit.automation_status.manual_confirmation_required;
  const brokerOff =
    !cockpit.broker_submission_enabled &&
    !cockpit.automation_status.broker_submission_enabled;
  const gatewayControlsUnavailable =
    brokerGatewayStatus?.kill_switch_status === 'unavailable' ||
    brokerGatewayStatus?.kill_switch_evidence_available === false;
  const latestExecutionReconciliationRun =
    executionReconciliationRunDetail ?? executionReconciliationRuns?.[0];

  return (
    <section
      data-testid="decision-automation-cockpit"
      className="app-terminal-panel min-w-0 overflow-hidden rounded-[28px] p-[1px]"
    >
      <div className="app-terminal-inner min-w-0 rounded-[27px] p-4 sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="app-product-mark">
              {locale === 'zh' ? '自动化控制' : 'Automation control'}
            </div>
            <h2 className="app-card-title mt-1.5">
              {locale === 'zh' ? '自动化待办' : 'Automation to-do'}
            </h2>
          </div>
          <div className="min-w-0 rounded-full border border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_10%,transparent)] px-3 py-1.5 text-sm font-semibold text-[var(--app-warning)] sm:text-right">
            {locale === 'zh' ? '下一步：' : 'Next: '}
            {nextAction}
          </div>
        </div>

        <div className="mt-4 grid min-w-0 gap-2 md:grid-cols-4">
          <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '执行模式' : 'Execution mode'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {automationModeLabel(automationExecutionMode(cockpit), locale)}
            </div>
          </div>
          <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '确认门禁' : 'Confirmation gate'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {manualDefault
                ? locale === 'zh'
                  ? '默认仍需人工确认'
                  : 'Manual confirmation remains default'
                : locale === 'zh'
                  ? '人工确认未强制'
                  : 'Manual confirmation not enforced'}
            </div>
          </div>
          <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '券商提交' : 'Broker submission'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {brokerOff
                ? locale === 'zh'
                  ? '券商提交关闭'
                  : 'Broker submission off'
                : locale === 'zh'
                  ? '券商提交已开启'
                  : 'Broker submission on'}
            </div>
          </div>
          <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
            <div className="app-muted text-xs">
              {locale === 'zh' ? '待处理' : 'Queue'}
            </div>
            <div className="mt-1 text-sm font-semibold text-[var(--app-text)]">
              {locale === 'zh'
                ? `${openAlerts} 个开放告警 · ${reconciliationReviews} 个对账复核 · ${currentPerOrderReviewCount} 个逐单复核`
                : `${openAlerts} open alert${
                    openAlerts === 1 ? '' : 's'
                  } · ${reconciliationReviews} reconciliation review${
                    reconciliationReviews === 1 ? '' : 's'
                  } · ${currentPerOrderReviewCount} per-order review${
                    currentPerOrderReviewCount === 1 ? '' : 's'
                  }`}
            </div>
          </div>
        </div>

        {cockpit.daily_candidate_financial_preflight ? (
          <DailyCandidateFinancialPreflightPanel
            preflight={cockpit.daily_candidate_financial_preflight}
          />
        ) : null}

        {cockpit.daily_candidate_trial ? (
          <DailyCandidateTrialPanel
            trial={cockpit.daily_candidate_trial}
            runtime={cockpit.daily_candidate_runtime}
            reviewEnabled={!gatewayControlsUnavailable}
          />
        ) : null}
        <CurrentPerOrderReviewSection
          reviews={cockpit.current_per_order_reviews}
        />
        <ControlledExecutionSection
          controlledExecution={cockpit.controlled_execution}
        />
        <AutomationOpenAlertSection alert={cockpit.open_alerts[0]} />
        <StrategyPromotionStatesSection cockpit={cockpit} />
        <BrokerGatewayStatusSection
          brokerGatewayStatus={brokerGatewayStatus}
          brokerGatewayLoading={brokerGatewayLoading}
          brokerGatewayError={brokerGatewayError}
        />
        <BrokerConnectorHealthSection
          brokerConnectorHealth={brokerConnectorHealth}
          brokerConnectorHealthLoading={brokerConnectorHealthLoading}
          brokerConnectorHealthError={brokerConnectorHealthError}
        />
        <BrokerAccountFactsSection
          brokerAccountFacts={brokerAccountFacts}
          brokerAccountFactsLoading={brokerAccountFactsLoading}
          brokerAccountFactsError={brokerAccountFactsError}
        />
        <BrokerFillsSection
          brokerFills={brokerFills}
          brokerFillsLoading={brokerFillsLoading}
          brokerFillsError={brokerFillsError}
          reconciliationRun={latestExecutionReconciliationRun}
        />
        <ExecutionReconciliationSection
          executionReconciliationRuns={executionReconciliationRuns}
          executionReconciliationRunDetail={executionReconciliationRunDetail}
          executionReconciliationLoading={executionReconciliationLoading}
          executionReconciliationError={executionReconciliationError}
          brokerOrderQuery={brokerOrderQuery}
          brokerOrderQueryLoading={brokerOrderQueryLoading}
          brokerOrderQueryError={brokerOrderQueryError}
        />
      </div>
    </section>
  );
}
