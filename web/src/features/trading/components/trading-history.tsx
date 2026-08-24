import { ChevronDown } from 'lucide-react';

import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { EvidenceState } from '../../../shared/ui/workbench';
import { AuditRow } from './order-queue';
import type { TradingPageController } from './use-trading-page-controller';

export function TradingHistory({
  controller,
}: {
  controller: TradingPageController;
}) {
  const labels = useCopy().trading.page;
  const { locale } = usePreferences();
  const { completedOrders, instrumentNames } = controller;

  return (
    <details
      className="group app-workbench-section min-w-0"
      data-testid="trading-history-disclosure"
    >
      <summary className="flex min-h-16 cursor-pointer list-none items-center justify-between gap-4 px-1 py-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] sm:px-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-product-mark block">{labels.historyKicker}</span>
          <span className="app-card-title mt-1.5 block">
            {labels.historyTitle}
          </span>
          <span className="app-muted mt-1 block text-sm">
            {locale === 'zh'
              ? `${completedOrders.length} 条已完成决策`
              : `${completedOrders.length} completed decision${completedOrders.length === 1 ? '' : 's'}`}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs font-semibold text-[var(--app-text-secondary)]">
          <span>{labels.expandOnDemand}</span>
          <ChevronDown
            aria-hidden="true"
            className="size-4 transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] motion-reduce:transition-none group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="border-t border-[var(--app-divider)] px-1 py-4 sm:px-3">
        <p className="app-muted text-sm">{labels.historyDetail}</p>
        {completedOrders.length === 0 ? (
          <EvidenceState
            className="mt-4"
            kind="empty"
            statusLabel={labels.historyKicker}
            title={labels.noHistory}
            description={labels.historyDetail}
          />
        ) : (
          <div className="mt-4 grid divide-y divide-[var(--app-divider)]">
            {completedOrders.slice(0, 8).map((order) => (
              <AuditRow
                key={order.order_id}
                order={order}
                instrumentNames={instrumentNames}
              />
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
