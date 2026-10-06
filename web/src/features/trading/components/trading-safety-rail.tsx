import { ChevronDown } from 'lucide-react';
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
        className="group min-w-0 border-y border-[var(--app-divider)] sm:col-span-2"
        data-testid="trading-broker-boundary-disclosure"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 py-2.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-[var(--app-text)]">
              {labels.brokerBoundaryEvidence}
            </span>
          </span>
          <span className="flex shrink-0 items-center gap-1.5 text-xs text-[var(--app-text-tertiary)]">
            <span className="sr-only">{labels.expandOnDemand}</span>
            <ChevronDown
              aria-hidden="true"
              className="size-4 shrink-0 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
            />
          </span>
        </summary>
        <div className="space-y-5 py-4">
          <div className="rounded-[var(--app-radius-control)] border border-[var(--app-divider)] bg-[var(--app-surface)] p-3 text-xs leading-relaxed text-[var(--app-text-secondary)]">
            <span className="font-semibold text-[var(--app-text)]">
              {locale === 'zh' ? '只读审计凭证下钻：' : 'Audit Drill-down: '}
            </span>
            {labels.brokerBoundaryEvidenceDetail}
          </div>
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
