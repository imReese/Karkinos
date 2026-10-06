import { ChevronDown } from 'lucide-react';

import type { RiskPageController } from '../model/use-risk-page-controller';
import { KillSwitchPanel } from '../risk-feature-boundary';

export function RiskControlledActionDisclosure({
  controller,
}: {
  controller: RiskPageController;
}) {
  const { locale } = controller;
  return (
    <details
      className="group min-w-0 border-y border-[var(--app-divider)]"
      data-testid="risk-controlled-action-disclosure"
    >
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--app-focus-ring)] [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="app-type-section-title block text-[var(--app-text)]">
            {locale === 'zh'
              ? '受控操作与交易熔断'
              : 'Controlled action & kill switches'}
          </span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 text-[var(--app-text-tertiary)] transition-transform duration-[var(--app-motion-fast)] ease-[var(--app-ease-standard)] group-open:rotate-180 motion-reduce:transition-none"
        />
      </summary>
      <div
        className="border-t border-[var(--app-divider)] py-3"
        data-testid="risk-trading-control-grid"
      >
        <KillSwitchPanel />
      </div>
    </details>
  );
}
