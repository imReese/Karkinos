import { useCopy } from '../../../shared/i18n/context';
import { type Locale } from '../../../shared/preferences/context';
import { MetricStrip } from '../../../shared/ui/workbench';
import {
  ControlledBrokerWriteReleaseOperatorPanel,
  CurrentPerOrderDossierOperatorPanel,
  SignedBrokerAdapterReleaseReviewOperatorPanel,
} from '../operations-boundary';
import { AutomaticTradingPanel } from './automatic-trading-panel';
import { BrokerAdapterReadinessPanel } from './broker-readiness-panel';
import { KillSwitchPanel } from './kill-switch-panel';
import type { TradingPageController } from './use-trading-page-controller';

export function TradingSafetyRail({
  controller,
  locale,
}: {
  controller: TradingPageController;
  locale: Locale;
}) {
  const labels = useCopy().trading.page;
  const {
    counts,
    brokerAdapterReadiness,
    operationsToday,
    brokerSoakPromotion,
  } = controller;

  return (
    <aside
      className="order-2 grid min-w-0 content-start gap-4 sm:grid-cols-2"
      data-testid="trading-safety-rail"
    >
      <MetricStrip
        ariaLabel={labels.ordersTitle}
        className="sm:grid-flow-row sm:auto-cols-auto sm:grid-cols-3"
        items={[
          {
            id: 'confirmed',
            label: labels.confirmed,
            value: String(counts.confirmed),
          },
          {
            id: 'rejected',
            label: labels.rejected,
            value: String(counts.rejected),
          },
          {
            id: 'canceled',
            label: labels.canceled,
            value: String(counts.canceled),
          },
        ]}
      />
      <KillSwitchPanel />
      <AutomaticTradingPanel />

      <details
        className="min-w-0 border-y border-[var(--app-divider)] sm:col-span-2"
        data-testid="trading-broker-boundary-disclosure"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)]">
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-[var(--app-text)]">
              {labels.brokerBoundaryEvidence}
            </span>
            <span className="mt-0.5 block text-xs font-normal text-[var(--app-text-secondary)]">
              {labels.brokerBoundaryEvidenceDetail}
            </span>
          </span>
          <span className="shrink-0 text-xs text-[var(--app-text-secondary)]">
            {labels.expandOnDemand}
          </span>
        </summary>
        <div className="space-y-5 py-4">
          <BrokerAdapterReadinessPanel
            readiness={brokerAdapterReadiness}
            loading={operationsToday.isLoading}
            error={operationsToday.isError}
            soak={brokerSoakPromotion.data ?? null}
            soakLoading={brokerSoakPromotion.isLoading}
            soakError={brokerSoakPromotion.isError}
          />

          <SignedBrokerAdapterReleaseReviewOperatorPanel locale={locale} />

          <ControlledBrokerWriteReleaseOperatorPanel
            locale={locale}
            readiness={brokerAdapterReadiness}
            soak={brokerSoakPromotion.data ?? null}
          />

          <CurrentPerOrderDossierOperatorPanel locale={locale} />
        </div>
      </details>
    </aside>
  );
}
