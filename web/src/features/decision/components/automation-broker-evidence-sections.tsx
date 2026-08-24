import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import {
  type ExecutionReconciliationRun,
  type BrokerGatewayAccountFactsResponse,
  type BrokerGatewayFillsQueryResponse,
} from '../decision-feature-boundary';
import {
  countLabel,
  stagedFillReconciliationReviewHint,
  stagedFillSymbolSummary,
} from './decision-execution-evidence-model';

export function BrokerAccountFactsSection({
  brokerAccountFacts,
  brokerAccountFactsLoading,
  brokerAccountFactsError,
}: {
  brokerAccountFacts: BrokerGatewayAccountFactsResponse | undefined;
  brokerAccountFactsLoading: boolean;
  brokerAccountFactsError: boolean;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const showAccountFacts =
    brokerAccountFactsLoading ||
    brokerAccountFactsError ||
    (brokerAccountFacts?.broker_event_count ?? 0) > 0 ||
    Boolean(brokerAccountFacts?.cash_balances.length) ||
    Boolean(brokerAccountFacts?.positions.length) ||
    Boolean(brokerAccountFacts?.fills.length);
  return (
    <>
      {showAccountFacts ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '暂存账户事实' : 'Staged account facts'}
            </div>
            <span className="app-chip">
              {brokerAccountFacts
                ? countLabel(
                    brokerAccountFacts.broker_event_count,
                    locale === 'zh'
                      ? '条券商证据事件'
                      : 'broker evidence event',
                    'broker evidence events',
                    locale,
                  )
                : brokerAccountFactsLoading
                  ? copy.states.loading
                  : locale === 'zh'
                    ? '不可用'
                    : 'Unavailable'}
            </span>
          </div>
          {brokerAccountFactsError && !brokerAccountFacts ? (
            <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
              {locale === 'zh'
                ? '暂存账户事实不可用'
                : 'Staged account facts unavailable'}
            </div>
          ) : brokerAccountFacts ? (
            <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-3">
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '资金' : 'Cash'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {countLabel(
                    brokerAccountFacts.cash_balances.length,
                    locale === 'zh' ? '条资金' : 'cash',
                    'cash',
                    locale,
                  )}
                </div>
              </div>
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '持仓' : 'Positions'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {countLabel(
                    brokerAccountFacts.positions.length,
                    locale === 'zh' ? '条持仓' : 'position',
                    'positions',
                    locale,
                  )}
                </div>
              </div>
              <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                <div className="app-muted text-xs">
                  {locale === 'zh' ? '成交' : 'Fills'}
                </div>
                <div className="mt-1 font-semibold text-[var(--app-text)]">
                  {countLabel(
                    brokerAccountFacts.fills.length,
                    locale === 'zh' ? '条成交' : 'fill',
                    'fills',
                    locale,
                  )}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export function BrokerFillsSection({
  brokerFills,
  brokerFillsLoading,
  brokerFillsError,
  reconciliationRun,
}: {
  brokerFills: BrokerGatewayFillsQueryResponse | undefined;
  brokerFillsLoading: boolean;
  brokerFillsError: boolean;
  reconciliationRun: ExecutionReconciliationRun | undefined;
}) {
  const copy = useCopy();
  const { locale } = usePreferences();
  const showBrokerFills =
    brokerFillsLoading ||
    brokerFillsError ||
    (brokerFills?.fill_count ?? 0) > 0 ||
    Boolean(brokerFills?.fills.length);
  const stagedFillReviewHint = stagedFillReconciliationReviewHint(
    brokerFills,
    reconciliationRun,
    locale,
  );
  return (
    <>
      {showBrokerFills ? (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] pt-4">
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="app-kicker text-[length:var(--app-font-size-micro)] text-[var(--app-text-tertiary)]">
              {locale === 'zh' ? '暂存成交轮询' : 'Staged fill polling'}
            </div>
            <span className="app-chip">
              {brokerFills
                ? countLabel(
                    brokerFills.fill_count,
                    locale === 'zh' ? '条暂存成交' : 'staged fill',
                    'staged fills',
                    locale,
                  )
                : brokerFillsLoading
                  ? copy.states.loading
                  : locale === 'zh'
                    ? '不可用'
                    : 'Unavailable'}
            </span>
          </div>
          {brokerFillsError && !brokerFills ? (
            <div className="mt-2 text-sm font-semibold text-[var(--app-danger)]">
              {locale === 'zh'
                ? '暂存成交查询不可用'
                : 'Staged fill query unavailable'}
            </div>
          ) : brokerFills ? (
            <>
              <div className="mt-3 grid min-w-0 gap-2 text-sm sm:grid-cols-3">
                <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '券商证据事件' : 'Broker evidence'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {countLabel(
                      brokerFills.broker_event_count,
                      locale === 'zh'
                        ? '条券商证据事件'
                        : 'broker evidence event',
                      'broker evidence events',
                      locale,
                    )}
                  </div>
                </div>
                <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '样本标的' : 'Sample symbols'}
                  </div>
                  <div className="mt-1 break-words font-semibold text-[var(--app-text)]">
                    {stagedFillSymbolSummary(brokerFills, locale)}
                  </div>
                </div>
                <div className="min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-border)_30%,transparent)] bg-[color-mix(in_srgb,var(--app-surface-0)_10%,transparent)] px-3 py-2.5">
                  <div className="app-muted text-xs">
                    {locale === 'zh' ? '安全边界' : 'Safety boundary'}
                  </div>
                  <div className="mt-1 font-semibold text-[var(--app-text)]">
                    {brokerFills.submitted_to_broker ||
                    brokerFills.can_submit_orders
                      ? locale === 'zh'
                        ? '需要人工复核'
                        : 'Needs review'
                      : locale === 'zh'
                        ? '不提交券商订单'
                        : 'No broker submission'}
                  </div>
                </div>
              </div>
              {stagedFillReviewHint ? (
                <div className="mt-3 min-w-0 rounded-[var(--app-radius-surface)] border border-[color-mix(in_srgb,var(--app-warning)_28%,transparent)] bg-[color-mix(in_srgb,var(--app-warning)_8%,transparent)] px-3 py-2.5">
                  <div className="text-sm font-semibold text-[var(--app-text)]">
                    {stagedFillReviewHint.title}
                  </div>
                  <div className="app-muted mt-1 break-words text-xs leading-5">
                    {stagedFillReviewHint.detail}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
