import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicStatus } from '../../../shared/public-labels';
import {
  type ExecutionReconciliationRun,
  type ExecutionReconciliationItem,
  type BrokerGatewayOrderQueryResponse,
} from '../decision-feature-boundary';
import { PlanPaperActualComparison } from './plan-paper-actual-comparison';
import {
  executionReconciliationActionLabel,
  executionReconciliationItemStatusLabel,
  executionReconciliationStatusLabel,
  omsOrderStatusLabel,
} from './decision-execution-model';
import {
  brokerTradeCostEvidenceForItem,
  countLabel,
  manualBrokerComparisonEvidenceForItem,
  manualExecutionEvidenceForItem,
  primaryExecutionReconciliationItemForRun,
} from './decision-execution-evidence-model';

type ExecutionReconciliationSectionProps = {
  executionReconciliationRuns: ExecutionReconciliationRun[] | undefined;
  executionReconciliationRunDetail: ExecutionReconciliationRun | undefined;
  executionReconciliationLoading: boolean;
  executionReconciliationError: boolean;
  brokerOrderQuery: BrokerGatewayOrderQueryResponse | undefined;
  brokerOrderQueryLoading: boolean;
  brokerOrderQueryError: boolean;
};

export function ExecutionReconciliationSection(
  props: ExecutionReconciliationSectionProps,
) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const {
    executionReconciliationRuns,
    executionReconciliationRunDetail,
    executionReconciliationLoading,
    executionReconciliationError,
  } = props;
  const latestExecutionReconciliationRun =
    executionReconciliationRunDetail ?? executionReconciliationRuns?.[0];
  const primaryExecutionReconciliationItem =
    primaryExecutionReconciliationItemForRun(latestExecutionReconciliationRun);
  const showExecutionReconciliation =
    executionReconciliationLoading ||
    executionReconciliationError ||
    Boolean(latestExecutionReconciliationRun);
  return (
    <>
      {showExecutionReconciliation ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '执行对账' : 'Execution reconciliation'}
            </div>
            <span className="app-chip">
              {latestExecutionReconciliationRun
                ? executionReconciliationStatusLabel(
                    latestExecutionReconciliationRun.status,
                    locale,
                  )
                : executionReconciliationLoading
                  ? copy.states.loading
                  : locale === 'zh'
                    ? '不可用'
                    : 'Unavailable'}
            </span>
          </div>
          {executionReconciliationError && !latestExecutionReconciliationRun ? (
            <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
              {locale === 'zh'
                ? '执行对账不可用'
                : 'Execution reconciliation unavailable'}
            </div>
          ) : latestExecutionReconciliationRun ? (
            <div className="mt-3 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[var(--app-text)]">
                    {latestExecutionReconciliationRun.run_id}
                  </div>
                  <div className="app-muted mt-1 text-xs">
                    {locale === 'zh'
                      ? `${latestExecutionReconciliationRun.open_item_count} 个未处理 / 共 ${latestExecutionReconciliationRun.item_count} 个`
                      : `${latestExecutionReconciliationRun.open_item_count} open of ${latestExecutionReconciliationRun.item_count}`}
                  </div>
                </div>
                {latestExecutionReconciliationRun.run_date ? (
                  <span className="app-chip">
                    {latestExecutionReconciliationRun.run_date}
                  </span>
                ) : null}
              </div>
              {primaryExecutionReconciliationItem ? (
                <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
                  <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-[var(--app-text)]">
                        {primaryExecutionReconciliationItem.order_id ?? '--'}
                      </div>
                      <div className="app-muted mt-1 text-xs">
                        {executionReconciliationItemStatusLabel(
                          primaryExecutionReconciliationItem.item_status ??
                            primaryExecutionReconciliationItem.status ??
                            'unknown',
                          locale,
                        )}
                      </div>
                    </div>
                    <span className="app-chip">
                      {executionReconciliationActionLabel(
                        primaryExecutionReconciliationItem.suggested_action ??
                          primaryExecutionReconciliationItem.recommended_action ??
                          'review_order_state',
                        locale,
                      )}
                    </span>
                  </div>
                  {primaryExecutionReconciliationItem.detail ? (
                    <div className="app-muted mt-2 break-words text-sm leading-6">
                      {primaryExecutionReconciliationItem.detail}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {primaryExecutionReconciliationItem ? (
                <PlanPaperActualComparison
                  item={primaryExecutionReconciliationItem}
                  locale={locale}
                />
              ) : null}
              <ExecutionReconciliationEvidence
                item={primaryExecutionReconciliationItem}
              />
              <BrokerOrderQueryEvidence
                item={primaryExecutionReconciliationItem}
                query={props.brokerOrderQuery}
                loading={props.brokerOrderQueryLoading}
                error={props.brokerOrderQueryError}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function ExecutionReconciliationEvidence({
  item: primaryExecutionReconciliationItem,
}: {
  item: ExecutionReconciliationItem | undefined;
}) {
  const { locale } = usePreferences();
  const brokerTradeCostEvidence = brokerTradeCostEvidenceForItem(
    primaryExecutionReconciliationItem,
    locale,
  );
  const manualExecutionEvidence = manualExecutionEvidenceForItem(
    primaryExecutionReconciliationItem,
    locale,
  );
  const manualBrokerComparisonEvidence = manualBrokerComparisonEvidenceForItem(
    primaryExecutionReconciliationItem,
    locale,
  );
  return (
    <>
      {brokerTradeCostEvidence ? (
        <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '券商成本证据' : 'Broker cost evidence'}
            </div>
            <span className="app-chip">
              {brokerTradeCostEvidence.eventCountLabel}
            </span>
          </div>
          {brokerTradeCostEvidence.items.length ? (
            <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
              {brokerTradeCostEvidence.items.map((entry) => (
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
          {brokerTradeCostEvidence.safetyLabels.length ? (
            <div className="mt-3 flex min-w-0 flex-wrap gap-2">
              {brokerTradeCostEvidence.safetyLabels.map((label) => (
                <span className="app-chip" key={label}>
                  {label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {manualExecutionEvidence ? (
        <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '手工成交证据' : 'Manual execution evidence'}
            </div>
            <span className="app-chip">
              {manualExecutionEvidence.eventCountLabel}
            </span>
          </div>
          {manualExecutionEvidence.items.length ? (
            <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
              {manualExecutionEvidence.items.map((entry) => (
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
          {manualExecutionEvidence.safetyLabels.length ? (
            <div className="mt-3 flex min-w-0 flex-wrap gap-2">
              {manualExecutionEvidence.safetyLabels.map((label) => (
                <span className="app-chip" key={label}>
                  {label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {manualBrokerComparisonEvidence ? (
        <div
          className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3"
          data-testid="manual-broker-comparison-evidence"
        >
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh'
                ? '手工成交 / 券商证据对比'
                : 'Manual / broker evidence comparison'}
            </div>
            <span className="app-chip">
              {manualBrokerComparisonEvidence.statusLabel}
            </span>
          </div>
          <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {manualBrokerComparisonEvidence.items.map((entry) => (
              <div
                className={`min-w-0 rounded-[var(--app-radius-surface)] border px-3 py-2.5 ${
                  entry.isMismatch
                    ? 'border-[color-mix(in_srgb,var(--app-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)]'
                    : 'border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)]'
                }`}
                key={entry.label}
              >
                <div className="font-semibold text-[var(--app-text)]">
                  {entry.label}
                </div>
                <div className="app-muted mt-1 break-words text-xs">
                  {entry.manualValue}
                </div>
                <div className="app-muted mt-1 break-words text-xs">
                  {entry.brokerValue}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex min-w-0 flex-wrap gap-2">
            {manualBrokerComparisonEvidence.safetyLabels.map((label) => (
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

function BrokerOrderQueryEvidence({
  item: primaryExecutionReconciliationItem,
  query: brokerOrderQuery,
  loading: brokerOrderQueryLoading,
  error: brokerOrderQueryError,
}: {
  item: ExecutionReconciliationItem | undefined;
  query: BrokerGatewayOrderQueryResponse | undefined;
  loading: boolean;
  error: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const showBrokerOrderQuery =
    Boolean(primaryExecutionReconciliationItem?.order_id) &&
    (brokerOrderQueryLoading ||
      brokerOrderQueryError ||
      Boolean(brokerOrderQuery));
  return (
    <>
      {showBrokerOrderQuery ? (
        <div className="mt-3 border-t border-[color-mix(in_srgb,var(--app-border)_26%,transparent)] pt-3">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '只读订单查询' : 'Read-only order query'}
            </div>
            <span className="app-chip">
              {brokerOrderQuery
                ? brokerOrderQuery.status === 'query_ready'
                  ? locale === 'zh'
                    ? '查询就绪'
                    : 'Query ready'
                  : formatPublicStatus(brokerOrderQuery.status, locale)
                : brokerOrderQueryLoading
                  ? copy.states.loading
                  : locale === 'zh'
                    ? '不可用'
                    : 'Unavailable'}
            </span>
          </div>
          {brokerOrderQueryError && !brokerOrderQuery ? (
            <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
              {locale === 'zh'
                ? '只读订单查询不可用'
                : 'Read-only order query unavailable'}
            </div>
          ) : brokerOrderQuery ? (
            <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? 'OMS 订单' : 'OMS order'}
                </div>
                <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                  {String(
                    brokerOrderQuery.oms_order?.order_id ??
                      primaryExecutionReconciliationItem?.order_id ??
                      '--',
                  )}
                </div>
                <div className="app-muted mt-1 break-words text-xs leading-5">
                  {omsOrderStatusLabel(
                    String(brokerOrderQuery.oms_order?.status ?? 'unknown'),
                    locale,
                  )}
                </div>
              </div>
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '网关审计' : 'Gateway audit'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {countLabel(
                    brokerOrderQuery.gateway_event_count,
                    locale === 'zh' ? '条网关事件' : 'gateway event',
                    'gateway events',
                    locale,
                  )}
                </div>
              </div>
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '暂存成交' : 'Staged broker fills'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {countLabel(
                    brokerOrderQuery.staged_broker_fill_count,
                    locale === 'zh' ? '条暂存成交' : 'staged broker fill',
                    'staged broker fills',
                    locale,
                  )}
                </div>
              </div>
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '安全边界' : 'Safety boundary'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {brokerOrderQuery.submitted_to_broker ||
                  brokerOrderQuery.can_submit_orders
                    ? locale === 'zh'
                      ? '需要人工复核'
                      : 'Needs review'
                    : locale === 'zh'
                      ? '不提交券商订单'
                      : 'No broker submission'}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
