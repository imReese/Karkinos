type AssetClassLabels = {
  assetClassStock: string;
  assetClassEtf: string;
  assetClassFund: string;
  assetClassGold: string;
  assetClassBond: string;
  assetClassCash: string;
};

export function formatAssetClassLabel(
  assetClass: string | null | undefined,
  labels: AssetClassLabels,
) {
  const normalized = (assetClass ?? '').trim().toLowerCase();
  if (normalized === 'stock') return labels.assetClassStock;
  if (normalized === 'etf') return labels.assetClassEtf;
  if (normalized === 'fund') return labels.assetClassFund;
  if (normalized === 'gold') return labels.assetClassGold;
  if (normalized === 'bond') return labels.assetClassBond;
  if (normalized === 'cash') return labels.assetClassCash;
  return assetClass || '--';
}
