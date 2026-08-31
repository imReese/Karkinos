import { HoldingDetailController } from './holding-detail-controller';

/** Stable route-facing facade for the holding evidence workbench. */
export function HoldingDetailPage({ symbol }: { symbol: string }) {
  return <HoldingDetailController symbol={symbol} />;
}
