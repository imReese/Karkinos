import { useNavigate } from '@tanstack/react-router';

import { usePreferences } from '../../../shared/preferences/context';
import { overviewPresentation } from '../model/overview-presentation';
import { useCopy } from '../../../shared/i18n/context';
import {
  PositionsTable,
  type PortfolioSnapshot,
} from '../overview-feature-boundary';
import { OverviewStatusCard } from './overview-status-card';

export function OverviewHoldingsSection({
  positions,
  assetClassBySymbol,
  weightBySymbol,
  className,
}: {
  positions: PortfolioSnapshot['positions'];
  assetClassBySymbol: Record<string, string>;
  weightBySymbol?: Record<string, number>;
  className?: string;
}) {
  const copy = useCopy();
  const navigate = useNavigate();
  const { locale } = usePreferences();
  const labels = overviewPresentation[locale];

  return (
    <section
      className={`min-w-0 border-t border-[var(--app-divider)] pt-4 ${className ?? ''}`.trim()}
      data-testid="overview-holdings-section"
    >
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[var(--app-text)]">
            {labels.holdings}{' '}
            <span className="ml-2 font-normal tabular-nums text-[var(--app-text-tertiary)]">
              {positions.length}
            </span>
          </h2>
        </div>
        <a
          href="/portfolio"
          className="text-xs text-[var(--app-accent)] hover:underline"
        >
          {labels.viewPortfolio}
        </a>
      </div>
      {positions.length === 0 ? (
        <OverviewStatusCard
          title={copy.states.empty}
          detail={copy.portfolio.positionsEmpty}
        />
      ) : (
        <PositionsTable
          positions={positions}
          assetClassBySymbol={assetClassBySymbol}
          weightBySymbol={weightBySymbol}
          variant="dashboard"
          onOpenPosition={(symbol) => {
            void navigate({
              to: '/portfolio/$symbol',
              params: { symbol },
            });
          }}
        />
      )}
    </section>
  );
}
