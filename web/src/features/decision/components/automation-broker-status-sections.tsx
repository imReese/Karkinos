import { usePreferences } from '../../../shared/preferences/context';
import { formatPublicCode } from '../../../shared/public-labels';
import {
  type BrokerConnectorHealthResponse,
  type BrokerGatewayStatusResponse,
} from '../decision-feature-boundary';
import {
  brokerConnectorStatusLabel,
  brokerGatewayBlockedReason,
  brokerGatewayDisplayName,
  brokerGatewayStatusLabel,
  controlledBridgeListSummary,
  controlledBridgePolicyStatusLabel,
  controlledBridgeTokenList,
} from './decision-automation-model';
import {
  brokerConnectorCapabilityLabel,
  brokerGatewayCapabilityLabel,
} from './decision-execution-model';

export function BrokerGatewayStatusSection({
  brokerGatewayStatus,
  brokerGatewayLoading,
  brokerGatewayError,
}: {
  brokerGatewayStatus: BrokerGatewayStatusResponse | undefined;
  brokerGatewayLoading: boolean;
  brokerGatewayError: boolean;
}) {
  const { locale } = usePreferences();
  const gatewayControlsUnavailable =
    brokerGatewayStatus?.kill_switch_status === 'unavailable' ||
    brokerGatewayStatus?.kill_switch_evidence_available === false;
  const gatewayStatusTitle =
    brokerGatewayError && !brokerGatewayStatus
      ? locale === 'zh'
        ? '网关状态不可用'
        : 'Gateway status unavailable'
      : brokerGatewayLoading && !brokerGatewayStatus
        ? locale === 'zh'
          ? '网关状态加载中'
          : 'Gateway status loading'
        : gatewayControlsUnavailable
          ? locale === 'zh'
            ? '交易控制状态不可用'
            : 'Trading controls unavailable'
          : brokerGatewayStatus?.kill_switch_enabled
            ? locale === 'zh'
              ? '熔断开关已开启'
              : 'Kill switch active'
            : locale === 'zh'
              ? '熔断开关关闭'
              : 'Kill switch clear';
  const gatewayStatusDetail = gatewayControlsUnavailable
    ? locale === 'zh'
      ? '缺少可验证的 Kill Switch 快照；恢复控制状态并重新复核前，人工工单保持阻断。'
      : 'No verifiable Kill Switch snapshot is available. Manual tickets stay blocked until control state is restored and reviewed.'
    : (brokerGatewayStatus?.kill_switch_reason ??
      brokerGatewayStatus?.gateways.find((gateway) => gateway.blocked_reason)
        ?.blocked_reason ??
      null);
  return (
    <>
      {brokerGatewayStatus || brokerGatewayLoading || brokerGatewayError ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '券商网关状态' : 'Broker gateway status'}
            </div>
            <span
              className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
                gatewayControlsUnavailable ||
                brokerGatewayStatus?.kill_switch_enabled ||
                brokerGatewayError
                  ? 'border-[color-mix(in_srgb,var(--app-danger)_40%,transparent)] text-[var(--app-danger)]'
                  : 'border-[color-mix(in_srgb,var(--app-success)_35%,transparent)] text-[var(--app-success)]'
              }`}
            >
              {gatewayStatusTitle}
            </span>
          </div>
          {gatewayStatusDetail ? (
            <div className="app-muted mt-2 break-words text-sm leading-6">
              {gatewayStatusDetail}
            </div>
          ) : null}
          {brokerGatewayStatus?.gateways.length ? (
            <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
              {brokerGatewayStatus.gateways.map((gateway) => (
                <div
                  className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                  key={gateway.gateway_id}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0 text-sm font-semibold text-[var(--app-text)]">
                      {brokerGatewayDisplayName(gateway, locale)}
                    </div>
                    <span className="app-chip">
                      {brokerGatewayStatusLabel(gateway.status, locale)}
                    </span>
                  </div>
                  <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'preview',
                        gateway.can_preview_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'export',
                        gateway.can_export_tickets,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'dry_run',
                        gateway.can_dry_run_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'query_orders',
                        gateway.can_query_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'query_fills',
                        gateway.can_query_fills,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'read_positions',
                        gateway.can_query_positions,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'read_cash',
                        gateway.can_query_cash,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'submit',
                        gateway.can_submit_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerGatewayCapabilityLabel(
                        'cancel',
                        gateway.can_cancel_orders,
                        locale,
                      )}
                    </span>
                  </div>
                  {brokerGatewayBlockedReason(gateway, locale) ? (
                    <div className="app-muted mt-2 break-words text-xs leading-5">
                      {brokerGatewayBlockedReason(gateway, locale)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          {brokerGatewayStatus?.controlled_bridge_policy ? (
            <div className="mt-3 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[var(--app-text)]">
                    {locale === 'zh'
                      ? '受控桥接策略'
                      : 'Controlled bridge policy'}
                  </div>
                  <div className="app-muted mt-1 break-words text-xs leading-5">
                    {brokerGatewayStatus.controlled_bridge_policy.policy_id}
                  </div>
                </div>
                <span className="app-chip">
                  {controlledBridgePolicyStatusLabel(
                    brokerGatewayStatus.controlled_bridge_policy.status,
                    locale,
                  )}
                </span>
              </div>
              <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                <span>
                  {controlledBridgeListSummary(
                    'connector',
                    brokerGatewayStatus.controlled_bridge_policy
                      .allowed_connector_ids,
                    locale,
                  )}
                </span>
                <span>
                  {controlledBridgeListSummary(
                    'account',
                    brokerGatewayStatus.controlled_bridge_policy
                      .allowed_account_aliases,
                    locale,
                  )}
                </span>
                <span>
                  {controlledBridgeListSummary(
                    'strategy',
                    brokerGatewayStatus.controlled_bridge_policy
                      .allowed_strategy_ids,
                    locale,
                  )}
                </span>
                <span>
                  {controlledBridgeListSummary(
                    'symbol',
                    brokerGatewayStatus.controlled_bridge_policy
                      .allowed_symbols,
                    locale,
                  )}
                </span>
              </div>
              <div className="app-muted mt-2 break-words text-xs leading-5">
                {locale === 'zh' ? '必要门禁' : 'Required gates'}:{' '}
                {controlledBridgeTokenList(
                  brokerGatewayStatus.controlled_bridge_policy.required_gates,
                  locale,
                )}
              </div>
              {brokerGatewayStatus.controlled_bridge_policy.blockers?.length ? (
                <div className="app-muted mt-1 break-words text-xs leading-5">
                  {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
                  {controlledBridgeTokenList(
                    brokerGatewayStatus.controlled_bridge_policy.blockers,
                    locale,
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

export function BrokerConnectorHealthSection({
  brokerConnectorHealth,
  brokerConnectorHealthLoading,
  brokerConnectorHealthError,
}: {
  brokerConnectorHealth: BrokerConnectorHealthResponse | undefined;
  brokerConnectorHealthLoading: boolean;
  brokerConnectorHealthError: boolean;
}) {
  const { locale } = usePreferences();
  const showConnectorHealth =
    brokerConnectorHealthLoading ||
    brokerConnectorHealthError ||
    Boolean(brokerConnectorHealth?.connectors.length);
  return (
    <>
      {showConnectorHealth ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
            {locale === 'zh'
              ? '持久化券商生命周期证据'
              : 'Persisted broker lifecycle evidence'}
          </div>
          {brokerConnectorHealthLoading && !brokerConnectorHealth ? (
            <div className="app-muted mt-2 text-sm">
              {locale === 'zh'
                ? '连接器状态加载中'
                : 'Connector status loading'}
            </div>
          ) : brokerConnectorHealthError && !brokerConnectorHealth ? (
            <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
              {locale === 'zh'
                ? '连接器状态不可用'
                : 'Connector status unavailable'}
            </div>
          ) : brokerConnectorHealth?.connectors.length ? (
            <div className="mt-3 grid min-w-0 gap-2 md:grid-cols-2">
              {brokerConnectorHealth.connectors.map((connector) => (
                <div
                  className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5"
                  key={connector.connector_id}
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-[var(--app-text)]">
                        {connector.connector_id}
                      </div>
                      {connector.account_aliases?.length ? (
                        <div className="app-muted mt-0.5 break-words text-xs">
                          {connector.account_aliases.join(', ')}
                        </div>
                      ) : null}
                    </div>
                    <span className="app-chip">
                      {brokerConnectorStatusLabel(connector.status, locale)}
                    </span>
                  </div>
                  <div className="mt-2 grid min-w-0 gap-1 text-xs text-[var(--app-soft)] sm:grid-cols-2">
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'read_account',
                        connector.capabilities?.can_read_account,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'read_cash',
                        connector.capabilities?.can_read_cash,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'read_positions',
                        connector.capabilities?.can_read_positions,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'read_orders',
                        connector.capabilities?.can_read_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'read_fills',
                        connector.capabilities?.can_read_fills,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'preview_orders',
                        connector.capabilities?.can_preview_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'export_tickets',
                        connector.capabilities?.can_export_tickets,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'dry_run_orders',
                        connector.capabilities?.can_dry_run_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'submit',
                        connector.capabilities?.can_submit_orders,
                        locale,
                      )}
                    </span>
                    <span>
                      {brokerConnectorCapabilityLabel(
                        'cancel',
                        connector.capabilities?.can_cancel_orders,
                        locale,
                      )}
                    </span>
                  </div>
                  {connector.message ? (
                    <div className="app-muted mt-2 break-words text-xs leading-5">
                      {connector.message}
                    </div>
                  ) : null}
                  <div className="app-muted mt-2 break-words text-xs leading-5">
                    {connector.provider_contact_performed
                      ? locale === 'zh'
                        ? '阻断：读取期间联系了外部服务'
                        : 'Blocked: provider contact occurred during read'
                      : locale === 'zh'
                        ? '仅持久化事实 · 未联系外部服务 · 无提交/撤单权限'
                        : 'Persisted facts only · no provider contact · no submit/cancel authority'}
                  </div>
                  {connector.blockers?.length ? (
                    <div className="app-muted mt-1 break-words text-xs leading-5">
                      {locale === 'zh' ? '阻断项' : 'Blockers'}:{' '}
                      {connector.blockers
                        .map((item) => formatPublicCode(item, locale))
                        .join(' · ')}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
