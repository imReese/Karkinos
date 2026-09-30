import { useMemo, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader } from '../../../shared/ui/workbench';
import { overviewPresentation } from '../model/overview-presentation';
import {
  PositionsTable,
  resolvePositionAssetClass,
  type PortfolioSnapshot,
} from '../overview-feature-boundary';
import { OverviewStatusCard } from './overview-status-card';

const PREFERRED_ASSET_CLASS_ORDER = [
  'stock',
  'fund',
  'etf',
  'bond',
  'gold',
  'cash',
];

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
  const [selectedAssetClass, setSelectedAssetClass] = useState<string>('all');

  const assetClassCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const pos of positions) {
      const raw = resolvePositionAssetClass(pos, assetClassBySymbol);
      const ac = (raw || 'unknown').trim().toLowerCase();
      counts[ac] = (counts[ac] ?? 0) + 1;
    }
    return counts;
  }, [positions, assetClassBySymbol]);

  const availableAssetClasses = useMemo(() => {
    const classes = Object.keys(assetClassCounts);
    return classes.sort((a, b) => {
      const idxA = PREFERRED_ASSET_CLASS_ORDER.indexOf(a);
      const idxB = PREFERRED_ASSET_CLASS_ORDER.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.localeCompare(b);
    });
  }, [assetClassCounts]);

  const activeCategory =
    selectedAssetClass === 'all' ||
    availableAssetClasses.includes(selectedAssetClass)
      ? selectedAssetClass
      : 'all';

  const sortedPositions = useMemo(() => {
    return [...positions].sort(
      (left, right) =>
        (right.market_value ??
          right.indicative_market_value ??
          Number.NEGATIVE_INFINITY) -
        (left.market_value ??
          left.indicative_market_value ??
          Number.NEGATIVE_INFINITY),
    );
  }, [positions]);

  const filteredPositions = useMemo(() => {
    if (activeCategory === 'all') {
      return sortedPositions;
    }
    return sortedPositions.filter((pos) => {
      const raw = resolvePositionAssetClass(pos, assetClassBySymbol);
      return (raw || 'unknown').trim().toLowerCase() === activeCategory;
    });
  }, [sortedPositions, activeCategory, assetClassBySymbol]);

  return (
    <section
      className={('min-w-0 py-4 ' + (className ?? '')).trim()}
      data-testid="overview-holdings-section"
    >
      <SectionHeader
        title={labels.holdings}
        meta={
          activeCategory === 'all'
            ? positions.length
            : `${filteredPositions.length} / ${positions.length}`
        }
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

      {positions.length > 0 ? (
        <div
          role="group"
          aria-label={labels.assetClassFilter}
          data-testid="overview-holdings-category-filter"
          className="app-inline-segmented mb-3 flex flex-wrap"
        >
          <button
            type="button"
            aria-pressed={activeCategory === 'all'}
            onClick={() => setSelectedAssetClass('all')}
            className={`app-inline-segmented-btn ${
              activeCategory === 'all' ? 'app-inline-segmented-btn-active' : ''
            }`}
          >
            {labels.allAssetClasses} ({positions.length})
          </button>
          {availableAssetClasses.map((ac) => (
            <button
              key={ac}
              type="button"
              aria-pressed={activeCategory === ac}
              onClick={() => setSelectedAssetClass(ac)}
              className={`app-inline-segmented-btn ${
                activeCategory === ac ? 'app-inline-segmented-btn-active' : ''
              }`}
            >
              {formatAssetClassLabel(ac, copy.common)} ({assetClassCounts[ac]})
            </button>
          ))}
        </div>
      ) : null}

      {positions.length === 0 ? (
        <OverviewStatusCard
          title={copy.states.empty}
          detail={copy.portfolio.positionsEmpty}
        />
      ) : filteredPositions.length === 0 ? (
        <OverviewStatusCard
          title={copy.states.empty}
          detail={labels.noFilteredHoldings}
        />
      ) : (
        <PositionsTable
          positions={filteredPositions}
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
