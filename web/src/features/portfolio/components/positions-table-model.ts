import type { MouseEvent } from 'react';

import type { Position } from '../api';

export type PositionsTableVariant = 'full' | 'dashboard' | 'history';

export type PositionsTableProps = {
  positions: Position[];
  assetClassBySymbol?: Record<string, string>;
  weightBySymbol?: Record<string, number | null | undefined>;
  variant?: PositionsTableVariant;
  onOpenPosition?: (symbol: string) => void;
};

export type PositionsTableModel = {
  positions: Position[];
  assetClassBySymbol: Record<string, string>;
  weightBySymbol: Record<string, number | null | undefined>;
  variant: PositionsTableVariant;
  onOpenPosition?: (symbol: string) => void;
  showFullColumns: boolean;
  showHistoryColumns: boolean;
};

export function buildPositionsTableModel({
  positions,
  assetClassBySymbol = {},
  weightBySymbol = {},
  variant = 'full',
  onOpenPosition,
}: PositionsTableProps): PositionsTableModel {
  return {
    positions,
    assetClassBySymbol,
    weightBySymbol,
    variant,
    onOpenPosition,
    showFullColumns: variant === 'full',
    showHistoryColumns: variant === 'history',
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
    !onOpenPosition ||
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }
  event.preventDefault();
  onOpenPosition(symbol);
}
