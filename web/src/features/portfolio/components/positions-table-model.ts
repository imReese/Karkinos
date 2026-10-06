import type { MouseEvent } from 'react';
import { handleClientNavigation } from '../../../shared/routing/client-navigate';

import type { Position } from '../api';

export type PositionsTableVariant = 'full' | 'dashboard' | 'history';

export type PositionsTableProps = {
  positions: Position[];
  assetClassBySymbol?: Record<string, string>;
  weightBySymbol?: Record<string, number | null | undefined>;
  variant?: PositionsTableVariant;
  onOpenPosition?: (symbol: string) => void;
  sortKey?: string;
  sortDirection?: 'asc' | 'desc';
  onSort?: (key: string | undefined, direction?: 'asc' | 'desc') => void;
};

export type PositionsTableModel = {
  positions: Position[];
  assetClassBySymbol: Record<string, string>;
  weightBySymbol: Record<string, number | null | undefined>;
  variant: PositionsTableVariant;
  onOpenPosition?: (symbol: string) => void;
  showFullColumns: boolean;
  showHistoryColumns: boolean;
  sortKey?: string;
  sortDirection?: 'asc' | 'desc';
  onSort?: (key: string | undefined, direction?: 'asc' | 'desc') => void;
};

export function buildPositionsTableModel({
  positions,
  assetClassBySymbol = {},
  weightBySymbol = {},
  variant = 'full',
  onOpenPosition,
  sortKey,
  sortDirection,
  onSort,
}: PositionsTableProps): PositionsTableModel {
  return {
    positions,
    assetClassBySymbol,
    weightBySymbol,
    variant,
    onOpenPosition,
    showFullColumns: variant === 'full',
    showHistoryColumns: variant === 'history',
    sortKey,
    sortDirection,
    onSort,
  };
}

export function holdingDetailHref(symbol: string) {
  return `/portfolio/${encodeURIComponent(symbol)}`;
}

export function resolvePositionName(position: Position) {
  return position.display_name || position.name || position.symbol;
}

export function resolvePositionTone(value: number | null | undefined) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) {
    return 'text-[var(--app-text)]';
  }
  return value > 0
    ? 'text-[var(--app-pnl-positive)]'
    : 'text-[var(--app-pnl-negative)]';
}

export function resolvePositionAssetClass(
  position: Position,
  assetClassBySymbol: Record<string, string>,
) {
  return (
    position.asset_class ?? assetClassBySymbol[position.symbol] ?? 'unknown'
  );
}

export function handlePositionLinkClick(
  event: MouseEvent<HTMLAnchorElement>,
  symbol: string,
  onOpenPosition?: (symbol: string) => void,
) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  if (onOpenPosition) {
    event.preventDefault();
    onOpenPosition(symbol);
    return;
  }
  handleClientNavigation(event, holdingDetailHref(symbol));
}
