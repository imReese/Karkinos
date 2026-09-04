import type {
  CurrentHoldingMarketEvidenceLane,
  CurrentHoldingMarketEvidenceReview,
} from './contracts';

function uniqueSymbols(symbols: readonly string[]) {
  return [...new Set(symbols.filter(Boolean))];
}

export function resolveMarketEvidenceRefreshTargets(
  report?: CurrentHoldingMarketEvidenceReview | null,
) {
  if (!report) {
    return { quoteSymbols: [], confirmedFundNavSymbols: [] };
  }

  const legacyConfirmedFundNavSymbols = report.items
    .filter(
      (item) =>
        item.asset_class === 'fund' &&
        item.review_reason === 'confirmed_nav_missing' &&
        item.explicit_refresh_eligible,
    )
    .map((item) => item.symbol);
  const confirmedFundNavSymbols = uniqueSymbols(
    report.confirmed_fund_nav_refresh_symbols ?? legacyConfirmedFundNavSymbols,
  );
  const confirmedFundNavSymbolSet = new Set(confirmedFundNavSymbols);
  const quoteSymbols = uniqueSymbols(
    report.quote_refresh_symbols ??
      report.refreshable_symbols.filter(
        (symbol) => !confirmedFundNavSymbolSet.has(symbol),
      ),
  );

  return { quoteSymbols, confirmedFundNavSymbols };
}

export function findMarketEvidenceLane(
  report: CurrentHoldingMarketEvidenceReview | null | undefined,
  assetClass: string,
): CurrentHoldingMarketEvidenceLane | undefined {
  const normalizedAssetClass = assetClass.trim().toLowerCase();
  return report?.evidence_lanes?.find(
    (lane) => lane.asset_class.trim().toLowerCase() === normalizedAssetClass,
  );
}
