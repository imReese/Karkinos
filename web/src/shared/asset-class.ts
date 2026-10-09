type AssetClassLabels = {
  assetClassStock: string;
  assetClassEtf: string;
  assetClassFund: string;
  assetClassGold: string;
  assetClassBond: string;
  assetClassCash: string;
  assetClassIndex?: string;
  assetClassOther?: string;
  assetClassUnknown?: string;
};

export function formatAssetClassLabel(
  assetClass: string | null | undefined,
  labels: AssetClassLabels,
) {
  const normalized = (assetClass ?? '').trim().toLowerCase().replace(/-/g, '_');
  if (normalized === 'stock') return labels.assetClassStock;
  if (normalized === 'etf') return labels.assetClassEtf;
  if (
    normalized === 'fund' ||
    normalized === 'open_end_fund' ||
    normalized === 'mutual_fund' ||
    normalized === 'money_market_fund' ||
    normalized === 'closed_end_fund'
  ) {
    return labels.assetClassFund;
  }
  if (normalized === 'gold') return labels.assetClassGold;
  if (normalized === 'bond' || normalized === 'convertible_bond') {
    return labels.assetClassBond;
  }
  if (normalized === 'cash') return labels.assetClassCash;
  if (normalized === 'index') {
    return (
      labels.assetClassIndex ??
      (labels.assetClassStock === '股票' ? '指数' : 'Index')
    );
  }
  if (normalized === 'other') {
    return (
      labels.assetClassOther ??
      (labels.assetClassStock === '股票' ? '其他' : 'Other')
    );
  }
  if (normalized === 'unknown') {
    return (
      labels.assetClassUnknown ??
      (labels.assetClassStock === '股票' ? '未知' : 'Unknown')
    );
  }
  return assetClass || '--';
}
