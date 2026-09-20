import { useNavigate } from '@tanstack/react-router';

import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
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
  const sortedPositions = [...positions].sort(
    (left, right) =>
      (right.market_value ?? Number.NEGATIVE_INFINITY) -
      (left.market_value ?? Number.NEGATIVE_INFINITY),
  );

  return (
    <section
      className={('min-w-0 py-4 ' + (className ?? '')).trim()}
      data-testid="overview-holdings-section"
    >
      <SectionHeader
        title={labels.holdings}
        meta={positions.length}
        actions={
          <a
            href="/portfolio"
            className="app-type-compact font-semibold text-[var(--app-accent)] hover:underline"
          >
            {labels.viewPortfolio}
          </a>
        }
        className="mb-2"
      />
      {positions.length === 0 ? (
        <OverviewStatusCard
          title={copy.states.empty}
          detail={copy.portfolio.positionsEmpty}
        />
      ) : (
        <PositionsTable
          positions={sortedPositions}
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
