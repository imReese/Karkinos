import { useMemo, useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { ArrowDown, ArrowUp } from 'lucide-react';

import { formatAssetClassLabel } from '../../../shared/asset-class';
import { useCopy } from '../../../shared/i18n/context';
import { usePreferences } from '../../../shared/preferences/context';
import { SectionHeader, WorkbenchSelect } from '../../../shared/ui/workbench';
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

export type OverviewHoldingSortKey =
  | 'market_value'
  | 'today_change_pct'
  | 'today_change'
  | 'unrealized_pnl'
  | 'weight';

function resolvePositionSortValue(
  position: PortfolioSnapshot['positions'][number],
  sortBy: OverviewHoldingSortKey,
  weightBySymbol?: Record<string, number>,
): number {
  switch (sortBy) {
    case 'market_value': {
      const val = position.market_value ?? position.indicative_market_value;
      return typeof val === 'number' && Number.isFinite(val)
        ? val
        : Number.NEGATIVE_INFINITY;
    }
    case 'today_change_pct': {
      if (
        position.today_change_pct != null &&
        Number.isFinite(position.today_change_pct)
      ) {
        return position.today_change_pct;
      }
      if (
        position.today_change != null &&
        Number.isFinite(position.today_change) &&
        position.market_value != null &&
        Number.isFinite(position.market_value)
      ) {
        const priorValue = position.market_value - position.today_change;
        if (priorValue > 0) {
          return (position.today_change / priorValue) * 100;
        }
      }
      if (
        position.latest_price != null &&
        position.baseline_price != null &&
        position.baseline_price > 0
      ) {
        return (
          ((position.latest_price - position.baseline_price) /
            position.baseline_price) *
          100
        );
      }
      return Number.NEGATIVE_INFINITY;
    }
    case 'today_change': {
      if (
        position.today_change != null &&
        Number.isFinite(position.today_change)
      ) {
        return position.today_change;
      }
      if (
        position.latest_price != null &&
        position.baseline_price != null &&
        position.quantity > 0
      ) {
        return (
          (position.latest_price - position.baseline_price) * position.quantity
        );
      }
      return Number.NEGATIVE_INFINITY;
    }
    case 'unrealized_pnl': {
      const val = position.unrealized_pnl;
      return typeof val === 'number' && Number.isFinite(val)
        ? val
        : Number.NEGATIVE_INFINITY;
    }
    case 'weight': {
      const val = weightBySymbol?.[position.symbol];
      return typeof val === 'number' && Number.isFinite(val)
        ? val
        : Number.NEGATIVE_INFINITY;
    }
    default:
      return Number.NEGATIVE_INFINITY;
  }
}

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
  const [sortBy, setSortBy] = useState<OverviewHoldingSortKey>('market_value');
  const [sortDirection, setSortDirection] = useState<'desc' | 'asc'>('desc');

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

  const filteredPositions = useMemo(() => {
    const list =
      activeCategory === 'all'
        ? [...positions]
        : positions.filter((pos) => {
            const raw = resolvePositionAssetClass(pos, assetClassBySymbol);
            return (raw || 'unknown').trim().toLowerCase() === activeCategory;
          });

    return list.sort((left, right) => {
      const leftVal = resolvePositionSortValue(left, sortBy, weightBySymbol);
      const rightVal = resolvePositionSortValue(right, sortBy, weightBySymbol);
      const leftMissing = !Number.isFinite(leftVal);
      const rightMissing = !Number.isFinite(rightVal);
      if (leftMissing && rightMissing) {
        return left.symbol.localeCompare(right.symbol);
      }
      if (leftMissing) return 1;
      if (rightMissing) return -1;
      if (sortDirection === 'desc') {
        if (rightVal !== leftVal) return rightVal - leftVal;
      } else {
        if (leftVal !== rightVal) return leftVal - rightVal;
      }
      return left.symbol.localeCompare(right.symbol);
    });
  }, [
    positions,
    activeCategory,
    assetClassBySymbol,
    sortBy,
    sortDirection,
    weightBySymbol,
  ]);

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
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div
            role="group"
            aria-label={labels.assetClassFilter}
            data-testid="overview-holdings-category-filter"
            className="app-inline-segmented flex flex-wrap"
          >
            <button
              type="button"
              aria-pressed={activeCategory === 'all'}
              onClick={() => setSelectedAssetClass('all')}
              className={`app-inline-segmented-btn ${
                activeCategory === 'all'
                  ? 'app-inline-segmented-btn-active'
                  : ''
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
                {formatAssetClassLabel(ac, copy.common)} ({assetClassCounts[ac]}
                )
              </button>
            ))}
          </div>

          <div
            data-testid="overview-holdings-sort-control"
            className="flex items-center gap-1.5"
          >
            <span className="app-type-micro font-medium text-[var(--app-text-tertiary)]">
              {labels.sortBy}:
            </span>
            <WorkbenchSelect
              aria-label={labels.sortBy}
              value={sortBy}
              onChange={(value) => setSortBy(value as OverviewHoldingSortKey)}
              options={[
                { value: 'market_value', label: labels.sortMarketValue },
                { value: 'today_change_pct', label: labels.sortTodayPct },
                { value: 'today_change', label: labels.sortTodayPnl },
                { value: 'unrealized_pnl', label: labels.sortUnrealizedPnl },
                { value: 'weight', label: labels.sortWeight },
              ]}
              className="text-xs"
            />
            <button
              type="button"
              onClick={() =>
                setSortDirection((prev) => (prev === 'desc' ? 'asc' : 'desc'))
              }
              className="inline-flex h-8 items-center gap-1 rounded border border-[var(--app-divider)] bg-[var(--app-surface-overlay)] px-2 text-xs font-medium text-[var(--app-text-secondary)] transition-all hover:bg-[var(--app-surface)] hover:text-[var(--app-text)] active:scale-[0.97]"
              aria-label={`${labels.sortBy}: ${
                sortDirection === 'desc' ? labels.desc : labels.asc
              }`}
              title={sortDirection === 'desc' ? labels.desc : labels.asc}
            >
              {sortDirection === 'desc' ? (
                <ArrowDown size={12} strokeWidth={2} aria-hidden="true" />
              ) : (
                <ArrowUp size={12} strokeWidth={2} aria-hidden="true" />
              )}
              <span>{sortDirection === 'desc' ? labels.desc : labels.asc}</span>
            </button>
          </div>
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
