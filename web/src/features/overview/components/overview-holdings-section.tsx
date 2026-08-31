import { useNavigate } from '@tanstack/react-router';

import { useCopy } from '../../../shared/i18n/context';
import {
  PositionsTable,
  type PortfolioSnapshot,
} from '../overview-feature-boundary';
import { OverviewStatusCard } from './overview-status-card';

export function OverviewHoldingsSection({
  positions,
  assetClassBySymbol,
  className,
}: {
  positions: PortfolioSnapshot['positions'];
  assetClassBySymbol: Record<string, string>;
  className?: string;
}) {
  const copy = useCopy();
  const navigate = useNavigate();

  return (
    <section
      className={`min-w-0 ${className ?? ''}`.trim()}
      data-testid="overview-holdings-section"
    >
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="app-type-section-title text-[var(--app-text)]">
            {copy.overview.dashboard.positionsPanel}
          </h2>
          <p className="mt-1 text-xs text-[var(--app-text-secondary)]">
            {copy.overview.dashboard.positionsDetail}
          </p>
        </div>
        <span className="text-xs tabular-nums text-[var(--app-text-tertiary)]">
          {positions.length} {copy.overview.risk.positions}
        </span>
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
